"""Award-related handlers for the moderation module."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message

from modules.moderation.data import ModerationAction


async def handle_award(module: "AdvancedModerationModule", message: Message, bot: Bot) -> None:
    """Delegate for :meth:`AdvancedModerationModule.handle_award`."""

    language = module._language(message)
    raw_text = (message.text or message.caption or "").strip()
    parts = raw_text.split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            module._t(
                "moderation.award.usage",
                language,
                "Usage: /award <text> (reply to a user's message).",
            ),
            parse_mode=None,
        )
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply(
            module._t(
                "moderation.award.reply_required",
                language,
                "❌ You must reply to a user's message to give an award.",
            ),
            parse_mode=None,
        )
        return

    actor_level, _ = await module._get_member_level(message, message.from_user.id)
    required_level, _ = module._command_requirement(
        message,
        default_level=2,
        canonical="award",
    )
    if actor_level < required_level:
        await message.reply(
            module._t(
                "moderation.award.level_required",
                language,
                "❌ You need moderation level {level}+ to add awards.",
                level=required_level,
            ),
            parse_mode=None,
        )
        return

    award_text = parts[1].strip()
    target_user = message.reply_to_message.from_user
    award_id = module.db.add_award(
        message.chat.id, target_user.id, message.from_user.id, award_text
    )

    module.db.add_action(
        ModerationAction(
            action_type="award",
            user_id=target_user.id,
            admin_id=message.from_user.id,
            chat_id=message.chat.id,
            reason=award_text,
        ),
        active=False,
    )

    target_name = await module._resolve_display_name(message, target_user.id)
    response = module._t(
        "moderation.award.success",
        language,
        "🏅 Award #{award_id} added for {target}: {text}",
        award_id=award_id,
        target=target_name,
        text=award_text,
    )
    await message.reply(response, parse_mode="HTML")


async def handle_delete_award(
    module: "AdvancedModerationModule", message: Message, bot: Bot
) -> None:
    """Delegate for :meth:`AdvancedModerationModule.handle_delete_award`."""

    language = module._language(message)
    raw_text = (message.text or message.caption or "").strip()
    parts = raw_text.split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip():
        await message.reply(
            module._t(
                "moderation.award.delete_usage",
                language,
                "Usage: /delreward <award id>.",
            ),
            parse_mode=None,
        )
        return

    arg = parts[1].strip().split()[0]
    try:
        award_id = int(arg)
    except ValueError:
        await message.reply(
            module._t(
                "moderation.award.delete_invalid",
                language,
                "❌ Award id must be a number.",
            ),
            parse_mode=None,
        )
        return

    award = module.db.get_award(award_id)
    if not award or award.get("chat_id") != message.chat.id:
        await message.reply(
            module._t(
                "moderation.award.delete_missing",
                language,
                "❌ Award not found for this chat.",
            ),
            parse_mode=None,
        )
        return

    actor_level, _ = await module._get_member_level(message, message.from_user.id)
    required_level, _ = module._command_requirement(
        message,
        default_level=3,
        canonical="delreward",
    )
    if award.get("admin_id") != message.from_user.id:
        if actor_level < required_level:
            await message.reply(
                module._t(
                    "moderation.award.delete_level",
                    language,
                    "❌ You need moderation level {level}+ to remove someone else's award.",
                    level=required_level,
                ),
                parse_mode=None,
            )
            return

        target_level, _ = await module._get_member_level(message, award["user_id"])

        if award["user_id"] != message.from_user.id and actor_level <= target_level:
            await message.reply(
                module._t(
                    "moderation.award.delete_forbidden",
                    language,
                    "❌ You cannot remove awards from this user.",
                ),
                parse_mode=None,
            )
            return

    if not module.db.delete_award(award_id):
        await message.reply(
            module._t(
                "moderation.award.delete_missing",
                language,
                "❌ Award not found for this chat.",
            ),
            parse_mode=None,
        )
        return

    module.db.add_action(
        ModerationAction(
            action_type="delreward",
            user_id=award["user_id"],
            admin_id=message.from_user.id,
            chat_id=message.chat.id,
            reason=award.get("text"),
        ),
        active=False,
    )

    target_name = await module._resolve_display_name(message, award["user_id"])
    response = module._t(
        "moderation.award.delete_success",
        language,
        "🗑 Removed award #{award_id} from {target}.",
        award_id=award_id,
        target=target_name,
    )
    await message.reply(response, parse_mode="HTML")


# The imports are intentionally placed at the end to avoid circular dependencies
# when type checking. They are only needed for type hinting at runtime.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported only for typing
    from modules.moderation.router import AdvancedModerationModule
