"""Settings related bot commands."""

from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from modules.moderation.command_restrictions import (
    extract_command_name,
    get_effective_command_level,
)
from modules.moderation.level_storage import moderation_levels
from utils.chat_settings import chat_language_storage
from utils.localization import (
    SUPPORTED_LANGUAGES,
    gettext,
    language_from_message,
    localization_manager,
    normalize_language_code,
)


router = Router(name="settings")
priority = 2


async def _get_member_level(message: Message, user_id: int) -> int:
    if message.chat.type == ChatType.PRIVATE:
        logging.getLogger(__name__).debug(
            "Detected private chat; granting maximum level for user %s", user_id
        )
        return 5

    status = None
    bot = getattr(message, "bot", None)
    if bot is not None:
        try:
            member = await bot.get_chat_member(message.chat.id, user_id)
            status = getattr(member, "status", None)
        except Exception:
            status = None

    if status is None:
        try:
            member = await message.chat.get_member(user_id)
            status = getattr(member, "status", None)
        except Exception:
            status = None

    level = moderation_levels.get_effective_level(
        message.chat.id, user_id, status=status
    )
    return level


@router.message(Command("language"))
async def handle_language_command(message: Message) -> None:
    logger = logging.getLogger(__name__)
    ui_language = language_from_message(message)
    command_name = extract_command_name(message.text or message.caption)
    candidates = []
    if command_name:
        candidates.append(command_name)
    candidates.append("language")
    required_level = get_effective_command_level(
        message.chat.id,
        candidates[0],
        5,
        aliases=candidates[1:],
    )
    actor_level = await _get_member_level(message, message.from_user.id)
    if actor_level < required_level:
        logger.info(
            "User %s lacks level %s for /language in chat %s",
            message.from_user.id,
            required_level,
            message.chat.id,
        )
        await message.answer(
            gettext(
                "settings.language.permission_denied",
                language=ui_language,
                default="❌ Only level {level}+ members can change the chat language.",
                level=required_level,
            )
        )
        return

    raw_text = (message.text or message.caption or "").strip()
    parts = raw_text.split(maxsplit=1)
    args = parts[1].strip() if len(parts) > 1 else ""

    current_language = chat_language_storage.get_language(message.chat.id) or localization_manager.default_language
    available_codes = ", ".join(sorted(SUPPORTED_LANGUAGES))
    escaped_codes = html.escape(available_codes)
    escaped_current = html.escape(current_language)

    if not args:
        logger.debug(
            "User %s requested /language help in chat %s",
            message.from_user.id,
            message.chat.id,
        )
        await message.answer(
            gettext(
                "settings.language.usage",
                language=ui_language,
                default="Usage: /language [{languages}] (send /language default to reset). Current: {current}.",
                languages=escaped_codes,
                current=escaped_current,
            ),
            parse_mode=None,
        )
        return

    argument = args.split()[0].lower()
    escaped_argument = html.escape(argument)
    if argument in {"default", "reset"}:
        chat_language_storage.clear_language(message.chat.id)
        default_language = localization_manager.default_language
        logger.info(
            "Chat %s language reset by user %s",
            message.chat.id,
            message.from_user.id,
        )
        await message.answer(
            gettext(
                "settings.language.reset",
                language=normalize_language_code(default_language),
                default="✅ Chat language reset to default ({code}).",
                code=html.escape(default_language),
            )
        )
        return

    if argument not in SUPPORTED_LANGUAGES:
        logger.debug(
            "Unsupported language %s requested in chat %s by user %s",
            argument,
            message.chat.id,
            message.from_user.id,
        )
        await message.answer(
            gettext(
                "settings.language.unsupported",
                language=ui_language,
                default="❌ Unsupported language '{code}'. Available: {languages}.",
                code=escaped_argument,
                languages=escaped_codes,
            )
        )
        return

    chat_language_storage.set_language(message.chat.id, argument)
    logger.info(
        "Chat %s language set to %s by user %s",
        message.chat.id,
        argument,
        message.from_user.id,
    )
    await message.answer(
        gettext(
            "settings.language.set",
            language=argument,
            default="✅ Chat language set to {code}.",
            code=escaped_argument,
        )
    )
