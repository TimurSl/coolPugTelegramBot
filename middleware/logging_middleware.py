"""Request/response logging middleware."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message, TelegramObject


class LoggingMiddleware(BaseMiddleware):
    """Log incoming updates and handler outcomes with structured metadata."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        logger = logging.getLogger("middleware.logging")
        if isinstance(event, Message):
            logger.info(
                "incoming message",
                extra={
                    "chat_id": getattr(event.chat, "id", None),
                    "chat_type": getattr(event.chat, "type", None),
                    "user_id": getattr(event.from_user, "id", None),
                    "username": getattr(event.from_user, "username", None),
                    "text": event.text or event.caption,
                },
            )
        else:
            logger.debug("incoming update", extra={"type": type(event).__name__})

        try:
            result = await handler(event, data)
            logger.debug(
                "handler completed",
                extra={
                    "type": type(event).__name__,
                    "handler": getattr(handler, "__qualname__", repr(handler)),
                },
            )
            return result
        except SkipHandler:
            logger.debug(
                "handler skipped",
                extra={
                    "type": type(event).__name__,
                    "handler": getattr(handler, "__qualname__", repr(handler)),
                },
            )
            raise
        except Exception:
            logger.exception(
                "handler raised exception",
                extra={"type": type(event).__name__},
            )
            raise


def setup_middlewares(dispatcher, _container) -> None:
    """Register the logging middleware on the dispatcher."""

    dispatcher.message.middleware(LoggingMiddleware())

