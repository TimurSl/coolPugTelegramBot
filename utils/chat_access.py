"""Chat-level access restrictions for bot features."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Dict, Set

from utils.path_utils import get_home_dir


class ChatFeature(str, Enum):
    """Features that can be toggled per chat."""

    AI_ASSISTANT = "assistant"
    EXECUTOR = "executor"


@dataclass(frozen=True)
class ChatRestriction:
    chat_id: int
    feature: ChatFeature


class ChatAccessStorage:
    """Persist chat feature restrictions on disk."""

    def __init__(self, filename: str = "chat_access.json") -> None:
        self._lock = RLock()
        base_dir = Path(get_home_dir())
        base_dir.mkdir(parents=True, exist_ok=True)
        self._path = base_dir / filename
        self._restrictions: Dict[str, Set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logging.debug("Chat access file %s not found; starting empty", self._path)
            self._restrictions = {}
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logging.warning(
                "Failed to load chat access restrictions from %s; resetting file",
                self._path,
            )
            self._restrictions = {}
            self._save()
            return

        restrictions: Dict[str, Set[str]] = {}
        if isinstance(data, dict):
            raw_restrictions = data.get("restrictions", data)
            if isinstance(raw_restrictions, dict):
                for chat_id, features in raw_restrictions.items():
                    if not isinstance(chat_id, (str, int)):
                        continue
                    if not isinstance(features, (list, tuple, set, frozenset)):
                        continue
                    valid = {
                        str(feature)
                        for feature in features
                        if isinstance(feature, (str, ChatFeature))
                        and str(feature) in {item.value for item in ChatFeature}
                    }
                    if valid:
                        restrictions[str(chat_id)] = valid
        self._restrictions = restrictions

    def _save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serialisable = {
                chat_id: sorted(features)
                for chat_id, features in self._restrictions.items()
            }
            payload = {"restrictions": serialisable}
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def is_blocked(self, chat_id: int, feature: ChatFeature) -> bool:
        with self._lock:
            features = self._restrictions.get(str(chat_id), set())
            return feature.value in features

    def block(self, chat_id: int, feature: ChatFeature) -> None:
        with self._lock:
            features = self._restrictions.setdefault(str(chat_id), set())
            if feature.value not in features:
                features.add(feature.value)
                self._save()

    def unblock(self, chat_id: int, feature: ChatFeature) -> bool:
        with self._lock:
            features = self._restrictions.get(str(chat_id))
            if not features or feature.value not in features:
                return False
            features.remove(feature.value)
            if not features:
                del self._restrictions[str(chat_id)]
            self._save()
            return True

    def blocked_features(self, chat_id: int) -> Set[ChatFeature]:
        with self._lock:
            features = self._restrictions.get(str(chat_id), set())
            return {ChatFeature(feature) for feature in features}


chat_access_storage = ChatAccessStorage()

__all__ = [
    "ChatAccessStorage",
    "ChatFeature",
    "ChatRestriction",
    "chat_access_storage",
]