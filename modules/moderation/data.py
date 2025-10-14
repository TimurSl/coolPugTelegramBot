import sqlite3
import logging
from dataclasses import field, dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Sequence, Tuple
from pathlib import Path


def _safe_fromisoformat(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class ModerationAction:
    """Data class for moderation actions"""
    action_type: str  # ban, mute, warn, kick
    user_id: int
    admin_id: int
    chat_id: int
    duration: Optional[timedelta] = None
    reason: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None


class ModerationDatabase:
    """Database handler for moderation actions"""

    def __init__(self, db_path: str = "moderation.db"):
        self.db_path = db_path
        self.init_database()
        absolutepath = Path(__file__).parent.absolute() / self.db_path
        logging.info("ModerationDatabase initialized with DB at %s", absolutepath)

    def init_database(self):
        """Initialize database tables"""
        logging.info("init db")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                         CREATE TABLE IF NOT EXISTS moderation_actions
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             action_type
                             TEXT
                             NOT
                             NULL,
                             user_id
                             INTEGER
                             NOT
                             NULL,
                             admin_id
                             INTEGER
                             NOT
                             NULL,
                             chat_id
                             INTEGER
                             NOT
                             NULL,
                             duration_seconds
                             INTEGER,
                             reason
                             TEXT,
                             timestamp
                             TEXT
                             NOT
                             NULL,
                             expires_at
                             TEXT,
                             active
                             BOOLEAN
                             DEFAULT
                             TRUE
                         )
                         ''')

            conn.execute('''
                         CREATE TABLE IF NOT EXISTS warnings
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             user_id
                             INTEGER
                             NOT
                             NULL,
                             chat_id
                             INTEGER
                             NOT
                             NULL,
                             admin_id
                             INTEGER
                             NOT
                             NULL,
                             reason
                             TEXT,
                             timestamp
                             TEXT
                             NOT
                             NULL,
                             active
                             BOOLEAN
                             DEFAULT
                             TRUE
                         )
                         ''')

            conn.execute('''
                         CREATE TABLE IF NOT EXISTS awards
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             chat_id
                             INTEGER
                             NOT
                             NULL,
                             user_id
                             INTEGER
                             NOT
                             NULL,
                             admin_id
                             INTEGER
                             NOT
                             NULL,
                             text
                             TEXT
                             NOT
                             NULL,
                             timestamp
                             TEXT
                             NOT
                             NULL
                         )
                         ''')

            conn.execute('''
                         CREATE TABLE IF NOT EXISTS reports
                         (
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             chat_id INTEGER NOT NULL,
                             chat_title TEXT,
                             chat_username TEXT,
                             message_id INTEGER NOT NULL,
                             reporter_id INTEGER NOT NULL,
                             target_user_id INTEGER,
                             target_user_name TEXT,
                             message_text TEXT,
                             has_photo BOOLEAN DEFAULT FALSE,
                             has_video BOOLEAN DEFAULT FALSE,
                             created_at TEXT NOT NULL,
                             status TEXT DEFAULT 'open',
                             closed_by_user_id INTEGER,
                             closed_by_user_name TEXT
                         )
                         ''')

            conn.execute('''
                         CREATE TABLE IF NOT EXISTS appeals
                         (
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             user_id INTEGER NOT NULL,
                             description TEXT NOT NULL,
                             created_at TEXT NOT NULL,
                             status TEXT DEFAULT 'open'
                         )
                         ''')

            self._ensure_column_exists(
                conn,
                "reports",
                "closed_by_user_id",
                "INTEGER",
            )
            self._ensure_column_exists(
                conn,
                "reports",
                "closed_by_user_name",
                "TEXT",
            )

            logging.info("Database initialized")

    def _ensure_column_exists(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        """Ensure a column exists on the given table, adding it if necessary."""

        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        existing_columns = {info[1] for info in cursor.fetchall()}
        if column not in existing_columns:
            logging.info("Adding missing column %s.%s", table, column)
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def add_action(self, action: ModerationAction, *, active: bool = True) -> int:
        """Add moderation action to database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           INSERT INTO moderation_actions
                           (action_type, user_id, admin_id, chat_id, duration_seconds,
                            reason, timestamp, expires_at, active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ''', (
                               action.action_type,
                               action.user_id,
                               action.admin_id,
                               action.chat_id,
                               action.duration.total_seconds() if action.duration else None,
                               action.reason,
                               action.timestamp.isoformat(),
                               action.expires_at.isoformat() if action.expires_at else None,
                               1 if active else 0
                           ))

            logging.debug("Added action: %s", action)
            return cursor.lastrowid

    def get_user_warnings(self, user_id: int, chat_id: int) -> List[dict]:
        """Get active warnings for user"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           SELECT *
                           FROM warnings
                           WHERE user_id = ?
                             AND chat_id = ?
                             AND active = TRUE
                           ORDER BY timestamp DESC
                           ''', (user_id, chat_id))
            logging.debug("Fetched warnings for user_id=%d in chat_id=%d", user_id, chat_id)

            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def add_award(self, chat_id: int, user_id: int, admin_id: int, text: str) -> int:
        """Store a new award entry and return its identifier."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO awards (chat_id, user_id, admin_id, text, timestamp)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (chat_id, user_id, admin_id, text, datetime.now().isoformat()),
            )

            logging.debug(
                "Added award for user_id=%s in chat_id=%s by admin_id=%s: %s",
                user_id,
                chat_id,
                admin_id,
                text,
            )
            return cursor.lastrowid

    def get_award(self, award_id: int) -> Optional[dict]:
        """Fetch a single award by id."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, chat_id, user_id, admin_id, text, timestamp
                FROM awards
                WHERE id = ?
                ''',
                (award_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        columns = ["id", "chat_id", "user_id", "admin_id", "text", "timestamp"]
        return dict(zip(columns, row))

    def list_awards(self, chat_id: int, user_id: int) -> List[dict]:
        """List awards for a specific user within a chat."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, admin_id, text, timestamp
                FROM awards
                WHERE chat_id = ? AND user_id = ?
                ORDER BY timestamp DESC, id DESC
                ''',
                (chat_id, user_id),
            )
            columns = ["id", "admin_id", "text", "timestamp"]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def delete_award(self, award_id: int) -> bool:
        """Delete an award by id."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                DELETE FROM awards
                WHERE id = ?
                ''',
                (award_id,),
            )
            deleted = cursor.rowcount > 0

        logging.debug("Deleted award_id=%s success=%s", award_id, deleted)
        return deleted

    def add_report(
        self,
        *,
        chat_id: int,
        chat_title: Optional[str],
        chat_username: Optional[str],
        message_id: int,
        reporter_id: int,
        target_user_id: Optional[int],
        target_user_name: Optional[str],
        message_text: Optional[str],
        has_photo: bool,
        has_video: bool,
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO reports (
                    chat_id, chat_title, chat_username, message_id, reporter_id,
                    target_user_id, target_user_name, message_text, has_photo,
                    has_video, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    chat_id,
                    chat_title,
                    chat_username,
                    message_id,
                    reporter_id,
                    target_user_id,
                    target_user_name,
                    message_text,
                    1 if has_photo else 0,
                    1 if has_video else 0,
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    def list_reports(
        self,
        chat_ids: Optional[Sequence[int]] = None,
        *,
        status: str = "open",
    ) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            params: List[object] = [status]
            query = '''
                SELECT id, chat_id, chat_title, chat_username, message_id, reporter_id,
                       target_user_id, target_user_name, message_text, has_photo,
                       has_video, created_at, status, closed_by_user_id,
                       closed_by_user_name
                FROM reports
                WHERE status = ?
            '''
            if chat_ids:
                placeholders = ",".join("?" for _ in chat_ids)
                query += f" AND chat_id IN ({placeholders})"
                params.extend(chat_ids)
            query += " ORDER BY datetime(created_at) DESC, id DESC"
            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

        results: List[dict] = []
        for row in rows:
            entry = dict(zip(columns, row))
            entry["has_photo"] = bool(entry.get("has_photo"))
            entry["has_video"] = bool(entry.get("has_video"))
            entry["created_at"] = _safe_fromisoformat(entry.get("created_at"))
            results.append(entry)
        return results

    def get_report(self, report_id: int) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, chat_id, chat_title, chat_username, message_id, reporter_id,
                       target_user_id, target_user_name, message_text, has_photo,
                       has_video, created_at, status, closed_by_user_id,
                       closed_by_user_name
                FROM reports
                WHERE id = ?
                ''',
                (report_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        columns = [
            "id",
            "chat_id",
            "chat_title",
            "chat_username",
            "message_id",
            "reporter_id",
            "target_user_id",
            "target_user_name",
            "message_text",
            "has_photo",
            "has_video",
            "created_at",
            "status",
            "closed_by_user_id",
            "closed_by_user_name",
        ]
        entry = dict(zip(columns, row))
        entry["has_photo"] = bool(entry.get("has_photo"))
        entry["has_video"] = bool(entry.get("has_video"))
        entry["created_at"] = _safe_fromisoformat(entry.get("created_at"))
        return entry

    def update_report_status(
        self,
        report_id: int,
        status: str,
        *,
        closed_by: Optional[int] = None,
        closed_by_name: Optional[str] = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if closed_by is None:
                cursor.execute(
                    "UPDATE reports SET status = ? WHERE id = ?",
                    (status, report_id),
                )
            else:
                try:
                    cursor.execute(
                        "UPDATE reports SET status = ?, closed_by_user_id = ?, closed_by_user_name = ? WHERE id = ?",
                        (status, closed_by, closed_by_name, report_id),
                    )
                except sqlite3.OperationalError:
                    logging.warning(
                        "Closed-by columns missing when updating report %s; falling back to status only",
                        report_id,
                    )
                    cursor.execute(
                        "UPDATE reports SET status = ? WHERE id = ?",
                        (status, report_id),
                    )
            conn.commit()

    def update_appeal_status(self, appeal_id: int, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE appeals SET status = ? WHERE id = ?",
                (status, appeal_id),
            )

    def add_appeal(self, user_id: int, description: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO appeals (user_id, description, created_at)
                VALUES (?, ?, ?)
                ''',
                (user_id, description, datetime.now().isoformat()),
            )
            return cursor.lastrowid

    def list_appeals(self, *, status: str = "open") -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, user_id, description, created_at, status
                FROM appeals
                WHERE status = ?
                ORDER BY datetime(created_at) DESC, id DESC
                ''',
                (status,),
            )
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

        results: List[dict] = []
        for row in rows:
            entry = dict(zip(columns, row))
            entry["created_at"] = _safe_fromisoformat(entry.get("created_at"))
            results.append(entry)
        return results

    def get_appeal(self, appeal_id: int) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, user_id, description, created_at, status
                FROM appeals
                WHERE id = ?
                ''',
                (appeal_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        entry = dict(
            zip(["id", "user_id", "description", "created_at", "status"], row)
        )
        entry["created_at"] = _safe_fromisoformat(entry.get("created_at"))
        return entry

    def deactivate_actions_for_user(
        self, chat_id: int, user_id: int, action_type: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                UPDATE moderation_actions
                SET active = FALSE
                WHERE chat_id = ? AND user_id = ? AND action_type = ? AND active = TRUE
                ''',
                (chat_id, user_id, action_type),
            )

    def deactivate_actions_by_ids(self, action_ids: Sequence[int]) -> None:
        if not action_ids:
            return
        placeholders = ",".join("?" for _ in action_ids)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE moderation_actions SET active = FALSE WHERE id IN ({placeholders})",
                tuple(action_ids),
            )

    def clean_actions_for_chat(self, chat_id: int, action_type: str) -> int:
        """Deactivate all actions of a specific type for a chat."""

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE moderation_actions
                SET active = FALSE
                WHERE chat_id = ? AND action_type = ? AND active = TRUE
                ''',
                (chat_id, action_type),
            )
            affected = cursor.rowcount or 0

        return int(affected)

    def list_active_actions(self, chat_id: int, action_type: str) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, user_id, admin_id, reason, duration_seconds, timestamp, expires_at
                FROM moderation_actions
                WHERE chat_id = ? AND action_type = ? AND active = TRUE
                ORDER BY datetime(timestamp) DESC, id DESC
                ''',
                (chat_id, action_type),
            )
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

        active_entries: List[dict] = []
        expired_ids: List[int] = []
        now = datetime.now()
        for row in rows:
            entry = dict(zip(columns, row))
            expires = _safe_fromisoformat(entry.get("expires_at"))
            if expires and expires <= now:
                expired_ids.append(entry["id"])
                continue
            entry["timestamp"] = _safe_fromisoformat(entry.get("timestamp"))
            entry["expires_at"] = expires
            active_entries.append(entry)

        if expired_ids:
            self.deactivate_actions_by_ids(expired_ids)

        return active_entries

    def get_actions_page(
        self,
        chat_ids: Sequence[int],
        *,
        limit: int,
        offset: int,
    ) -> Tuple[List[dict], bool]:
        if not chat_ids:
            return [], False

        placeholders = ",".join("?" for _ in chat_ids)
        params: List[object] = list(chat_ids)
        params.extend([limit + 1, offset])

        query = f'''
            SELECT id, action_type, user_id, admin_id, chat_id, duration_seconds,
                   reason, timestamp, expires_at
            FROM moderation_actions
            WHERE chat_id IN ({placeholders})
            ORDER BY datetime(timestamp) DESC, id DESC
            LIMIT ? OFFSET ?
        '''

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

        has_next = len(rows) > limit
        trimmed_rows = rows[:limit]

        actions: List[dict] = []
        for row in trimmed_rows:
            entry = dict(zip(columns, row))
            entry["timestamp"] = _safe_fromisoformat(entry.get("timestamp"))
            entry["expires_at"] = _safe_fromisoformat(entry.get("expires_at"))
            actions.append(entry)

        return actions, has_next

    def clean_warnings_for_chat(self, chat_id: int) -> int:
        """Deactivate all warnings for a chat."""

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE warnings
                SET active = FALSE
                WHERE chat_id = ? AND active = TRUE
                ''',
                (chat_id,),
            )
            affected = cursor.rowcount or 0

        return int(affected)

    def list_known_chat_ids(self) -> List[int]:
        """Return distinct chat identifiers referenced in moderation actions."""

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT chat_id FROM moderation_actions WHERE chat_id IS NOT NULL"
            )
            rows = cursor.fetchall()

        return [int(chat_id) for (chat_id,) in rows if chat_id is not None]

    def list_report_chat_ids(self) -> List[int]:
        """Return distinct chat identifiers referenced in reports."""

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT chat_id FROM reports WHERE chat_id IS NOT NULL"
            )
            rows = cursor.fetchall()

        return [int(chat_id) for (chat_id,) in rows if chat_id is not None]

    def get_report_history_page(
        self,
        chat_ids: Optional[Sequence[int]],
        *,
        limit: int,
        offset: int,
    ) -> tuple[List[dict], bool]:
        """Fetch a page of report history entries."""

        params: List[object] = []
        where_clause = ""
        if chat_ids:
            placeholders = ",".join("?" for _ in chat_ids)
            where_clause = f"WHERE chat_id IN ({placeholders})"
            params.extend(chat_ids)

        query = f'''
            SELECT id, chat_id, chat_title, chat_username, message_id, reporter_id,
                   target_user_id, target_user_name, message_text, has_photo,
                   has_video, created_at, status, closed_by_user_id,
                   closed_by_user_name
            FROM reports
            {where_clause}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
        '''

        params.extend([limit + 1, offset])

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

        has_more = len(rows) > limit
        trimmed = rows[:limit]

        entries: List[dict] = []
        for row in trimmed:
            entry = dict(zip(columns, row))
            entry["has_photo"] = bool(entry.get("has_photo"))
            entry["has_video"] = bool(entry.get("has_video"))
            entry["created_at"] = _safe_fromisoformat(entry.get("created_at"))
            entries.append(entry)

        return entries, has_more
