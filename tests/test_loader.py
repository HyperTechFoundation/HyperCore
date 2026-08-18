import types
import unittest
from unittest.mock import patch

from hypercore.core.loader import PluginLoader
from hypercore.core.plugin_manifest import PluginManifest


class _DummyRegistry:
    def __init__(self) -> None:
        self._commands: set[str] = set()

    def register(self, name, handler=None, **kwargs):
        del handler, kwargs
        self._commands.add(name.strip().lower())

    def has_command(self, name: str) -> bool:
        return name.strip().lower() in self._commands


class _DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args) -> None:
        self.messages.append(message % args)


class _DummyCore:
    def __init__(self) -> None:
        self.registry = _DummyRegistry()
        self.logger = _DummyLogger()
        self.errors: list[tuple[str, Exception]] = []

    def log_exception(self, message: str, exc: Exception) -> None:
        self.errors.append((message, exc))


class PluginLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_all_registers_valid_manifest(self) -> None:
        core = _DummyCore()

        def setup(loaded_core) -> None:
            loaded_core.registry.register("demo")

        module = types.SimpleNamespace(
            PLUGIN_MANIFEST=PluginManifest(
                name="demo",
                version="0.3.0",
                description="Demo plugin",
                commands=("demo",),
                platforms=("bot", "userbot"),
            ),
            setup=setup,
        )

        with patch(
            "hypercore.core.loader.importlib.import_module",
            return_value=module,
        ):
            loader = PluginLoader(core, modules=("hypercore.plugins.demo",))
            await loader.load_all()

        self.assertEqual(loader.loaded_plugins, ["demo"])
        self.assertEqual(loader.loaded_manifests[0].name, "demo")
        self.assertEqual(core.logger.messages, ["Loaded plugin: demo"])

    async def test_load_all_rejects_missing_manifest_command(self) -> None:
        core = _DummyCore()
        module = types.SimpleNamespace(
            PLUGIN_MANIFEST=PluginManifest(
                name="broken",
                version="0.3.0",
                description="Broken plugin",
                commands=("missing",),
            ),
            setup=lambda loaded_core: loaded_core.registry.register("other"),
        )

        with patch(
            "hypercore.core.loader.importlib.import_module",
            return_value=module,
        ):
            loader = PluginLoader(core, modules=("hypercore.plugins.broken",))
            with self.assertRaisesRegex(RuntimeError, "commands were not registered"):
                await loader.load_all()

        self.assertEqual(len(core.errors), 1)

    async def test_load_all_rejects_missing_dependency(self) -> None:
        core = _DummyCore()
        module = types.SimpleNamespace(
            PLUGIN_MANIFEST=PluginManifest(
                name="dependent", version="0.5.0", description="Dependent",
                dependencies=("base",),
            ), setup=lambda loaded_core: None,
        )
        with patch("hypercore.core.loader.importlib.import_module", return_value=module):
            loader = PluginLoader(core, modules=("hypercore.plugins.dependent",))
            with self.assertRaisesRegex(RuntimeError, "dependencies missing"):
                await loader.load_all()
