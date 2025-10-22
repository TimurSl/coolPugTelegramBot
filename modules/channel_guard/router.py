from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import F
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Chat, Message
from aiogram import Bot

from modules.base import Module


@dataclass(frozen=True)
class _ForwardDetails:
    chat_type: Optional[str]
    is_automatic_forward: bool

    @classmethod
    def from_message(cls, message: Message) -> "_ForwardDetails":
        forward_chat = getattr(message, "forward_from_chat", None)
        chat_type = getattr(forward_chat, "type", None)
        return cls(
            chat_type=chat_type,
            is_automatic_forward=bool(getattr(message, "is_automatic_forward", False)),
        )

    def is_channel_forward(self) -> bool:
        return self.is_automatic_forward and self.chat_type == "channel"


class AutoUnpinModule(Module):
    """Automatically unpin channel posts forwarded into discussion chats."""

    def __init__(self) -> None:
        super().__init__("auto_unpin", priority=30)
        self._logger = logging.getLogger(__name__)

    def get_router(self):  # type: ignore[override]
        return super().get_router()

    async def register(self, container) -> None:  # type: ignore[override]
        self.router.message.register(
            self._handle_channel_forward,
            F.is_automatic_forward == True,
        )
        self.router.message.register(
            self._handle_pinned_service,
            F.pinned_message,
        )

    async def _handle_channel_forward(self, message: Message, bot: Bot) -> None:
        if not self.enabled:
            return

        if not self._is_group_chat(message.chat):
            return

        details = _ForwardDetails.from_message(message)
        if not details.is_channel_forward():
            return

        await self._unpin_message(bot, message.chat.id, message.message_id)

    async def _handle_pinned_service(self, message: Message, bot: Bot) -> None:
        if not self.enabled:
            return

        if not self._is_group_chat(message.chat):
            return

        pinned = message.pinned_message
        if pinned is None:
            return

        details = _ForwardDetails.from_message(pinned)
        if not details.is_channel_forward():
            return

        await self._unpin_message(bot, message.chat.id, pinned.message_id)

    async def _unpin_message(self, bot: Bot, chat_id: int, message_id: int) -> None:
        try:
            await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
            self._logger.debug(
                "Unpinned channel forward in chat %s (message %s)",
                chat_id,
                message_id,
            )
        except TelegramAPIError as exc:
            self._logger.debug(
                "Unable to unpin message %s in chat %s: %s",
                message_id,
                chat_id,
                exc,
            )

    @staticmethod
    def _is_group_chat(chat: Optional[Chat]) -> bool:
        if chat is None:
            return False
        return chat.type in {"group", "supergroup"}


module = AutoUnpinModule()
router = module.get_router()
priority = module.priority