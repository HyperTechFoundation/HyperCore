"""Command registration and dispatch for HyperCore."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from contextlib import contextmanager
from typing import TYPE_CHECKING, Awaitable, Callable

from hypercore.core.errors import CommandError, PlatformError, PermissionDeniedError
from hypercore.core.events import CoreEventType
from hypercore.core.platforms import PlatformCapabilities, PlatformInfo

if TYPE_CHECKING:
    from hypercore.core.kernel import HyperCoreKernel


@dataclass(slots=True, frozen=True)
class CommandResponse:
    text: str
    parse_mode: str | None = None
    edit: bool = True


CommandHandler = Callable[
    ["CommandContext"], Awaitable["CommandResponse | str | None"]
]
ReplyCallback = Callable[[CommandResponse], Awaitable[None]]


class CommandAccess(str, Enum):
    OWNER = "owner"
    SUDO = "sudo"


@dataclass(slots=True, frozen=True)
class CommandSpec:
    name: str
    access: CommandAccess
    description: str = ""
    usage: str | None = None
    aliases: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    owner: str | None = None

    @property
    def all_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)

    def supports_platform(self, platform: str) -> bool:
        return not self.platforms or platform in self.platforms


@dataclass(slots=True)
class IncomingMessage:
    platform: str
    platform_info: PlatformInfo
    sender_id: int | None
    chat_id: int | None
    text: str
    received_at: float
    reply_to_user_id: int | None
    send_reply: ReplyCallback


@dataclass(slots=True)
class CommandContext:
    core: "HyperCoreKernel"
    platform: str
    platform_info: PlatformInfo
    spec: CommandSpec
    sender_id: int
    chat_id: int | None
    text: str
    received_at: float
    name: str
    args: list[str]
    reply_to_user_id: int | None
    _send_reply: ReplyCallback

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self.platform_info.capabilities

    @property
    def command_prefix(self) -> str:
        return self.platform_info.primary_command_prefix

    def command_ref(self, name: str, *args: str) -> str:
        normalized_name = name.lstrip("./")
        parts = [f"{self.command_prefix}{normalized_name}"]
        parts.extend(arg for arg in args if arg)
        return " ".join(parts)

    def require_capability(
        self,
        capability_name: str,
        *,
        message: str | None = None,
    ) -> None:
        if getattr(self.capabilities, capability_name):
            return
        error_message = message or f"Platform does not support {capability_name}."
        raise PlatformError(error_message)

    async def reply(
        self,
        text: str | CommandResponse,
        parse_mode: str | None = None,
        edit: bool = True,
    ) -> None:
        if isinstance(text, CommandResponse):
            await self._send_reply(text)
            return
        await self._send_reply(
            CommandResponse(text=text, parse_mode=parse_mode, edit=edit)
        )


@dataclass(slots=True)
class _RegisteredCommand:
    spec: CommandSpec
    handler: CommandHandler


class CommandRegistry:
    def __init__(self, core: "HyperCoreKernel") -> None:
        self._core = core
        self._commands: dict[str, _RegisteredCommand] = {}
        self._registered_specs: dict[str, _RegisteredCommand] = {}
        self._owner: str | None = None

    @contextmanager
    def plugin_scope(self, owner: str):
        previous = self._owner
        self._owner = owner
        try:
            yield
        finally:
            self._owner = previous

    def register(
        self,
        name: str,
        handler: CommandHandler,
        access: CommandAccess = CommandAccess.SUDO,
        *,
        description: str = "",
        usage: str | None = None,
        aliases: tuple[str, ...] = (),
        platforms: tuple[str, ...] = (),
        owner: str | None = None,
    ) -> CommandSpec:
        normalized = _normalize_command_name(name)
        if not normalized:
            raise ValueError("Command name must not be empty.")
        normalized_aliases = tuple(_normalize_command_name(alias) for alias in aliases)
        command_names = (normalized, *normalized_aliases)
        if any(not command_name for command_name in command_names):
            raise ValueError("Command aliases must not be empty.")
        if len(set(command_names)) != len(command_names):
            raise ValueError(f"Command aliases must be unique: {normalized}")

        for command_name in command_names:
            if command_name in self._commands:
                raise ValueError(f"Command is already registered: {command_name}")

        spec = CommandSpec(
            name=normalized,
            access=access,
            description=description.strip(),
            usage=usage.strip() if usage else None,
            aliases=normalized_aliases,
            platforms=tuple(platform.strip() for platform in platforms if platform.strip()),
            owner=owner or self._owner,
        )
        registered = _RegisteredCommand(
            spec=spec,
            handler=handler,
        )
        for command_name in spec.all_names:
            self._commands[command_name] = registered
        self._registered_specs[spec.name] = registered
        return spec

    async def dispatch(self, message: IncomingMessage) -> bool:
        text = message.text.strip()
        prefix = _match_command_prefix(text, message.platform_info)
        if prefix is None:
            return False

        body = text[len(prefix):].strip()
        if not body:
            return False

        tokens = body.split()
        command_name = tokens[0].lower()
        if prefix == "/":
            command_name = command_name.split("@", 1)[0]
        registered = self._commands.get(command_name)
        if registered is None or message.sender_id is None:
            return False
        if not registered.spec.supports_platform(message.platform):
            return False

        if not await self._is_authorized(message.sender_id, registered.spec.access):
            await message.send_reply(
                _render_command_error(
                    PermissionDeniedError(),
                    message.platform_info.capabilities,
                )
            )
            self._core.events.emit(
                CoreEventType.COMMAND_EXECUTED,
                command=registered.spec.name,
                platform=message.platform,
                sender_id=message.sender_id,
                outcome="denied",
            )
            return True

        context = CommandContext(
            core=self._core,
            platform=message.platform,
            platform_info=message.platform_info,
            spec=registered.spec,
            sender_id=message.sender_id,
            chat_id=message.chat_id,
            text=text,
            received_at=message.received_at,
            name=registered.spec.name,
            args=tokens[1:],
            reply_to_user_id=message.reply_to_user_id,
            _send_reply=message.send_reply,
        )

        try:
            response = await registered.handler(context)
        except CommandError as exc:
            self._core.events.emit(
                CoreEventType.COMMAND_EXECUTED,
                command=registered.spec.name,
                platform=message.platform,
                sender_id=message.sender_id,
                outcome="error",
                status=exc.status_label.lower(),
            )
            await message.send_reply(
                _render_command_error(exc, message.platform_info.capabilities)
            )
            return True
        except Exception as exc:
            self._core.events.emit(
                CoreEventType.COMMAND_EXECUTED,
                command=registered.spec.name,
                platform=message.platform,
                sender_id=message.sender_id,
                outcome="failed",
            )
            self._core.handle_command_error(registered.spec.name, exc)
            await message.send_reply(
                _render_command_error(
                    CommandError("Command failed."),
                    message.platform_info.capabilities,
                )
            )
            return True

        if response:
            await message.send_reply(_coerce_response(response))
        self._core.events.emit(
            CoreEventType.COMMAND_EXECUTED,
            command=registered.spec.name,
            platform=message.platform,
            sender_id=message.sender_id,
            outcome="ok",
        )
        return True

    async def _is_authorized(self, sender_id: int, access: CommandAccess) -> bool:
        return await self._core.authorizer.is_authorized(sender_id, access)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registered_specs))

    @property
    def commands(self) -> tuple[CommandSpec, ...]:
        return tuple(
            self._registered_specs[name].spec
            for name in sorted(self._registered_specs)
        )

    def has_command(self, name: str) -> bool:
        return _normalize_command_name(name) in self._registered_specs

    def command_names_for_platform(self, platform: str) -> tuple[str, ...]:
        return tuple(
            spec.name
            for spec in self.commands
            if spec.supports_platform(platform)
        )


def _coerce_response(response: CommandResponse | str) -> CommandResponse:
    if isinstance(response, CommandResponse):
        return response
    return CommandResponse(text=response)


def _normalize_command_name(name: str) -> str:
    return name.strip().lower().lstrip("./")


def _match_command_prefix(
    text: str,
    platform_info: PlatformInfo,
) -> str | None:
    for prefix in platform_info.command_prefixes:
        if prefix and text.startswith(prefix):
            return prefix
    return None


def _render_command_error(
    error: CommandError,
    capabilities: PlatformCapabilities,
) -> CommandResponse:
    from hypercore.core.formatter import make_status_response

    return make_status_response(
        error.status_label,
        error.message,
        capabilities=capabilities,
        edit=error.edit,
    )


__all__ = [
    "CommandAccess",
    "CommandContext",
    "CommandRegistry",
    "CommandResponse",
    "CommandSpec",
    "IncomingMessage",
]
