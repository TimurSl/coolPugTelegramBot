"""Persistence layer for NSFW checker configuration."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Set

from utils.path_utils import get_home_dir


class NsfwSettingsStorage:
    """Manage chat and topic configuration for the NSFW checker."""

    def __init__(self, db_name: str = "nsfw_checker.db") -> None:
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = base_path / db_name
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS enabled_chats (
                    chat_id INTEGER PRIMARY KEY
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ignored_topics (
                    chat_id INTEGER NOT NULL,
                    topic_id INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, topic_id)
                )
                """
            )

    def enable_chat(self, chat_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO enabled_chats (chat_id) VALUES (?)",
                (chat_id,),
            )

    def disable_chat(self, chat_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM enabled_chats WHERE chat_id=?", (chat_id,))
            conn.execute("DELETE FROM ignored_topics WHERE chat_id=?", (chat_id,))

    def is_chat_enabled(self, chat_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM enabled_chats WHERE chat_id=?", (chat_id,)
            ).fetchone()
        return row is not None

    def ignore_topic(self, chat_id: int, topic_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO ignored_topics (chat_id, topic_id) VALUES (?, ?)",
                (chat_id, topic_id),
            )

    def unignore_topic(self, chat_id: int, topic_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM ignored_topics WHERE chat_id=? AND topic_id=?",
                (chat_id, topic_id),
            )

    def is_topic_ignored(self, chat_id: int, topic_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM ignored_topics WHERE chat_id=? AND topic_id=?",
                (chat_id, topic_id),
            ).fetchone()
        return row is not None

    def list_ignored_topics(self, chat_id: int) -> Set[int]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT topic_id FROM ignored_topics WHERE chat_id=?",
                (chat_id,),
            ).fetchall()
        return {row[0] for row in rows}

