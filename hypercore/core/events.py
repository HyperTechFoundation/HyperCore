"""Core runtime event recording for HyperCore."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any


class CoreEventType(str, Enum):
    STARTUP_COMPLETE = "startup_complete"
    COMMAND_EXECUTED = "command_executed"
    RESTART_REQUESTED = "restart_requested"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    UPDATE_FINISHED = "update_finished"


@dataclass(slots=True, frozen=True)
class CoreEvent:
    event_type: CoreEventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CoreEventBus:
    def __init__(
        self,
        logger: logging.Logger,
        *,
        max_events: int = 100,
    ) -> None:
        self._logger = logger
        self._events: deque[CoreEvent] = deque(maxlen=max_events)
        self._handlers: dict[str, list[Callable[[CoreEvent], Awaitable[None] | None]]] = {}

    def emit(self, event_type: CoreEventType | str, **payload: Any) -> CoreEvent:
        event_name = event_type.value if isinstance(event_type, CoreEventType) else event_type
        event = CoreEvent(event_type=event_type, payload=dict(payload))
        self._events.append(event)
        details = " ".join(
            f"{key}={value}"
            for key, value in sorted(payload.items())
            if value is not None
        )
        if details:
            self._logger.debug("Core event: %s %s", event_name, details)
        else:
            self._logger.debug("Core event: %s", event_name)
        for handler in tuple(self._handlers.get(event_name, ())):
            try:
                result = handler(event)
            except Exception as exc:
                self._logger.error("Event handler failed for %s: %s", event_name, exc)
                continue
            if inspect.isawaitable(result):
                try:
                    asyncio.get_running_loop().create_task(result)
                except RuntimeError:
                    if hasattr(result, "close"):
                        result.close()
                    self._logger.warning("Event handler ignored outside an event loop: %s", event_name)
        return event

    def on(self, event_type: CoreEventType | str, handler: Callable[[CoreEvent], Awaitable[None] | None]) -> None:
        name = event_type.value if isinstance(event_type, CoreEventType) else event_type
        self._handlers.setdefault(name, []).append(handler)

    def off(self, event_type: CoreEventType | str, handler: Callable[[CoreEvent], Awaitable[None] | None]) -> None:
        name = event_type.value if isinstance(event_type, CoreEventType) else event_type
        handlers = self._handlers.get(name, [])
        if handler in handlers:
            handlers.remove(handler)

    def recent(self) -> tuple[CoreEvent, ...]:
        return tuple(self._events)


__all__ = ["CoreEvent", "CoreEventBus", "CoreEventType"]
