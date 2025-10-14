"""Persistent storage for chat-specific settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import Dict, Optional

from utils.path_utils import get_home_dir


class ChatLanguageStorage:
    """Store chat-specific language preferences."""

    def __init__(self, filename: str = "chat_settings.json") -> None:
        self._lock = RLock()
        base_dir = Path(get_home_dir())
        self._path = base_dir / filename
        self._languages: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logging.debug("Chat language storage file %s does not exist", self._path)
            self._languages = {}
            return

        try:
            raw_data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logging.warning(
                "Failed to load chat language storage from %s. Resetting file.",
                self._path,
            )
            self._languages = {}
            self._save()
            return

        if isinstance(raw_data, dict):
            languages = raw_data.get("languages", raw_data)
            if isinstance(languages, dict):
                self._languages = {
                    str(chat_id): str(language)
                    for chat_id, language in languages.items()
                    if isinstance(chat_id, (str, int)) and isinstance(language, str)
                }
                return

        logging.warning(
            "Unexpected structure in chat language storage. Resetting file %s",
            self._path,
        )
        self._languages = {}
        self._save()

    def _save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"languages": self._languages}
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get_language(self, chat_id: int) -> Optional[str]:
        with self._lock:
            return self._languages.get(str(chat_id))

    def set_language(self, chat_id: int, language: str) -> None:
        with self._lock:
            self._languages[str(chat_id)] = language
            self._save()

    def clear_language(self, chat_id: int) -> bool:
        key = str(chat_id)
        with self._lock:
            if key in self._languages:
                del self._languages[key]
                self._save()
                return True
        return False


chat_language_storage = ChatLanguageStorage()
