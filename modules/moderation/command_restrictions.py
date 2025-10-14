import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Sequence

from utils.path_utils import get_home_dir


def _normalise_command_name(command: str) -> str:
    command = (command or "").strip()
    if command.startswith("/"):
        command = command[1:]
    if "@" in command:
        command = command.split("@", 1)[0]
    return command.lower()


class CommandRestrictionStorage:
    _lock = threading.RLock()

    def __init__(self, db_name: str = "moderation.db") -> None:
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = base_path / db_name
        logging.debug(
            "Initialising CommandRestrictionStorage at %s", self.db_path
        )
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_levels (
                    chat_id INTEGER NOT NULL,
                    command TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, command)
                )
                """
            )
        logging.debug("CommandRestrictionStorage schema ensured")

    def set_command_level(self, chat_id: int, command: str, level: int) -> None:
        normalised = _normalise_command_name(command)
        if not normalised:
            raise ValueError("Command name cannot be empty")

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO command_levels (chat_id, command, level)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chat_id, command) DO UPDATE SET level = excluded.level
                    """,
                    (chat_id, normalised, level),
                )
        logging.debug(
            "Set restriction for chat_id=%s command=%s level=%s",
            chat_id,
            normalised,
            level,
        )

    def clear_command_level(self, chat_id: int, command: str) -> bool:
        normalised = _normalise_command_name(command)
        if not normalised:
            return False

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM command_levels WHERE chat_id = ? AND command = ?",
                    (chat_id, normalised),
                )
                deleted = cursor.rowcount > 0
        logging.debug(
            "Cleared restriction for chat_id=%s command=%s (deleted=%s)",
            chat_id,
            normalised,
            deleted,
        )
        return deleted

    def get_command_level(self, chat_id: int, command: str) -> Optional[int]:
        normalised = _normalise_command_name(command)
        if not normalised:
            return None

        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT level FROM command_levels WHERE chat_id = ? AND command = ?",
                    (chat_id, normalised),
                ).fetchone()
        if row:
            logging.debug(
                "Restriction lookup chat_id=%s command=%s -> %s",
                chat_id,
                normalised,
                row[0],
            )
            return int(row[0])
        logging.debug(
            "Restriction lookup chat_id=%s command=%s -> not set",
            chat_id,
            normalised,
        )
        return None

    def list_command_levels(self, chat_id: int) -> dict[str, int]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT command, level FROM command_levels WHERE chat_id = ?",
                    (chat_id,),
                ).fetchall()
        return {str(command): int(level) for command, level in rows}



command_restrictions = CommandRestrictionStorage()


def extract_command_name(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    first_part = stripped.split(maxsplit=1)[0]
    normalised = _normalise_command_name(first_part)
    return normalised or None


def get_effective_command_level(
    chat_id: int,
    command: str,
    default_level: int,
    *,
    aliases: Sequence[str] = (),
) -> int:
    seen: set[str] = set()

    def _candidates() -> list[str]:
        ordered = [command, *aliases]
        result: list[str] = []
        for name in ordered:
            normalised = _normalise_command_name(name)
            if not normalised or normalised in seen:
                continue
            seen.add(normalised)
            result.append(normalised)
        return result

    for candidate in _candidates():
        override = command_restrictions.get_command_level(chat_id, candidate)
        if override is not None:
            return override
    return default_level


__all__ = [
    "CommandRestrictionStorage",
    "command_restrictions",
    "extract_command_name",
    "get_effective_command_level",
    "_normalise_command_name",
]
