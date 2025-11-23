"""Module router for NSFW image moderation."""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from modules.base import Module
from modules.nsfw_guard.detector import NsfwDetectionService
from modules.nsfw_guard.middleware import ModerationWarningService, NsfwGuardMiddleware
from modules.nsfw_guard.storage import NsfwSettingsStorage


class NsfwGuardModule(Module):
    """Moderate images using a NSFW classifier with chat/topic controls."""

    OWNER_IDS = {999034568}

    def __init__(
        self,
        storage: Optional[NsfwSettingsStorage] = None,
        detector: Optional[NsfwDetectionService] = None,
        warning_service: Optional[ModerationWarningService] = None,
    ) -> None:
        super().__init__(name="nsfw_guard", priority=5)
        self.storage = storage or NsfwSettingsStorage()
        self.detector = detector or NsfwDetectionService()
        self.warning_service = warning_service or ModerationWarningService()
        self.middleware = NsfwGuardMiddleware(
            self.storage, self.detector, self.warning_service
        )
        self._logger = logging.getLogger(__name__)

        self.router.message.middleware(self.middleware)
        self.router.message.register(self._handle_dontcheck, Command("dontcheck"))
        self.router.message.register(self._handle_enable_for, Command("enablefor"))

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
            await message.answer("Usage: /enablefor <chat_id>", parse_mode=None)
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

def get_module(*_) -> NsfwGuardModule:
    return NsfwGuardModule()


module = NsfwGuardModule()
router: Router = module.get_router()
priority = module.priority

