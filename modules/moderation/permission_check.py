from typing import Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner

from modules.moderation.level_storage import moderation_levels


class PermissionChecker:
    """Check admin permissions for moderation actions"""

    @staticmethod
    async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
        """Check if user is admin in chat"""
        status = None
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            status = getattr(member, "status", None)
        except TelegramAPIError:
            member = None
        level = moderation_levels.get_effective_level(chat_id, user_id, status=status)
        return level >= 1

    @staticmethod
    async def can_restrict_members(bot: Bot, chat_id: int, user_id: int) -> bool:
        """Check if admin can restrict members"""
        status = None
        member = None
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            status = getattr(member, "status", None)
        except TelegramAPIError:
            pass
        level = moderation_levels.get_effective_level(chat_id, user_id, status=status)
        if level >= 1:
            return True
        if isinstance(member, ChatMemberOwner):
            return True
        if isinstance(member, ChatMemberAdministrator):
            return bool(member.can_restrict_members)
        return False

    @staticmethod
    async def can_moderate_user(bot: Bot, chat_id: int, admin_id: int, target_id: int) -> Tuple[bool, str]:
        """Check if admin can moderate target user"""
        admin_error = None
        target_error = None
        admin_member = None
        target_member = None

        try:
            admin_member = await bot.get_chat_member(chat_id, admin_id)
            admin_status = getattr(admin_member, "status", None)
        except TelegramAPIError as exc:
            admin_error = exc
            admin_status = None

        try:
            target_member = await bot.get_chat_member(chat_id, target_id)
            target_status = getattr(target_member, "status", None)
        except TelegramAPIError as exc:
            target_error = exc
            target_status = None

        admin_level = moderation_levels.get_effective_level(
            chat_id, admin_id, status=admin_status
        )
        if admin_level <= 0:
            return False, "You don't have permission to restrict members"

        target_level = moderation_levels.get_effective_level(
            chat_id, target_id, status=target_status
        )
        if target_id != admin_id and target_level >= admin_level:
            return False, "Cannot moderate members with equal or higher level"

        if admin_error:
            return False, f"Error checking permissions: {admin_error}"
        if target_error:
            return False, f"Error checking permissions: {target_error}"

        return True, "OK"
