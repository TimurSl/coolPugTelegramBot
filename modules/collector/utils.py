import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .storage import UserStorage


class UserCollector:
    """Статический доступ к хранилищу пользователей (sqlite)"""

    storage = UserStorage()

    @staticmethod
    def get_id(username: str) -> Optional[int]:
        logging.debug("UserCollector.get_id lookup for username=%s", username)
        return UserCollector.storage.get_id_by_username(username)

    @staticmethod
    def get_username(user_id: int) -> Optional[str]:
        logging.debug("UserCollector.get_username lookup for user_id=%s", user_id)
        return UserCollector.storage.get_username_by_id(user_id)

    @staticmethod
    def get_random_user(chat_id: Optional[int]) -> Optional[Tuple[int, str, Optional[str]]]:
        logging.debug("UserCollector.get_random_user invoked for chat_id=%s", chat_id)
        return UserCollector.storage.get_random_user(chat_id)

    @staticmethod
    def record_activity(
        *,
        chat_id: Optional[int],
        user_id: int,
        username: Optional[str],
        display_name: Optional[str],
        occurred_at: Optional[datetime],
    ) -> None:
        logging.debug(
            "Recording activity for user_id=%s in chat_id=%s", user_id, chat_id
        )
        UserCollector.storage.record_message_activity(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            display_name=display_name,
            occurred_at=occurred_at,
        )

    @staticmethod
    def get_statistics(
        chat_id: int, user_id: int, *, reference: Optional[datetime] = None
    ) -> Dict[str, int]:
        logging.debug(
            "Fetching statistics for user_id=%s in chat_id=%s", user_id, chat_id
        )
        return UserCollector.storage.get_message_statistics(
            chat_id, user_id, reference=reference
        )

    @staticmethod
    def get_top_users(
        chat_id: int,
        period: str,
        *,
        limit: int = 10,
        reference: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        logging.debug(
            "Fetching top users for chat_id=%s period=%s limit=%s",
            chat_id,
            period,
            limit,
        )
        return UserCollector.storage.get_top_users(
            chat_id,
            period,
            limit=limit,
            reference=reference,
        )

    @staticmethod
    def get_first_seen(chat_id: int, user_id: int) -> Optional[datetime]:
        logging.debug(
            "Fetching first_seen for user_id=%s in chat_id=%s", user_id, chat_id
        )
        return UserCollector.storage.get_first_seen(chat_id, user_id)

    @staticmethod
    def get_display_name(chat_id: int, user_id: int) -> Optional[str]:
        logging.debug(
            "Fetching display name for user_id=%s in chat_id=%s", user_id, chat_id
        )
        return UserCollector.storage.get_display_name(chat_id, user_id)

