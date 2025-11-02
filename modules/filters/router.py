from __future__ import annotations

import html
import logging
import re
import shlex
from collections import defaultdict
from functools import wraps
from typing import Any, Dict, Optional, Tuple

from aiogram.filters import Command
from aiogram.types import Message, MessageEntity
from aiogram.utils.text_decorations import html_decoration

from modules.base import Module
from modules.collector.utils import UserCollector
from modules.filters.storage import (
    MATCH_TYPE_CONTAINS,
    MATCH_TYPE_REGEX,
    FilterStorage,
    FilterTemplate,
)
from modules.moderation.command_restrictions import (
    extract_command_name,
    get_effective_command_level,
)
from modules.moderation.level_storage import moderation_levels
from modules.roleplay.nickname_storage import CustomNicknameStorage
from utils.localization import gettext, language_from_message


def _escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def require_level(
    default_command: str,
    default_level: int = 1,
    *,
    aliases: tuple[str, ...] = (),
):
    def decorator(func):
        @wraps(func)
        async def wrapper(message: Message, *args, **kwargs):
            command_name = extract_command_name(message.text or message.caption)
            candidates = []
            if command_name:
                candidates.append(command_name)
            candidates.append(default_command)
            candidates.extend(aliases)
            required_level = get_effective_command_level(
                message.chat.id,
                candidates[0],
                default_level,
                aliases=candidates[1:],
            )

            status = None
            try:
                member = await message.chat.get_member(message.from_user.id)
                status = getattr(member, "status", None)
            except Exception:
                member = None
            level = moderation_levels.get_effective_level(
                message.chat.id, message.from_user.id, status=status
            )
            if level < required_level:
                language = language_from_message(message)
                await message.answer(
                    gettext(
                        "filters.permission_denied",
                        language=language,
                        default="❌ Only level {level}+ members can manage filters.",
                        level=required_level,
                    )
                )
                return
            return await func(message, *args, **kwargs)

        return wrapper

    return decorator


class FilterService:
    """Service layer that provides filter rendering and storage helpers."""

    PLACEHOLDER_PATTERN = re.compile(
        r"{(randomUser|randomMention|randomRpUser|argument|argumentNoQuestion)}"
    )

    def __init__(
        self,
        storage: Optional[FilterStorage] = None,
        nickname_storage: Optional[CustomNicknameStorage] = None,
    ) -> None:
        self._storage = storage or FilterStorage()
        self._nickname_storage = nickname_storage or CustomNicknameStorage()

    @property
    def storage(self) -> FilterStorage:
        return self._storage

    @property
    def nickname_storage(self) -> CustomNicknameStorage:
        return self._nickname_storage

    async def handle_trigger_message(self, message: Message) -> None:
        if message.from_user and message.from_user.is_bot:
            return

        text = message.text or message.caption
        if not text:
            return

        chat = getattr(message, "chat", None)
        if not chat:
            return

        definitions = self.storage.list_filter_definitions(chat.id)
        if not definitions:
            return

        language = language_from_message(message)
        text_lower = text.lower()
        matches: list[tuple[str, str, str]] = []
        match_arguments: dict[tuple[str, str], str] = {}
        for trigger_key, pattern, match_type in definitions:
            if match_type == MATCH_TYPE_REGEX:
                try:
                    match_obj = re.search(pattern, text, flags=re.IGNORECASE)
                except re.error:
                    logging.exception(
                        "Invalid regex filter skipped for chat_id=%s pattern='%s'",
                        chat.id,
                        pattern,
                    )
                    continue
                if match_obj:
                    matches.append((trigger_key, pattern, match_type))
                    match_arguments.setdefault(
                        (trigger_key, match_type), text[match_obj.end() :].lstrip()
                    )
            else:
                index = text_lower.find(trigger_key)
                if index != -1:
                    matches.append((trigger_key, pattern, match_type))
                    argument_text = text[index + len(trigger_key) :].lstrip()
                    match_arguments.setdefault((trigger_key, match_type), argument_text)

        if not matches:
            return

        processed: set[tuple[str, str]] = set()
        for trigger_key, pattern, match_type in matches:
            key = (trigger_key, match_type)
            if key in processed:
                continue
            processed.add(key)

            template = self.storage.get_random_template(
                chat.id, pattern, match_type=match_type
            )
            if not template:
                continue

            entities = self.build_entities(template.parsed_entities())
            try:
                await self.send_template_response(
                    message,
                    template,
                    entities,
                    argument=match_arguments.get((trigger_key, match_type)),
                    language=language,
                )
            except Exception:
                logging.exception(
                    "Failed to send filter response for chat_id=%s trigger='%s' template_id=%s",
                    chat.id,
                    pattern,
                    getattr(template, "template_id", None),
                )

    def extract_content(self, src: Message) -> Dict[str, Any]:
        text = src.text or src.caption
        if text:
            text = text.strip()

        entities = None
        if src.entities:
            entities = [entity.model_dump() for entity in src.entities]
        elif src.caption_entities:
            entities = [entity.model_dump() for entity in src.caption_entities]

        media_type = None
        file_id = None
        if src.photo:
            media_type = "photo"
            file_id = src.photo[-1].file_id
        elif src.animation:
            media_type = "animation"
            file_id = src.animation.file_id
        elif src.video:
            media_type = "video"
            file_id = src.video.file_id
        elif src.document:
            media_type = "document"
            file_id = src.document.file_id
        elif src.audio:
            media_type = "audio"
            file_id = src.audio.file_id
        elif src.voice:
            media_type = "voice"
            file_id = src.voice.file_id
        elif src.video_note:
            media_type = "video_note"
            file_id = src.video_note.file_id
        elif src.sticker:
            media_type = "sticker"
            file_id = src.sticker.file_id

        return {
            "text": text,
            "entities": entities,
            "media_type": media_type,
            "file_id": file_id,
        }

    def preview_text(self, text: Optional[str], has_media: bool, *, language: str) -> str:
        if text:
            cleaned = " ".join(text.split())
        else:
            cleaned = gettext(
                "filters.preview.no_text",
                language=language,
                default="No text",
            )
        if len(cleaned) > 20:
            cleaned = cleaned[:20].rstrip()
        preview = f"{cleaned}..."
        if has_media:
            preview += " 🖼"
        return preview

    def _select_random_user(self, chat_id: Optional[int]) -> Optional[Tuple[int, str, Optional[str]]]:
        result = UserCollector.get_random_user(chat_id)
        if not result:
            logging.debug("Random user placeholder requested but no users are stored yet")
            return None

        user_id, username, display_name = result
        if not username:
            logging.debug(
                "Random user lookup returned empty username for user_id=%s", user_id
            )
            return user_id, str(user_id), display_name

        cleaned_username = username.lstrip("@")
        return user_id, cleaned_username or str(user_id), display_name

    def _build_roleplay_placeholder_label(
        self,
        chat_id: Optional[int],
        user_id: int,
        *,
        prefer_rp: bool,
        mention_label: str,
        username_label: str,
        display_name: Optional[str],
        fallback: str,
        use_html: bool,
    ) -> str:
        rp_nickname = (
            self._nickname_storage.get_nickname(chat_id, user_id) if chat_id else None
        )
        if prefer_rp:
            if rp_nickname:
                base_label = rp_nickname
            elif display_name:
                base_label = display_name
            elif username_label:
                base_label = username_label
            else:
                base_label = fallback
        else:
            if mention_label:
                base_label = mention_label
            elif username_label:
                base_label = username_label
            else:
                base_label = fallback

        return _escape_html(base_label) if use_html else base_label

    @staticmethod
    def _format_html_link(label: str, user_id: int) -> str:
        return f'<a href="tg://user?id={user_id}">{label}</a>'

    def _resolve_placeholder_value(
        self,
        placeholder: str,
        *,
        chat_id: Optional[int],
        fallback: str,
        use_html: bool,
    ) -> str:
        random_user = self._select_random_user(chat_id)
        if not random_user:
            return fallback

        user_id, username, display_name = random_user
        if placeholder == "randomUser":
            base_label = username or fallback
            return _escape_html(base_label) if use_html else base_label

        mention_label = f"@{username}" if username else ""
        prefer_rp = placeholder == "randomRpUser"
        display_label = self._build_roleplay_placeholder_label(
            chat_id,
            user_id,
            prefer_rp=prefer_rp,
            mention_label=mention_label,
            username_label=username or "",
            display_name=display_name,
            fallback=fallback,
            use_html=use_html,
        )

        if placeholder == "randomMention":
            if use_html:
                return self._format_html_link(display_label, user_id)
            return mention_label or display_label

        if use_html:
            return self._format_html_link(display_label, user_id)
        return display_label

    async def apply_dynamic_placeholders(
        self,
        text: Optional[str],
        entities: Optional[list[MessageEntity]],
        *,
        chat_id: Optional[int],
        argument: Optional[str],
        language: str,
    ) -> tuple[Optional[str], Optional[list[MessageEntity]], Optional[str]]:
        if not text:
            return text, entities, None

        matches = list(self.PLACEHOLDER_PATTERN.finditer(text))
        if not matches:
            return text, entities, None

        requires_html = bool(entities) or any(
            match.group(1) in {"randomMention", "randomRpUser"} for match in matches
        )

        if entities:
            working_text = html_decoration.unparse(text, entities)
        elif requires_html:
            working_text = _escape_html(text)
        else:
            working_text = text

        matches = list(self.PLACEHOLDER_PATTERN.finditer(working_text))
        fallback_value = gettext(
            "filters.placeholders.unknown_user",
            language=language,
            default="unknown user",
        )
        fallback = _escape_html(fallback_value) if requires_html else fallback_value

        argument_raw = (argument or "").strip()
        argument_value = _escape_html(argument_raw) if requires_html else argument_raw
        argument_no_question_raw = argument_raw.replace("?", "").strip()
        argument_no_question = (
            _escape_html(argument_no_question_raw)
            if requires_html
            else argument_no_question_raw
        )

        new_text_parts: list[str] = []
        last_index = 0

        for match in matches:
            segment = working_text[last_index : match.start()]
            new_text_parts.append(segment)

            placeholder_type = match.group(1)
            if placeholder_type in {"randomUser", "randomMention", "randomRpUser"}:
                replacement = self._resolve_placeholder_value(
                    placeholder_type,
                    chat_id=chat_id,
                    fallback=fallback,
                    use_html=requires_html,
                )
            elif placeholder_type == "argument":
                replacement = argument_value
            else:
                replacement = argument_no_question
            new_text_parts.append(replacement)
            last_index = match.end()

        new_text_parts.append(working_text[last_index:])
        new_text = "".join(new_text_parts)

        if requires_html:
            return new_text, None, "HTML"

        return new_text, None, None

    def build_entities(
        self, entities_data: Optional[list[dict]]
    ) -> Optional[list[MessageEntity]]:
        if not entities_data:
            return None
        return [MessageEntity.model_validate(entity) for entity in entities_data]

    def split_text_chunks(self, text: str, limit: int = 4000) -> list[str]:
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            split_index = remaining.rfind("\n", 0, limit)
            if split_index == -1:
                split_index = limit

            chunk = remaining[:split_index]
            if chunk:
                chunks.append(chunk)

            remaining = remaining[split_index:]
            remaining = remaining.lstrip("\n")

        return chunks or [text]

    async def send_template_response(
        self,
        message: Message,
        template: FilterTemplate,
        entities: Optional[list[MessageEntity]],
        *,
        argument: Optional[str],
        language: str,
    ) -> None:
        rendered_text, rendered_entities, parse_mode = await self.apply_dynamic_placeholders(
            template.text,
            entities,
            chat_id=getattr(message.chat, "id", None),
            argument=argument,
            language=language,
        )

        def _caption_kwargs() -> Dict[str, Any]:
            if parse_mode:
                return {"parse_mode": parse_mode}
            if rendered_entities:
                return {"caption_entities": rendered_entities}
            return {}

        if template.media_type == "photo":
            await message.answer_photo(
                template.file_id,
                caption=rendered_text,
                **_caption_kwargs(),
            )
        elif template.media_type == "animation":
            await message.answer_animation(
                template.file_id,
                caption=rendered_text,
                **_caption_kwargs(),
            )
        elif template.media_type == "video":
            await message.answer_video(
                template.file_id,
                caption=rendered_text,
                **_caption_kwargs(),
            )
        elif template.media_type == "document":
            await message.answer_document(
                template.file_id,
                caption=rendered_text,
                **_caption_kwargs(),
            )
        elif template.media_type == "audio":
            await message.answer_audio(
                template.file_id,
                caption=rendered_text,
                **_caption_kwargs(),
            )
        elif template.media_type == "voice":
            await message.answer_voice(
                template.file_id,
                caption=rendered_text,
                **_caption_kwargs(),
            )
        elif template.media_type == "video_note":
            await message.answer_video_note(template.file_id)
            if rendered_text:
                await message.answer(
                    rendered_text,
                    parse_mode=parse_mode,
                    entities=None if parse_mode else rendered_entities,
                )
        elif template.media_type == "sticker":
            await message.answer_sticker(template.file_id)
            if rendered_text:
                await message.answer(
                    rendered_text,
                    parse_mode=parse_mode,
                    entities=None if parse_mode else rendered_entities,
                )
        else:
            await message.answer(
                rendered_text or "",
                parse_mode=parse_mode,
                entities=None if parse_mode else rendered_entities,
            )


class FilterCommandHandler:
    """Encapsulates command handlers that manage filter templates."""

    def __init__(self, service: FilterService) -> None:
        self._service = service

    @property
    def storage(self) -> FilterStorage:
        return self._service.storage

    @staticmethod
    def _split_command_args(message: Message) -> list[str]:
        text = message.text or ""
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()

    @staticmethod
    def _extract_trigger_argument(
        args: list[str],
        *,
        start_index: int = 1,
        join_rest: bool = True,
    ) -> tuple[Optional[str], str, int]:
        match_type = MATCH_TYPE_CONTAINS
        index = start_index
        if index < len(args) and args[index].lower() in ("--regex", "-r"):
            match_type = MATCH_TYPE_REGEX
            index += 1
        if index >= len(args):
            return None, match_type, index
        if join_rest:
            trigger = " ".join(args[index:]).strip()
            index = len(args)
        else:
            trigger = args[index].strip()
            index += 1
        if not trigger:
            return None, match_type, index
        return trigger, match_type, index

    @staticmethod
    def _format_trigger_label(pattern: str, match_type: str, *, language: str) -> str:
        if match_type == MATCH_TYPE_REGEX:
            return gettext(
                "filters.trigger.regex",
                language=language,
                default="[regex] <code>{pattern}</code>",
                pattern=pattern,
            )
        return gettext(
            "filters.trigger.contains",
            language=language,
            default="[contains] <code>{pattern}</code>",
            pattern=pattern,
        )

    @staticmethod
    def _validate_regex(pattern: str) -> Optional[str]:
        try:
            re.compile(pattern)
        except re.error as exc:  # pragma: no cover - validation branch
            return str(exc)
        return None

    async def handle_filter_add(self, message: Message) -> None:
        language = language_from_message(message)
        args = self._split_command_args(message)
        trigger, match_type, _ = self._extract_trigger_argument(args)
        if not trigger:
            await message.answer(
                gettext(
                    "filters.add.usage",
                    language=language,
                    default="Usage: /filteradd [--regex] word (command must reply to a message)",
                )
            )
            return

        if not message.reply_to_message:
            await message.answer(
                gettext(
                    "filters.error.reply_required",
                    language=language,
                    default="❌ The command must reply to a message containing the template.",
                )
            )
            return

        if match_type == MATCH_TYPE_REGEX:
            error = self._validate_regex(trigger)
            if error:
                await message.answer(
                    gettext(
                        "filters.error.invalid_regex",
                        language=language,
                        default="❌ Invalid regular expression: {error}",
                        error=error,
                    )
                )
                return

        content = self._service.extract_content(message.reply_to_message)
        if not content["text"] and not content["file_id"]:
            await message.answer(
                gettext(
                    "filters.error.empty_template",
                    language=language,
                    default="⚠ The template must contain text or media.",
                )
            )
            return

        template_id = self.storage.add_template(
            message.chat.id,
            trigger,
            text=content["text"],
            entities=content["entities"],
            media_type=content["media_type"],
            file_id=content["file_id"],
            match_type=match_type,
        )
        await message.answer(
            gettext(
                "filters.add.success",
                language=language,
                default="✅ Template #{template_id} for {trigger_label} saved.",
                template_id=template_id,
                trigger_label=self._format_trigger_label(trigger, match_type, language=language),
            )
        )

    async def handle_filter_list(self, message: Message) -> None:
        language = language_from_message(message)
        args = self._split_command_args(message)
        trigger, match_type, _ = self._extract_trigger_argument(args)
        if not trigger:
            await message.answer(
                gettext(
                    "filters.list.usage",
                    language=language,
                    default="Usage: /filterlist [--regex] word",
                )
            )
            return

        if match_type == MATCH_TYPE_REGEX:
            error = self._validate_regex(trigger)
            if error:
                await message.answer(
                    gettext(
                        "filters.error.invalid_regex",
                        language=language,
                        default="❌ Invalid regular expression: {error}",
                        error=error,
                    )
                )
                return

        templates = self.storage.list_templates(message.chat.id, trigger, match_type=match_type)
        if not templates:
            await message.answer(
                gettext(
                    "filters.list.empty",
                    language=language,
                    default="ℹ️ No templates found for this word.",
                )
            )
            return

        display_pattern = templates[0].pattern
        lines = [
            gettext(
                "filters.list.header",
                language=language,
                default="📁 Templates for {trigger_label}:",
                trigger_label=self._format_trigger_label(
                    display_pattern, templates[0].match_type, language=language
                ),
            )
        ]
        for template in templates:
            lines.append(
                gettext(
                    "filters.list.item",
                    language=language,
                    default="{id}. {preview}",
                    id=template.template_id,
                    preview=self._service.preview_text(
                        template.text, template.has_media, language=language
                    ),
                )
            )
        text = "\n".join(lines)
        for chunk in self._service.split_text_chunks(text):
            await message.answer(chunk)

    async def handle_filter_replace(self, message: Message) -> None:
        language = language_from_message(message)
        args = self._split_command_args(message)
        trigger, match_type, index = self._extract_trigger_argument(args, join_rest=False)
        if not trigger or index >= len(args):
            await message.answer(
                gettext(
                    "filters.replace.usage",
                    language=language,
                    default="Usage: /filterreplace [--regex] word id (command must reply to a message)",
                )
            )
            return

        if not message.reply_to_message:
            await message.answer(
                gettext(
                    "filters.replace.reply_required",
                    language=language,
                    default="❌ The command must reply to a message with a new template.",
                )
            )
            return

        if match_type == MATCH_TYPE_REGEX:
            error = self._validate_regex(trigger)
            if error:
                await message.answer(
                    gettext(
                        "filters.error.invalid_regex",
                        language=language,
                        default="❌ Invalid regular expression: {error}",
                        error=error,
                    )
                )
                return

        try:
            template_id = int(args[index])
        except (ValueError, IndexError):
            await message.answer(
                gettext(
                    "filters.error.id_number",
                    language=language,
                    default="❌ ID must be a number.",
                )
            )
            return

        content = self._service.extract_content(message.reply_to_message)
        if not content["text"] and not content["file_id"]:
            await message.answer(
                gettext(
                    "filters.error.empty_template",
                    language=language,
                    default="⚠ The template must contain text or media.",
                )
            )
            return

        updated = self.storage.replace_template(
            message.chat.id,
            trigger,
            template_id,
            text=content["text"],
            entities=content["entities"],
            media_type=content["media_type"],
            file_id=content["file_id"],
            match_type=match_type,
        )
        if updated:
            await message.answer(
                gettext(
                    "filters.replace.success",
                    language=language,
                    default="♻️ Template #{template_id} for {trigger_label} updated.",
                    template_id=template_id,
                    trigger_label=self._format_trigger_label(
                        trigger, match_type, language=language
                    ),
                )
            )
        else:
            await message.answer(
                gettext(
                    "filters.replace.not_found",
                    language=language,
                    default="⚠ The specified template was not found.",
                )
            )

    async def handle_filter_remove(self, message: Message) -> None:
        language = language_from_message(message)
        args = self._split_command_args(message)
        trigger, match_type, index = self._extract_trigger_argument(args, join_rest=False)
        if not trigger or index >= len(args):
            await message.answer(
                gettext(
                    "filters.remove.usage",
                    language=language,
                    default="Usage: /filterremove [--regex] word id",
                )
            )
            return

        if match_type == MATCH_TYPE_REGEX:
            error = self._validate_regex(trigger)
            if error:
                await message.answer(
                    gettext(
                        "filters.error.invalid_regex",
                        language=language,
                        default="❌ Invalid regular expression: {error}",
                        error=error,
                    )
                )
                return

        try:
            template_id = int(args[index])
        except (ValueError, IndexError):
            await message.answer(
                gettext(
                    "filters.error.id_number",
                    language=language,
                    default="❌ ID must be a number.",
                )
            )
            return

        removed = self.storage.remove_template(
            message.chat.id, trigger, template_id, match_type=match_type
        )
        if removed:
            await message.answer(
                gettext(
                    "filters.remove.success",
                    language=language,
                    default="🗑 Template #{template_id} for {trigger_label} deleted. Indexes recalculated.",
                    template_id=template_id,
                    trigger_label=self._format_trigger_label(
                        trigger, match_type, language=language
                    ),
                )
            )
        else:
            await message.answer(
                gettext(
                    "filters.remove.not_found",
                    language=language,
                    default="⚠ Template with this ID not found.",
                )
            )

    async def handle_filter_clear(self, message: Message) -> None:
        language = language_from_message(message)
        args = self._split_command_args(message)
        trigger, match_type, _ = self._extract_trigger_argument(args)
        if not trigger:
            await message.answer(
                gettext(
                    "filters.clear.usage",
                    language=language,
                    default="Usage: /filterclear [--regex] word",
                )
            )
            return

        if match_type == MATCH_TYPE_REGEX:
            error = self._validate_regex(trigger)
            if error:
                await message.answer(
                    gettext(
                        "filters.error.invalid_regex",
                        language=language,
                        default="❌ Invalid regular expression: {error}",
                        error=error,
                    )
                )
                return

        if self.storage.clear_trigger(message.chat.id, trigger, match_type=match_type):
            await message.answer(
                gettext(
                    "filters.clear.success",
                    language=language,
                    default="🧹 All templates for {trigger_label} have been deleted.",
                    trigger_label=self._format_trigger_label(
                        trigger, match_type, language=language
                    ),
                )
            )
        else:
            await message.answer(
                gettext(
                    "filters.clear.empty",
                    language=language,
                    default="ℹ️ There were no templates for this word.",
                )
            )

    async def handle_filter_list_all(self, message: Message) -> None:
        language = language_from_message(message)
        templates = list(self.storage.list_all_templates(message.chat.id))
        if not templates:
            await message.answer(
                gettext(
                    "filters.list_all.empty",
                    language=language,
                    default="ℹ️ There are no filters for this chat yet.",
                )
            )
            return

        grouped: dict[tuple[str, str], list[FilterTemplate]] = defaultdict(list)
        for template in templates:
            key = (template.pattern, template.match_type)
            grouped[key].append(template)

        lines = [
            gettext(
                "filters.list_all.header",
                language=language,
                default="📚 All filters:",
            )
        ]
        for (pattern, match_type), items in sorted(
            grouped.items(), key=lambda entry: (entry[0][1], entry[0][0])
        ):
            previews = "; ".join(
                gettext(
                    "filters.list_all.preview",
                    language=language,
                    default="{id}. {preview}",
                    id=item.template_id,
                    preview=self._service.preview_text(
                        item.text, item.has_media, language=language
                    ),
                )
                for item in items
            )
            lines.append(
                gettext(
                    "filters.list_all.item",
                    language=language,
                    default="• {trigger_label}: {previews}",
                    trigger_label=self._format_trigger_label(
                        pattern, match_type, language=language
                    ),
                    previews=previews,
                )
            )

        text = "\n".join(lines)
        for chunk in self._service.split_text_chunks(text):
            await message.answer(chunk)


class FilterTriggerHandler:
    """Adapter that routes plain chat messages through the filter service."""

    def __init__(self, service: FilterService) -> None:
        self._service = service

    async def handle_filter_message(self, message: Message) -> None:
        try:
            await self._service.handle_trigger_message(message)
        except Exception:
            logging.exception(
                "Failed to process filter triggers for chat_id=%s",  # pragma: no cover
                getattr(getattr(message, "chat", None), "id", None),
            )


class FiltersModule(Module):
    """Module entry point that wires command handlers and middleware."""

    required_services = ["filter_service"]

    def __init__(self) -> None:
        super().__init__("filters", priority=60)
        self._service: Optional[FilterService] = None
        self._commands: Optional[FilterCommandHandler] = None
        self._triggers: Optional[FilterTriggerHandler] = None

    def _ensure_service(self) -> FilterService:
        if self._service is None:
            self._service = getattr(self, "filter_service", None) or FilterService()
        return self._service

    def _ensure_commands(self) -> FilterCommandHandler:
        if self._commands is None:
            self._commands = FilterCommandHandler(self._ensure_service())
        return self._commands

    def _ensure_trigger_handler(self) -> FilterTriggerHandler:
        if self._triggers is None:
            self._triggers = FilterTriggerHandler(self._ensure_service())
        return self._triggers

    async def register(self, _container) -> None:
        commands = self._ensure_commands()
        self.router.message.register(
            require_level("filteradd")(commands.handle_filter_add),
            Command("filteradd"),
        )
        self.router.message.register(
            commands.handle_filter_list,
            Command("filterlist"),
        )
        self.router.message.register(
            require_level("filterreplace")(commands.handle_filter_replace),
            Command("filterreplace"),
        )
        self.router.message.register(
            require_level("filterremove")(commands.handle_filter_remove),
            Command("filterremove"),
        )
        self.router.message.register(
            require_level("filterclear")(commands.handle_filter_clear),
            Command("filterclear"),
        )
        self.router.message.register(
            commands.handle_filter_list_all,
            Command("filterlistall"),
        )

        self.router.message.register(
            self._ensure_trigger_handler().handle_filter_message,
            flags={"block": False},
        )


module = FiltersModule()
router = module.router
