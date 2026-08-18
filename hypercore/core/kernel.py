"""Kernel orchestration for HyperCore."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from hypercore.core.auth import AuthorizationService
from hypercore.core.commands import CommandRegistry, IncomingMessage, ReplyCallback
from hypercore.core.config import CORE_NAME, CORE_VERSION
from hypercore.core.env_loader import PlatformEnv, load_platform_env, project_root
from hypercore.core.events import CoreEventBus, CoreEventType
from hypercore.core.instance_guard import InstanceGuard
from hypercore.core.lifecycle import LifecycleManager, LifecycleStage
from hypercore.core.loader import PluginLoader
from hypercore.core.plugin_manager import PluginManager
from hypercore.core.logger import configure_logging, log_exception
from hypercore.core.platforms import PlatformInfo
from hypercore.core.status import CoreStatusService
from hypercore.core.storage import StateStore, create_state_store
from hypercore.core.updater import CoreUpdater, UpdateResult
from hypercore.platform.telegram.bot import TelegramBot
from hypercore.platform.telegram.userbot import TelegramUserbot


class HyperCoreKernel:
    def __init__(self, runtime_mode: str = "both") -> None:
        self.root_path = project_root()
        self.logger = configure_logging()
        self.runtime_mode = runtime_mode
        self.env: PlatformEnv | None = None
        self.store: StateStore = create_state_store(None, self.root_path)
        self.authorizer = AuthorizationService(self)
        self.events = CoreEventBus(self.logger)
        self.instance_guard = InstanceGuard(self.root_path)
        self.lifecycle = LifecycleManager()
        self.registry = CommandRegistry(self)
        self.loader = PluginLoader(self)
        self.plugin_manager = PluginManager(self, loader=self.loader)
        self.status_service = CoreStatusService(self)
        self.updater = CoreUpdater(self.root_path)
        self.userbot: TelegramUserbot | None = None
        self.bot: TelegramBot | None = None
        self.owner_id: int | None = None
        self.started_at = datetime.now(timezone.utc)
        self._stop_event = asyncio.Event()
        self._restart_requested = False
        self._shutdown_started = False
        self._signal_values: list[signal.Signals] = []

    async def run(self) -> int:
        try:
            self.instance_guard.acquire(self.runtime_mode)
            self._install_signal_handlers()
            await self._bootstrap()
            await self.lifecycle.run(
                LifecycleStage.AFTER_START,
                on_error=self.log_exception,
                raise_on_error=True,
            )
            self.logger.info("%s %s is running.", CORE_NAME, CORE_VERSION)
            await self._stop_event.wait()
        finally:
            await self._shutdown()
            self._remove_signal_handlers()

        if self._restart_requested:
            self._restart_process()
        return 0

    async def _bootstrap(self) -> None:
        self.env = load_platform_env()
        self.store = create_state_store(self.env.database_url, self.root_path)
        await self.store.initialize()

        self.registry = CommandRegistry(self)
        self.loader = PluginLoader(self)
        self.plugin_manager = PluginManager(self, loader=self.loader)
        await self.plugin_manager.start()

        if self.runtime_mode in {"both", "userbot"}:
            self.userbot = TelegramUserbot(self, self.env)
            await self.userbot.start()
            self.owner_id = self.userbot.owner_id

        if self.runtime_mode in {"both", "bot"} and self.env.bot_token:
            if self.owner_id is None:
                owner_id, telethon_version = await TelegramUserbot.resolve_owner_identity(
                    self.root_path,
                    self.env,
                )
                self.owner_id = owner_id
                self.logger.info(
                    "Resolved bot owner from Telethon session (%s).",
                    telethon_version,
                )
            self.bot = TelegramBot(self, self.env.bot_token)
            await self.bot.start()

        if self.runtime_mode == "bot" and not self.env.bot_token:
            raise RuntimeError("BOT_TOKEN is required when runtime mode is 'bot'.")

        self.logger.info("Environment loaded from %s", self.env.env_path)
        self.logger.info("Storage mode: %s", self.store.mode)
        self.logger.info("Runtime mode: %s", self.runtime_mode)
        self.events.emit(
            CoreEventType.STARTUP_COMPLETE,
            runtime_mode=self.runtime_mode,
            storage_mode=self.store.mode,
            plugin_count=len(self.plugin_manager.loaded_plugins),
        )

    async def handle_incoming_message(
        self,
        platform: str,
        platform_info: PlatformInfo,
        sender_id: int | None,
        chat_id: int | None,
        text: str,
        received_at: float,
        reply_to_user_id: int | None,
        send_reply: ReplyCallback,
    ) -> None:
        await self.registry.dispatch(
            IncomingMessage(
                platform=platform,
                platform_info=platform_info,
                sender_id=sender_id,
                chat_id=chat_id,
                text=text,
                received_at=received_at,
                reply_to_user_id=reply_to_user_id,
                send_reply=send_reply,
            )
        )

    async def perform_core_update(self) -> UpdateResult:
        result = await asyncio.to_thread(self.updater.update_core)
        self.events.emit(
            CoreEventType.UPDATE_FINISHED,
            success=result.success,
            changed=result.changed,
        )
        return result

    def request_restart(self) -> None:
        self.events.emit(CoreEventType.RESTART_REQUESTED, runtime_mode=self.runtime_mode)
        self._restart_requested = True
        self._stop_event.set()

    def request_shutdown(self) -> None:
        self.events.emit(CoreEventType.SHUTDOWN_REQUESTED, runtime_mode=self.runtime_mode)
        self._restart_requested = False
        self._stop_event.set()

    def handle_command_error(self, command_name: str, exc: Exception) -> None:
        log_exception(self.logger, f"Command '{command_name}' failed", exc)

    def log_exception(self, message: str, exc: Exception) -> None:
        log_exception(self.logger, message, exc)

    @property
    def uptime(self) -> timedelta:
        return datetime.now(timezone.utc) - self.started_at

    async def _shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        if self._restart_requested:
            await self.lifecycle.run(
                LifecycleStage.BEFORE_RESTART,
                on_error=self.log_exception,
            )

        await self.lifecycle.run(
            LifecycleStage.BEFORE_SHUTDOWN,
            on_error=self.log_exception,
        )

        if self.bot is not None:
            try:
                await self.bot.stop()
            except Exception as exc:
                self.log_exception("Failed to stop bot", exc)

        if self.userbot is not None:
            try:
                await self.userbot.stop()
            except Exception as exc:
                self.log_exception("Failed to stop userbot", exc)

        try:
            await self.plugin_manager.stop()
        except Exception as exc:
            self.log_exception("Failed to stop external runtimes", exc)

        try:
            await self.store.close()
        except Exception as exc:
            self.log_exception("Failed to close state store", exc)
        finally:
            self.instance_guard.release()

    def _restart_process(self) -> None:
        self.logger.info("Restarting process.")
        command = [sys.executable, "-m", "hypercore", "--runtime", self.runtime_mode]
        if os.name == "nt":
            subprocess.Popen(
                command,
                cwd=self.root_path,
            )
            raise SystemExit(0)
        os.execv(sys.executable, command)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signal_name in ("SIGINT", "SIGTERM"):
            if not hasattr(signal, signal_name):
                continue
            signal_value = getattr(signal, signal_name)
            try:
                loop.add_signal_handler(signal_value, self.request_shutdown)
                self._signal_values.append(signal_value)
            except (NotImplementedError, RuntimeError):
                continue

    def _remove_signal_handlers(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for signal_value in self._signal_values:
            try:
                loop.remove_signal_handler(signal_value)
            except (NotImplementedError, RuntimeError):
                continue
        self._signal_values.clear()


__all__ = ["HyperCoreKernel"]
