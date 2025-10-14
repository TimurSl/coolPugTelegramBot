import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class UserStorage:
    _lock = threading.RLock()

    def __init__(
        self,
        db_path: str = "user_cache.db",
        legacy_json_path: Optional[str] = "users.json",
    ):
        self.db_path = Path(db_path)
        self.legacy_json_path = Path(legacy_json_path) if legacy_json_path else None
        logging.debug("UserStorage initialised with db=%s", self.db_path)
        self._initialise_database()
        self._import_legacy_json_if_needed()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _initialise_database(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_users (
                    chat_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    display_name TEXT,
                    PRIMARY KEY (chat_id, username),
                    UNIQUE (chat_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_stats (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id, date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_presence (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    first_seen TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
                """
            )

            # Backwards compatibility for display_name column
            cursor = conn.execute("PRAGMA table_info(chat_users)")
            columns = {row[1] for row in cursor.fetchall()}
            if "display_name" not in columns:
                logging.info("Adding display_name column to chat_users table")
                conn.execute(
                    "ALTER TABLE chat_users ADD COLUMN display_name TEXT"
                )
        logging.debug("UserStorage database initialised at %s", self.db_path)

    def _normalise_structure(self, raw: object) -> Dict[str, Any]:
        def normalise_username(value: str) -> str:
            return value.lower().lstrip("@")

        if not isinstance(raw, dict):
            return {"global": {}, "chats": {}}

        if "chats" in raw or "global" in raw:
            global_map = {}
            for username, user_id in raw.get("global", {}).items():
                if not isinstance(username, str) or not isinstance(user_id, int):
                    continue
                global_map[normalise_username(username)] = user_id

            chats_map: Dict[str, Dict[str, int]] = {}
            chats_raw = raw.get("chats", {})
            if isinstance(chats_raw, dict):
                for chat_id, users in chats_raw.items():
                    if not isinstance(users, dict):
                        continue
                    normalised_users: Dict[str, int] = {}
                    for username, user_id in users.items():
                        if not isinstance(username, str) or not isinstance(user_id, int):
                            continue
                        normalised_users[normalise_username(username)] = user_id
                    chats_map[str(chat_id)] = normalised_users
            return {"global": global_map, "chats": chats_map}

        legacy_map: Dict[str, int] = {}
        for username, user_id in raw.items():
            if not isinstance(username, str) or not isinstance(user_id, int):
                continue
            legacy_map[username.lower().lstrip("@")] = user_id
        return {"global": legacy_map, "chats": {}}

    def _import_legacy_json_if_needed(self):
        if not self.legacy_json_path or not self.legacy_json_path.exists():
            return

        logging.info(
            "Legacy users json detected at %s; beginning import to sqlite",
            self.legacy_json_path,
        )
        try:
            with self.legacy_json_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:
            logging.exception("Failed to read legacy users json %s: %s", self.legacy_json_path, exc)
            return

        data = self._normalise_structure(raw)
        imported_rows = 0
        with self._lock:
            with self._get_connection() as conn:
                for username, user_id in data.get("global", {}).items():
                    self._upsert_user_in_conn(conn, user_id, username)
                    imported_rows += 1
                for chat_id, users in data.get("chats", {}).items():
                    try:
                        normalised_chat_id = int(chat_id)
                    except (TypeError, ValueError):
                        logging.debug("Skipping legacy chat id %s - not an integer", chat_id)
                        continue
                    for username, user_id in users.items():
                        self._upsert_user_in_conn(conn, user_id, username, normalised_chat_id)
                        imported_rows += 1

        backup_path = self.legacy_json_path.with_name("olduserbd.json.bak")
        try:
            self.legacy_json_path.replace(backup_path)
            logging.info(
                "Imported %s legacy users into %s and renamed json to %s",
                imported_rows,
                self.db_path,
                backup_path,
            )
        except Exception as exc:
            logging.exception(
                "Imported legacy users but failed to rename %s to %s: %s",
                self.legacy_json_path,
                backup_path,
                exc,
            )

    @staticmethod
    def _normalise_username(username: str) -> str:
        return username.lower().lstrip("@")

    def _upsert_user_in_conn(
        self,
        conn: sqlite3.Connection,
        user_id: int,
        username: Optional[str],
        chat_id: Optional[int] = None,
        display_name: Optional[str] = None,
    ):
        if username:
            normalised_username = self._normalise_username(username)
            conn.execute(
                """
                UPDATE users
                SET username = ?
                WHERE user_id = ?
                """,
                (normalised_username, user_id),
            )
            conn.execute(
                """
                INSERT INTO users (username, user_id)
                VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET user_id = excluded.user_id
                """,
                (normalised_username, user_id),
            )

        if chat_id is not None and username:
            conn.execute(
                """
                UPDATE chat_users
                SET username = ?, display_name = COALESCE(?, display_name)
                WHERE chat_id = ? AND user_id = ?
                """,
                (normalised_username, display_name, chat_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO chat_users (chat_id, username, user_id, display_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, username) DO UPDATE SET
                    user_id = excluded.user_id,
                    display_name = COALESCE(excluded.display_name, chat_users.display_name)
                """,
                (chat_id, normalised_username, user_id, display_name),
            )

    def upsert_user(
        self,
        user_id: int,
        username: Optional[str],
        chat_id: Optional[int] = None,
        display_name: Optional[str] = None,
    ):
        if not username and not display_name:
            logging.debug(
                "Skipping upsert for user_id=%s due to empty username and display name",
                user_id,
            )
            return

        with self._lock:
            logging.debug(
                "Upserting user '%s' -> %s (chat_id=%s)",
                username,
                user_id,
                chat_id,
            )
            with self._get_connection() as conn:
                self._upsert_user_in_conn(conn, user_id, username, chat_id, display_name)

    def get_id_by_username(self, username: str) -> Optional[int]:
        normalised_username = self._normalise_username(username)
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT user_id FROM users WHERE username = ?",
                    (normalised_username,),
                )
                row = cursor.fetchone()
                if row:
                    user_id = row[0]
                    logging.debug("Lookup username '%s' -> %s (global)", normalised_username, user_id)
                    return user_id

                cursor = conn.execute(
                    "SELECT user_id FROM chat_users WHERE username = ? LIMIT 1",
                    (normalised_username,),
                )
                row = cursor.fetchone()
                if row:
                    user_id = row[0]
                    logging.debug(
                        "Lookup username '%s' -> %s (chat-specific)",
                        normalised_username,
                        user_id,
                    )
                    return user_id

        logging.debug("Lookup username '%s' -> not found", normalised_username)
        return None

    def get_username_by_id(self, user_id: int) -> Optional[str]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT username FROM users WHERE user_id = ?",
                    (user_id,),
                )
                row = cursor.fetchone()
                if row:
                    username = row[0]
                    logging.debug("Lookup user_id=%s -> username '%s' (global)", user_id, username)
                    return username

                cursor = conn.execute(
                    "SELECT username FROM chat_users WHERE user_id = ? LIMIT 1",
                    (user_id,),
                )
                row = cursor.fetchone()
                if row:
                    username = row[0]
                    logging.debug("Lookup user_id=%s -> username '%s' (chat-specific)", user_id, username)
                    return username

        logging.debug("No username found for user_id=%s", user_id)
        return None

    def get_random_user(self, chat_id: Optional[int]) -> Optional[Tuple[int, str, Optional[str]]]:
        if chat_id is None:
            logging.debug("Random user requested without chat_id")
            return None

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT user_id, username, display_name FROM chat_users
                    WHERE chat_id = ?
                    ORDER BY RANDOM()
                    LIMIT 1
                    """,
                    (chat_id,),
                )
                row = cursor.fetchone()

        if not row:
            logging.debug("Random user requested for chat_id=%s but none stored", chat_id)
            return None

        user_id, username, display_name = row
        logging.debug(
            "Random user selected for chat_id=%s: %s -> %s",
            chat_id,
            username,
            user_id,
        )
        return user_id, username, display_name

    def record_message_activity(
        self,
        *,
        chat_id: Optional[int],
        user_id: int,
        username: Optional[str],
        display_name: Optional[str],
        occurred_at: Optional[datetime],
    ) -> None:
        if chat_id is None:
            logging.debug("record_message_activity called without chat_id")
            return

        timestamp = occurred_at or datetime.utcnow()
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)

        date_str = timestamp.date().isoformat()

        with self._lock:
            with self._get_connection() as conn:
                self._upsert_user_in_conn(conn, user_id, username, chat_id, display_name)
                conn.execute(
                    """
                    INSERT INTO message_stats (chat_id, user_id, date, count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(chat_id, user_id, date) DO UPDATE SET
                        count = count + 1
                    """,
                    (chat_id, user_id, date_str),
                )
                conn.execute(
                    """
                    INSERT INTO user_presence (chat_id, user_id, first_seen)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chat_id, user_id) DO NOTHING
                    """,
                    (chat_id, user_id, timestamp.isoformat()),
                )

    def get_message_statistics(
        self,
        chat_id: int,
        user_id: int,
        *,
        reference: Optional[datetime] = None,
    ) -> Dict[str, int]:
        ref = reference or datetime.utcnow()
        ref_date = ref.date()
        day_key = ref_date.isoformat()
        week_start = (ref_date - timedelta(days=6)).isoformat()
        month_start = ref_date.replace(day=1).isoformat()

        with self._lock:
            with self._get_connection() as conn:
                day_row = conn.execute(
                    """
                    SELECT count FROM message_stats
                    WHERE chat_id = ? AND user_id = ? AND date = ?
                    """,
                    (chat_id, user_id, day_key),
                ).fetchone()
                week_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(count), 0) FROM message_stats
                    WHERE chat_id = ? AND user_id = ? AND date >= ?
                    """,
                    (chat_id, user_id, week_start),
                ).fetchone()
                month_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(count), 0) FROM message_stats
                    WHERE chat_id = ? AND user_id = ? AND date >= ?
                    """,
                    (chat_id, user_id, month_start),
                ).fetchone()
                total_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(count), 0) FROM message_stats
                    WHERE chat_id = ? AND user_id = ?
                    """,
                    (chat_id, user_id),
                ).fetchone()

        return {
            "day": day_row[0] if day_row else 0,
            "week": week_row[0] if week_row else 0,
            "month": month_row[0] if month_row else 0,
            "total": total_row[0] if total_row else 0,
        }

    def get_top_users(
        self,
        chat_id: int,
        period: str,
        *,
        limit: int = 10,
        reference: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []

        ref = reference or datetime.utcnow()
        ref_date = ref.date()
        filters = ["ms.chat_id = ?"]
        params: list[Any] = [chat_id]

        if period == "day":
            filters.append("ms.date = ?")
            params.append(ref_date.isoformat())
        elif period == "week":
            filters.append("ms.date >= ?")
            params.append((ref_date - timedelta(days=6)).isoformat())
        elif period == "month":
            filters.append("ms.date >= ?")
            params.append(ref_date.replace(day=1).isoformat())
        elif period in {"total", "all"}:
            pass
        else:
            raise ValueError(f"Unsupported period '{period}'")

        where_clause = " AND ".join(filters)
        query = f"""
            SELECT
                ms.user_id,
                SUM(ms.count) AS total_count,
                MAX(cu.display_name) AS display_name,
                MAX(cu.username) AS chat_username,
                MAX(u.username) AS global_username
            FROM message_stats ms
            LEFT JOIN chat_users cu
                ON cu.chat_id = ms.chat_id AND cu.user_id = ms.user_id
            LEFT JOIN users u ON u.user_id = ms.user_id
            WHERE {where_clause}
            GROUP BY ms.user_id
            ORDER BY total_count DESC, ms.user_id ASC
            LIMIT ?
        """

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(query, (*params, limit))
                rows = cursor.fetchall()

        results: List[Dict[str, Any]] = []
        for user_id, total_count, display_name, chat_username, global_username in rows:
            results.append(
                {
                    "user_id": user_id,
                    "count": total_count,
                    "display_name": display_name,
                    "chat_username": chat_username,
                    "global_username": global_username,
                }
            )

        return results

    def get_first_seen(self, chat_id: int, user_id: int) -> Optional[datetime]:
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT first_seen FROM user_presence
                    WHERE chat_id = ? AND user_id = ?
                    """,
                    (chat_id, user_id),
                ).fetchone()

        if not row or not row[0]:
            return None

        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            logging.debug(
                "Failed to parse first_seen timestamp '%s' for chat_id=%s user_id=%s",
                row[0],
                chat_id,
                user_id,
            )
            return None

    def get_display_name(self, chat_id: int, user_id: int) -> Optional[str]:
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT display_name FROM chat_users
                    WHERE chat_id = ? AND user_id = ?
                    """,
                    (chat_id, user_id),
                ).fetchone()

        if row and row[0]:
            return row[0]
        return None

