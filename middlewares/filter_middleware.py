from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from modules.filters.router import FilterService
from modules.filters.storage import MATCH_TYPE_REGEX
from utils.localization import language_from_message


class FilterMessageMiddleware(BaseMiddleware):
    """Handler middleware that applies chat filters to regular messages."""

    def __init__(self, service: Optional[FilterService] = None) -> None:
        super().__init__()
        self._service = service or FilterService()

    @property
    def service(self) -> FilterService:
        return self._service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            try:
                await self._process_message(event)
            except Exception:
                logging.exception(
                    "Failed to process filter middleware for chat_id=%s",
                    getattr(getattr(event, "chat", None), "id", None),
                )

        return await handler(event, data)

    async def _process_message(self, message: Message) -> None:
        if message.from_user and message.from_user.is_bot:
            return

        text = message.text or message.caption
        if not text:
            return

        chat = getattr(message, "chat", None)
        if not chat:
            return

        definitions = self.service.storage.list_filter_definitions(chat.id)
        if not definitions:
            return

        language = language_from_message(message)
        text_lower = text.lower()
        matches: list[tuple[str, str, str]] = []
        match_arguments: dict[tuple[str, str], str] = {}

        for trigger_key, pattern, match_type in definitions:
            if match_type == MATCH_TYPE_REGEX:
                try:
                    match_obj = re.search(pattern, text, flags=re.IGNORECASE)
                except re.error:
                    logging.exception(
                        "Invalid regex filter skipped for chat_id=%s pattern='%s'",
                        chat.id,
                        pattern,
                    )
                    continue

                if match_obj:
                    matches.append((trigger_key, pattern, match_type))
                    match_arguments.setdefault(
                        (trigger_key, match_type), text[match_obj.end() :].lstrip()
                    )
            else:
                index = text_lower.find(trigger_key)
                if index != -1:
                    matches.append((trigger_key, pattern, match_type))
                    argument_text = text[index + len(trigger_key) :].lstrip()
                    match_arguments.setdefault((trigger_key, match_type), argument_text)

        if not matches:
            return

        processed: set[tuple[str, str]] = set()
        for trigger_key, pattern, match_type in matches:
            key = (trigger_key, match_type)
            if key in processed:
                continue
            processed.add(key)

            template = self.service.storage.get_random_template(
                chat.id, pattern, match_type=match_type
            )
            if not template:
                continue

            entities = self.service.build_entities(template.parsed_entities())
            try:
                await self.service.send_template_response(
                    message,
                    template,
                    entities,
                    argument=match_arguments.get((trigger_key, match_type)),
                    language=language,
                )
            except Exception:
                logging.exception(
                    "Failed to send filter response for chat_id=%s trigger='%s' template_id=%s",
                    chat.id,
                    pattern,
                    getattr(template, "template_id", None),
                )

