"""Versioned engine-level configuration for HyperCore.

This module is intentionally static. Core behavior must not be driven by
platform or user environment variables.
"""

from typing import Final

CORE_NAME: Final[str] = "HyperCore"
CORE_VERSION: Final[str] = "0.5.0"
CORE_DEBUG: Final[bool] = False
LOG_LEVEL: Final[str] = "INFO"
PLUGIN_FAIL_STRATEGY: Final[str] = "stop"

_ALLOWED_LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)
_ALLOWED_PLUGIN_FAIL_STRATEGIES: Final[frozenset[str]] = frozenset(
    {"stop", "continue"}
)


def validate_core_config() -> None:
    """Fail fast if the engine defaults are edited into an invalid state."""
    if not CORE_NAME.strip():
        raise ValueError("CORE_NAME must not be empty.")

    if not CORE_VERSION.strip():
        raise ValueError("CORE_VERSION must not be empty.")

    if LOG_LEVEL not in _ALLOWED_LOG_LEVELS:
        allowed_levels = ", ".join(sorted(_ALLOWED_LOG_LEVELS))
        raise ValueError(f"LOG_LEVEL must be one of: {allowed_levels}")

    if PLUGIN_FAIL_STRATEGY not in _ALLOWED_PLUGIN_FAIL_STRATEGIES:
        allowed_strategies = ", ".join(sorted(_ALLOWED_PLUGIN_FAIL_STRATEGIES))
        raise ValueError(
            "PLUGIN_FAIL_STRATEGY must be one of: "
            f"{allowed_strategies}"
        )


validate_core_config()

__all__ = [
    "CORE_NAME",
    "CORE_VERSION",
    "CORE_DEBUG",
    "LOG_LEVEL",
    "PLUGIN_FAIL_STRATEGY",
    "validate_core_config",
]
