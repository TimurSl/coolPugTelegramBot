import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User

from modules.collector.utils import UserCollector
from modules.roleplay.router import (
    _escape_markdown,
    _get_display_name,
    build_action_text,
    format_roleplay_profile_reference,
    rp_config,
)


class RoleplayMiddleware(BaseMiddleware):
    """Middleware that handles inline RP commands when replying or mentioning."""

    def __init__(self, config=None):
        super().__init__()
        self.config = config or rp_config
        logging.debug(
            "RoleplayMiddleware initialised with config=%s", type(self.config).__name__
        )

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message):
            try:
                handled = await self._handle_roleplay(event)
                if handled:
                    # If middleware handled the roleplay command, don't call the handler
                    return None
            except Exception:
                logging.exception(
                    "Unexpected error during roleplay middleware for message_id=%s",
                    getattr(event, "message_id", None),
                )

        # Only call handler if message wasn't handled by roleplay middleware
        result = await handler(event, data)
        return result

    async def _handle_roleplay(self, message: Message) -> bool:
        if not message.text:
            return False

        actor = message.from_user
        if not actor:
            return False

        text = message.text.strip()

        if message.reply_to_message:
            command = self.config.get_command(message.chat.id, text)
            if command:
                target = message.reply_to_message.from_user
                if not target:
                    return False

                response_text = self._build_response_text(
                    message.chat.id,
                    command,
                    actor,
                    (target.id, target.full_name),
                )
                media = command.get("media") or {}
                await self._send_media_response(message, media, response_text)
                return True

        command_keyword, remainder = self._split_command_and_remainder(text)
        if not command_keyword or not remainder:
            return False

        command = self.config.get_command(message.chat.id, command_keyword)
        if not command:
            return False

        username = self._extract_username(remainder)
        if not username:
            return False

        target_id = UserCollector.get_id(username)
        if target_id:
            target_info: Optional[Tuple[int, str]] = (target_id, f"@{username}")
        else:
            target_info = None

        response_text = self._build_response_text(
            message.chat.id,
            command,
            actor,
            target_info,
            fallback_username=username,
        )

        media = command.get("media") or {}
        await self._send_media_response(message, media, response_text)
        return True

    def _split_command_and_remainder(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        if not text:
            return None, None

        parts = text.split(maxsplit=1)
        if not parts:
            return None, None

        command = parts[0].strip().strip(".,!?:;")
        remainder = parts[1].strip() if len(parts) > 1 else None
        return command or None, remainder or None

    def _extract_username(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None

        match = re.search(r"@([A-Za-z0-9_]{1,32})", text)
        if not match:
            return None
        return match.group(1)

    def _build_response_text(
        self,
        chat_id: int,
        command: Dict[str, Any],
        actor: User,
        target_info: Optional[Tuple[int, str]],
        *,
        fallback_username: Optional[str] = None,
    ) -> str:
        action_text = build_action_text(command["action"], command.get("random_variants"))
        actor_name = _get_display_name(chat_id, actor.id, actor.full_name)
        actor_part = format_roleplay_profile_reference(
            actor_name,
            actor.id,
            name_is_escaped=True,
        )

        target_part: str
        if target_info:
            target_id, fallback = target_info
            target_name = _get_display_name(chat_id, target_id, fallback)
            target_part = format_roleplay_profile_reference(
                target_name,
                target_id,
                name_is_escaped=True,
            )
        elif fallback_username:
            target_part = _escape_markdown(f"@{fallback_username}")
        else:
            target_part = _escape_markdown("@unknown")

        return f"{command['emoji']} | {actor_part} {action_text} {target_part}"
    async def _send_media_response(self, message: Message, media: Dict[str, Any], text: str) -> None:
        target_message = message.reply_to_message or message
        media_type = media.get("type")
        file_id = media.get("file_id")

        if media_type == "photo" and file_id:
            await target_message.reply_photo(file_id, caption=text, parse_mode="Markdown", disable_web_page_preview=True)
        elif media_type == "animation" and file_id:
            await target_message.reply_animation(file_id, caption=text, parse_mode="Markdown", disable_web_page_preview=True)
        elif media_type == "video" and file_id:
            await target_message.reply_video(file_id, caption=text, parse_mode="Markdown", disable_web_page_preview=True)
        elif media_type == "sticker" and file_id:
            await target_message.reply_sticker(file_id)
            await target_message.reply(text, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await target_message.reply(text, parse_mode="Markdown", disable_web_page_preview=True)

    async def _safe_delete(self, message: Message) -> None:
        try:
            #await message.delete()
            pass
        except Exception:
            logging.debug(
                "Failed to delete roleplay command message_id=%s",
                getattr(message, "message_id", None),
            )
