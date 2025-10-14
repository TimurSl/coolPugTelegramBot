import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from modules.moderation.command_restrictions import (
    _normalise_command_name,
    command_restrictions,
)
from modules.moderation.level_storage import moderation_levels
from utils.localization import gettext, language_from_message


class CommandRestrictionMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()
        logging.debug("CommandRestrictionMiddleware initialised")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            command_name = self._extract_command_name(event.text or event.caption)
            if command_name and event.chat and event.from_user:
                required_level = command_restrictions.get_command_level(
                    event.chat.id, command_name
                )
                if required_level is not None:
                    status = None
                    bot = data.get("bot")
                    if bot is not None:
                        try:
                            member = await bot.get_chat_member(
                                event.chat.id, event.from_user.id
                            )
                            status = getattr(member, "status", None)
                        except Exception as exc:
                            logging.debug(
                                "Failed to fetch chat member for command restriction: %s",
                                exc,
                            )
                    user_level = moderation_levels.get_effective_level(
                        event.chat.id,
                        event.from_user.id,
                        status=status,
                    )
                    if user_level < required_level:
                        language = language_from_message(event)
                        reply_text = gettext(
                            "moderation.command_restrict.denied",
                            language=language,
                            default="❌ Only level {level}+ members can use {command}.",
                            level=required_level,
                            command=f"/{command_name}",
                        )
                        await event.answer(reply_text, parse_mode=None)
                        return None
        return await handler(event, data)

    @staticmethod
    def _extract_command_name(text: Optional[str]) -> Optional[str]:
        if not text or not text.startswith("/"):
            return None
        first_part = text.split(maxsplit=1)[0]
        name = _normalise_command_name(first_part)
        return name or None
