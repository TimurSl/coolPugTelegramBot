"""Report and appeal handlers for the moderation module."""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, MessageEntity

from modules.moderation.level_storage import moderation_levels


class ReportsState(StatesGroup):
    awaiting_selection = State()


class AppealState(StatesGroup):
    awaiting_reason = State()


def _extract_message_text_with_links(message: Message) -> Optional[str]:
    """Return message text with inline links expanded to plain text."""

    text = getattr(message, "text", None)
    entities: Optional[Iterable[MessageEntity]] = getattr(message, "entities", None)

    if text is None:
        text = getattr(message, "caption", None)
        entities = getattr(message, "caption_entities", None)

    if not text:
        return None

    if not entities:
        return text

    parts: list[str] = []
    last_index = 0
    text_length = len(text)

    for entity in entities:
        start = max(0, min(entity.offset, text_length))
        end = max(start, min(start + entity.length, text_length))
        if start < last_index:
            continue

        parts.append(text[last_index:start])
        entity_text = text[start:end]

        if entity.type == "text_link" and entity.url:
            parts.append(f"{entity_text} ({entity.url})")
        else:
            parts.append(entity_text)

        last_index = end

    parts.append(text[last_index:])
    return "".join(parts)


async def handle_report(module: "AdvancedModerationModule", message: Message) -> None:
    language = module._language(message)

    if message.chat.type == "private":
        await message.reply(
            module._t(
                "moderation.report.only_groups",
                language,
                "❌ You can only use this command in group chats.",
            ),
            parse_mode=None,
        )
        return

    target = message.reply_to_message
    if not target:
        await message.reply(
            module._t(
                "moderation.report.reply_required",
                language,
                "❌ Reply to the message you want to report.",
            ),
            parse_mode=None,
        )
        return

    target_user = getattr(target, "from_user", None)
    target_user_id = getattr(target_user, "id", None)
    if target_user and getattr(target_user, "is_bot", False):
        await message.reply(
            module._t(
                "moderation.report.target_is_bot",
                language,
                "❌ You cannot report bot messages.",
            ),
            parse_mode=None,
        )
        return
    target_user_name = None
    if target_user:
        target_user_name = (
            getattr(target_user, "full_name", None)
            or getattr(target_user, "username", None)
        )

    message_text = _extract_message_text_with_links(target)

    module.db.add_report(
        chat_id=message.chat.id,
        chat_title=getattr(message.chat, "title", None),
        chat_username=getattr(message.chat, "username", None),
        message_id=target.message_id,
        reporter_id=message.from_user.id,
        target_user_id=target_user_id,
        target_user_name=target_user_name,
        message_text=message_text,
        has_photo=bool(getattr(target, "photo", None)),
        has_video=bool(getattr(target, "video", None)),
    )

    await message.reply(
        module._t(
            "moderation.report.received",
            language,
            "✅ Report submitted. Moderators will review it in their direct messages.",
        ),
        parse_mode=None,
    )


async def handle_reports_overview(
    module: "AdvancedModerationModule", message: Message, bot: Bot, state: FSMContext
) -> None:
    language = module._language(message)

    if message.chat.type != "private":
        await message.reply(
            module._t(
                "moderation.report.dm_only",
                language,
                "❌ Use this command in a private chat with the bot.",
            ),
            parse_mode=None,
        )
        return

    await state.clear()

    raw_reports = module.db.list_reports()
    reports = await module._filter_reports_for_admin(bot, message.from_user.id, raw_reports)
    stored_levels = moderation_levels.get_chats_for_user(message.from_user.id)
    is_admin_any = bool(reports) or any(level >= 1 for level in stored_levels.values())

    if not is_admin_any:
        await message.answer(
            module._t(
                "moderation.report.not_admin",
                language,
                "❌ You are not a moderator in any tracked chats.",
            ),
            parse_mode=None,
        )
        return

    appeals = module.db.list_appeals()

    if not reports and not appeals:
        await message.answer(
            module._t(
                "moderation.report.empty",
                language,
                "There are no pending reports or appeals right now.",
            ),
            parse_mode=None,
        )
        return

    entries, mapping = module._build_overview_entries(reports, appeals, language)
    text, markup, page, total_pages = module._render_reports_overview_page(
        entries=entries,
        language=language,
        page=0,
        per_page=module._reports_overview_page_size,
    )

    message_obj = await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=markup,
        disable_web_page_preview=True,
    )

    await state.update_data(
        entries=mapping,
        display_entries=entries,
        page=page,
        per_page=module._reports_overview_page_size,
        overview_message_id=message_obj.message_id,
        overview_chat_id=message_obj.chat.id,
        requester_id=message.from_user.id,
        language=language,
        total_pages=total_pages,
    )
    await state.set_state(ReportsState.awaiting_selection)


async def handle_report_selection(
    module: "AdvancedModerationModule", message: Message, bot: Bot, state: FSMContext
) -> None:
    data = await state.get_data()
    entries: list[dict[str, object]] = data.get("entries") or []
    if not entries:
        await message.answer(
            module._t(
                "moderation.report.selection.no_active_menu",
                module._language(message),
                "Use /reports to request the overview again.",
            ),
            parse_mode=None,
        )
        return

    requester_id = data.get("requester_id")
    if requester_id and requester_id != message.from_user.id:
        await message.answer(
            module._t(
                "moderation.report.selection.only_requester",
                module._language(message),
                "Only the moderator who opened the menu can select entries.",
            ),
            parse_mode=None,
        )
        return

    language = data.get("language") or module._language(message)

    raw_reports = module.db.list_reports()
    reports = await module._filter_reports_for_admin(bot, message.from_user.id, raw_reports)
    allowed_ids = {report.get("id") for report in reports}

    entries = [
        entry
        for entry in entries
        if entry.get("type") != "report" or entry.get("id") in allowed_ids
    ]

    if not entries:
        await message.answer(
            module._t(
                "moderation.report.selection.no_longer_available",
                language,
                "No entries available. Use /reports to refresh the list.",
            ),
            parse_mode=None,
        )
        return

    text_value = (message.text or "").strip()
    if text_value.startswith("/"):
        return

    if not text_value.isdigit():
        await message.answer(
            module._t(
                "moderation.report.selection.number_required",
                language,
                "Please send the number from the list to view the entry.",
            ),
            parse_mode=None,
        )
        return

    selection = int(text_value)
    if selection < 1 or selection > len(entries):
        await message.answer(
            module._t(
                "moderation.report.selection.out_of_range",
                language,
                "The selected number is outside of the available range.",
            ),
            parse_mode=None,
        )
        return

    entry = entries[selection - 1]
    entry_type = entry.get("type")
    entry_id = entry.get("id")

    if entry_type == "report":
        report = module.db.get_report(int(entry_id)) if entry_id is not None else None
        if not report:
            await message.answer(
                module._t(
                    "moderation.report.selection.report_missing",
                    language,
                    "This report is no longer available.",
                ),
                parse_mode=None,
            )
            return

        text, keyboard = module._build_report_detail_view(report, language)
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return

    if entry_type == "appeal":
        appeal = module.db.get_appeal(int(entry_id)) if entry_id is not None else None
        if not appeal:
            await message.answer(
                module._t(
                    "moderation.report.selection.appeal_missing",
                    language,
                    "This appeal is no longer available.",
                ),
                parse_mode=None,
            )
            return

        text, keyboard = module._build_appeal_detail_view(appeal, language)
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return

    await message.answer(
        module._t(
            "moderation.report.selection.unknown_entry",
            language,
            "Unknown entry type. Please request the list again with /reports.",
        ),
        parse_mode=None,
    )


async def handle_reports_page_callback(
    module: "AdvancedModerationModule", callback: CallbackQuery, state: FSMContext
) -> None:
    data = await state.get_data()
    entries: list[dict[str, object]] = data.get("display_entries") or []
    if not entries:
        await callback.answer()
        return

    per_page = data.get("per_page", module._reports_overview_page_size)
    try:
        requested_page = int((callback.data or "").split(":")[2])
    except (IndexError, ValueError):
        await callback.answer()
        return

    current_page = data.get("page", 0)
    if requested_page == current_page:
        await callback.answer()
        return

    language = data.get("language") or module._language(callback.message)
    text, markup, page, _ = module._render_reports_overview_page(
        entries=entries,
        language=language,
        page=requested_page,
        per_page=per_page,
    )

    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=markup,
        )
    except TelegramAPIError as exc:
        logging.debug("Failed to edit reports overview page: %s", exc)

    await state.update_data(page=page)
    await callback.answer()


async def handle_report_close_callback(
    module: "AdvancedModerationModule", callback: CallbackQuery, state: FSMContext
) -> None:
    payload = (callback.data or "").split(":")
    if len(payload) != 4:
        await callback.answer()
        return

    _, action, entry_type, entry_id_raw = payload
    if action != "close":
        await callback.answer()
        return

    try:
        entry_id = int(entry_id_raw)
    except ValueError:
        await callback.answer()
        return

    state_data = await state.get_data()
    language = state_data.get("language") or module._language(callback.message)

    if entry_type == "report":
        report = module.db.get_report(entry_id)
        if not report:
            await callback.answer(
                module._t(
                    "moderation.report.selection.report_missing",
                    language,
                    "This report is no longer available.",
                ),
                show_alert=True,
            )
            return

        if (report.get("status") or "open").lower() == "closed":
            text, markup = module._build_report_detail_view(report, language)
            try:
                await callback.message.edit_text(
                    text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=markup,
                )
            except TelegramAPIError as exc:
                logging.debug(
                    "Failed to edit report detail message: %s",
                    exc,
                )
            await callback.answer(
                module._t(
                    "moderation.report.selection.close_already",
                    language,
                    "Report already closed.",
                )
            )
            return

        closer = callback.from_user
        closed_by_id = closer.id if closer else None
        closed_by_name = closer.full_name if closer else None

        module.db.update_report_status(
            entry_id,
            "closed",
            closed_by=closed_by_id,
            closed_by_name=closed_by_name,
        )
        report["status"] = "closed"
        if closed_by_id is not None:
            report["closed_by_user_id"] = closed_by_id
        if closed_by_name:
            report["closed_by_user_name"] = closed_by_name
        text, markup = module._build_report_detail_view(report, language)
        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
            )
        except TelegramAPIError as exc:
            logging.debug(
                "Failed to edit report detail message: %s",
                exc,
            )
        await callback.answer(
            module._t(
                "moderation.report.selection.close_success",
                language,
                "Report closed.",
            )
        )
        await module._refresh_reports_overview_message(
            bot=callback.bot,
            state=state,
            user_id=callback.from_user.id,
            language=language,
        )
        return

    if entry_type == "appeal":
        appeal = module.db.get_appeal(entry_id)
        if not appeal:
            await callback.answer(
                module._t(
                    "moderation.report.selection.appeal_missing",
                    language,
                    "This appeal is no longer available.",
                ),
                show_alert=True,
            )
            return

        if (appeal.get("status") or "open").lower() == "closed":
            text, markup = module._build_appeal_detail_view(appeal, language)
            try:
                await callback.message.edit_text(
                    text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=markup,
                )
            except TelegramAPIError as exc:
                logging.debug(
                    "Failed to edit appeal detail message: %s",
                    exc,
                )
            await callback.answer(
                module._t(
                    "moderation.report.selection.close_appeal_already",
                    language,
                    "Appeal already closed.",
                )
            )
            return

        module.db.update_appeal_status(entry_id, "closed")
        appeal["status"] = "closed"
        text, markup = module._build_appeal_detail_view(appeal, language)
        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
            )
        except TelegramAPIError as exc:
            logging.debug(
                "Failed to edit appeal detail message: %s",
                exc,
            )
        await callback.answer(
            module._t(
                "moderation.report.selection.close_appeal_success",
                language,
                "Appeal closed.",
            )
        )
        await module._refresh_reports_overview_message(
            bot=callback.bot,
            state=state,
            user_id=callback.from_user.id,
            language=language,
        )
        return

    await callback.answer()


async def handle_main_menu(
    module: "AdvancedModerationModule", message: Message, state: FSMContext
) -> None:
    language = module._language(message)
    await state.clear()
    await message.answer(
        module._t(
            "moderation.menu.exit_confirmation",
            language,
            "🏠 You're back in the main menu. Use /help to see available commands.",
        ),
        parse_mode=None,
    )


async def handle_appeal(
    module: "AdvancedModerationModule", message: Message, state: FSMContext
) -> None:
    language = module._language(message)

    if message.chat.type != "private":
        await message.reply(
            module._t(
                "moderation.appeal.dm_only",
                language,
                "❌ Send appeals to the bot in a private chat.",
            ),
            parse_mode=None,
        )
        return

    await state.set_state(AppealState.awaiting_reason)
    await message.answer(
        module._t(
            "moderation.appeal.prompt",
            language,
            "Please describe why you believe the punishment was a mistake.",
        ),
        parse_mode=None,
    )


async def handle_appeal_reason(
    module: "AdvancedModerationModule", message: Message, state: FSMContext
) -> None:
    if message.chat.type != "private":
        return

    reason = (message.text or "").strip()
    if not reason:
        await message.answer(
            "Please send a text description for your appeal.",
            parse_mode=None,
        )
        return

    module.db.add_appeal(message.from_user.id, reason)
    await state.clear()
    await message.answer(
        "✅ Your appeal has been submitted. Moderators will reach out in private messages if they need more details.",
        parse_mode=None,
    )


from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported only for typing
    from modules.moderation.router import AdvancedModerationModule
