import sqlite3
from pathlib import Path
from typing import List

from utils.path_utils import get_home_dir


class AutoDeleteStorage:
    def __init__(self, db_name: str = "autodelete.db"):
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = base_path / db_name
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auto_delete_commands (
                    chat_id INTEGER NOT NULL,
                    command TEXT NOT NULL,
                    PRIMARY KEY (chat_id, command)
                )
                """
            )

    @staticmethod
    def normalise_command(command: str) -> str:
        command = command.strip()
        if not command.startswith("/"):
            raise ValueError("Command must start with '/'")
        command = command.split()[0]
        if "@" in command:
            command = command.split("@", 1)[0]
        return command.lower()

    def enable(self, chat_id: int, command: str) -> None:
        command = self.normalise_command(command)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO auto_delete_commands (chat_id, command) VALUES (?, ?)",
                (chat_id, command),
            )

    def disable(self, chat_id: int, command: str) -> None:
        command = self.normalise_command(command)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM auto_delete_commands WHERE chat_id=? AND command=?",
                (chat_id, command),
            )

    def toggle(self, chat_id: int, command: str) -> bool:
        command = self.normalise_command(command)
        if self.is_enabled(chat_id, command):
            self.disable(chat_id, command)
            return False
        self.enable(chat_id, command)
        return True

    def is_enabled(self, chat_id: int, command: str) -> bool:
        command = self.normalise_command(command)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM auto_delete_commands WHERE chat_id=? AND command=?",
                (chat_id, command),
            ).fetchone()
            return row is not None

    def list_commands(self, chat_id: int) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT command FROM auto_delete_commands WHERE chat_id=? ORDER BY command",
                (chat_id,),
            ).fetchall()
        return [row[0] for row in rows]
