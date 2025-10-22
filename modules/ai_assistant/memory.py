from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from utils.path_utils import get_home_dir


@dataclass(frozen=True)
class MemoryEntry:
    username: str | None
    user_id: int
    user_summary: str
    ai_summary: str
    created_at: datetime


class AIMemoryRepository:
    """Persistent storage for AI interaction summaries."""

    def __init__(self, db_name: str = "ai_memory.db") -> None:
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self._db_path = base_path / db_name
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    user_id INTEGER NOT NULL,
                    user_summary TEXT NOT NULL,
                    ai_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_memories_user
                ON ai_memories(user_id, created_at)
                """
            )

    def add_memory(
        self,
        *,
        username: str | None,
        user_id: int,
        user_summary: str,
        ai_summary: str,
    ) -> None:
        timestamp = datetime.utcnow().isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO ai_memories (username, user_id, user_summary, ai_summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, user_id, user_summary, ai_summary, timestamp),
            )

    def get_recent(self, user_id: int, limit: int = 3) -> List[MemoryEntry]:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                """
                SELECT username, user_id, user_summary, ai_summary, created_at
                FROM ai_memories
                WHERE user_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = cursor.fetchall()

        entries: List[MemoryEntry] = []
        for username, uid, user_summary, ai_summary, created_at in rows:
            parsed = self._safe_fromisoformat(created_at)
            if parsed is None:
                parsed = datetime.utcnow()
            entries.append(
                MemoryEntry(
                    username=username,
                    user_id=int(uid),
                    user_summary=user_summary,
                    ai_summary=ai_summary,
                    created_at=parsed,
                )
            )
        return entries

    @staticmethod
    def _safe_fromisoformat(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None