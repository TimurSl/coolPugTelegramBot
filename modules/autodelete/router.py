"""Handlers for the /autodelete command group."""

from __future__ import annotations

import logging
from typing import Tuple

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from modules.autodelete.storage import AutoDeleteStorage
from modules.moderation.command_restrictions import (
    extract_command_name,
    get_effective_command_level,
)
from modules.moderation.level_storage import moderation_levels
from utils.localization import gettext, language_from_message

router = Router(name="autodelete")
priority = 40

storage = AutoDeleteStorage()


async def _check_permission(
    message: Message,
    *,
    canonical: str,
    default_level: int,
    aliases: tuple[str, ...] = (),
) -> Tuple[bool, int]:
    command_name = extract_command_name(message.text or message.caption)
    candidates = []
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

    status = None
    try:
        member = await message.chat.get_member(message.from_user.id)
        status = getattr(member, "status", None)
    except Exception:
        member = None
    level = moderation_levels.get_effective_level(
        message.chat.id, message.from_user.id, status=status
    )
    return level >= required_level, required_level


@router.message(Command("autodelete"))
async def handle_autodelete_toggle(message: Message) -> None:
    language = language_from_message(message)
    logging.getLogger(__name__).debug(
        "Handling /autodelete in chat %s by user %s",
        message.chat.id,
        message.from_user.id,
    )
    allowed, required_level = await _check_permission(
        message,
        canonical="autodelete",
        default_level=1,
        aliases=("nodelete",),
    )
    if not allowed:
        await message.answer(
            gettext(
                "autodelete.permission_denied",
                language=language,
                default="❌ Only level {level}+ members can manage auto-delete.",
                level=required_level,
            )
        )
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            gettext(
                "autodelete.usage.add",
                language=language,
                default="Usage: /autodelete /command",
            )
        )
        return

    command = args[1].strip()
    try:
        normalised = AutoDeleteStorage.normalise_command(command)
        enabled = storage.toggle(message.chat.id, normalised)
    except ValueError:
        await message.answer(
            gettext(
                "autodelete.invalid_command",
                language=language,
                default="❌ The command must start with '/'.",
            )
        )
        return

    if enabled:
        response = gettext(
            "autodelete.toggle.enabled",
            language=language,
            default="✅ Command {command} will now be auto-deleted.",
            command=normalised,
        )
    else:
        response = gettext(
            "autodelete.toggle.disabled",
            language=language,
            default="ℹ️ Command {command} will no longer be auto-deleted.",
            command=normalised,
        )

    await message.answer(response)
    try:
        await message.delete()
    except Exception:
        pass


@router.message(Command("nodelete"))
async def handle_nodelete(message: Message) -> None:
    language = language_from_message(message)
    logging.getLogger(__name__).debug(
        "Handling /nodelete in chat %s by user %s",
        message.chat.id,
        message.from_user.id,
    )
    allowed, required_level = await _check_permission(
        message,
        canonical="nodelete",
        default_level=1,
        aliases=("autodelete",),
    )
    if not allowed:
        await message.answer(
            gettext(
                "autodelete.permission_denied",
                language=language,
                default="❌ Only level {level}+ members can manage auto-delete.",
                level=required_level,
            )
        )
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            gettext(
                "autodelete.usage.remove",
                language=language,
                default="Usage: /nodelete /command",
            )
        )
        return

    command = args[1].strip()
    try:
        normalised = AutoDeleteStorage.normalise_command(command)
        storage.disable(message.chat.id, normalised)
    except ValueError:
        await message.answer(
            gettext(
                "autodelete.invalid_command",
                language=language,
                default="❌ The command must start with '/'.",
            )
        )
        return

    await message.answer(
        gettext(
            "autodelete.toggle.disabled",
            language=language,
            default="ℹ️ Command {command} will no longer be auto-deleted.",
            command=normalised,
        )
    )
    try:
        await message.delete()
    except Exception:
        pass


@router.message(Command("autodeletelist"))
async def handle_autodelete_list(message: Message) -> None:
    language = language_from_message(message)
    logging.getLogger(__name__).debug(
        "Handling /autodeletelist in chat %s by user %s",
        message.chat.id,
        message.from_user.id,
    )
    commands = storage.list_commands(message.chat.id)
    if not commands:
        await message.answer(
            gettext(
                "autodelete.list.empty",
                language=language,
                default="ℹ️ Auto-delete is not configured for any commands.",
            )
        )
        return

    formatted = "\n".join(f"• {cmd}" for cmd in commands)
    await message.answer(
        gettext(
            "autodelete.list.success",
            language=language,
            default="🧾 Auto-delete commands:\n{commands}",
            commands=formatted,
        )
    )

