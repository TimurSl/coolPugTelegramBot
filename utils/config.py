"""Configuration helpers for CoolPugBot."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
import sys
from typing import Iterable

from dotenv import find_dotenv, load_dotenv


# NOTE: ``dataclass`` gained support for ``slots`` starting with Python 3.10.
# The runtime for CoolPugBot may use an older interpreter, so we apply the
# ``slots`` option only when it is supported. This keeps the public interface
# unchanged while preserving compatibility with Python 3.9 and earlier.
if sys.version_info >= (3, 10):
    def _settings_dataclass(cls):
        return dataclass(cls, slots=True)
else:
    def _settings_dataclass(cls):
        return dataclass(cls)


@_settings_dataclass
class BotSettings:
    """Runtime settings loaded from the environment."""

    bot_token: str
    gemini_token: str
    log_level: str = "INFO"


REQUIRED_ENVIRONMENT_VARIABLES: tuple[str, ...] = ("BOT_TOKEN",)


def _load_env_file() -> None:
    """Load variables from a .env file when available."""

    env_file = find_dotenv(usecwd=True)
    if env_file:
        load_dotenv(env_file)
        logging.getLogger(__name__).debug("Loaded environment variables from %s", env_file)
    else:
        logging.getLogger(__name__).debug("No .env file discovered; using process environment")


def _missing_variables(required: Iterable[str]) -> list[str]:
    return [name for name in required if not os.getenv(name)]


def load_settings() -> BotSettings:
    """Load settings from the environment and ensure required values exist."""

    _load_env_file()
    missing = _missing_variables(REQUIRED_ENVIRONMENT_VARIABLES)
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(sorted(missing))
        )

    return BotSettings(
        bot_token=os.environ["BOT_TOKEN"],
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        gemini_token=os.getenv("GEMINI_API_KEY", ""),
    )

