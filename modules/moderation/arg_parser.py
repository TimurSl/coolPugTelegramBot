from typing import Tuple, Optional, List

from aiogram.types import Message
from modules.collector.utils import UserCollector
from utils.time_utils import TimeUtils


class ModerationArgParser:
    """Flexible argument parser for moderation commands"""

    @staticmethod
    def extract_user_from_message(message: Message, args: List[str]) -> Tuple[Optional[int], List[str]]:
        """
        Extract user ID from message (reply, mention, or ID)
        Returns: (user_id, remaining_args)
        """
        # Check if replying to a message
        if message.reply_to_message and message.reply_to_message.from_user:
            return message.reply_to_message.from_user.id, args

        # Look for user mention or ID in arguments
        for i, arg in enumerate(args):
            # Check for @username mention
            if arg.startswith('@'):
                uid = UserCollector.get_id(arg)
                if uid:
                    remaining_args = args[:i] + args[i + 1:]
                    return uid, remaining_args

            # Check for user ID (numeric)
            if arg.isdigit():
                user_id = int(arg)
                remaining_args = args[:i] + args[i + 1:]
                return user_id, remaining_args

        return None, args

    @classmethod
    def parse_moderation_args(cls, message: Message, command_args: str) -> dict:
        """
        Parse moderation command arguments flexibly
        Handles: /ban @user 1d reason, /ban 1d @user reason, /ban reason @user 1d
        """
        args = command_args.split() if command_args else []

        result = {
            'user_id': None,
            'duration': None,
            'reason': None,
            'success': False
        }

        # Extract user from reply or arguments
        user_id, remaining_args = cls.extract_user_from_message(message, args)
        result['user_id'] = user_id

        if not user_id and not message.reply_to_message:
            result['reason'] = "No user specified. Reply to a message or mention a user."
            return result

        # Look for duration in remaining args
        duration = None
        duration_arg_index = None

        for i, arg in enumerate(remaining_args):
            parsed_duration = TimeUtils.parse_duration(arg)
            if parsed_duration is not None:
                duration = parsed_duration
                duration_arg_index = i
                break

        result['duration'] = duration

        # Everything else is the reason
        reason_args = remaining_args.copy()
        if duration_arg_index is not None:
            reason_args.pop(duration_arg_index)

        if reason_args:
            result['reason'] = ' '.join(reason_args)

        result['success'] = True
        return result