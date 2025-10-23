"""Manage chat-level access restrictions."""

from __future__ import annotations

import html
import logging
from enum import Enum

from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import Message

from modules.base import Module
from utils.chat_access import ChatFeature, chat_access_storage
from utils.localization import gettext, language_from_message


class FeatureName(str, Enum):
    ASSISTANT = ChatFeature.AI_ASSISTANT.value
    EXECUTOR = ChatFeature.EXECUTOR.value

    @property
    def feature(self) -> ChatFeature:
        return ChatFeature(self.value)

    @property
    def localized(self) -> str:
        mapping = {
            FeatureName.ASSISTANT: "blacklist.feature.assistant",
            FeatureName.EXECUTOR: "blacklist.feature.executor",
        }
        key = mapping.get(self)
        return key or self.value


class ChatAccessModule(Module):
    """Handle /blacklist command."""

    def __init__(self) -> None:
        super().__init__("chat_access", priority=40)
        self.router.message.register(self._handle_blacklist, Command("blacklist"))
        self._logger = logging.getLogger(__name__)

    async def _handle_blacklist(self, message: Message, bot: Bot) -> None:
        if not self.enabled or message.chat is None or message.from_user is None:
            return

        language = language_from_message(message)
        if not await self._is_authorized(message, bot):
            await message.reply(
                gettext(
                    "blacklist.not_authorized",
                    language=language,
                    default="❌ Only chat administrators can change blacklist settings.",
                ),
                parse_mode=None,
            )
            return

        raw_text = (message.text or message.caption or "").strip()
        parts = raw_text.split(maxsplit=2)

        if len(parts) < 2:
            summary = self._format_summary(message.chat.id, language)
            await message.reply(
                gettext(
                    "blacklist.usage",
                    language=language,
                    default=(
                        "Usage: /blacklist <assistant|executor> <on|off>. {summary}"
                    ),
                    summary=summary,
                ),
                parse_mode=None,
            )
            return

        feature_name = parts[1].lower()
        feature = self._resolve_feature(feature_name)
        if feature is None:
            await message.reply(
                gettext(
                    "blacklist.unknown_feature",
                    language=language,
                    default="❌ Unknown feature '{feature}'. Use assistant or executor.",
                    feature=html.escape(feature_name),
                ),
                parse_mode=None,
            )
            return

        action = parts[2].lower() if len(parts) > 2 else ""
        if action not in {"on", "off"}:
            summary = self._format_summary(message.chat.id, language)
            await message.reply(
                gettext(
                    "blacklist.invalid_action",
                    language=language,
                    default="Specify 'on' or 'off'. {summary}",
                    summary=summary,
                ),
                parse_mode=None,
            )
            return

        if action == "on":
            chat_access_storage.block(message.chat.id, feature.feature)
        else:
            chat_access_storage.unblock(message.chat.id, feature.feature)

        status = gettext(
            "blacklist.status.blocked" if action == "on" else "blacklist.status.allowed",
            language=language,
            default="blocked" if action == "on" else "allowed",
        )
        feature_label = gettext(
            feature.localized,
            language=language,
            default=feature.value,
        )
        await message.reply(
            gettext(
                "blacklist.updated",
                language=language,
                default="✅ {feature} is now {status} in this chat.",
                feature=feature_label,
                status=status,
            ),
            parse_mode=None,
        )

    async def _is_authorized(self, message: Message, bot: Bot) -> bool:
        if message.chat.type == "private":
            return True
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        except Exception:
            self._logger.exception(
                "Failed to fetch member info for chat %s", message.chat.id
            )
            return False
        status = getattr(member, "status", None)
        return status in {"administrator", "creator"}

    def _format_summary(self, chat_id: int, language: str) -> str:
        blocked = chat_access_storage.blocked_features(chat_id)
        if not blocked:
            return gettext(
                "blacklist.summary.none",
                language=language,
                default="All features allowed.",
            )
        parts = []
        for feature in sorted(blocked, key=lambda item: item.value):
            feature_label = gettext(
                FeatureName(feature.value).localized,
                language=language,
                default=feature.value,
            )
            parts.append(feature_label)
        feature_list = ", ".join(parts)
        return gettext(
            "blacklist.summary.blocked",
            language=language,
            default="Blocked: {features}.",
            features=feature_list,
        )

    def _resolve_feature(self, name: str) -> FeatureName | None:
        for feature in FeatureName:
            if feature.value == name:
                return feature
        return None


module = ChatAccessModule()
router = module.get_router()
priority = module.priority