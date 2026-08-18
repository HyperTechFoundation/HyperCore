"""Credential-free HyperCore diagnostics for development and CI."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hypercore import CORE_NAME, CORE_VERSION
from hypercore.core.config import validate_core_config
from hypercore.core.events import CoreEventType
from hypercore.core.kernel import HyperCoreKernel
from hypercore.core.lifecycle import LifecycleStage
from hypercore.core.protocol import ProtocolMessage, decode_message, encode_message
from hypercore.core.runtime import RuntimeManager
from hypercore.core.storage import create_state_store


@dataclass(slots=True, frozen=True)
class HealthCheck:
    status: str
    name: str
    detail: str = ""


@dataclass(slots=True)
class HealthReport:
    sections: dict[str, list[HealthCheck]] = field(default_factory=dict)

    def add(self, section: str, status: str, name: str, detail: str = "") -> None:
        self.sections.setdefault(section, []).append(HealthCheck(status, name, detail))

    @property
    def failed(self) -> bool:
        return any(check.status == "FAIL" for checks in self.sections.values() for check in checks)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def render(self) -> str:
        lines = ["HyperCore Health Check", "======================", ""]
        section_order = ("Core", "Plugins", "Protocol", "Runtime", "Integration")
        sections = [(name, self.sections[name]) for name in section_order if name in self.sections]
        sections.extend((name, checks) for name, checks in self.sections.items() if name not in section_order)
        for section, checks in sections:
            lines.append(section)
            for check in checks:
                suffix = f" — {check.detail}" if check.detail else ""
                lines.append(f"[{check.status}] {check.name}{suffix}")
            lines.append("")
        lines.extend(["======================", f"RESULT: {'UNHEALTHY' if self.failed else 'HEALTHY'}"])
        return "\n".join(lines)


class HealthChecker:
    def __init__(
        self,
        root_path: Path,
        *,
        node_lookup: Callable[[str], str | None] = shutil.which,
        logger: logging.Logger | None = None,
    ) -> None:
        self.root_path = root_path
        self.node_lookup = node_lookup
        self.logger = logger or logging.getLogger("hypercore.health")

    async def run(self) -> HealthReport:
        report = HealthReport()
        kernel: HyperCoreKernel | None = None
        store = None
        runtime_manager = RuntimeManager(self.logger, timeout=2.0)
        process_runtime = None
        typescript_runtime = None

        self._check(report, "Core", "Python environment", self._python_environment)
        self._check(report, "Core", "HyperCore import", lambda: (CORE_NAME == "HyperCore", f"{CORE_NAME} {CORE_VERSION}"))
        self._check(report, "Core", "Configuration", lambda: (self._validate_configuration(), "static configuration valid"))

        try:
            kernel = HyperCoreKernel(runtime_mode="health")
            report.add("Core", "PASS", "Kernel initialization")
        except Exception as exc:
            report.add("Core", "FAIL", "Kernel initialization", str(exc))

        try:
            if kernel is None:
                raise RuntimeError("kernel unavailable")
            await kernel.loader.load_all()
            report.add("Plugins", "PASS", "Plugin discovery", f"{len(kernel.loader.loaded_plugins)} loaded")
            report.add("Plugins", "PASS", "Dependency resolution")
        except Exception as exc:
            report.add("Plugins", "FAIL", "Plugin discovery", str(exc))
            report.add("Plugins", "FAIL", "Dependency resolution", "plugin loading did not complete")

        try:
            message = ProtocolMessage("command.execute", {"name": "health"}, "health")
            if decode_message(encode_message(message)) != message:
                raise RuntimeError("protocol round trip mismatch")
            report.add("Protocol", "PASS", "Protocol validation")
        except Exception as exc:
            report.add("Protocol", "FAIL", "Protocol validation", str(exc))

        try:
            store = create_state_store(":memory:", self.root_path)
            await store.initialize()
            await store.list_sudos()
            report.add("Core", "PASS", "Storage initialization")
        except Exception as exc:
            report.add("Core", "FAIL", "Storage initialization", str(exc))

        try:
            if kernel is None:
                raise RuntimeError("kernel unavailable")
            called = asyncio.Event()

            def on_event(event) -> None:
                if event.payload.get("health"):
                    called.set()

            kernel.events.on(CoreEventType.COMMAND_EXECUTED, on_event)
            kernel.events.emit(CoreEventType.COMMAND_EXECUTED, health=True)
            await asyncio.sleep(0)
            if not called.is_set():
                raise RuntimeError("event subscriber was not called")
            report.add("Integration", "PASS", "Event dispatch")
        except Exception as exc:
            report.add("Integration", "FAIL", "Event dispatch", str(exc))

        try:
            if kernel is None:
                raise RuntimeError("kernel unavailable")
            if not kernel.registry.names:
                raise RuntimeError("no commands registered")
            report.add("Integration", "PASS", "Command registration", f"{len(kernel.registry.names)} commands")
        except Exception as exc:
            report.add("Integration", "FAIL", "Command registration", str(exc))

        try:
            process_code = (
                "import json, sys\n"
                "for line in sys.stdin:\n"
                " message = json.loads(line)\n"
                " print(json.dumps({'protocol_version': 1, 'type': 'runtime.stopped', 'payload': {}, 'request_id': message.get('request_id')}), flush=True)\n"
                " if message.get('type') == 'runtime.shutdown': break\n"
            )
            process_runtime = await runtime_manager.start(
                [sys.executable, "-c", process_code], cwd=self.root_path
            )
            report.add("Runtime", "PASS", "Process runtime")
        except Exception as exc:
            report.add("Runtime", "FAIL", "Process runtime", str(exc))

        node = self.node_lookup("node")
        if node is None:
            report.add("Runtime", "WARN", "TypeScript runtime", "Node.js not installed; optional")
        else:
            try:
                runtime_script = self.root_path / "runtimes/typescript/src/runtime.js"
                plugin = self.root_path / "plugins/examples/typescript/ping.js"
                typescript_runtime = await runtime_manager.start(
                    [node, str(runtime_script), str(plugin)], cwd=self.root_path
                )
                ready = await typescript_runtime.request("runtime.initialize", {"plugin": str(plugin)})
                if ready.type != "runtime.ready":
                    raise RuntimeError(f"unexpected response: {ready.type}")
                response = await typescript_runtime.request("command.execute", {"name": "tsping", "args": []})
                if response.payload.get("text") != "pong from TypeScript":
                    raise RuntimeError("unexpected TypeScript command response")
                await typescript_runtime.request("event.emit", {"name": "startup_complete", "payload": {}})
                report.add("Runtime", "PASS", "TypeScript runtime")
            except Exception as exc:
                report.add("Runtime", "WARN", "TypeScript runtime", f"optional: {exc}")

        try:
            if kernel is None:
                raise RuntimeError("kernel unavailable")
            await kernel.lifecycle.run(LifecycleStage.AFTER_START, on_error=kernel.log_exception)
            await kernel.lifecycle.run(LifecycleStage.BEFORE_SHUTDOWN, on_error=kernel.log_exception)
            report.add("Integration", "PASS", "Clean startup/shutdown")
        except Exception as exc:
            report.add("Integration", "FAIL", "Clean startup/shutdown", str(exc))
        finally:
            if typescript_runtime is not None:
                await runtime_manager.stop(typescript_runtime)
            if process_runtime is not None:
                await process_runtime.stop()
            if store is not None:
                await store.close()

        return report

    def _python_environment(self) -> tuple[bool, str]:
        return sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}"

    @staticmethod
    def _validate_configuration() -> bool:
        validate_core_config()
        return True

    @staticmethod
    def _check(report: HealthReport, section: str, name: str, check: Callable[[], tuple[bool, str]]) -> None:
        try:
            passed, detail = check()
            report.add(section, "PASS" if passed else "FAIL", name, detail)
        except Exception as exc:
            report.add(section, "FAIL", name, str(exc))


async def run_health_check(root_path: Path) -> HealthReport:
    return await HealthChecker(root_path).run()


__all__ = ["HealthCheck", "HealthChecker", "HealthReport", "run_health_check"]
