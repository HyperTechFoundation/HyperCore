"""External runtime supervision and the narrow bridge used by the kernel."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from hypercore.core.protocol import ProtocolError, ProtocolMessage, decode_message, encode_message

MessageHandler = Callable[[ProtocolMessage], Awaitable[None] | None]


class RuntimeDisconnected(RuntimeError):
    pass


class ProcessRuntime:
    def __init__(self, command: list[str], *, cwd: Path, logger: logging.Logger, timeout: float = 5.0) -> None:
        self.command, self.cwd, self.logger, self.timeout = command, cwd, logger, timeout
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[ProtocolMessage]] = {}
        self._counter = 0
        self._handler: MessageHandler | None = None

    async def start(self, handler: MessageHandler | None = None) -> None:
        self._handler = handler
        self.process = await asyncio.create_subprocess_exec(
            *self.command, cwd=self.cwd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_messages())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def request(self, message_type: str, payload: dict[str, Any]) -> ProtocolMessage:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("External runtime is not running.")
        self._counter += 1
        request_id = str(self._counter)
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = ProtocolMessage(message_type, payload, request_id)
        self.process.stdin.write((encode_message(message) + "\n").encode())
        await self.process.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout=self.timeout)
        finally:
            self._pending.pop(request_id, None)

    async def stop(self, *, graceful: bool = True) -> None:
        if self.process is None:
            return
        if self.process.returncode is None:
            if graceful:
                try:
                    await self.request("runtime.shutdown", {})
                except Exception as exc:
                    self.logger.warning("External runtime shutdown failed: %s", exc)
            if self.process.returncode is None:
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=self.timeout)
                except asyncio.TimeoutError:
                    self.process.terminate()
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        self.process.kill()
                        await self.process.wait()
        if self._reader_task:
            await asyncio.gather(self._reader_task, return_exceptions=True)
        if self._stderr_task:
            await asyncio.gather(self._stderr_task, return_exceptions=True)
        self.process = None

    async def _read_messages(self) -> None:
        assert self.process and self.process.stdout
        async for raw_line in self.process.stdout:
            try:
                message = decode_message(raw_line.decode())
            except ProtocolError as exc:
                self.logger.error("Invalid protocol message from runtime: %s", exc)
                continue
            if message.request_id and message.request_id in self._pending:
                future = self._pending[message.request_id]
                if not future.done():
                    future.set_result(message)
            elif self._handler:
                result = self._handler(message)
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    task.add_done_callback(self._report_handler_failure)
        error = RuntimeDisconnected("External runtime disconnected.")
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)

    async def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        async for raw_line in self.process.stderr:
            self.logger.info("external-runtime: %s", raw_line.decode(errors="replace").rstrip())

    def _report_handler_failure(self, task: asyncio.Task[object]) -> None:
        if not task.cancelled() and task.exception() is not None:
            self.logger.error("External runtime message handler failed: %s", task.exception())


class RuntimeManager:
    def __init__(self, logger: logging.Logger, *, timeout: float = 5.0) -> None:
        self.logger, self.timeout = logger, timeout

    async def start(self, command: list[str], *, cwd: Path, handler: MessageHandler | None = None) -> ProcessRuntime:
        runtime = ProcessRuntime(command, cwd=cwd, logger=self.logger, timeout=self.timeout)
        await runtime.start(handler)
        return runtime

    async def stop(self, runtime: ProcessRuntime) -> None:
        await runtime.stop()


RuntimeBridge = ProcessRuntime

__all__ = ["ProcessRuntime", "RuntimeBridge", "RuntimeDisconnected", "RuntimeManager"]
