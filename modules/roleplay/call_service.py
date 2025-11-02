"""Utilities for building chat-wide call messages."""

from __future__ import annotations

from typing import Callable, Iterable, List, Sequence


class CallCommandService:
    """Prepare batched call messages with HTML mentions."""

    def __init__(
        self,
        *,
        emojis: Sequence[str],
        batch_size: int = 5,
        random_choice: Callable[[Sequence[str]], str] | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not emojis:
            raise ValueError("emojis must not be empty")

        self._emojis: Sequence[str] = tuple(emojis)
        self._batch_size = batch_size
        self._random_choice = random_choice or _default_choice

    def build_call_messages(
        self,
        caller_label: str,
        template: str,
        user_ids: Iterable[int],
    ) -> List[str]:
        ordered_unique_ids = self._deduplicate_ids(user_ids)
        if not ordered_unique_ids:
            return []

        messages: List[str] = []
        for chunk in self._chunk_user_ids(ordered_unique_ids):
            mentions = self._format_mentions(chunk)
            if not mentions:
                continue
            message_text = template.format(
                caller=caller_label,
                mentions=" ".join(mentions),
            )
            messages.append(message_text)
        return messages

    def _deduplicate_ids(self, user_ids: Iterable[int]) -> List[int]:
        unique_ids: List[int] = []
        seen: set[int] = set()
        for user_id in user_ids:
            if not isinstance(user_id, int) or user_id in seen:
                continue
            seen.add(user_id)
            unique_ids.append(user_id)
        return unique_ids

    def _chunk_user_ids(self, user_ids: Sequence[int]) -> Iterable[Sequence[int]]:
        for index in range(0, len(user_ids), self._batch_size):
            yield user_ids[index : index + self._batch_size]

    def _format_mentions(self, chunk: Sequence[int]) -> List[str]:
        mentions: List[str] = []
        for user_id in chunk:
            emoji = self._random_choice(self._emojis)
            mentions.append(f'<a href="tg://user?id={user_id}">{emoji}</a>')
        return mentions


def _default_choice(options: Sequence[str]) -> str:
    from random import choice

    return choice(options)
