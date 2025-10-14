"""Mod log related handlers for the moderation module."""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message


async def handle_modlogs(
    module: "AdvancedModerationModule", message: Message, bot: Bot
) -> None:
    language = module._language(message)

    if message.chat.type != "private":
        await message.reply(
            module._t(
                "moderation.modlogs.dm_only",
                language,
                "❌ Open mod logs in a private chat with the bot.",
            ),
            parse_mode=None,
        )
        return

    chat_ids = await module._collect_level5_chats(bot, message.from_user.id)
    if not chat_ids:
        await message.answer(
            module._t(
                "moderation.modlogs.permission",
                language,
                "❌ Only level 5 moderators can view the moderation logs.",
            ),
            parse_mode=None,
        )
        return

    text, markup, has_entries = await module._render_modlogs(
        bot=bot,
        chat_ids=chat_ids,
        page=0,
        user_id=message.from_user.id,
        language=language,
    )

    if not has_entries:
        await message.answer(text, parse_mode="HTML")
        return

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=markup,
        disable_web_page_preview=True,
    )


async def handle_modlogs_callback(
    module: "AdvancedModerationModule", query: CallbackQuery, bot: Bot
) -> None:
    if not query.data or not query.message:
        await query.answer()
        return

    try:
        prefix, user_id_str, page_str = query.data.split(":", 2)
        if prefix != "modlogs":
            await query.answer()
            return
        expected_user_id = int(user_id_str)
        page = max(int(page_str), 0)
    except ValueError:
        await query.answer()
        return

    if query.from_user.id != expected_user_id:
        await query.answer("This menu belongs to another moderator.", show_alert=True)
        return

    language = module._language(query.message)
    chat_ids = await module._collect_level5_chats(bot, query.from_user.id)
    if not chat_ids:
        await query.answer("You no longer have permission to view these logs.", show_alert=True)
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        return

    text, markup, has_entries = await module._render_modlogs(
        bot=bot,
        chat_ids=chat_ids,
        page=page,
        user_id=query.from_user.id,
        language=language,
    )

    if not has_entries:
        await query.answer("No more entries on this page.")
        return

    await query.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    await query.answer()


from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - only used for typing hints
    from modules.moderation.router import AdvancedModerationModule
