"""Entrypoint for the CoolPugBot application."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

import faulthandler

from bot_core.bot import ModularBot
from utils import path_utils
from utils.config import BotSettings, load_settings
from utils.logging_utils import configure_logging

faulthandler.enable()


async def main(settings: BotSettings) -> None:
    """Start the bot using the provided settings."""

    path_utils.set_home_dir(Path(__file__).parent.absolute())
    logging.getLogger(__name__).debug(
        "Application home directory initialised at %s", path_utils.get_home_dir()
    )

    bot = ModularBot(settings.bot_token)
    await bot.start()


def _bootstrap() -> None:
    """Load configuration, configure logging and start the asyncio loop."""

    project_root = Path(__file__).parent
    settings = load_settings()

    log_dir = project_root / "logs"
    configure_logging(log_dir, level=settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("CoolPugBot starting up")
    try:
        asyncio.run(main(settings))
    except KeyboardInterrupt:
        logger.info("CoolPugBot interrupted by user")
    except Exception:  # pragma: no cover - safety net
        logger.exception("CoolPugBot stopped due to an unexpected error")
        raise
    finally:
        # Ensure logging handlers flush buffers before the interpreter exits.
        for handler in logging.getLogger().handlers:
            with suppress(Exception):
                handler.flush()


if __name__ == "__main__":
    _bootstrap()

