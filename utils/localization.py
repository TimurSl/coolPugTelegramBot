import json
import logging
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from utils import path_utils
from utils.chat_settings import chat_language_storage


SUPPORTED_LANGUAGES = {"en", "ru", "uk"}


class LocalizationManager:
    """Simple JSON-based localization manager with automatic key creation."""

    def __init__(
        self,
        locales_dir: Optional[Path] = None,
        default_language: str = "en",
    ) -> None:
        self._lock = RLock()
        self.default_language = default_language
        base_dir = (
            locales_dir
            if locales_dir is not None
            else Path(path_utils.get_home_dir()) / "locales"
        )
        self.locales_dir = base_dir
        self.locales_dir.mkdir(parents=True, exist_ok=True)
        self._translations: Dict[str, Dict[str, str]] = {}

    def _language_path(self, language: str) -> Path:
        return self.locales_dir / f"{language}.json"

    def _ensure_language_loaded(self, language: str) -> Dict[str, str]:
        with self._lock:
            if language in self._translations:
                return self._translations[language]

            path = self._language_path(language)
            if not path.exists():
                logging.info("Locale file %s was missing. Creating empty file.", path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logging.warning(
                    "Locale file %s is corrupted. Re-creating empty structure.", path
                )
                data = {}
                path.write_text("{}", encoding="utf-8")

            if not isinstance(data, dict):
                logging.warning(
                    "Locale file %s did not contain an object. Resetting to empty.", path
                )
                data = {}
                path.write_text("{}", encoding="utf-8")

            self._translations[language] = data
            return data

    def _save_language(self, language: str) -> None:
        with self._lock:
            data = self._translations.get(language)
            if data is None:
                return
            path = self._language_path(language)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_default_language(self, language: str) -> None:
        self.default_language = language

    def get_text(
        self,
        key: str,
        language: Optional[str] = None,
        default: Optional[str] = None,
        **format_kwargs: Any,
    ) -> str:
        target_language = language or self.default_language
        translations = self._ensure_language_loaded(target_language)

        if key not in translations:
            fallback_text = self._get_fallback_text(key, default)
            translations[key] = fallback_text
            self._save_language(target_language)
        text = translations[key]

        if format_kwargs:
            try:
                text = text.format(**format_kwargs)
            except Exception:
                logging.exception("Failed to format localized string for key '%s'", key)
        return text

    def _get_fallback_text(self, key: str, default: Optional[str]) -> str:
        if default is not None:
            self._ensure_key_in_default(key, default)
            return default

        default_language_data = self._ensure_language_loaded(self.default_language)
        if key in default_language_data:
            return default_language_data[key]

        default_language_data[key] = key
        self._save_language(self.default_language)
        return key

    def _ensure_key_in_default(self, key: str, value: str) -> None:
        default_language_data = self._ensure_language_loaded(self.default_language)
        if default_language_data.get(key) != value:
            default_language_data[key] = value
            self._save_language(self.default_language)

    def ensure_key(self, key: str, value: str, language: Optional[str] = None) -> None:
        translations = self._ensure_language_loaded(language or self.default_language)
        if key not in translations:
            translations[key] = value
            self._save_language(language or self.default_language)


localization_manager = LocalizationManager()


def gettext(key: str, language: Optional[str] = None, default: Optional[str] = None, **kwargs: Any) -> str:
    return localization_manager.get_text(key, language=language, default=default, **kwargs)


def normalize_language_code(language_code: Optional[str]) -> str:
    if not language_code:
        return localization_manager.default_language

    base = language_code.split("-")[0].lower()
    if base in SUPPORTED_LANGUAGES:
        return base

    return localization_manager.default_language


def language_from_message(message: Any) -> str:
    chat = getattr(message, "chat", None)
    if chat is not None:
        chat_id = getattr(chat, "id", None)
        if chat_id is not None:
            override = chat_language_storage.get_language(chat_id)
            if override:
                return normalize_language_code(override)

    from_user = getattr(message, "from_user", None)
    if from_user is None:
        return localization_manager.default_language

    language_code = getattr(from_user, "language_code", None)
    return normalize_language_code(language_code)
