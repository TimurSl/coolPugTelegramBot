import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from utils.path_utils import get_home_dir


class ModerationLevelStorage:
    """Persistent storage for per-user moderation levels."""

    _lock = threading.RLock()

    def __init__(self, db_name: str = "moderation.db") -> None:
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = base_path / db_name
        logging.debug("Initialising ModerationLevelStorage at %s", self.db_path)
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_levels (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    level INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
                """
            )
        logging.debug("ModerationLevelStorage schema ensured")

    def set_level(self, chat_id: int, user_id: int, level: int) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO moderation_levels (chat_id, user_id, level)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chat_id, user_id) DO UPDATE SET level = excluded.level
                    """,
                    (chat_id, user_id, level),
                )
        logging.debug(
            "Set moderation level for user_id=%s chat_id=%s to %s",
            user_id,
            chat_id,
            level,
        )

    def clear_level(self, chat_id: int, user_id: int) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM moderation_levels WHERE chat_id = ? AND user_id = ?",
                    (chat_id, user_id),
                )
        logging.debug(
            "Cleared moderation level for user_id=%s chat_id=%s",
            user_id,
            chat_id,
        )

    def get_level(self, chat_id: int, user_id: int) -> Optional[int]:
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT level FROM moderation_levels WHERE chat_id = ? AND user_id = ?",
                    (chat_id, user_id),
                ).fetchone()

        return row[0] if row else None

    def get_effective_level(self, chat_id: int, user_id: int, *, status: Optional[str]) -> int:
        stored = self.get_level(chat_id, user_id)
        if stored is not None:
            return stored

        status = (status or "member").lower()
        if status == "creator":
            return 5
        if status == "administrator":
            return 3
        if status in {"restricted", "limited"}:
            return 0
        return 0

    def get_levels_for_chat(self, chat_id: int) -> dict[int, int]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT user_id, level FROM moderation_levels WHERE chat_id = ?",
                    (chat_id,),
                ).fetchall()

        return {int(user_id): int(level) for user_id, level in rows}

    def get_chats_for_user(self, user_id: int) -> dict[int, int]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT chat_id, level FROM moderation_levels WHERE user_id = ?",
                    (user_id,),
                ).fetchall()

        return {int(chat_id): int(level) for chat_id, level in rows}


moderation_levels = ModerationLevelStorage()
