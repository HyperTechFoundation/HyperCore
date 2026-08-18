from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from hypercore.__main__ import main
from hypercore.core.health import HealthChecker, HealthReport


ROOT = Path(__file__).resolve().parents[1]


class HealthCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_core_and_clean_shutdown(self) -> None:
        report = await HealthChecker(ROOT, node_lookup=lambda name: None).run()

        self.assertEqual(report.exit_code, 0)
        self.assertFalse(report.failed)
        checks = [check for values in report.sections.values() for check in values]
        self.assertIn("PASS", {check.status for check in checks})
        self.assertEqual(
            next(check.status for check in report.sections["Integration"] if check.name == "Clean startup/shutdown"),
            "PASS",
        )

    async def test_optional_typescript_runtime_is_warning_when_node_is_unavailable(self) -> None:
        report = await HealthChecker(ROOT, node_lookup=lambda name: None).run()

        runtime_check = next(check for check in report.sections["Runtime"] if check.name == "TypeScript runtime")
        self.assertEqual(runtime_check.status, "WARN")
        self.assertEqual(report.exit_code, 0)

    async def test_required_check_failure_returns_one(self) -> None:
        report = HealthReport()
        report.add("Core", "FAIL", "Configuration", "broken")

        self.assertEqual(report.exit_code, 1)
        self.assertIn("RESULT: UNHEALTHY", report.render())

    def test_health_cli_returns_two_when_health_runner_cannot_run(self) -> None:
        with patch("hypercore.__main__.run_health_check", new=AsyncMock(side_effect=RuntimeError("environment"))):
            self.assertEqual(main(["--health"]), 2)
