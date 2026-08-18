import unittest
from datetime import timedelta
from types import SimpleNamespace

from hypercore.core.platforms import PlatformCapabilities, PlatformInfo
from hypercore.core.status import CoreStatusService


class _DummyStore:
    def __init__(self, mode: str, sudo_count: int) -> None:
        self.mode = mode
        self._sudo_count = sudo_count

    async def count_sudos(self) -> int:
        return self._sudo_count


class _DummyCore:
    def __init__(self) -> None:
        self.runtime_mode = "both"
        self.loader = SimpleNamespace(loaded_plugins=["system", "sudo"])
        self.store = _DummyStore(mode="sqlite", sudo_count=3)
        self.userbot = SimpleNamespace(is_running=True)
        self.bot = SimpleNamespace(is_running=True)
        self.env = SimpleNamespace(bot_token="token")
        self.uptime = timedelta(hours=2, minutes=5)


class CoreStatusServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_returns_runtime_snapshot(self) -> None:
        core = _DummyCore()
        service = CoreStatusService(core)
        platform = PlatformInfo(
            key="userbot",
            display_name="Telethon",
            version="1.40.0",
            capabilities=PlatformCapabilities(
                can_edit_source_message=True,
                can_edit_response_message=True,
                preferred_parse_mode="HTML",
            ),
        )

        status = await service.collect(platform)

        self.assertEqual(status.core_name, "HyperCore")
        self.assertEqual(status.core_version, "0.5.0")
        self.assertEqual(status.uptime, timedelta(hours=2, minutes=5))
        self.assertEqual(status.request_platform_name, "Telethon")
        self.assertEqual(status.request_platform_version, "1.40.0")
        self.assertEqual(status.runtime_platform_summary, "userbot=online, bot=online")
        self.assertEqual(status.plugin_count, 2)
        self.assertEqual(status.plugin_names, ("system", "sudo"))
        self.assertEqual(status.database_status, "Functional (SQLite)")
        self.assertEqual(status.storage_mode, "sqlite")
        self.assertEqual(status.sudo_user_count, 3)
        self.assertRegex(status.python_version, r"^\d+\.\d+\.\d+")
