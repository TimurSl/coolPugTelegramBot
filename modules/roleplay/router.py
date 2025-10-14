import json
import os
import random
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from modules.collector.utils import UserCollector
from modules.moderation.command_restrictions import (
    extract_command_name,
    get_effective_command_level,
)
from modules.moderation.data import ModerationDatabase
from modules.moderation.level_storage import moderation_levels
from modules.roleplay.nickname_storage import CustomNicknameStorage
from utils.localization import gettext, language_from_message
from utils.path_utils import get_home_dir

router = Router(name="rp_config")
priority = 50

CONFIG_FILE = os.path.join(get_home_dir(), "rp_config.json")


class RPConfig:
    def __init__(self):
        self.default_config = {
            "обнять": {"action": "обнял", "emoji": "🫂", "media": None, "random_variants": []},
            "ударить": {"action": "ударил", "emoji": "👊", "media": None, "random_variants": []},
        }
        self.config: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.load_config()

    def _empty_chat_entry(self) -> Dict[str, Dict[str, Any]]:
        return {"commands": {}}

    def load_config(self):
        self.config = {}
        if not os.path.exists(CONFIG_FILE):
            self.save_config()
            return

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        for chat_id, entry in (raw or {}).items():
            commands_raw: Dict[str, Any]

            if isinstance(entry, dict) and "commands" in entry:
                commands_raw = entry.get("commands", {}) or {}
            else:
                commands_raw = entry if isinstance(entry, dict) else {}
                if isinstance(commands_raw, dict):
                    commands_raw.pop("__aliases__", None)

            normalised_commands: Dict[str, Dict[str, Any]] = {}
            for keyword, data in (commands_raw or {}).items():
                if not isinstance(keyword, str) or not isinstance(data, dict):
                    continue
                normalised_commands[keyword.lower()] = {
                    "action": data.get("action", ""),
                    "emoji": data.get("emoji", ""),
                    "media": data.get("media"),
                    "random_variants": data.get("random_variants") or [],
                }

            self.config[str(chat_id)] = {
                "commands": normalised_commands,
            }

    def save_config(self):
        serialised: Dict[str, Dict[str, Any]] = {}
        for chat_id, entry in self.config.items():
            serialised[chat_id] = {
                "commands": entry.get("commands", {}),
            }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(serialised, f, ensure_ascii=False, indent=2)

    def _get_chat_entry(self, chat_id: int) -> Dict[str, Dict[str, Any]]:
        key = str(chat_id)
        if key not in self.config:
            self.config[key] = self._empty_chat_entry()
        return self.config[key]

    def get_chat_config(self, chat_id: int) -> Dict[str, Dict[str, Any]]:
        return self._get_chat_entry(chat_id)["commands"]

    def get_command(self, chat_id: int, keyword: str):
        chat_conf = self.get_chat_config(chat_id)
        keyword_lower = keyword.lower()
        if keyword_lower in chat_conf:
            return chat_conf[keyword_lower]
        return self.default_config.get(keyword_lower)

    def add_command(
        self,
        chat_id: int,
        keyword: str,
        action: str,
        emoji: str,
        media=None,
        random_variants=None,
    ):
        chat_conf = self.get_chat_config(chat_id)
        chat_conf[keyword.lower()] = {
            "action": action,
            "emoji": emoji,
            "media": media,
            "random_variants": random_variants or [],
        }
        self.save_config()

    def del_command(self, chat_id: int, keyword: str):
        chat_entry = self._get_chat_entry(chat_id)
        key = keyword.lower()
        commands = chat_entry["commands"]
        if key in commands:
            del commands[key]
            self.save_config()
            return True
        return False


rp_config = RPConfig()
nickname_storage = CustomNicknameStorage()


def _required_level(
    message: Message,
    canonical: str,
    default_level: int,
    *,
    aliases: tuple[str, ...] = (),
) -> int:
    command_name = extract_command_name(message.text or message.caption)
    candidates = []
    if command_name:
        candidates.append(command_name)
    candidates.append(canonical)
    candidates.extend(aliases)
    return get_effective_command_level(
        message.chat.id,
        candidates[0],
        default_level,
        aliases=candidates[1:],
    )
moderation_db = ModerationDatabase(os.path.join(get_home_dir(), "moderation.db"))


def _escape_markdown(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("~", "\\~")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _get_display_name(chat_id: int, user_id: int, fallback: str) -> str:
    nickname = nickname_storage.get_nickname(chat_id, user_id)
    if nickname:
        return _escape_markdown(nickname)
    stored = UserCollector.get_display_name(chat_id, user_id)
    if stored:
        return _escape_markdown(stored)
    return _escape_markdown(fallback)


def _build_profile_link(user_id: int) -> str:
    username = UserCollector.get_username(user_id)
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


def format_roleplay_profile_reference(
    name: str, user_id: int, *, name_is_escaped: bool = False
) -> str:
    safe_name = name if name_is_escaped else _escape_markdown(name)
    profile_link = _escape_markdown(_build_profile_link(user_id))
    return f"[{safe_name}]({profile_link})"


async def _fetch_chat_member(message: Message, user_id: int):
    bot = getattr(message, "bot", None)
    if bot is not None:
        try:
            return await bot.get_chat_member(message.chat.id, user_id)
        except Exception:
            pass

    try:
        return await message.chat.get_member(user_id)
    except Exception:
        return None


async def _get_user_avatar_file_id(message: Message, user_id: int) -> Optional[str]:
    bot = getattr(message, "bot", None)
    if bot is None:
        return None

    try:
        photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
    except Exception:
        return None

    if not photos or not photos.photos:
        return None

    first_entry = photos.photos[0] if photos.photos else None
    if not first_entry:
        return None

    best_photo = max(
        first_entry,
        key=lambda item: (
            item.file_size or 0,
            item.width or 0,
            item.height or 0,
        ),
    )

    return getattr(best_photo, "file_id", None)


async def _get_member_level(message: Message, user_id: int) -> tuple[int, Optional[str]]:
    member = await _fetch_chat_member(message, user_id)
    status = getattr(member, "status", None) if member else None
    level = moderation_levels.get_effective_level(
        message.chat.id, user_id, status=status
    )
    if level >= 1 and status not in {"administrator", "creator"}:
        status = f"lvl {level}"
    return level, status


def _format_join_info(
    first_seen: Optional[datetime], language: str
) -> tuple[str, str]:
    if not first_seen:
        unknown = gettext(
            "roleplay.profile.joined.unknown",
            language=language,
            default="unknown",
        )
        unknown_duration = gettext(
            "roleplay.profile.duration.unknown",
            language=language,
            default="unknown",
        )
        return unknown, unknown_duration

    now = datetime.utcnow()
    delta = now - first_seen
    day_abbr = gettext(
        "roleplay.profile.duration.day_abbr",
        language=language,
        default="d",
    )
    hour_abbr = gettext(
        "roleplay.profile.duration.hour_abbr",
        language=language,
        default="h",
    )
    minute_abbr = gettext(
        "roleplay.profile.duration.minute_abbr",
        language=language,
        default="m",
    )
    less_than_minute = gettext(
        "roleplay.profile.duration.lt_minute",
        language=language,
        default="<1m",
    )

    parts: list[str] = []
    if delta.days:
        parts.append(f"{delta.days}{day_abbr}")

    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60

    if hours:
        parts.append(f"{hours}{hour_abbr}")
    if minutes and len(parts) < 2:
        parts.append(f"{minutes}{minute_abbr}")

    if not parts:
        parts.append(less_than_minute)

    date_format = gettext(
        "roleplay.profile.date_format",
        language=language,
        default="%Y-%m-%d %H:%M",
    )
    return first_seen.strftime(date_format), " ".join(parts)


@router.message(Command("rpnick"))
async def handle_set_rp_nick(message: Message):
    language = language_from_message(message)
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            gettext(
                "roleplay.nick.usage",
                language=language,
                default="Usage: /rpnick new_nickname (can be used in reply)",
            )
        )
        return

    target_user = message.from_user
    actor_level, actor_status = await _get_member_level(message, message.from_user.id)
    required_level = _required_level(
        message,
        "rpnick",
        1,
        aliases=("rpnickclear",),
    )
    can_manage_others = actor_level >= required_level

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        if not can_manage_others and target_user.id != message.from_user.id:
            await message.answer(
                gettext(
                    "roleplay.nick.permission_denied",
                    language=language,
                    default="❌ Only level {level}+ members can set nicknames for other users.",
                    level=required_level,
                )
            )
            return

        if target_user.id != message.from_user.id:
            target_level, _ = await _get_member_level(message, target_user.id)
            if actor_level < target_level:
                await message.answer(
                    gettext(
                        "roleplay.nick.level_denied",
                        language=language,
                        default="❌ You cannot change the nickname of someone with a higher level.",
                    )
                )
                return

    nickname = args[1].strip()
    try:
        nickname_storage.set_nickname(message.chat.id, target_user.id, nickname)
    except ValueError:
        await message.answer(
            gettext(
                "roleplay.nick.empty",
                language=language,
                default="❌ The nickname must not be empty.",
            )
        )
        return

    if target_user.id == message.from_user.id:
        await message.answer(
            gettext(
                "roleplay.nick.self_success",
                language=language,
                default="✅ Your RP nickname has been updated!",
            )
        )
    else:
        profile_reference = format_roleplay_profile_reference(
            target_user.full_name or str(target_user.id),
            target_user.id,
        )
        await message.answer(
            gettext(
                "roleplay.nick.other_success",
                language=language,
                default="✅ RP nickname for {profile_reference} updated.",
                profile_reference=profile_reference,
            ),
            parse_mode="Markdown",
        )


@router.message(Command("rpnickclear"))
async def handle_clear_rp_nick(message: Message):
    language = language_from_message(message)
    target_user = message.from_user
    actor_level, actor_status = await _get_member_level(message, message.from_user.id)
    required_level = _required_level(
        message,
        "rpnickclear",
        1,
        aliases=("rpnick",),
    )
    can_manage_others = actor_level >= required_level

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        if not can_manage_others and target_user.id != message.from_user.id:
            await message.answer(
                gettext(
                    "roleplay.clear.permission_denied",
                    language=language,
                    default="❌ Only level {level}+ members can reset nicknames for other users.",
                    level=required_level,
                )
            )
            return

        if target_user.id != message.from_user.id:
            target_level, _ = await _get_member_level(message, target_user.id)
            if actor_level < target_level:
                await message.answer(
                    gettext(
                        "roleplay.clear.level_denied",
                        language=language,
                        default="❌ You cannot reset the nickname of someone with a higher level.",
                    )
                )
                return

    removed = nickname_storage.clear_nickname(message.chat.id, target_user.id)
    if removed:
        profile_reference = format_roleplay_profile_reference(
            target_user.full_name or str(target_user.id),
            target_user.id,
        )
        if target_user.id == message.from_user.id:
            await message.answer(
                gettext(
                    "roleplay.clear.self_success",
                    language=language,
                    default="🗑 Your RP nickname has been reset.",
                )
            )
        else:
            await message.answer(
                gettext(
                    "roleplay.clear.other_success",
                    language=language,
                    default="🗑 RP nickname for {profile_reference} has been reset.",
                    profile_reference=profile_reference,
                ),
                parse_mode="Markdown",
            )
    else:
        await message.answer(
            gettext(
                "roleplay.clear.not_found",
                language=language,
                default="ℹ️ No saved RP nickname was found.",
            )
        )


def _normalise_command_keyword(raw: str) -> tuple[str, str]:
    token = (raw or "").strip()
    token = token.lstrip("/")
    if "@" in token:
        token = token.split("@", 1)[0]
    cleaned = token.strip(".,!?:;")
    return cleaned, cleaned.lower()


def _extract_command_from_text(full_text: str) -> tuple[Optional[str], str]:
    stripped = (full_text or "").strip()
    if not stripped:
        return None, ""
    parts = stripped.split(maxsplit=1)
    keyword_raw = parts[0]
    remainder = parts[1] if len(parts) > 1 else ""
    _, keyword_lower = _normalise_command_keyword(keyword_raw)
    return (keyword_lower or None), remainder


def build_action_text(action: str, random_variants):
    if "{random}" not in action:
        return action

    variants = [variant for variant in (random_variants or []) if variant]
    if not variants:
        return action.replace("{random}", "")

    result = action
    while "{random}" in result:
        result = result.replace("{random}", random.choice(variants), 1)
    return result


@router.message(Command("addrp"))
async def handle_add_rp(message: Message):
    language = language_from_message(message)
    actor_level, _ = await _get_member_level(message, message.from_user.id)
    required_level = _required_level(
        message,
        "addrp",
        1,
        aliases=("delrp",),
    )
    if actor_level < required_level:
        await message.answer(
            gettext(
                "roleplay.add.permission_denied",
                language=language,
                default="❌ Only level {level}+ members can add RP commands.",
                level=required_level,
            )
        )
        return

    usage_text = gettext(
        "roleplay.add.usage",
        language=language,
        default="⚠ Provide text: /addrp emoji keyword action",
    )

    if not message.text:  # сообщение без текста
        await message.answer(usage_text)
        return

    lines = message.text.splitlines()
    command_line = lines[0] if lines else ""
    parts = command_line.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer(usage_text, parse_mode=None)
        return

    emoji, keyword, action = parts[1], parts[2], parts[3]
    media = None
    random_variants = [line.strip() for line in lines[1:] if line.strip()]

    # проверяем прикреплённое медиа или ответ
    src = message.reply_to_message or message
    if src.photo:
        media = {"type": "photo", "file_id": src.photo[-1].file_id}
    elif src.animation:
        media = {"type": "animation", "file_id": src.animation.file_id}
    elif src.video:
        media = {"type": "video", "file_id": src.video.file_id}
    elif src.sticker:
        media = {"type": "sticker", "file_id": src.sticker.file_id}

    rp_config.add_command(message.chat.id, keyword, action, emoji, media, random_variants)
    media_status = gettext(
        "roleplay.add.media.attached" if media else "roleplay.add.media.missing",
        language=language,
        default="attached" if media else "not attached",
    )
    await message.answer(
        gettext(
            "roleplay.add.success",
            language=language,
            default="✅ RP command '{keyword}' added (media {media_status}).",
            keyword=keyword,
            media_status=media_status,
        )
    )


@router.message(Command("delrp"))
async def handle_del_rp(message: Message):
    language = language_from_message(message)
    actor_level, _ = await _get_member_level(message, message.from_user.id)
    required_level = _required_level(
        message,
        "delrp",
        1,
        aliases=("addrp",),
    )
    if actor_level < required_level:
        await message.answer(
            gettext(
                "roleplay.delete.permission_denied",
                language=language,
                default="❌ Only level {level}+ members can delete RP commands.",
                level=required_level,
            )
        )
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            gettext(
                "roleplay.delete.usage",
                language=language,
                default="Usage: /delrp keyword",
            ),
            parse_mode=None,
        )
        return

    keyword = parts[1]
    if rp_config.del_command(message.chat.id, keyword):
        await message.answer(
            gettext(
                "roleplay.delete.success",
                language=language,
                default="🗑 RP command '{keyword}' removed.",
                keyword=keyword,
            )
        )
    else:
        await message.answer(
            gettext(
                "roleplay.delete.not_found",
                language=language,
                default="⚠ RP command '{keyword}' not found.",
                keyword=keyword,
            )
        )


@router.message(Command("listrp"))
async def handle_list_rp(message: Message):
    language = language_from_message(message)
    chat_conf = rp_config.get_chat_config(message.chat.id)
    header = gettext(
        "roleplay.list.header",
        language=language,
        default="📜 RP commands for this chat:",
    )
    lines = [header]
    combined = dict(rp_config.default_config)
    combined.update(chat_conf)
    for keyword, data in combined.items():
        media_flag = "📷" if data.get("media") else ""
        random_flag = "🎲" if data.get("random_variants") else ""
        lines.append(
            gettext(
                "roleplay.list.item",
                language=language,
                default="{emoji} {keyword} → {action} {media_flag}{random_flag}",
                emoji=data["emoji"],
                keyword=keyword,
                action=data["action"],
                media_flag=media_flag,
                random_flag=random_flag,
            )
        )

    await message.answer("\n".join(lines))


async def _send_profile_response(message: Message, language: str, arg_text: str) -> None:
    args = arg_text.split() if arg_text else []

    target_user = message.from_user
    target_user_id = target_user.id
    target_user_entity = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
    else:
        if message.entities:
            for entity in message.entities:
                if getattr(entity, "type", None) == "text_mention" and getattr(
                    entity, "user", None
                ):
                    target_user_entity = entity.user
                    target_user_id = entity.user.id
                    break

        if target_user_entity is None and args:
            for arg in args:
                if arg.startswith("@"):
                    resolved_id = UserCollector.get_id(arg)
                    if resolved_id:
                        target_user_id = resolved_id
                        break
                elif arg.isdigit():
                    target_user_id = int(arg)
                    break

        if target_user_entity:
            target_user = target_user_entity
        elif target_user_id != message.from_user.id:
            member = await _fetch_chat_member(message, target_user_id)
            if member and getattr(member, "user", None):
                target_user = member.user
            else:
                username = UserCollector.get_username(target_user_id)
                fallback_name = (
                    UserCollector.get_display_name(message.chat.id, target_user_id)
                    or (f"@{username}" if username else None)
                    or str(target_user_id)
                )
                target_user = SimpleNamespace(
                    id=target_user_id, full_name=fallback_name
                )

    stats = UserCollector.get_statistics(
        message.chat.id,
        target_user_id,
        reference=getattr(message, "date", None),
    )
    first_seen = UserCollector.get_first_seen(message.chat.id, target_user_id)
    joined_text, duration_text = _format_join_info(first_seen, language)

    nickname_value = nickname_storage.get_nickname(message.chat.id, target_user_id)
    if nickname_value:
        nickname_label = _escape_markdown(nickname_value)
    else:
        nickname_label = _escape_markdown(
            gettext(
                "roleplay.profile.nickname.none",
                language=language,
                default="not set",
            )
        )

    mod_level, _ = await _get_member_level(message, target_user_id)
    header = gettext(
        "roleplay.profile.header",
        language=language,
        default="📇 Profile for {name}",
        name=_escape_markdown(target_user.full_name),
    )
    nickname_line = gettext(
        "roleplay.profile.nickname",
        language=language,
        default="• RP nickname: {nickname}",
        nickname=nickname_label,
    )
    joined_line = gettext(
        "roleplay.profile.joined",
        language=language,
        default="• In chat since: {date} ({duration} ago)",
        date=joined_text,
        duration=duration_text,
    )
    mod_level_line = gettext(
        "roleplay.profile.mod_level",
        language=language,
        default="• Moderation level: {level}",
        level=mod_level,
    )
    stats_line = gettext(
        "roleplay.profile.stats",
        language=language,
        default="• Messages — today: {day}, week: {week}, month: {month}, total: {total}",
        day=stats.get("day", 0),
        week=stats.get("week", 0),
        month=stats.get("month", 0),
        total=stats.get("total", 0),
    )

    awards = moderation_db.list_awards(message.chat.id, target_user_id)
    if awards:
        awards_lines = [
            gettext(
                "roleplay.profile.awards.header",
                language=language,
                default="• Awards:",
            )
        ]
        for award in awards:
            awards_lines.append(
                gettext(
                    "roleplay.profile.awards.entry",
                    language=language,
                    default="    • #{award_id}: {text}",
                    award_id=award["id"],
                    text=_escape_markdown(award.get("text", "")),
                )
            )
        awards_block = "\n".join(awards_lines)
    else:
        awards_block = gettext(
            "roleplay.profile.awards.none",
            language=language,
            default="• Awards: none",
        )

    profile_text = "\n".join(
        [header, nickname_line, joined_line, mod_level_line, stats_line, awards_block]
    )

    avatar_file_id = await _get_user_avatar_file_id(message, target_user_id)

    if avatar_file_id:
        await message.answer_photo(
            avatar_file_id,
            caption=profile_text,
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            profile_text,
            parse_mode="Markdown",
        )


@router.message(Command("profile"))
async def handle_profile(message: Message):
    language = language_from_message(message)
    raw_text = (message.text or message.caption or "").strip()
    _, arg_text = _extract_command_from_text(raw_text)
    await _send_profile_response(message, language, arg_text or "")


