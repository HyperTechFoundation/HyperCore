import unittest

from hypercore.core.protocol import ProtocolError, ProtocolMessage, decode_message, encode_message


class ProtocolTests(unittest.TestCase):
    def test_round_trip_is_json_compatible(self) -> None:
        message = ProtocolMessage("command.register", {"id": "ping"}, "42")
        self.assertEqual(decode_message(encode_message(message)), message)

    def test_rejects_malformed_messages(self) -> None:
        for value in ("not json", '{"type":"x"}', '{"protocol_version":1,"type":"x","payload":[]}' ):
            with self.assertRaises(ProtocolError):
                decode_message(value)
