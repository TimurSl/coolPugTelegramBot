"""Middleware to guard chats against NSFW images."""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from modules.nsfw_guard.detector import NsfwDetectionService
from modules.nsfw_guard.storage import NsfwSettingsStorage


class NsfwGuardMiddleware(BaseMiddleware):
    """Aiogram middleware that deletes unspoiled NSFW images."""

    def __init__(
        self,
        storage: NsfwSettingsStorage,
        detector: NsfwDetectionService,
    ) -> None:
        super().__init__()
        self.storage = storage
        self.detector = detector
        self._logger = logging.getLogger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        if not self._should_check(event):
            return await handler(event, data)

        media_object = self._extract_media(event)
        if media_object is None:
            return await handler(event, data)

        image_bytes = await self._download_media(event, media_object)
        if image_bytes is None:
            return await handler(event, data)

        self._logger.info(
            "Checking media for NSFW content via model %s (chat=%s, message=%s)",
            self.detector.model_name,
            event.chat.id,
            event.message_id,
        )

        try:
            is_nsfw = await self.detector.is_nsfw(image_bytes)
        except Exception:  # pragma: no cover - defensive safety
            self._logger.exception("Failed to classify media in chat %s", event.chat.id)
            return await handler(event, data)

        self._logger.info(
            "NSFW classification completed for chat %s message %s: %s",
            event.chat.id,
            event.message_id,
            "nsfw" if is_nsfw else "safe",
        )

        if is_nsfw:
            await self._handle_nsfw_detection(event)
            return None

        return await handler(event, data)

    def _should_check(self, message: Message) -> bool:
        if not self.storage.is_chat_enabled(message.chat.id):
            return False
        if message.message_thread_id and self.storage.is_topic_ignored(
            message.chat.id, message.message_thread_id
        ):
            return False
        if message.has_media_spoiler:
            return False
        return True

    def _extract_media(self, message: Message):
        if message.photo:
            return message.photo[-1]
        document = message.document
        if document and document.mime_type and document.mime_type.startswith("image/"):
            return document
        return None

    async def _download_media(self, message: Message, media_object) -> Optional[bytes]:
        bot = message.bot
        if bot is None:
            return None
        buffer = BytesIO()
        try:
            await bot.download(media_object, destination=buffer)
        except Exception:
            self._logger.exception("Failed to download media from chat %s", message.chat.id)
            return None
        return buffer.getvalue()

    async def _handle_nsfw_detection(self, message: Message) -> None:
        try:
            await message.delete()
        except Exception:
            self._logger.exception("Failed to delete NSFW message in chat %s", message.chat.id)
        await message.answer("NSFW without Spoilers")
