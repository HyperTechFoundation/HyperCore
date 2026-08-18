"""Owns plugin loading and delegates external processes to RuntimeManager."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypercore.core.loader import PluginLoader
from hypercore.core.plugin_manifest import PluginManifest
from hypercore.core.runtime import RuntimeManager, ProcessRuntime

if TYPE_CHECKING:
    from hypercore.core.kernel import HyperCoreKernel


class PluginManager:
    def __init__(self, core: "HyperCoreKernel", loader: PluginLoader | None = None) -> None:
        self.core = core
        self.loader = loader or PluginLoader(core)
        self.runtime_manager = RuntimeManager(core.logger)
        self.external_runtime: ProcessRuntime | None = None
        self.external_manifest: PluginManifest | None = None

    @property
    def loaded_plugins(self) -> list[str]:
        names = list(self.loader.loaded_plugins)
        if self.external_manifest:
            names.append(self.external_manifest.id)
        return names

    async def start(self) -> None:
        await self.loader.load_all()
        plugin_path = self.core.env.typescript_plugin if self.core.env else None
        if plugin_path is None:
            return
        runtime_script = self.core.root_path / "runtimes" / "typescript" / "src" / "runtime.js"
        if not runtime_script.exists():
            self.core.logger.error("External runtime is missing: %s", runtime_script)
            return
        try:
            self.external_runtime = await self.runtime_manager.start(
                ["node", str(runtime_script), str(plugin_path)], cwd=self.core.root_path
            )
            ready = await self.external_runtime.request("runtime.initialize", {"plugin": str(plugin_path)})
            self.external_manifest = PluginManifest.from_mapping(ready.payload["manifest"])
            if self.external_manifest.runtime != "typescript":
                raise RuntimeError("External plugin runtime must be 'typescript'.")
            for command in self.external_manifest.command_specs:
                self.core.registry.register(
                    command.name, self._external_command(command.name),
                    access=command.access, description=command.description,
                    usage=command.usage, aliases=command.aliases,
                    owner=self.external_manifest.id,
                )
            for event in self.external_manifest.events:
                self.core.events.on(event, self._forward_event)
        except Exception as exc:
            if self.external_runtime is not None:
                await self.runtime_manager.stop(self.external_runtime)
            self.external_runtime = None
            self.core.log_exception("External plugin failed to start", exc)

    def _external_command(self, name: str):
        async def handler(ctx):
            assert self.external_runtime is not None
            result = await self.external_runtime.request("command.execute", {
                "name": name, "args": ctx.args, "sender_id": ctx.sender_id,
                "chat_id": ctx.chat_id, "platform": ctx.platform, "text": ctx.text,
            })
            if result.type == "command.error":
                raise RuntimeError(result.payload.get("message", "External command failed"))
            return result.payload.get("text", "")
        return handler

    async def _forward_event(self, event) -> None:
        if self.external_runtime is None:
            return
        await self.external_runtime.request(
            "event.emit", {"name": getattr(event.event_type, "value", event.event_type), "payload": event.payload}
        )

    async def stop(self) -> None:
        if self.external_runtime is not None:
            await self.runtime_manager.stop(self.external_runtime)
            self.external_runtime = None


__all__ = ["PluginManager"]
