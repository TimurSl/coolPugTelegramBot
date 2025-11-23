"""Module router for NSFW image moderation."""

from __future__ import annotations

import logging
<<<<<<< ours
from io import BytesIO
from typing import Optional

from aiogram import F, Router
=======
from typing import Optional

from aiogram import Router
>>>>>>> theirs
from aiogram.filters import Command
from aiogram.types import Message

from modules.base import Module
from modules.nsfw_guard.detector import NsfwDetectionService
<<<<<<< ours
=======
from modules.nsfw_guard.middleware import NsfwGuardMiddleware
>>>>>>> theirs
from modules.nsfw_guard.storage import NsfwSettingsStorage


class NsfwGuardModule(Module):
    """Moderate images using a NSFW classifier with chat/topic controls."""

    OWNER_IDS = {999034568}

    def __init__(
        self,
        storage: Optional[NsfwSettingsStorage] = None,
        detector: Optional[NsfwDetectionService] = None,
    ) -> None:
        super().__init__(name="nsfw_guard", priority=5)
        self.storage = storage or NsfwSettingsStorage()
        self.detector = detector or NsfwDetectionService()
<<<<<<< ours
        self._logger = logging.getLogger(__name__)

        self.router.message.register(self._handle_dontcheck, Command("dontcheck"))
        self.router.message.register(self._handle_enable_for, Command("enablefor"))
        self.router.message.register(self._handle_photo, F.photo)
        self.router.message.register(self._handle_document, F.document)
=======
        self.middleware = NsfwGuardMiddleware(self.storage, self.detector)
        self._logger = logging.getLogger(__name__)

        self.router.message.middleware(self.middleware)
        self.router.message.register(self._handle_dontcheck, Command("dontcheck"))
        self.router.message.register(self._handle_enable_for, Command("enablefor"))
>>>>>>> theirs

    async def register(self, container):
        self._logger.info("NSFW guard module registered")

    async def on_shutdown(self):
        self.detector.unload()

    async def _handle_enable_for(self, message: Message) -> None:
        if not message.from_user or message.from_user.id not in self.OWNER_IDS:
            await message.answer("Only the bot creator can use this command")
            return

        args = (message.text or message.caption or "").split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Usage: /enablefor <chat_id>")
            return

        chat_id_str = args[1].strip()
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            await message.answer("Chat id must be a number")
            return

        self.storage.enable_chat(chat_id)
        await message.answer(f"NSFW checker enabled for chat {chat_id}")
        self._logger.info("NSFW checker enabled for chat %s by %s", chat_id, message.from_user.id)

    async def _handle_dontcheck(self, message: Message) -> None:
        if message.message_thread_id is None:
            await message.answer("This command works only inside a topic")
            return

        chat_id = message.chat.id
        topic_id = message.message_thread_id
        if self.storage.is_topic_ignored(chat_id, topic_id):
            self.storage.unignore_topic(chat_id, topic_id)
            await message.answer("NSFW check re-enabled for this topic")
            self._logger.info("Re-enabled NSFW checking for topic %s in chat %s", topic_id, chat_id)
            return

        self.storage.ignore_topic(chat_id, topic_id)
        await message.answer("NSFW check disabled for this topic")
        self._logger.info("Disabled NSFW checking for topic %s in chat %s", topic_id, chat_id)

<<<<<<< ours
    async def _handle_photo(self, message: Message) -> None:
        if not message.photo:
            return
        await self._process_media(message, message.photo[-1])

    async def _handle_document(self, message: Message) -> None:
        document = message.document
        if not document:
            return
        if not document.mime_type or not document.mime_type.startswith("image/"):
            return
        await self._process_media(message, document)

    async def _process_media(self, message: Message, media_object) -> None:
        if not self.storage.is_chat_enabled(message.chat.id):
            return
        if message.message_thread_id and self.storage.is_topic_ignored(
            message.chat.id, message.message_thread_id
        ):
            return
        if message.has_media_spoiler:
            return

        image_bytes = await self._download_media(message, media_object)
        if image_bytes is None:
            return

        try:
            is_nsfw = await self.detector.is_nsfw(image_bytes)
        except Exception as exc:  # pragma: no cover - defensive safety
            self._logger.exception("Failed to classify media in chat %s: %s", message.chat.id, exc)
            return

        if is_nsfw:
            await self._handle_nsfw_detection(message)

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

=======
>>>>>>> theirs

def get_module(*_) -> NsfwGuardModule:
    return NsfwGuardModule()


module = NsfwGuardModule()
router: Router = module.get_router()
priority = module.priority

