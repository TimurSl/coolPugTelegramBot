import logging
import sqlite3
from contextlib import suppress
from datetime import timedelta, datetime
from typing import Optional, Sequence
import html
import textwrap

from aiogram import Bot, Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    ChatPermissions,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from modules.collector.utils import UserCollector
from modules.moderation.arg_parser import ModerationArgParser
from modules.moderation.data import ModerationAction, ModerationDatabase
from modules.moderation.command_restrictions import (
    _normalise_command_name,
    command_restrictions,
    extract_command_name,
    get_effective_command_level,
)
from modules.moderation import award_module, modlogs_module, report_module
from modules.moderation.report_module import AppealState, ReportsState
from modules.moderation.level_storage import moderation_levels
from modules.moderation.permission_check import PermissionChecker
from modules.roleplay.nickname_storage import CustomNicknameStorage
from utils.localization import gettext, language_from_message, normalize_language_code
from utils.path_utils import get_home_dir
from utils.time_utils import TimeUtils
import math
import os


nickname_storage = CustomNicknameStorage()


def _escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def _build_profile_link(user_id: int) -> str:
    username = UserCollector.get_username(user_id)
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


def _format_profile_reference(label: str, user_id: int) -> str:
    """HTML-ссылка на профиль"""
    profile_link = _build_profile_link(user_id)
    # простое html-экранирование имени
    safe_label = (
        label.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
    )
    return f'<a href="{profile_link}">{safe_label}</a>'



def _strip_leading_at(text: str) -> str:
    if text.startswith("@"):
        return text[1:]
    return text


class AdvancedModerationModule:
    """Advanced moderation module with flexible command parsing"""

    def __init__(self):
        self.router = Router(name="moderation")
        self.db = ModerationDatabase(os.path.join(get_home_dir(), "moderation.db"))
        self._modlogs_page_size = 6
        self._reports_overview_page_size = 10
        self._report_history_page_size = 10
        self._modlog_labels = {
            "ban": "Banned",
            "unban": "Unbanned",
            "mute": "Muted",
            "unmute": "Unmuted",
            "warn": "Warned",
            "unwarn": "Removed warning from",
            "kick": "Kicked",
            "award": "Awarded",
            "delreward": "Removed award from",
        }

    def _language(self, message: Message) -> str:
        return language_from_message(message)

    def _t(self, key: str, language: str, default: str, **kwargs) -> str:
        return gettext(key, language=language, default=default, **kwargs)

    def _format_user_link(
        self,
        user_id: Optional[int],
        *,
        fallback: str,
        chat_id: Optional[int] = None,
        stored_name: Optional[str] = None,
    ) -> str:
        if user_id is None:
            return html.escape(stored_name or fallback)

        display = stored_name
        if not display and chat_id is not None:
            display = UserCollector.get_display_name(chat_id, user_id)
        if not display:
            display = UserCollector.get_username(user_id)
        if not display:
            display = fallback
        safe_display = html.escape(display)
        return f'<a href="{_build_profile_link(user_id)}">{safe_display}</a>'

    def _build_message_url(
        self, chat_id: int, message_id: int, username: Optional[str]
    ) -> str:
        if username:
            return f"https://t.me/{username}/{message_id}"
        chat_id_str = str(chat_id)
        if chat_id_str.startswith("-100"):
            return f"https://t.me/c/{chat_id_str[4:]}/{message_id}"
        if chat_id < 0:
            return f"https://t.me/c/{chat_id_str[1:]}/{message_id}"
        return f"tg://openmessage?chat_id={chat_id}&message_id={message_id}"

    def _shorten_preview(self, text: Optional[str]) -> str:
        base = (text or "").replace("\n", " ").strip()
        if not base:
            base = "[no text]"
        shortened = textwrap.shorten(base, width=60, placeholder="…")
        return html.escape(shortened)

    def _compose_report_summary(self, entry: dict) -> str:
        emoji_prefix = ""
        if entry.get("has_photo"):
            emoji_prefix += "🖼️ "
        if entry.get("has_video"):
            emoji_prefix += "🎞️ "
        return f"{emoji_prefix}{self._shorten_preview(entry.get('message_text'))}"

    def _compose_appeal_summary(self, entry: dict) -> str:
        return self._shorten_preview(entry.get("description"))

    def _build_overview_entries(
        self,
        reports: list[dict],
        appeals: list[dict],
        language: str,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        entries: list[dict[str, object]] = []
        mapping: list[dict[str, object]] = []
        index = 1

        for entry in reports:
            chat_label = html.escape(entry.get("chat_title") or str(entry.get("chat_id")))
            summary = self._compose_report_summary(entry)
            entries.append(
                {
                    "section": "report",
                    "text": f"{index}. {chat_label}: {summary}",
                    "type": "report",
                    "id": entry.get("id"),
                }
            )
            mapping.append({"type": "report", "id": entry.get("id")})
            index += 1

        for entry in appeals:
            user_link = self._format_user_link(
                entry.get("user_id"),
                fallback=str(entry.get("user_id") or "unknown"),
            )
            summary = self._compose_appeal_summary(entry)
            entries.append(
                {
                    "section": "appeal",
                    "text": f"{index}. {user_link}: {summary}",
                    "type": "appeal",
                    "id": entry.get("id"),
                }
            )
            mapping.append({"type": "appeal", "id": entry.get("id")})
            index += 1

        return entries, mapping

    def _render_reports_overview_page(
        self,
        *,
        entries: list[dict[str, object]],
        language: str,
        page: int,
        per_page: int,
    ) -> tuple[str, InlineKeyboardMarkup, int, int]:
        total_entries = len(entries)
        total_pages = max(1, math.ceil(total_entries / per_page)) if total_entries else 1
        page = max(0, min(page, total_pages - 1))

        start = page * per_page
        end = start + per_page
        page_entries = entries[start:end]

        lines: list[str] = []
        current_section: Optional[str] = None
        for entry in page_entries:
            section = entry.get("section")
            if section != current_section:
                if section == "report":
                    lines.append("<b>Reports:</b>")
                elif section == "appeal":
                    lines.append("<b>Appeals:</b>")
                current_section = section
            lines.append(str(entry.get("text")))

        if lines:
            lines.append("")
        lines.append(
            self._t(
                "moderation.report.instructions",
                language,
                "Send the number of an entry to view full details.",
            )
        )
        lines.append(
            self._t(
                "moderation.report.exit_hint",
                language,
                "Send /menu to leave this menu.",
            )
        )

        text = "\n".join(lines)

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        if total_pages > 1:
            buttons: list[InlineKeyboardButton] = []
            for idx in range(total_pages):
                label = str(idx + 1)
                if idx == page:
                    label = f"[{label}]"
                buttons.append(
                    InlineKeyboardButton(
                        text=label,
                        callback_data=f"reports:page:{idx}",
                    )
                )
            for offset in range(0, len(buttons), 5):
                keyboard_rows.append(buttons[offset : offset + 5])

        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=self._t(
                        "moderation.report.exit_button",
                        language,
                        "🏠 Back to menu",
                    ),
                    callback_data="reports:exit",
                )
            ]
        )

        markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        return text, markup, page, total_pages

    def _build_report_detail_view(
        self, report: dict, language: str
    ) -> tuple[str, Optional[InlineKeyboardMarkup]]:
        chat_name = html.escape(report.get("chat_title") or str(report.get("chat_id")))
        reporter_link = self._format_user_link(
            report.get("reporter_id"),
            fallback=str(report.get("reporter_id") or "unknown"),
            chat_id=report.get("chat_id"),
        )
        target_link = self._format_user_link(
            report.get("target_user_id"),
            fallback=str(report.get("target_user_id") or "unknown"),
            chat_id=report.get("chat_id"),
            stored_name=report.get("target_user_name"),
        )

        created_text = self._format_datetime(report.get("created_at"))
        message_body = html.escape(report.get("message_text") or "").replace(
            "\n", "<br>"
        )
        if not message_body:
            message_body = self._t(
                "moderation.report.selection.no_text",
                language,
                "<i>No text was attached to this message.</i>",
            )

        attachments: list[str] = []
        if report.get("has_photo"):
            attachments.append(
                html.escape(
                    self._t(
                        "moderation.report.selection.attachment.photo",
                        language,
                        "photo",
                    )
                )
            )
        if report.get("has_video"):
            attachments.append(
                html.escape(
                    self._t(
                        "moderation.report.selection.attachment.video",
                        language,
                        "video",
                    )
                )
            )

        details = [
            f"<b>Report #{report['id']}</b>",
            f"Chat: {chat_name}",
            f"Reporter: {reporter_link}",
            f"Target: {target_link}",
            f"Created: {created_text}",
            "",
            message_body,
        ]

        if attachments:
            details.append("")
            details.append(
                self._t(
                    "moderation.report.selection.contains",
                    language,
                    "<i>Contains: {items}</i>",
                    items=", ".join(attachments),
                )
            )

        status = (report.get("status") or "open").lower()
        status_label = self._t(
            f"moderation.report.selection.status.{status}",
            language,
            status,
        )
        details.append("")
        details.append(
            self._t(
                "moderation.report.selection.status",
                language,
                "Status: {status}",
                status=status_label,
            )
        )

        if status == "closed":
            closed_by_id = report.get("closed_by_user_id")
            closed_by_name = report.get("closed_by_user_name")
            if closed_by_id is not None or closed_by_name:
                fallback = closed_by_name or str(closed_by_id or "unknown")
                closed_by_link = self._format_user_link(
                    closed_by_id,
                    fallback=fallback,
                    chat_id=report.get("chat_id"),
                    stored_name=closed_by_name,
                )
                details.append(
                    self._t(
                        "moderation.report.selection.closed_by",
                        language,
                        "Closed by: {user}",
                        user=closed_by_link,
                    )
                )

        chat_id_value = report.get("chat_id")
        message_id_value = report.get("message_id")
        message_url = None
        if chat_id_value is not None and message_id_value is not None:
            message_url = self._build_message_url(
                int(chat_id_value),
                int(message_id_value),
                report.get("chat_username"),
            )

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        if message_url:
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text=self._t(
                            "moderation.report.selection.open_message",
                            language,
                            "Go To Message",
                        ),
                        url=message_url,
                    )
                ]
            )

        if status != "closed":
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text=self._t(
                            "moderation.report.selection.close_button",
                            language,
                            "✅ Close report",
                        ),
                        callback_data=f"reports:close:report:{report['id']}",
                    )
                ]
            )

        markup = (
            InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
            if keyboard_rows
            else None
        )
        return "\n".join(details), markup

    def _build_appeal_detail_view(
        self, appeal: dict, language: str
    ) -> tuple[str, Optional[InlineKeyboardMarkup]]:
        user_link = self._format_user_link(
            appeal.get("user_id"),
            fallback=str(appeal.get("user_id") or "unknown"),
        )
        created_text = self._format_datetime(appeal.get("created_at"))
        description = html.escape(appeal.get("description") or "").replace(
            "\n", "<br>"
        )
        if not description:
            description = self._t(
                "moderation.report.selection.no_description",
                language,
                "<i>No description provided.</i>",
            )

        status = (appeal.get("status") or "open").lower()
        status_label = self._t(
            f"moderation.report.selection.status.{status}",
            language,
            status,
        )

        details = [
            f"<b>Appeal #{appeal['id']}</b>",
            f"User: {user_link}",
            f"Created: {created_text}",
            "",
            description,
            "",
            self._t(
                "moderation.report.selection.status",
                language,
                "Status: {status}",
                status=status_label,
            ),
        ]

        keyboard_rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text=self._t(
                        "moderation.report.selection.open_dm",
                        language,
                        "Go To DM",
                    ),
                    url=_build_profile_link(appeal.get("user_id")),
                )
            ]
        ]

        if status != "closed":
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text=self._t(
                            "moderation.report.selection.close_appeal_button",
                            language,
                            "✅ Close appeal",
                        ),
                        callback_data=f"reports:close:appeal:{appeal['id']}",
                    )
                ]
            )

        markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        return "\n".join(details), markup

    async def _refresh_reports_overview_message(
        self,
        *,
        bot: Bot,
        state: FSMContext,
        user_id: int,
        language: str,
    ) -> None:
        data = await state.get_data()
        message_id = data.get("overview_message_id")
        chat_id = data.get("overview_chat_id")
        if not message_id or not chat_id:
            return

        per_page = data.get("per_page", self._reports_overview_page_size)

        raw_reports = self.db.list_reports()
        reports = await self._filter_reports_for_admin(bot, user_id, raw_reports)
        appeals = self.db.list_appeals()

        if not reports and not appeals:
            empty_text = self._t(
                "moderation.report.empty",
                language,
                "There are no pending reports or appeals right now.",
            )
            exit_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=self._t(
                                "moderation.report.exit_button",
                                language,
                                "🏠 Back to menu",
                            ),
                            callback_data="reports:exit",
                        )
                    ]
                ]
            )
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=empty_text,
                    disable_web_page_preview=True,
                    reply_markup=exit_markup,
                )
            except TelegramAPIError as exc:
                logging.debug(
                    "Failed to edit reports overview message: %s",
                    exc,
                )
            await state.clear()
            return

        display_entries, mapping = self._build_overview_entries(reports, appeals, language)
        total_pages = max(1, math.ceil(len(display_entries) / per_page))
        current_page = data.get("page", 0)
        if current_page >= total_pages:
            current_page = total_pages - 1

        text, markup, current_page, _ = self._render_reports_overview_page(
            entries=display_entries,
            language=language,
            page=current_page,
            per_page=per_page,
        )

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
            )
        except TelegramAPIError as exc:
            logging.debug(
                "Failed to edit reports overview message: %s",
                exc,
            )

        await state.update_data(
            entries=mapping,
            display_entries=display_entries,
            page=current_page,
            per_page=per_page,
            overview_message_id=message_id,
            overview_chat_id=chat_id,
            requester_id=user_id,
            language=language,
        )

    def _format_datetime(self, dt: Optional[datetime]) -> str:
        if not dt:
            return "unknown"
        return dt.strftime("%Y-%m-%d %H:%M")

    async def handle_main_menu(self, message: Message, state: FSMContext) -> None:
        await report_module.handle_main_menu(self, message, state)

    async def _is_admin_for_chat(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        stored_level = moderation_levels.get_level(chat_id, user_id)
        if stored_level is not None:
            return stored_level >= 1
        try:
            return await PermissionChecker.is_admin(bot, chat_id, user_id)
        except TelegramAPIError:
            return False

    async def _filter_reports_for_admin(
        self, bot: Bot, user_id: int, reports: list[dict]
    ) -> list[dict]:
        allowed: list[dict] = []
        cache: dict[int, bool] = {}
        for entry in reports:
            chat_id = entry.get("chat_id")
            if chat_id is None:
                continue
            allowed_cached = cache.get(chat_id)
            if allowed_cached is None:
                allowed_cached = await self._is_admin_for_chat(bot, chat_id, user_id)
                cache[chat_id] = allowed_cached
            if allowed_cached:
                allowed.append(entry)
        return allowed

    async def _collect_level5_chats(self, bot: Bot, user_id: int) -> list[int]:
        stored = moderation_levels.get_chats_for_user(user_id)
        eligible: set[int] = {
            int(chat_id) for chat_id, level in stored.items() if level >= 5
        }

        candidate_ids = set(self.db.list_known_chat_ids())
        candidate_ids.update(int(chat_id) for chat_id in stored.keys())

        for chat_id in candidate_ids:
            if chat_id in eligible:
                continue

            stored_level = stored.get(chat_id)
            if stored_level is not None and stored_level < 5:
                continue

            try:
                member = await bot.get_chat_member(chat_id, user_id)
            except TelegramAPIError:
                continue

            status = getattr(member, "status", None)
            effective = moderation_levels.get_effective_level(
                chat_id, user_id, status=status
            )
            if effective >= 5:
                eligible.add(int(chat_id))

        return sorted(eligible)

    async def _collect_moderated_chats(self, bot: Bot, user_id: int) -> set[int]:
        stored = moderation_levels.get_chats_for_user(user_id)
        candidate_ids: set[int] = {
            int(chat_id) for chat_id in stored.keys()
        }
        candidate_ids.update(self.db.list_known_chat_ids())
        candidate_ids.update(self.db.list_report_chat_ids())

        eligible: set[int] = set()
        cache: dict[int, bool] = {}

        for chat_id in candidate_ids:
            if chat_id in cache:
                allowed = cache[chat_id]
            else:
                allowed = await self._is_admin_for_chat(bot, chat_id, user_id)
                cache[chat_id] = allowed
            if allowed:
                eligible.add(int(chat_id))

        return eligible

    async def _ensure_chat_title(
        self, bot: Bot, chat_id: int, cache: dict[int, str]
    ) -> str:
        if chat_id in cache:
            return cache[chat_id]
        try:
            chat = await bot.get_chat(chat_id)
            title = getattr(chat, "title", None) or getattr(chat, "full_name", None)
            if not title:
                title = str(chat_id)
        except TelegramAPIError:
            title = str(chat_id)
        cache[chat_id] = title
        return title

    def _build_modlogs_keyboard(
        self, user_id: int, page: int, has_next: bool
    ) -> Optional[InlineKeyboardMarkup]:
        builder = InlineKeyboardBuilder()
        count = 0
        if page > 0:
            builder.button(
                text="⬅️ Prev",
                callback_data=f"modlogs:{user_id}:{page - 1}",
            )
            count += 1
        if has_next:
            builder.button(
                text="Next ➡️",
                callback_data=f"modlogs:{user_id}:{page + 1}",
            )
            count += 1
        if not count:
            return None
        builder.adjust(count)
        return builder.as_markup()

    async def _render_modlogs(
        self,
        *,
        bot: Bot,
        chat_ids: list[int],
        page: int,
        user_id: int,
        language: str,
    ) -> tuple[Optional[str], Optional[InlineKeyboardMarkup], bool]:
        offset = page * self._modlogs_page_size
        actions, has_next = self.db.get_actions_page(
            chat_ids, limit=self._modlogs_page_size, offset=offset
        )

        if not actions:
            if page == 0:
                empty_text = self._t(
                    "moderation.modlogs.empty",
                    language,
                    "No moderation actions have been logged yet.",
                )
                return empty_text, None, False
            return None, None, False

        chat_title_cache: dict[int, str] = {}
        lines: list[str] = [
            "<b>Moderator actions</b>",
            f"<i>Page {page + 1}</i>",
            "",
        ]

        for index, action in enumerate(actions, start=1 + offset):
            action_type = action.get("action_type") or "action"
            verb = self._modlog_labels.get(action_type, action_type.capitalize())
            admin_link = self._format_user_link(
                action.get("admin_id"),
                fallback=str(action.get("admin_id") or "unknown"),
            )
            target_link = self._format_user_link(
                action.get("user_id"),
                fallback=str(action.get("user_id") or "unknown"),
            )

            line = f"{index}. {admin_link} - {verb} {target_link}"

            duration_value = action.get("duration_seconds")
            expires_at = action.get("expires_at")
            timestamp = action.get("timestamp")
            duration_delta: Optional[timedelta] = None
            if duration_value is not None:
                try:
                    duration_delta = timedelta(seconds=float(duration_value))
                except (TypeError, ValueError):
                    duration_delta = None
            elif isinstance(expires_at, datetime) and isinstance(timestamp, datetime):
                duration_delta = expires_at - timestamp

            if action_type in {"ban", "mute"}:
                duration_text = self._format_duration_text(duration_delta, language)
                line += f" for {duration_text}"

            reason = action.get("reason") or ""
            if action_type == "award" and reason:
                line += f" — <i>Award:</i> {html.escape(reason)}"
            elif action_type == "delreward" and reason:
                line += f" — <i>Removed award:</i> {html.escape(reason)}"
            elif reason:
                line += f" for reason: {html.escape(reason)}"

            chat_id_value = action.get("chat_id")
            if chat_id_value is None:
                chat_title = "unknown"
            else:
                chat_title = html.escape(
                    await self._ensure_chat_title(
                        bot, int(chat_id_value), chat_title_cache
                    )
                )
            timestamp_text = self._format_datetime(timestamp)
            line += f" (chat: {chat_title}, at {timestamp_text})"

            lines.append(line)

        markup = self._build_modlogs_keyboard(user_id, page, has_next)
        return "\n".join(lines), markup, True

    def _localize_permission_error(self, error_msg: str, language: str) -> str:
        mapping = {
            "Cannot moderate members with equal or higher level": self._t(
                "moderation.error.cannot_moderate_admin",
                language,
                "Cannot moderate members with equal or higher level",
            ),
            "You don't have permission to restrict members": self._t(
                "moderation.error.no_permission",
                language,
                "You don't have permission to restrict members",
            ),
            "OK": "OK",
        }
        if error_msg in mapping:
            return mapping[error_msg]
        if error_msg.startswith("Error checking permissions: "):
            details = error_msg.split(": ", 1)[1]
            return self._t(
                "moderation.error.permission_check",
                language,
                "Error checking permissions: {details}",
                details=details,
            )
        return error_msg

    def _default_reason(self, language: str) -> str:
        return self._t(
            "moderation.reason.default",
            language,
            "No reason provided",
        )

    def _format_duration_text(self, duration: Optional[timedelta], language: str) -> str:
        if not duration:
            return self._t(
                "moderation.duration.permanent",
                language,
                "permanent",
            )

        raw = TimeUtils.format_duration(duration)
        try:
            count_str, unit = raw.split(" ", 1)
        except ValueError:
            return raw

        key = f"moderation.duration.{unit}".replace(" ", "_")
        default_map = {
            "second": "{count} second",
            "seconds": "{count} seconds",
            "minute": "{count} minute",
            "minutes": "{count} minutes",
            "hour": "{count} hour",
            "hours": "{count} hours",
            "day": "{count} day",
            "days": "{count} days",
        }
        default = default_map.get(unit, raw)
        return self._t(key, language, default, count=count_str)

    async def _resolve_display_name(self, message: Message, user_id: int) -> str:
        """Возвращает имя в виде HTML-ссылки"""
        display = (
                UserCollector.get_display_name(message.chat.id, user_id)
                or UserCollector.get_username(user_id)
        )

        if not display:
            member = await self._fetch_member(message, user_id)
            user = getattr(member, "user", None) if member else None
            if user:
                display = getattr(user, "full_name", None) or getattr(user, "username", None)

        display = display or str(user_id)

        # безопасное HTML-экранирование
        safe_display = (
            display.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return f'<a href="{_build_profile_link(user_id)}">{safe_display}</a>'

    async def _resolve_roleplay_name(self, message: Message, user_id: int) -> str:
        nickname = nickname_storage.get_nickname(message.chat.id, user_id)
        if nickname:
            safe_nickname = (
                nickname.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            return f'<a href="{_build_profile_link(user_id)}">{safe_nickname}</a>'
        return await self._resolve_display_name(message, user_id)

    async def _fetch_member(self, message: Message, user_id: int):
        bot = getattr(message, "bot", None)
        if bot is not None:
            try:
                return await bot.get_chat_member(message.chat.id, user_id)
            except TelegramAPIError as exc:
                logging.debug(
                    "Bot.get_chat_member failed for chat_id=%s user_id=%s: %s",
                    message.chat.id,
                    user_id,
                    exc,
                )
            except Exception as exc:
                logging.debug(
                    "Unexpected error in bot.get_chat_member for chat_id=%s user_id=%s: %s",
                    message.chat.id,
                    user_id,
                    exc,
                    exc_info=True,
                )

        try:
            return await message.chat.get_member(user_id)
        except Exception as exc:
            logging.debug(
                "message.chat.get_member failed for chat_id=%s user_id=%s: %s",
                message.chat.id,
                user_id,
                exc,
            )
            return None

    async def _get_member_level(self, message: Message, user_id: int) -> tuple[int, Optional[str]]:
        member = await self._fetch_member(message, user_id)
        status = getattr(member, "status", None) if member else None
        level = moderation_levels.get_effective_level(
            message.chat.id, user_id, status=status
        )
        if level >= 1 and status not in {"administrator", "creator"}:
            status = f"lvl {level}"
        return level, status

    def _command_requirement(
        self,
        message: Message,
        *,
        default_level: int,
        canonical: str,
        aliases: Sequence[str] = (),
    ) -> tuple[int, str]:
        command_name = extract_command_name(message.text or message.caption)
        candidates: list[str] = []
        if command_name:
            candidates.append(command_name)
        candidates.append(canonical)
        candidates.extend(aliases)
        required_level = get_effective_command_level(
            message.chat.id,
            candidates[0],
            default_level,
            aliases=candidates[1:],
        )
        return required_level, f"/{command_name or canonical}"

    @staticmethod
    def _parse_boolean_argument(value: str) -> Optional[bool]:
        lowered = value.casefold()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return None

    def _extract_mention_preference(self, arguments: Sequence[str]) -> Optional[bool]:
        for argument in arguments:
            key, separator, value = argument.partition("=")
            if separator and key.casefold() == "mention":
                return self._parse_boolean_argument(value)
        return False

    async def _collect_mod_entries(
        self,
        message: Message,
        bot: Bot,
        *,
        include_level_zero: bool = False,
    ) -> dict[int, tuple[int, str, str, str, bool]]:
        chat_id = message.chat.id

        stored_levels = moderation_levels.get_levels_for_chat(chat_id)
        user_entries: dict[int, tuple[int, str, str, str, bool]] = {}

        async def add_entry(user_id: int, level: int, *, is_admin: bool) -> None:
            if level <= 0 and not include_level_zero:
                return
            name = await self._resolve_roleplay_name(message, user_id)
            safe_label = _escape_html(name)
            mention = _format_profile_reference(safe_label, user_id)
            user_entries[user_id] = (level, name, mention, safe_label, is_admin)

        try:
            administrators = await bot.get_chat_administrators(chat_id)
        except TelegramAPIError as exc:
            logging.warning(
                "Failed to fetch administrators for chat_id=%s: %s",
                chat_id,
                exc,
            )
            administrators = []

        admin_ids = {
            admin.user.id for admin in administrators if getattr(admin, "user", None)
        }

        for user_id, level in stored_levels.items():
            await add_entry(user_id, level, is_admin=user_id in admin_ids)

        for admin in administrators:
            user = admin.user
            if not user:
                continue

            level = stored_levels.get(user.id)
            if level is None:
                level = moderation_levels.get_effective_level(
                    chat_id, user.id, status=admin.status
                )

            await add_entry(user.id, level, is_admin=True)

        return user_entries

    async def handle_report(self, message: Message):
        await report_module.handle_report(self, message)

    async def handle_reports_overview(
        self, message: Message, bot: Bot, state: FSMContext
    ):
        await report_module.handle_reports_overview(self, message, bot, state)

    async def handle_report_history(self, message: Message, bot: Bot):
        language = self._language(message)

        if message.chat.type != "private":
            await message.reply(
                self._t(
                    "moderation.report.dm_only",
                    language,
                    "❌ Use this command in a private chat with the bot.",
                ),
                parse_mode=None,
            )
            return

        parts = (message.text or "").split()
        page = 1
        if len(parts) > 1:
            with suppress(ValueError):
                candidate = int(parts[1])
                if candidate > 0:
                    page = candidate

        per_page = self._report_history_page_size
        offset = (page - 1) * per_page

        moderated_chat_ids = await self._collect_moderated_chats(bot, message.from_user.id)
        if not moderated_chat_ids:
            await message.answer(
                self._t(
                    "moderation.report.not_admin",
                    language,
                    "❌ You are not a moderator in any tracked chats.",
                ),
                parse_mode=None,
            )
            return

        entries, has_more = self.db.get_report_history_page(
            sorted(moderated_chat_ids),
            limit=per_page,
            offset=offset,
        )

        if not entries:
            if page == 1:
                await message.answer(
                    self._t(
                        "moderation.report.history.empty",
                        language,
                        "There are no reports recorded yet.",
                    ),
                    parse_mode=None,
                )
            else:
                await message.answer(
                    self._t(
                        "moderation.report.history.no_page",
                        language,
                        "No reports were found for this page.",
                    ),
                    parse_mode=None,
                )
            return

        header = self._t(
            "moderation.report.history.header",
            language,
            "<b>Report history — page {page}</b>",
            page=page,
        )

        lines = [header]
        for index, entry in enumerate(entries, start=offset + 1):
            chat_title = entry.get("chat_title") or str(entry.get("chat_id") or "unknown")
            safe_chat = html.escape(chat_title)
            message_id = entry.get("message_id")
            chat_id = entry.get("chat_id")
            chat_username = entry.get("chat_username")
            if chat_id and message_id:
                message_url = self._build_message_url(int(chat_id), int(message_id), chat_username)
                chat_display = f'<a href="{message_url}">{safe_chat}</a>'
            else:
                chat_display = safe_chat

            raw_status = (entry.get("status") or "open")
            status = raw_status.upper()
            reporter_link = self._format_user_link(
                entry.get("reporter_id"),
                fallback=str(entry.get("reporter_id") or "unknown"),
            )
            target_label = entry.get("target_user_name") or str(entry.get("target_user_id") or "unknown")
            target_link = self._format_user_link(
                entry.get("target_user_id"),
                fallback=target_label,
                stored_name=entry.get("target_user_name"),
            )
            summary = self._compose_report_summary(entry)
            created_at = self._format_datetime(entry.get("created_at"))

            entry_lines = [
                f"{index}. [{status}] {chat_display} — {summary}",
                (
                    f"<i>Reporter:</i> {reporter_link} • "
                    f"<i>Target:</i> {target_link} • "
                    f"<i>Created:</i> {created_at}"
                ),
            ]

            if raw_status.lower() == "closed":
                closed_by_id = entry.get("closed_by_user_id")
                closed_by_name = entry.get("closed_by_user_name")
                if closed_by_id is not None or closed_by_name:
                    fallback = closed_by_name or str(closed_by_id or "unknown")
                    closed_by_link = self._format_user_link(
                        closed_by_id,
                        fallback=fallback,
                        chat_id=chat_id,
                        stored_name=closed_by_name,
                    )
                    entry_lines.append(
                        self._t(
                            "moderation.report.history.closed_by",
                            language,
                            "<i>Closed by:</i> {user}",
                            user=closed_by_link,
                        )
                    )

            lines.append("\n".join(entry_lines))

        footer_lines: list[str] = []
        if page > 1:
            footer_lines.append(
                self._t(
                    "moderation.report.history.prev_hint",
                    language,
                    "Use /reporthistory {page} for the previous page.",
                    page=page - 1,
                )
            )
        if has_more:
            footer_lines.append(
                self._t(
                    "moderation.report.history.next_hint",
                    language,
                    "Use /reporthistory {page} for the next page.",
                    page=page + 1,
                )
            )
        if footer_lines:
            lines.append("\n".join(html.escape(line) if "</" not in line else line for line in footer_lines))

        await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

    async def handle_report_selection(
        self, message: Message, bot: Bot, state: FSMContext
    ):
        await report_module.handle_report_selection(self, message, bot, state)

    async def handle_reports_page_callback(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        await report_module.handle_reports_page_callback(self, callback, state)

    async def handle_report_close_callback(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        await report_module.handle_report_close_callback(self, callback, state)


    async def handle_appeal(self, message: Message, state: FSMContext):
        await report_module.handle_appeal(self, message, state)

    async def handle_appeal_reason(self, message: Message, state: FSMContext):
        await report_module.handle_appeal_reason(self, message, state)

    async def handle_banlist(self, message: Message, bot: Bot):
        language = self._language(message)

        if message.chat.type == "private":
            await message.reply(
                self._t(
                    "moderation.banlist.only_groups",
                    language,
                    "❌ This command works only inside group chats.",
                ),
                parse_mode=None,
            )
            return

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="banlist",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        active_bans = self.db.list_active_actions(message.chat.id, "ban")
        if not active_bans:
            await message.reply(
                self._t(
                    "moderation.banlist.empty",
                    language,
                    "No users are currently banned.",
                ),
                parse_mode=None,
            )
            return

        lines = ["<b>Active bans:</b>"]
        for index, entry in enumerate(active_bans, start=1):
            user_id = entry.get("user_id")
            if user_id is None:
                continue
            user_link = await self._resolve_display_name(message, int(user_id))
            admin_link = self._format_user_link(
                entry.get("admin_id"),
                fallback=str(entry.get("admin_id") or "unknown"),
                chat_id=message.chat.id,
            )

            duration_value = entry.get("duration_seconds")
            expires_at = entry.get("expires_at")
            timestamp = entry.get("timestamp")
            duration_delta: Optional[timedelta] = None
            if duration_value is not None:
                try:
                    duration_delta = timedelta(seconds=float(duration_value))
                except (TypeError, ValueError):
                    duration_delta = None
            elif isinstance(expires_at, datetime) and isinstance(timestamp, datetime):
                duration_delta = expires_at - timestamp

            duration_text = self._format_duration_text(duration_delta, language)
            reason = entry.get("reason") or ""
            reason_part = f" — reason: {html.escape(reason)}" if reason else ""
            lines.append(
                f"{index}. {user_link} — {duration_text} (by {admin_link}){reason_part}"
            )

        await message.reply(
            "\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_mutelist(self, message: Message, bot: Bot):
        language = self._language(message)

        if message.chat.type == "private":
            await message.reply(
                self._t(
                    "moderation.mutelist.only_groups",
                    language,
                    "❌ This command works only inside group chats.",
                ),
                parse_mode=None,
            )
            return

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="mutelist",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        active_mutes = self.db.list_active_actions(message.chat.id, "mute")
        if not active_mutes:
            await message.reply(
                self._t(
                    "moderation.mutelist.empty",
                    language,
                    "No users are currently muted.",
                ),
                parse_mode=None,
            )
            return

        lines = ["<b>Active mutes:</b>"]
        for index, entry in enumerate(active_mutes, start=1):
            user_id = entry.get("user_id")
            if user_id is None:
                continue
            user_link = await self._resolve_display_name(message, int(user_id))
            admin_link = self._format_user_link(
                entry.get("admin_id"),
                fallback=str(entry.get("admin_id") or "unknown"),
                chat_id=message.chat.id,
            )

            duration_value = entry.get("duration_seconds")
            expires_at = entry.get("expires_at")
            timestamp = entry.get("timestamp")
            duration_delta: Optional[timedelta] = None
            if duration_value is not None:
                try:
                    duration_delta = timedelta(seconds=float(duration_value))
                except (TypeError, ValueError):
                    duration_delta = None
            elif isinstance(expires_at, datetime) and isinstance(timestamp, datetime):
                duration_delta = expires_at - timestamp

            duration_text = self._format_duration_text(duration_delta, language)
            reason = entry.get("reason") or ""
            reason_part = f" — reason: {html.escape(reason)}" if reason else ""
            lines.append(
                f"{index}. {user_link} — {duration_text} (by {admin_link}){reason_part}"
            )

        await message.reply(
            "\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_clean_mutelist(self, message: Message, bot: Bot):
        language = self._language(message)

        if message.chat.type == "private":
            await message.reply(
                self._t(
                    "moderation.mutelist.only_groups",
                    language,
                    "❌ This command works only inside group chats.",
                ),
                parse_mode=None,
            )
            return

        required_level, command_display = self._command_requirement(
            message,
            default_level=5,
            canonical="cleanmutelist",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        removed = self.db.clean_actions_for_chat(message.chat.id, "mute")
        if removed:
            text = self._t(
                "moderation.cleanmutelist.success",
                language,
                "✅ Removed {count} mute entries.",
                count=removed,
            )
        else:
            text = self._t(
                "moderation.cleanmutelist.empty",
                language,
                "There were no active mute entries to clean.",
            )

        await message.reply(text, parse_mode=None)

    async def handle_clean_banlist(self, message: Message, bot: Bot):
        language = self._language(message)

        if message.chat.type == "private":
            await message.reply(
                self._t(
                    "moderation.banlist.only_groups",
                    language,
                    "❌ This command works only inside group chats.",
                ),
                parse_mode=None,
            )
            return

        required_level, command_display = self._command_requirement(
            message,
            default_level=5,
            canonical="cleanbanlist",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        removed = self.db.clean_actions_for_chat(message.chat.id, "ban")
        if removed:
            text = self._t(
                "moderation.cleanbanlist.success",
                language,
                "✅ Removed {count} ban entries.",
                count=removed,
            )
        else:
            text = self._t(
                "moderation.cleanbanlist.empty",
                language,
                "There were no active ban entries to clean.",
            )

        await message.reply(text, parse_mode=None)

    async def handle_clean_warnlist(self, message: Message, bot: Bot):
        language = self._language(message)

        if message.chat.type == "private":
            await message.reply(
                self._t(
                    "moderation.warnlist.only_groups",
                    language,
                    "❌ This command works only inside group chats.",
                ),
                parse_mode=None,
            )
            return

        required_level, command_display = self._command_requirement(
            message,
            default_level=5,
            canonical="cleanwarnlist",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        removed = self.db.clean_warnings_for_chat(message.chat.id)
        if removed:
            text = self._t(
                "moderation.cleanwarnlist.success",
                language,
                "✅ Removed {count} warnings.",
                count=removed,
            )
        else:
            text = self._t(
                "moderation.cleanwarnlist.empty",
                language,
                "There were no active warnings to clean.",
            )

        await message.reply(text, parse_mode=None)

    async def handle_modlogs(self, message: Message, bot: Bot):
        await modlogs_module.handle_modlogs(self, message, bot)

    async def handle_modlogs_callback(self, query: CallbackQuery, bot: Bot):
        await modlogs_module.handle_modlogs_callback(self, query, bot)

    async def handle_ban(self, message: Message, bot: Bot):
        """
        Handle /ban command with flexible arguments
        Usage: /ban @user 1d reason, /ban 1d @user, /ban @user (permanent)
        """
        logging.info("Handling /ban command")
        language = self._language(message)
        # Parse arguments
        command_args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)

        if not parsed['success'] or not parsed['user_id']:
            logging.error("Ban command failed: no user specified")
            await message.reply(
                self._t(
                    "moderation.ban.usage",
                    language,
                    "❌ Invalid usage! Examples:\n"
                    "/ban @user 1d spam - Ban user for 1 day\n"
                    "/ban 2h @user - Ban user for 2 hours\n"
                    "/ban @user - Permanent ban\n"
                    "Or reply to a message with /ban 1d",
                )
            )
            return

        user_id = parsed['user_id']
        duration = parsed['duration']
        reason = parsed['reason'] or self._default_reason(language)

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="ban",
            aliases=("бан", "banan"),
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        # Check permissions
        can_moderate, error_msg = await PermissionChecker.can_moderate_user(
            bot, message.chat.id, message.from_user.id, user_id
        )

        if not can_moderate:
            await message.reply(
                self._t(
                    "moderation.error.wrapper",
                    language,
                    "❌ {message}",
                    message=self._localize_permission_error(error_msg, language),
                )
            )
            return

        # Calculate expiry time
        until_date = None
        if duration:
            until_date = datetime.now() + duration
            # Telegram requires minimum 30 seconds, maximum 366 days
            if duration.total_seconds() < 30:
                until_date = datetime.now() + timedelta(seconds=30)
            elif duration.total_seconds() > 366 * 24 * 3600:
                until_date = None  # Permanent ban

        try:
            # Perform the ban
            await bot.ban_chat_member(
                chat_id=message.chat.id,
                user_id=user_id,
                until_date=until_date,
                revoke_messages=True
            )

            # Save to database
            action = ModerationAction(
                action_type="ban",
                user_id=user_id,
                admin_id=message.from_user.id,
                chat_id=message.chat.id,
                duration=duration,
                reason=reason,
                expires_at=until_date
            )
            self.db.add_action(action)

            # Format response
            duration_text = self._format_duration_text(duration, language)

            admin_identifier = (
                message.from_user.username or message.from_user.first_name or ""
            )
            response = self._t(
                "moderation.ban.response",
                language,
                "🔨 <b>User Banned</b>\n"
                "👤 User: {user_id}\n"
                "⏱ Duration: {duration}\n"
                "📝 Reason: {reason}\n"
                "👮‍♂️ By: @{admin}",
                user_id=_escape_html(str(user_id)),
                duration=_escape_html(duration_text),
                reason=_escape_html(reason),
                admin=_escape_html(admin_identifier),
            )

            await message.reply(response, parse_mode="HTML")

        except TelegramAPIError as e:
            if "user is an administrator of the chat" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.target_admin_funny",
                        language,
                        "Hey buddy, I'm not scared—watch your words.",
                    )
                )
            elif "can't remove chat owner" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.chat_owner_funny",
                        language,
                        "Bold move trying to remove the chat owner!",
                    )
                )
            elif "can't restrict self" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.self_action_funny",
                        language,
                        "That's a bit much—you can't restrict yourself.",
                    )
                )
            else:
                await message.reply(
                    self._t(
                        "moderation.ban.failure",
                        language,
                        "❌ Failed to ban user: {error}",
                        error=e,
                    )
                )

    async def handle_mute(self, message: Message, bot: Bot):
        """Handle /mute command"""
        logging.info("Handling /mute command")
        language = self._language(message)
        command_args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)

        if not parsed['success'] or not parsed['user_id']:
            logging.error("Mute command failed: no user specified")
            await message.reply(
                self._t(
                    "moderation.mute.usage",
                    language,
                    "❌ Invalid usage! Examples:\n"
                    "/mute @user 1h spam\n"
                    "/mute 30m @user\n"
                    "/mute @user - Permanent mute",
                )
            )
            return

        user_id = parsed['user_id']
        duration = parsed['duration']
        reason = parsed['reason'] or self._default_reason(language)

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="mute",
            aliases=("мут",),
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        # Check permissions
        can_moderate, error_msg = await PermissionChecker.can_moderate_user(
            bot, message.chat.id, message.from_user.id, user_id
        )

        if not can_moderate:
            await message.reply(
                self._t(
                    "moderation.error.wrapper",
                    language,
                    "❌ {message}",
                    message=self._localize_permission_error(error_msg, language),
                )
            )
            return

        # Calculate expiry
        until_date = None
        if duration:
            until_date = datetime.now() + duration

        # Define mute permissions (no messaging)
        mute_permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )

        try:
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=user_id,
                permissions=mute_permissions,
                until_date=until_date
            )

            # Save to database
            action = ModerationAction(
                action_type="mute",
                user_id=user_id,
                admin_id=message.from_user.id,
                chat_id=message.chat.id,
                duration=duration,
                reason=reason,
                expires_at=until_date
            )
            self.db.add_action(action)

            duration_text = self._format_duration_text(duration, language)

            response = self._t(
                "moderation.mute.response",
                language,
                "🔇 <b>User Muted</b>\n"
                "👤 User: {user_id}\n"
                "⏱ Duration: {duration}\n"
                "📝 Reason: {reason}",
                user_id=_escape_html(str(user_id)),
                duration=_escape_html(duration_text),
                reason=_escape_html(reason),
            )

            await message.reply(response, parse_mode="HTML")

        except TelegramAPIError as e:
            if "user is an administrator of the chat" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.target_admin_funny",
                        language,
                        "Hey buddy, I'm not scared—watch your words.",
                    )
                )
            elif "can't remove chat owner" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.chat_owner_funny",
                        language,
                        "Bold move trying to remove the chat owner!",
                    )
                )
            elif "can't restrict self" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.self_action_funny",
                        language,
                        "That's a bit much—you can't restrict yourself.",
                    )
                )
            else:
                await message.reply(
                    self._t(
                        "moderation.mute.failure",
                        language,
                        "❌ Failed to mute user: {error}",
                        error=e,
                    )
                )

    async def handle_warn(self, message: Message, bot: Bot):
        """Handle /warn command"""
        logging.info("Handling /warn command")
        language = self._language(message)
        command_args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)

        if not parsed['success'] or not parsed['user_id']:
            await message.reply(
                self._t(
                    "moderation.warn.usage",
                    language,
                    "❌ Please specify a user to warn or reply to their message.",
                )
            )
            logging.error("Warn command failed: no user specified")
            return

        user_id = parsed['user_id']
        reason = parsed['reason'] or self._default_reason(language)

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="warn",
            aliases=("варн",),
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        # Check permissions
        can_moderate, error_msg = await PermissionChecker.can_moderate_user(
            bot, message.chat.id, message.from_user.id, user_id
        )

        if not can_moderate:
            await message.reply(
                self._t(
                    "moderation.error.wrapper",
                    language,
                    "❌ {message}",
                    message=self._localize_permission_error(error_msg, language),
                )
            )
            return

        # Add warning to database
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute('''
                         INSERT INTO warnings (user_id, chat_id, admin_id, reason, timestamp)
                         VALUES (?, ?, ?, ?, ?)
                         ''', (user_id, message.chat.id, message.from_user.id, reason, datetime.now().isoformat()))

        # Get current warning count
        warnings = self.db.get_user_warnings(user_id, message.chat.id)
        warning_count = len(warnings)

        response = self._t(
            "moderation.warn.response",
            language,
            "⚠️ <b>Warning Issued</b>\n"
            "👤 User: {user_id}\n"
            "📝 Reason: {reason}\n"
            "🔢 Warning: {count}/3",
            user_id=_escape_html(str(user_id)),
            reason=_escape_html(reason),
            count=_escape_html(str(warning_count)),
        )

        self.db.add_action(
            ModerationAction(
                action_type="warn",
                user_id=user_id,
                admin_id=message.from_user.id,
                chat_id=message.chat.id,
                reason=reason,
            ),
            active=False,
        )

        # Check if max warnings reached
        if warning_count >= 3:
            response += "\n\n" + self._t(
                "moderation.warn.auto_mute_notice",
                language,
                "🔨 <b>Maximum warnings reached! User will be muted.</b>",
            )

            # Auto-mute after 3 warnings
            mute_permissions = ChatPermissions(can_send_messages=False)
            try:
                auto_mute_duration = timedelta(hours=1)
                auto_mute_until = datetime.now() + auto_mute_duration

                await bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=user_id,
                    permissions=mute_permissions,
                    until_date=auto_mute_until,
                )

                self.db.add_action(
                    ModerationAction(
                        action_type="mute",
                        user_id=user_id,
                        admin_id=message.from_user.id,
                        chat_id=message.chat.id,
                        duration=auto_mute_duration,
                        reason="Automatic mute after reaching 3 warnings.",
                        expires_at=auto_mute_until,
                    )
                )

                await self.clean_warns(user_id, message.chat.id)
            except TelegramAPIError:
                pass

        await message.reply(response, parse_mode="HTML")

    async def handle_warnlist(self, message: Message, bot: Bot):
        language = self._language(message)

        if message.chat.type == "private":
            await message.reply(
                self._t(
                    "moderation.warnlist.only_groups",
                    language,
                    "❌ This command works only inside group chats.",
                ),
                parse_mode=None,
            )
            return

        command_args = message.text.split(" ", 1)[1] if " " in (message.text or "") else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)
        user_id = parsed.get("user_id")

        if not user_id and message.reply_to_message and message.reply_to_message.from_user:
            user_id = message.reply_to_message.from_user.id

        if not user_id:
            await message.reply(
                self._t(
                    "moderation.warnlist.usage",
                    language,
                    "❌ Specify a user to view their warnings or reply to their message.",
                ),
                parse_mode=None,
            )
            return

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="warnlist",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        warnings = self.db.get_user_warnings(user_id, message.chat.id)
        if not warnings:
            await message.reply(
                self._t(
                    "moderation.warnlist.empty",
                    language,
                    "✅ This user has no active warnings.",
                ),
                parse_mode=None,
            )
            return

        target_name = await self._resolve_display_name(message, user_id)
        lines = [self._t(
            "moderation.warnlist.header",
            language,
            "<b>Warnings for {target}</b>",
            target=target_name,
        )]

        for index, entry in enumerate(warnings, start=1):
            reason = entry.get("reason") or self._default_reason(language)
            timestamp_raw = entry.get("timestamp")
            timestamp = None
            if isinstance(timestamp_raw, str):
                with suppress(ValueError):
                    timestamp = datetime.fromisoformat(timestamp_raw)
            timestamp_text = self._format_datetime(timestamp)
            admin_link = self._format_user_link(
                entry.get("admin_id"),
                fallback=str(entry.get("admin_id") or "unknown"),
                chat_id=message.chat.id,
            )
            lines.append(
                f"{index}. {html.escape(reason)} — {admin_link} at {timestamp_text}"
            )

        await message.reply(
            "\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def handle_award(self, message: Message, bot: Bot):
        await award_module.handle_award(self, message, bot)

    async def handle_delete_award(self, message: Message, bot: Bot):
        await award_module.handle_delete_award(self, message, bot)

    async def handle_kick(self, message: Message, bot: Bot):
        """Handle /kick command"""
        language = self._language(message)
        command_args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)

        if not parsed['success'] or not parsed['user_id']:
            await message.reply(
                self._t(
                    "moderation.kick.usage",
                    language,
                    "❌ Please specify a user to kick or reply to their message.",
                )
            )
            return

        user_id = parsed['user_id']
        reason = parsed['reason'] or self._default_reason(language)

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="kick",
            aliases=("кик",),
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        # Check permissions
        can_moderate, error_msg = await PermissionChecker.can_moderate_user(
            bot, message.chat.id, message.from_user.id, user_id
        )

        if not can_moderate:
            await message.reply(
                self._t(
                    "moderation.error.wrapper",
                    language,
                    "❌ {message}",
                    message=self._localize_permission_error(error_msg, language),
                )
            )
            return

        try:
            # Kick = ban then immediately unban
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_id)
            await bot.unban_chat_member(chat_id=message.chat.id, user_id=user_id)

            response = self._t(
                "moderation.kick.response",
                language,
                "👢 <b>User Kicked</b>\n"
                "👤 User: {user_id}\n"
                "📝 Reason: {reason}",
                user_id=_escape_html(str(user_id)),
                reason=_escape_html(reason),
            )

            await message.reply(response, parse_mode="HTML")

            self.db.add_action(
                ModerationAction(
                    action_type="kick",
                    user_id=user_id,
                    admin_id=message.from_user.id,
                    chat_id=message.chat.id,
                    reason=reason,
                ),
                active=False,
            )

        except TelegramAPIError as e:
            if "user is an administrator of the chat" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.target_admin_funny",
                        language,
                        "Hey buddy, I'm not scared—watch your words.",
                    )
                )
            elif "can't remove chat owner" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.chat_owner_funny",
                        language,
                        "Bold move trying to remove the chat owner!",
                    )
                )
            elif "can't restrict self" in e.message:
                await message.reply(
                    self._t(
                        "moderation.error.self_action_funny",
                        language,
                        "That's a bit much—you can't restrict yourself.",
                    )
                )
            else:
                await message.reply(
                    self._t(
                        "moderation.kick.failure",
                        language,
                        "❌ Failed to kick user: {error}",
                        error=e,
                    )
                )

    async def handle_unban(self, message: Message, bot: Bot):
        """Handle /unban command"""
        language = self._language(message)
        command_args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)

        if not parsed['success'] or not parsed['user_id']:
            await message.reply(
                self._t(
                    "moderation.unban.usage",
                    language,
                    "❌ Please specify a user to unban.",
                )
            )
            return

        user_id = parsed['user_id']

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="unban",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        try:
            await bot.unban_chat_member(
                chat_id=message.chat.id,
                user_id=user_id,
                only_if_banned=True
            )

            await message.reply(
                self._t(
                    "moderation.unban.success",
                    language,
                    "✅ User {user_id} has been unbanned.",
                    user_id=user_id,
                )
            )

            self.db.deactivate_actions_for_user(message.chat.id, user_id, "ban")
            self.db.add_action(
                ModerationAction(
                    action_type="unban",
                    user_id=user_id,
                    admin_id=message.from_user.id,
                    chat_id=message.chat.id,
                ),
                active=False,
            )

        except TelegramAPIError as e:
            await message.reply(
                self._t(
                    "moderation.unban.failure",
                    language,
                    "❌ Failed to unban user: {error}",
                    error=e,
                )
            )

    async def handle_unmute(self, message: Message, bot: Bot):
        """Handle /unmute command"""
        language = self._language(message)
        command_args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)

        if not parsed['success'] or not parsed['user_id']:
            await message.reply(
                self._t(
                    "moderation.unmute.usage",
                    language,
                    "❌ Please specify a user to unmute.",
                )
            )
            return

        user_id = parsed['user_id']

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="unmute",
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        # Restore full permissions
        full_permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )

        try:
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=user_id,
                permissions=full_permissions
            )

            await message.reply(
                self._t(
                    "moderation.unmute.success",
                    language,
                    "🔊 User {user_id} has been unmuted.",
                    user_id=user_id,
                )
            )

            self.db.deactivate_actions_for_user(message.chat.id, user_id, "mute")
            self.db.add_action(
                ModerationAction(
                    action_type="unmute",
                    user_id=user_id,
                    admin_id=message.from_user.id,
                    chat_id=message.chat.id,
                ),
                active=False,
            )

        except TelegramAPIError as e:
            await message.reply(
                self._t(
                    "moderation.unmute.failure",
                    language,
                    "❌ Failed to unmute user: {error}",
                    error=e,
                )
            )

    async def handle_unwarn(self, message: Message, bot: Bot):
        """Handle /unwarn command"""
        language = self._language(message)
        command_args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else ""
        parsed = ModerationArgParser.parse_moderation_args(message, command_args)

        if not parsed['success'] or not parsed['user_id']:
            await message.reply(
                self._t(
                    "moderation.unwarn.usage",
                    language,
                    "❌ Please specify a user to remove warning from.",
                )
            )
            return

        user_id = parsed['user_id']

        required_level, command_display = self._command_requirement(
            message,
            default_level=1,
            canonical="unwarn",
            aliases=("delwarn",),
        )
        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.denied",
                    language,
                    "❌ Only level {level}+ members can use {command}.",
                    level=required_level,
                    command=command_display,
                ),
                parse_mode=None,
            )
            return

        # Remove last warning
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute('''
                         UPDATE warnings
                         SET active = FALSE
                         WHERE rowid = (SELECT rowid
                                        FROM warnings
                                        WHERE user_id = ?
                                          AND chat_id = ?
                                          AND active = TRUE
                                        ORDER BY timestamp DESC
                             LIMIT 1
                             )
                         ''', (user_id, message.chat.id))

        warnings = self.db.get_user_warnings(user_id, message.chat.id)
        warning_count = len(warnings)

        self.db.add_action(
            ModerationAction(
                action_type="unwarn",
                user_id=user_id,
                admin_id=message.from_user.id,
                chat_id=message.chat.id,
            ),
            active=False,
        )

        await message.reply(
            self._t(
                "moderation.unwarn.success",
                language,
                "✅ Warning removed. User now has {count} warnings.",
                count=warning_count,
            )
        )

    async def handle_mod_level(self, message: Message):
        language = self._language(message)

        raw_text = (message.text or message.caption or "").strip()
        parts = raw_text.split()
        if len(parts) < 2:
            await message.reply(
                self._t(
                    "moderation.level.usage",
                    language,
                    "Usage: /modlevel <0-5> [@user|id] (0 removes moderation access)",
                ),
                parse_mode=None,
            )
            return

        args = parts[1:]
        try:
            level = int(args[0])
        except ValueError:
            await message.reply(
                self._t(
                    "moderation.level.invalid",
                    language,
                    "❌ Level must be a number between 0 and 5.",
                )
            )
            return

        if level < 0 or level > 5:
            await message.reply(
                self._t(
                    "moderation.level.range",
                    language,
                    "❌ Level must be between 0 and 5.",
                )
            )
            return

        target_user = message.reply_to_message.from_user if (
            message.reply_to_message and message.reply_to_message.from_user
        ) else None
        provided_target = len(args) > 1
        target_user_id = target_user.id if target_user else None

        remaining_args = args[1:] if len(args) > 1 else []
        if not target_user_id and remaining_args:
            for candidate in remaining_args:
                if candidate.startswith("@"):
                    resolved_id = UserCollector.get_id(candidate)
                    if resolved_id:
                        target_user_id = resolved_id
                        break
                elif candidate.isdigit():
                    target_user_id = int(candidate)
                    break

        target_user_entity = None
        if not target_user_id and message.entities:
            for entity in message.entities:
                if getattr(entity, "type", None) == "text_mention" and getattr(entity, "user", None):
                    target_user_entity = entity.user
                    target_user_id = entity.user.id
                    break

        if target_user_id is None:
            error_key = "moderation.level.user_not_found" if provided_target else "moderation.level.reply_required"
            default_text = (
                "❌ Could not find that user. Reply to a message or provide a valid username/ID."
                if provided_target
                else "❌ Reply to a user's message or specify a username/ID to set their level."
            )
            await message.reply(
                self._t(
                    error_key,
                    language,
                    default_text,
                )
            )
            return

        if not target_user or target_user.id != target_user_id:
            target_user = target_user_entity
            if not target_user:
                member = await self._fetch_member(message, target_user_id)
                target_user = getattr(member, "user", None) if member else None

        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        target_level, _ = await self._get_member_level(message, target_user_id)

        if message.from_user.id != target_user_id and actor_level <= target_level:
            await message.reply(
                self._t(
                    "moderation.level.insufficient",
                    language,
                    "❌ You cannot change the level of someone with equal or higher rank.",
                )
            )
            return

        if level > actor_level:
            await message.reply(
                self._t(
                    "moderation.level.too_high",
                    language,
                    "❌ You cannot assign a level higher than your own.",
                )
            )
            return

        if target_user and hasattr(target_user, "full_name"):
            target_name = target_user.full_name
        else:
            target_name = (
                UserCollector.get_display_name(message.chat.id, target_user_id)
                or str(target_user_id)
            )

        moderation_levels.set_level(message.chat.id, target_user_id, level)
        await message.reply(
            self._t(
                "moderation.level.set",
                language,
                "✅ Moderation level for {name} set to {level}.",
                name=target_name,
                level=level,
            )
        )

    async def handle_restrict_command_level(self, message: Message):
        language = self._language(message)

        actor_level, _ = await self._get_member_level(message, message.from_user.id)
        required_level, _ = self._command_requirement(
            message,
            default_level=5,
            canonical="restrictcommand",
        )
        if actor_level < required_level:
            await message.reply(
                self._t(
                    "moderation.command_restrict.permission_denied",
                    language,
                    "❌ Only level {level}+ members can configure command restrictions.",
                    level=required_level,
                ),
                parse_mode=None,
            )
            return

        raw_text = (message.text or message.caption or "").strip()
        parts = raw_text.split()
        if len(parts) < 3:
            await message.reply(
                self._t(
                    "moderation.command_restrict.usage",
                    language,
                    "Usage: /restrictcommand <level 0-5> <command> (use level 0 to remove)",
                ),
                parse_mode=None,
            )
            return

        try:
            level = int(parts[1])
        except ValueError:
            await message.reply(
                self._t(
                    "moderation.command_restrict.level_range",
                    language,
                    "❌ Level must be a number between 0 and 5.",
                ),
                parse_mode=None,
            )
            return

        if level < 0 or level > 5:
            await message.reply(
                self._t(
                    "moderation.command_restrict.level_range",
                    language,
                    "❌ Level must be a number between 0 and 5.",
                ),
                parse_mode=None,
            )
            return

        command_name = _normalise_command_name(parts[2])
        if not command_name:
            await message.reply(
                self._t(
                    "moderation.command_restrict.invalid_command",
                    language,
                    "❌ Please provide a command to restrict.",
                ),
                parse_mode=None,
            )
            return

        display_command = f"/{command_name}"

        if level == 0:
            command_restrictions.clear_command_level(message.chat.id, command_name)
            await message.reply(
                self._t(
                    "moderation.command_restrict.cleared",
                    language,
                    "🧹 Restriction removed for {command}. Anyone can use it now.",
                    command=display_command,
                ),
                parse_mode=None,
            )
            return

        command_restrictions.set_command_level(message.chat.id, command_name, level)
        await message.reply(
            self._t(
                "moderation.command_restrict.set",
                language,
                "✅ Command {command} now requires level {level}.",
                command=display_command,
                level=level,
            ),
            parse_mode=None,
        )

    async def handle_list_mods(self, message: Message, bot: Bot):
        language = self._language(message)

        parts = (message.text or message.caption or "").split()
        mention_preference = self._extract_mention_preference(parts[1:])
        if mention_preference is None:
            await message.reply(
                self._t(
                    "moderation.common.mention_invalid",
                    language,
                    "❌ The mention argument accepts 'on' or 'off'.",
                ),
                parse_mode=None,
            )
            return

        use_mentions = mention_preference

        user_entries = await self._collect_mod_entries(message, bot)
        if not user_entries:
            await message.reply(
                self._t(
                    "moderation.mods.empty",
                    language,
                    "No moderators have been assigned yet.",
                ),
                parse_mode=None,
            )
            return

        levels_to_names: dict[int, list[tuple[str, str]]] = {}
        for _, (level, name, mention, safe_label, is_admin) in user_entries.items():
            sort_key = name.casefold() if name else safe_label.casefold()
            display_text = mention if use_mentions else safe_label
            if is_admin:
                display_text = f"🛡 {display_text}"
            levels_to_names.setdefault(level, []).append((sort_key, display_text))

        lines: list[str] = []
        for level in range(5, 0, -1):
            entries = levels_to_names.get(level)
            if not entries:
                continue

            stars = "⭐️" * level
            header = self._t(
                "moderation.mods.header",
                language,
                "{stars} Mod Level {level}:",
                stars=stars,
                level=level,
            )
            lines.append(header)
            for _, display in sorted(entries, key=lambda item: item[0]):
                if "<a href=" in display:
                    lines.append(display)
                else:
                    lines.append(escape(display))

        await message.reply("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

    async def handle_restrict_command(self, message: Message, bot: Bot):
        language = self._language(message)
        parts = (message.text or message.caption or "").split()

        if len(parts) < 2:
            await message.reply(
                self._t(
                    "moderation.restrict.usage",
                    language,
                    "Usage: /restrict <0-5> — show members with that exact level.",
                ),
                parse_mode=None,
            )
            return

        try:
            level = int(parts[1])
        except ValueError:
            await message.reply(
                self._t(
                    "moderation.restrict.range",
                    language,
                    "❌ Level must be a number between 0 and 5.",
                ),
                parse_mode=None, 
            )
            return

        if level < 0 or level > 5:
            await message.reply(
                self._t(
                    "moderation.restrict.range",
                    language,
                    "❌ Level must be a number between 0 and 5.",
                ),
                parse_mode=None,
            )
            return

        mention_preference = self._extract_mention_preference(parts[2:])
        if mention_preference is None:
            await message.reply(
                self._t(
                    "moderation.common.mention_invalid",
                    language,
                    "❌ The mention argument accepts 'on' or 'off'.",
                ),
                parse_mode=None,
            )
            return

        use_mentions = mention_preference

        user_entries = await self._collect_mod_entries(
            message,
            bot,
            include_level_zero=(level == 0),
        )
        matches = [
            (
                name.casefold() if name else safe_label.casefold(),
                mention if use_mentions else safe_label,
                is_admin,
            )
            for stored_level, name, mention, safe_label, is_admin in user_entries.values()
            if stored_level == level
        ]

        if not matches:
            await message.reply(
                self._t(
                    "moderation.restrict.empty",
                    language,
                    "❌ Nobody currently has level {level}.",
                    level=level,
                ),
                parse_mode=None,
            )
            return

        header = self._t(
            "moderation.restrict.header",
            language,
            "⭐️ Level {level} members:",
            level=level,
        )
        lines = [header]
        
        for _, display, is_admin in sorted(matches, key=lambda item: item[0]):
            if is_admin:
                prefix = "🛡 "
            else:
                prefix = ""

            if "<a href=" in display:
                lines.append(f"{prefix}{display}")
            else:
                lines.append(f"{prefix}{escape(display)}")
        await message.reply("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

    async def clean_warns(self, user_id: int, chat_id: int):
        """Utility to clean up old warnings (not used directly in handlers)"""
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute('''
                         UPDATE warnings
                         SET active = FALSE
                         WHERE user_id = ?
                           AND chat_id = ?
                           AND active = TRUE
                         ''', (user_id, chat_id))
            conn.commit()

        logging.info(f"Cleaned up old warnings for user {user_id} in chat {chat_id}")


moderation_module = AdvancedModerationModule()
router = moderation_module.router
priority = 1
if router:
    logging.info("AdvancedModerationModule router initialized")
    logging.info(f"Router name: {router.name}")


@router.message(Command("report"))
async def report_command_handler(message: Message):
    await moderation_module.handle_report(message)


@router.message(Command("reports"))
async def reports_command_handler(message: Message, bot: Bot, state: FSMContext):
    await moderation_module.handle_reports_overview(message, bot, state)


@router.message(Command("reporthistory"))
async def report_history_command_handler(message: Message, bot: Bot):
    await moderation_module.handle_report_history(message, bot)


@router.message(ReportsState.awaiting_selection)
async def reports_selection_handler(
    message: Message, bot: Bot, state: FSMContext
):
    await moderation_module.handle_report_selection(message, bot, state)


@router.callback_query(F.data.startswith("reports:page:"))
async def reports_page_callback_handler(callback: CallbackQuery, state: FSMContext):
    await moderation_module.handle_reports_page_callback(callback, state)


@router.callback_query(F.data.startswith("reports:close:"))
async def reports_close_callback_handler(
    callback: CallbackQuery, state: FSMContext
):
    await moderation_module.handle_report_close_callback(callback, state)


@router.callback_query(F.data == "reports:exit")
async def reports_exit_callback_handler(callback: CallbackQuery, state: FSMContext):
    language = normalize_language_code(callback.from_user.language_code)
    await callback.answer(
        gettext(
            "moderation.report.menu_exit_callback",
            language=language,
            default="Reports menu closed.",
        )
    )
    if callback.message:
        with suppress(TelegramAPIError):
            await callback.message.edit_reply_markup(reply_markup=None)
        await moderation_module.handle_main_menu(callback.message, state)


@router.message(Command("menu"))
async def menu_command_handler(message: Message, state: FSMContext):
    await moderation_module.handle_main_menu(message, state)


@router.message(Command("appeal"))
async def appeal_command_handler(message: Message, state: FSMContext):
    await moderation_module.handle_appeal(message, state)


@router.message(AppealState.awaiting_reason)
async def appeal_reason_handler(message: Message, state: FSMContext):
    await moderation_module.handle_appeal_reason(message, state)


@router.message(Command("banlist"))
async def banlist_command_handler(message: Message, bot: Bot):
    await moderation_module.handle_banlist(message, bot)


@router.message(Command("cleanbanlist"))
async def cleanbanlist_command_handler(message: Message, bot: Bot):
    await moderation_module.handle_clean_banlist(message, bot)


@router.message(Command("mutelist"))
async def mutelist_command_handler(message: Message, bot: Bot):
    await moderation_module.handle_mutelist(message, bot)


@router.message(Command("cleanmutelist"))
async def cleanmutelist_command_handler(message: Message, bot: Bot):
    await moderation_module.handle_clean_mutelist(message, bot)


@router.message(Command("modlogs"))
async def modlogs_command_handler(message: Message, bot: Bot):
    await moderation_module.handle_modlogs(message, bot)


@router.callback_query(F.data.startswith("modlogs:"))
async def modlogs_callback_handler(query: CallbackQuery, bot: Bot):
    await moderation_module.handle_modlogs_callback(query, bot)


@router.message(Command("ban", "бан", "banan"))
async def ban_handler(message: Message, bot: Bot):
    await moderation_module.handle_ban(message, bot)


@router.message(Command("unban"))
async def unban_handler(message: Message, bot: Bot):
    await moderation_module.handle_unban(message, bot)


@router.message(Command("mute", "мут"))
async def mute_handler(message: Message, bot: Bot):
    await moderation_module.handle_mute(message, bot)


@router.message(Command("unmute"))
async def unmute_handler(message: Message, bot: Bot):
    await moderation_module.handle_unmute(message, bot)


@router.message(Command("warn", "варн"))
async def warn_handler(message: Message, bot: Bot):
    await moderation_module.handle_warn(message, bot)


@router.message(Command("warnlist"))
async def warnlist_handler(message: Message, bot: Bot):
    await moderation_module.handle_warnlist(message, bot)


@router.message(Command("cleanwarnlist"))
async def cleanwarnlist_command_handler(message: Message, bot: Bot):
    await moderation_module.handle_clean_warnlist(message, bot)


@router.message(Command("unwarn", "delwarn"))
async def unwarn_handler(message: Message, bot: Bot):
    await moderation_module.handle_unwarn(message, bot)


@router.message(Command("award"))
async def award_handler(message: Message, bot: Bot):
    await moderation_module.handle_award(message, bot)


@router.message(Command("delreward"))
async def delete_award_handler(message: Message, bot: Bot):
    await moderation_module.handle_delete_award(message, bot)


@router.message(Command("modlevel"))
async def modlevel_handler(message: Message):
    await moderation_module.handle_mod_level(message)


@router.message(Command("restrictcommand"))
async def restrict_command_handler(message: Message):
    await moderation_module.handle_restrict_command_level(message)


@router.message(Command("restrict"))
async def restrict_handler(message: Message, bot: Bot):
    await moderation_module.handle_restrict_command(message, bot)


@router.message(Command("mods"))
async def mods_handler(message: Message, bot: Bot):
    await moderation_module.handle_list_mods(message, bot)


@router.message(Command("kick", "кик"))
async def kick_handler(message: Message, bot: Bot):
    await moderation_module.handle_kick(message, bot)

