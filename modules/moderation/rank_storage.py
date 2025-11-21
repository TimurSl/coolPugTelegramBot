import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from utils.path_utils import get_home_dir


@dataclass(frozen=True)
class ModeratorRank:
    """Represents a moderator rank with a permission level and display priority."""

    id: int
    name: str
    level: int
    priority: int


class ModeratorRankStorage:
    """Persistent storage for moderator rank metadata."""

    _lock = threading.RLock()

    def __init__(self, db_name: str = "moderation.db") -> None:
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = base_path / db_name
        logging.debug("Initialising ModeratorRankStorage at %s", self.db_path)
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moderator_ranks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    priority INTEGER NOT NULL,
                    UNIQUE(chat_id, level)
                )
                """
            )
        logging.debug("ModeratorRankStorage schema ensured")

    def _row_to_rank(self, row: tuple) -> ModeratorRank:
        return ModeratorRank(
            id=int(row[0]),
            name=str(row[2]),
            level=int(row[3]),
            priority=int(row[4]),
        )

    def ensure_defaults(self, chat_id: int) -> None:
        """Ensure base ranks exist for the chat to keep behaviour predictable."""

        default_ranks = [
            ("Member", 0, 0),
            ("Level 1", 1, 1),
            ("Level 2", 2, 2),
            ("Level 3", 3, 3),
            ("Level 4", 4, 4),
            ("Level 5", 5, 5),
        ]

        with self._lock:
            with self._get_connection() as conn:
                for name, level, priority in default_ranks:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO moderator_ranks (chat_id, name, level, priority)
                        VALUES (?, ?, ?, ?)
                        """,
                        (chat_id, name, level, priority),
                    )

    def add_rank(self, chat_id: int, name: str, priority: int) -> ModeratorRank:
        name = name.strip()
        if not name:
            raise ValueError("Rank name cannot be empty")

        with self._lock:
            with self._get_connection() as conn:
                current_max = conn.execute(
                    "SELECT COALESCE(MAX(level), 0) FROM moderator_ranks WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()[0]
                next_level = int(current_max) + 1
                cursor = conn.execute(
                    """
                    INSERT INTO moderator_ranks (chat_id, name, level, priority)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chat_id, name, next_level, priority),
                )
                rank_id = cursor.lastrowid
        logging.info(
            "Created rank id=%s chat_id=%s name=%s level=%s priority=%s",
            rank_id,
            chat_id,
            name,
            next_level,
            priority,
        )
        return ModeratorRank(id=int(rank_id), name=name, level=next_level, priority=priority)

    def rename_rank(self, chat_id: int, rank_id: int, name: str) -> bool:
        name = name.strip()
        if not name:
            return False
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    UPDATE moderator_ranks
                    SET name = ?
                    WHERE id = ? AND chat_id = ?
                    """,
                    (name, rank_id, chat_id),
                )
                updated = cursor.rowcount > 0
        logging.debug(
            "Renamed rank id=%s chat_id=%s to %s (updated=%s)",
            rank_id,
            chat_id,
            name,
            updated,
        )
        return updated

    def get_rank(self, chat_id: int, rank_id: int) -> Optional[ModeratorRank]:
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM moderator_ranks WHERE chat_id = ? AND id = ?",
                    (chat_id, rank_id),
                ).fetchone()
        return self._row_to_rank(row) if row else None

    def get_rank_by_level(self, chat_id: int, level: int) -> Optional[ModeratorRank]:
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM moderator_ranks WHERE chat_id = ? AND level = ?",
                    (chat_id, level),
                    ).fetchone()
        return self._row_to_rank(row) if row else None

    def list_ranks(self, chat_id: int) -> List[ModeratorRank]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM moderator_ranks WHERE chat_id = ?",
                    (chat_id,),
                ).fetchall()
        return [self._row_to_rank(row) for row in rows]

    def ensure_rank_for_level(self, chat_id: int, level: int) -> ModeratorRank:
        existing = self.get_rank_by_level(chat_id, level)
        if existing:
            return existing

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO moderator_ranks (chat_id, name, level, priority)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chat_id, f"Level {level}", level, level),
                )
                rank_id = cursor.lastrowid
        logging.info(
            "Created fallback rank id=%s chat_id=%s level=%s", rank_id, chat_id, level
        )
        return ModeratorRank(id=int(rank_id), name=f"Level {level}", level=level, priority=level)

    def _sorted(self, ranks: Iterable[ModeratorRank]) -> list[ModeratorRank]:
        return sorted(ranks, key=lambda rank: (rank.priority, -rank.level, rank.id))

    def ordered_ranks(self, chat_id: int) -> list[ModeratorRank]:
        return self._sorted(self.list_ranks(chat_id))


moderator_ranks = ModeratorRankStorage()

