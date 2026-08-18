"""Versioned, JSON-line protocol shared by HyperCore runtimes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MESSAGE_TYPES = frozenset({
    "runtime.initialize", "runtime.ready", "runtime.shutdown", "runtime.stopped",
    "command.register", "command.execute", "command.response", "command.error",
    "event.subscribe", "event.emit", "event.ack", "error", "runtime.error",
})


class ProtocolError(ValueError):
    """Raised when an IPC message is not a valid HyperCore message."""


@dataclass(frozen=True, slots=True)
class ProtocolMessage:
    type: str
    payload: dict[str, Any]
    request_id: str | None = None
    protocol_version: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "type": self.type,
            "payload": self.payload,
        }
        if self.request_id is not None:
            result["request_id"] = self.request_id
        return result


def encode_message(message: ProtocolMessage) -> str:
    validate_message(message)
    return json.dumps(message.to_dict(), separators=(",", ":"), sort_keys=True)


def decode_message(line: str) -> ProtocolMessage:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Protocol message must be a JSON object.")
    version = value.get("protocol_version")
    message_type = value.get("type")
    payload = value.get("payload", {})
    request_id = value.get("request_id")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {version!r}")
    if not isinstance(message_type, str) or not message_type.strip():
        raise ProtocolError("Protocol message type must be a non-empty string.")
    if not isinstance(payload, dict):
        raise ProtocolError("Protocol message payload must be an object.")
    if request_id is not None and not isinstance(request_id, str):
        raise ProtocolError("Protocol request_id must be a string.")
    message = ProtocolMessage(message_type, payload, request_id, version)
    validate_message(message)
    return message


def validate_message(message: ProtocolMessage) -> None:
    if message.protocol_version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {message.protocol_version!r}")
    if message.type not in MESSAGE_TYPES:
        raise ProtocolError(f"Unknown protocol message type: {message.type}")
    required: dict[str, tuple[str, ...]] = {
        "runtime.initialize": ("plugin",), "command.execute": ("name",),
        "command.response": ("text",), "command.error": ("code", "message"),
        "event.emit": ("name",), "error": ("code", "message"),
        "runtime.error": ("code", "message"),
    }
    for key in required.get(message.type, ()):
        if key not in message.payload:
            raise ProtocolError(f"{message.type} payload requires '{key}'.")


__all__ = ["MESSAGE_TYPES", "PROTOCOL_VERSION", "ProtocolError", "ProtocolMessage", "decode_message", "encode_message", "validate_message"]
