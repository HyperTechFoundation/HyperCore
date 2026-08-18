"""Load user-level platform configuration from the single supported .env file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

_FORBIDDEN_CORE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "CORE_NAME",
        "CORE_VERSION",
        "CORE_DEBUG",
        "LOG_LEVEL",
        "PLUGIN_FAIL_STRATEGY",
    }
)


@dataclass(slots=True, frozen=True)
class PlatformEnv:
    api_id: int
    api_hash: str
    bot_token: str | None
    database_url: str | None
    log_channel: str | None
    env_path: Path
    typescript_plugin: Path | None = None


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_platform_env(env_path: Path | None = None) -> PlatformEnv:
    path = env_path or project_root() / ".env"
    if not path.exists():
        raise FileNotFoundError(f"Missing .env file: {path}")

    values = _parse_env_file(path)
    forbidden_keys = sorted(_FORBIDDEN_CORE_KEYS.intersection(values))
    if forbidden_keys:
        names = ", ".join(forbidden_keys)
        raise ValueError(f"Core config keys are not allowed in .env: {names}")

    api_id_raw = _required_value(values, "API_ID")
    api_hash = _required_value(values, "API_HASH")

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise ValueError("API_ID must be an integer.") from exc

    if api_id <= 0:
        raise ValueError("API_ID must be greater than zero.")

    return PlatformEnv(
        api_id=api_id,
        api_hash=api_hash,
        bot_token=_optional_value(values, "BOT_TOKEN"),
        database_url=_optional_value(values, "DATABASE_URL"),
        log_channel=_optional_value(values, "LOG_CHANNEL"),
        env_path=path,
        typescript_plugin=_optional_path(values, "TYPESCRIPT_PLUGIN", path.parent),
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"Invalid .env entry on line {line_number}: {raw_line}")

        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(raw_value.strip())
        values[key] = value
    return values


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _required_value(values: dict[str, str], key: str) -> str:
    value = _optional_value(values, key)
    if value is None:
        raise ValueError(f"{key} is required in .env.")
    return value


def _optional_value(values: dict[str, str], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _optional_path(values: dict[str, str], key: str, root: Path) -> Path | None:
    value = _optional_value(values, key)
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


__all__ = ["PlatformEnv", "load_platform_env", "project_root"]
