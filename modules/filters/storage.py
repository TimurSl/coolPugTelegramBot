"""Persistence layer for filter templates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from utils.path_utils import get_home_dir


MATCH_TYPE_CONTAINS = "contains"
MATCH_TYPE_REGEX = "regex"


@dataclass
class FilterTemplate:
    template_id: int
    text: Optional[str]
    entities: Optional[str]
    media_type: Optional[str]
    file_id: Optional[str]
    pattern: str
    match_type: str
    delete_original: bool = False

    @property
    def has_media(self) -> bool:
        return self.media_type is not None and self.file_id is not None

    def parsed_entities(self):
        if not self.entities:
            return None
        return json.loads(self.entities)


class FilterStorage:
    def __init__(self, db_name: str = "filters.db"):
        base_path = Path(get_home_dir())
        base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = base_path / db_name
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS filter_templates (
                    chat_id INTEGER NOT NULL,
                    trigger TEXT NOT NULL,
                    template_id INTEGER NOT NULL,
                    text TEXT,
                    entities TEXT,
                    media_type TEXT,
                    file_id TEXT,
                    pattern TEXT,
                    match_type TEXT NOT NULL DEFAULT 'contains',
                    delete_original INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (chat_id, trigger, template_id)
                )
                """
            )

            columns = {
                column_info[1]
                for column_info in conn.execute("PRAGMA table_info(filter_templates)")
            }
            if "pattern" not in columns:
                conn.execute("ALTER TABLE filter_templates ADD COLUMN pattern TEXT")
                conn.execute("UPDATE filter_templates SET pattern = trigger")
            if "match_type" not in columns:
                conn.execute(
                    "ALTER TABLE filter_templates ADD COLUMN match_type TEXT NOT NULL DEFAULT 'contains'"
                )
            if "delete_original" not in columns:
                conn.execute(
                    "ALTER TABLE filter_templates ADD COLUMN delete_original INTEGER NOT NULL DEFAULT 0"
                )

    def _normalise_trigger(self, trigger: str, match_type: str) -> str:
        value = trigger.strip()
        if match_type == MATCH_TYPE_REGEX:
            return f"regex::{value}"
        return value.lower()

    def _present_pattern(
        self, pattern: Optional[str], trigger_value: str, match_type: str
    ) -> str:
        if pattern and pattern.strip():
            return pattern.strip()
        cleaned = trigger_value.strip()
        if match_type == MATCH_TYPE_REGEX and cleaned.startswith("regex::"):
            cleaned = cleaned[len("regex::") :]
        return cleaned

    def add_template(
        self,
        chat_id: int,
        trigger: str,
        *,
        text: Optional[str],
        entities,
        media_type: Optional[str],
        file_id: Optional[str],
        match_type: str = MATCH_TYPE_CONTAINS,
        delete_original: bool = False,
    ) -> int:
        trigger_key = self._normalise_trigger(trigger, match_type)
        pattern = trigger.strip()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COALESCE(MAX(template_id), 0) FROM filter_templates WHERE chat_id=? AND trigger=? AND match_type=?",
                (chat_id, trigger_key, match_type),
            )
            next_id = (cursor.fetchone() or (0,))[0] + 1
            conn.execute(
                """
                INSERT INTO filter_templates (
                    chat_id,
                    trigger,
                    template_id,
                    text,
                    entities,
                    media_type,
                    file_id,
                    pattern,
                    match_type,
                    delete_original
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    trigger_key,
                    next_id,
                    text,
                    json.dumps(entities) if entities is not None else None,
                    media_type,
                    file_id,
                    pattern,
                    match_type,
                    1 if delete_original else 0,
                ),
            )
        return next_id

    def replace_template(
        self,
        chat_id: int,
        trigger: str,
        template_id: int,
        *,
        text: Optional[str],
        entities,
        media_type: Optional[str],
        file_id: Optional[str],
        match_type: str = MATCH_TYPE_CONTAINS,
        delete_original: bool = False,
    ) -> bool:
        trigger_key = self._normalise_trigger(trigger, match_type)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE filter_templates
                SET text=?, entities=?, media_type=?, file_id=?, delete_original=?
                WHERE chat_id=? AND trigger=? AND match_type=? AND template_id=?
                """,
                (
                    text,
                    json.dumps(entities) if entities is not None else None,
                    media_type,
                    file_id,
                    1 if delete_original else 0,
                    chat_id,
                    trigger_key,
                    match_type,
                    template_id,
                ),
            )
            return cursor.rowcount > 0

    def remove_template(
        self,
        chat_id: int,
        trigger: str,
        template_id: int,
        match_type: str = MATCH_TYPE_CONTAINS,
    ) -> bool:
        trigger_key = self._normalise_trigger(trigger, match_type)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM filter_templates WHERE chat_id=? AND trigger=? AND match_type=? AND template_id=?",
                (chat_id, trigger_key, match_type, template_id),
            )
            if cursor.rowcount == 0:
                return False

            rows = conn.execute(
                "SELECT rowid FROM filter_templates WHERE chat_id=? AND trigger=? AND match_type=? ORDER BY template_id",
                (chat_id, trigger_key, match_type),
            ).fetchall()
            for index, (rowid,) in enumerate(rows, start=1):
                conn.execute(
                    "UPDATE filter_templates SET template_id=? WHERE rowid=?",
                    (index, rowid),
                )
            return True

    def clear_trigger(
        self, chat_id: int, trigger: str, match_type: str = MATCH_TYPE_CONTAINS
    ) -> bool:
        trigger_key = self._normalise_trigger(trigger, match_type)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM filter_templates WHERE chat_id=? AND trigger=? AND match_type=?",
                (chat_id, trigger_key, match_type),
            )
            return cursor.rowcount > 0

    def list_templates(
        self, chat_id: int, trigger: str, match_type: str = MATCH_TYPE_CONTAINS
    ) -> List[FilterTemplate]:
        trigger_key = self._normalise_trigger(trigger, match_type)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT template_id, text, entities, media_type, file_id, pattern, match_type, trigger, delete_original
                FROM filter_templates
                WHERE chat_id=? AND trigger=? AND match_type=?
                ORDER BY template_id
                """,
                (chat_id, trigger_key, match_type),
            ).fetchall()

        templates = []
        for row in rows:
            (
                template_id,
                text,
                entities,
                media_type,
                file_id,
                pattern,
                match_type_value,
                trigger_value,
                delete_original,
            ) = row
            templates.append(
                FilterTemplate(
                    template_id=template_id,
                    text=text,
                    entities=entities,
                    media_type=media_type,
                    file_id=file_id,
                    pattern=self._present_pattern(
                        pattern, trigger_value, match_type_value or match_type
                    ),
                    match_type=(match_type_value or MATCH_TYPE_CONTAINS),
                    delete_original=bool(delete_original),
                )
            )
        return templates

    def get_random_template(
        self, chat_id: int, trigger: str, match_type: str = MATCH_TYPE_CONTAINS
    ) -> Optional[FilterTemplate]:
        trigger_key = self._normalise_trigger(trigger, match_type)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT template_id, text, entities, media_type, file_id, pattern, match_type, trigger, delete_original
                FROM filter_templates
                WHERE chat_id=? AND trigger=? AND match_type=?
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (chat_id, trigger_key, match_type),
            ).fetchone()
        if not row:
            return None
        return FilterTemplate(
            template_id=row[0],
            text=row[1],
            entities=row[2],
            media_type=row[3],
            file_id=row[4],
            pattern=self._present_pattern(row[5], row[7], row[6] or match_type),
            match_type=(row[6] or MATCH_TYPE_CONTAINS),
            delete_original=bool(row[8]),
        )

    def has_templates(
        self, chat_id: int, trigger: str, match_type: str = MATCH_TYPE_CONTAINS
    ) -> bool:
        trigger_key = self._normalise_trigger(trigger, match_type)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM filter_templates WHERE chat_id=? AND trigger=? AND match_type=? LIMIT 1",
                (chat_id, trigger_key, match_type),
            ).fetchone()
            return row is not None

    def list_filter_definitions(self, chat_id: int) -> List[tuple[str, str, str]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT trigger, COALESCE(pattern, trigger), match_type
                FROM filter_templates
                WHERE chat_id=?
                """,
                (chat_id,),
            ).fetchall()
        return [
            (
                trigger,
                self._present_pattern(pattern, trigger, match_type),
                match_type or MATCH_TYPE_CONTAINS,
            )
            for trigger, pattern, match_type in rows
        ]

    def list_all_templates(self, chat_id: int) -> Iterable[FilterTemplate]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT template_id, text, entities, media_type, file_id, pattern, match_type, trigger, delete_original
                FROM filter_templates
                WHERE chat_id=?
                ORDER BY match_type, pattern, template_id
                """,
                (chat_id,),
            ).fetchall()
        for row in rows:
            yield FilterTemplate(
                template_id=row[0],
                text=row[1],
                entities=row[2],
                media_type=row[3],
                file_id=row[4],
                pattern=self._present_pattern(row[5], row[7], row[6] or MATCH_TYPE_CONTAINS),
                match_type=(row[6] or MATCH_TYPE_CONTAINS),
                delete_original=bool(row[8]),
            )
