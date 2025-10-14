import sqlite3
from pathlib import Path
from typing import Optional

from utils.path_utils import get_home_dir


class CustomNicknameStorage:
    """Storage for custom RP nicknames per chat."""

    def __init__(self, db_name: str = "roleplay_nicks.db"):
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = base_path / db_name
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_nicks (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    nickname TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
                """
            )

    def set_nickname(self, chat_id: int, user_id: int, nickname: str) -> None:
        nickname = nickname.strip()
        if not nickname:
            raise ValueError("Nickname must not be empty")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO custom_nicks (chat_id, user_id, nickname)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET nickname=excluded.nickname
                """,
                (chat_id, user_id, nickname),
            )

    def clear_nickname(self, chat_id: int, user_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM custom_nicks WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            return cursor.rowcount > 0

    def get_nickname(self, chat_id: int, user_id: int) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT nickname FROM custom_nicks WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            row = cursor.fetchone()
            return row[0] if row else None
