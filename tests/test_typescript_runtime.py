from pathlib import Path
import unittest

from hypercore.core.runtime import RuntimeBridge


ROOT = Path(__file__).resolve().parents[1]


class TypeScriptRuntimeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_node_plugin_round_trip_and_shutdown(self) -> None:
        bridge = RuntimeBridge(
            ["node", str(ROOT / "runtimes/typescript/src/runtime.js"), str(ROOT / "plugins/examples/typescript/ping.js")],
            cwd=ROOT,
            logger=__import__("logging").getLogger("hypercore.test.runtime"),
        )
        await bridge.start()
        try:
            ready = await bridge.request(
                "runtime.initialize",
                {"plugin": str(ROOT / "plugins/examples/typescript/ping.js")},
            )
            self.assertEqual(ready.type, "runtime.ready")
            self.assertEqual(ready.payload["manifest"]["runtime"], "typescript")
            response = await bridge.request("command.execute", {"name": "tsping", "args": []})
            self.assertEqual(response.type, "command.response")
            self.assertEqual(response.payload["text"], "pong from TypeScript")
            event = await bridge.request("event.emit", {"name": "startup_complete", "payload": {}})
            self.assertEqual(event.type, "event.ack")
        finally:
            await bridge.stop()
        self.assertIsNone(bridge.process)
