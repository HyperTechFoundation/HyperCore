"""Plugin metadata definitions for HyperCore."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hypercore.core.commands import CommandAccess


@dataclass(slots=True, frozen=True)
class PluginCommand:
    name: str
    description: str = ""
    usage: str | None = None
    aliases: tuple[str, ...] = ()
    access: CommandAccess = CommandAccess.SUDO


@dataclass(slots=True, frozen=True)
class PluginManifest:
    name: str
    version: str
    description: str
    commands: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    runtime: str = "python"
    plugin_id: str | None = None
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    lifecycle: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.plugin_id or self.name

    def supports_platform(self, platform: str) -> bool:
        return not self.platforms or platform in self.platforms

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "description": self.description, "runtime": self.runtime,
            "commands": [
                {"name": command.name, "description": command.description,
                 "usage": command.usage, "aliases": list(command.aliases),
                 "access": command.access.value}
                for command in self.command_specs
            ], "events": list(self.events),
            "dependencies": list(self.dependencies), "capabilities": list(self.capabilities),
            "lifecycle": list(self.lifecycle), "platforms": list(self.platforms),
        }

    @property
    def command_specs(self) -> tuple[PluginCommand, ...]:
        return tuple(
            item if isinstance(item, PluginCommand) else PluginCommand(name=item)
            for item in self.commands
        )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "PluginManifest":
        if not isinstance(value, dict):
            raise ValueError("Plugin manifest must be an object.")
        raw_commands = value.get("commands", ())
        commands = tuple(
            PluginCommand(
                name=item["name"], description=item.get("description", ""),
                usage=item.get("usage"), aliases=tuple(item.get("aliases", ())),
                access=CommandAccess(item.get("access", "sudo")),
            ) if isinstance(item, dict) else str(item)
            for item in raw_commands
        )
        manifest = cls(
            name=str(value.get("name", value.get("id", ""))),
            plugin_id=str(value.get("id", "")) or None,
            version=str(value.get("version", "")),
            description=str(value.get("description", "")),
            runtime=str(value.get("runtime", "python")), commands=commands,
            events=tuple(value.get("events", ())), dependencies=tuple(value.get("dependencies", ())),
            capabilities=tuple(value.get("capabilities", ())), lifecycle=tuple(value.get("lifecycle", ())),
            platforms=tuple(value.get("platforms", ())),
        )
        if not manifest.id.strip() or not manifest.version.strip():
            raise ValueError("Plugin manifest requires id and version.")
        return manifest


__all__ = ["PluginCommand", "PluginManifest"]
