import html
import logging
from typing import Dict, Iterable, Optional, Set

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramAPIError

from modules.collector.utils import UserCollector
from modules.roleplay.nickname_storage import CustomNicknameStorage
from utils.localization import gettext, language_from_message

router = Router(name="statistics")
priority = 50


nickname_storage = CustomNicknameStorage()


PERIOD_ALIASES: Dict[str, str] = {
    "day": "day",
    "week": "week",
    "month": "month",
    "all": "total",
}


@router.message(Command("top"))
async def command_top(message: Message) -> None:
    language = language_from_message(message)
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    raw_text = (message.text or message.caption or "").strip()
    parts = raw_text.split(maxsplit=1)
    argument = parts[1].strip().lower() if len(parts) > 1 else ""

    if chat_id is None:
        await message.answer(
            gettext(
                "statistics.top.unsupported_chat",
                language=language,
                default="❌ This command is only available in group chats.",
            )
        )
        return

    if not argument:
        await message.answer(
            gettext(
                "statistics.top.usage",
                language=language,
                default="Usage: /top <day|week|month|all>",
            ),
            parse_mode=None,
        )
        return

    period_key = PERIOD_ALIASES.get(argument)
    if period_key is None:
        await message.answer(
            gettext(
                "statistics.top.unknown_period",
                language=language,
                default="❌ Unknown period '{value}'. Use one of: day, week, month, all.",
                value=html.escape(argument),
            ),
            parse_mode=None,
        )
        return

    reference = getattr(message, "date", None)
    top_users = UserCollector.get_top_users(
        chat_id,
        period_key,
        limit=10,
        reference=reference,
    )

    if not top_users:
        await message.answer(
            gettext(
                "statistics.top.empty",
                language=language,
                default="No activity recorded for this period yet.",
            ),
            parse_mode=None,
        )
        return

    period_labels = {
        "day": gettext(
            "statistics.top.period.day",
            language=language,
            default="today",
        ),
        "week": gettext(
            "statistics.top.period.week",
            language=language,
            default="this week",
        ),
        "month": gettext(
            "statistics.top.period.month",
            language=language,
            default="this month",
        ),
        "total": gettext(
            "statistics.top.period.total",
            language=language,
            default="all time",
        ),
    }

    header = gettext(
        "statistics.top.header",
        language=language,
        default="🏆 Top message senders ({period})",
        period=period_labels.get(period_key, period_key),
    )

    admin_ids = await _get_admin_ids(message)

    lines = [html.escape(header)]

    for index, entry in enumerate(top_users, start=1):
        name = _format_user_name(message, entry, admin_ids)
        lines.append(
            gettext(
                "statistics.top.row",
                language=language,
                default="{index}. {name} — {count} messages",
                index=index,
                name=name,
                count=entry["count"],
            )
        )

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _get_admin_ids(message: Message) -> Set[int]:
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    bot = getattr(message, "bot", None)
    if chat_id is None:
        return set()

    administrators: Iterable = ()

    if bot is not None:
        try:
            administrators = await bot.get_chat_administrators(chat_id)
        except TelegramAPIError as exc:
            logging.warning(
                "Failed to fetch administrators for chat_id=%s: %s",
                chat_id,
                exc,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning(
                "Unexpected error while fetching administrators for chat_id=%s: %s",
                chat_id,
                exc,
                exc_info=True,
            )
    elif hasattr(chat, "get_administrators"):
        try:
            administrators = await chat.get_administrators()
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning(
                "chat.get_administrators failed for chat_id=%s: %s",
                chat_id,
                exc,
            )

    admin_ids: Set[int] = set()
    for admin in administrators:
        user = getattr(admin, "user", None)
        user_id = getattr(user, "id", None)
        if isinstance(user_id, int):
            admin_ids.add(user_id)
    return admin_ids


def _format_user_name(
    message: Message, entry: Dict[str, object], admin_ids: Set[int]
) -> str:
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    user_id = entry.get("user_id")

    label: Optional[str] = None
    if chat_id is not None and isinstance(user_id, int):
        nickname = nickname_storage.get_nickname(chat_id, user_id)
        if isinstance(nickname, str) and nickname:
            label = nickname

    if label is None:
        display_name = entry.get("display_name")
        if isinstance(display_name, str) and display_name:
            label = display_name

    if label is None:
        for username_key in ("chat_username", "global_username"):
            username = entry.get(username_key)
            if isinstance(username, str) and username:
                label = f"@{username}"
                break

    if label is None:
        label = str(user_id)

    safe_label = html.escape(label)
    profile_link = _build_profile_link(entry)
    name = f'<a href="{profile_link}">{safe_label}</a>'

    if isinstance(user_id, int) and user_id in admin_ids:
        name = f"⭐️ {name}"

    return name


def _build_profile_link(entry: Dict[str, object]) -> str:
    for username_key in ("chat_username", "global_username"):
        username = entry.get(username_key)
        if isinstance(username, str) and username:
            url = f"https://t.me/{username}"
            return html.escape(url, quote=True)

    user_id = entry.get("user_id")
    url = f"tg://user?id={user_id}"
    return html.escape(url, quote=True)
