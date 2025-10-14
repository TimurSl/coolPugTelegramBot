import asyncio
import logging
from typing import Callable, Dict, Awaitable, Any, List, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message

from modules.autodelete.storage import AutoDeleteStorage


class AutoDeleteCommandMiddleware(BaseMiddleware):
    """
    Middleware that automatically deletes command messages after specified delay.
    Demonstrates async task scheduling and message management.
    """

    def __init__(
        self,
        delay_seconds: int = 2,
        delete_commands_only: bool = True,
        storage: Optional[AutoDeleteStorage] = None,
        exclude: Optional[List[str]] = None,
    ):
        self.delay_seconds = delay_seconds
        self.delete_commands_only = delete_commands_only
        self.deletion_tasks = []  # Track active deletion tasks
        self.storage = storage
        self.exclude = [self._normalise_command(cmd) for cmd in (exclude or [])]
        logging.debug(
            "AutoDeleteCommandMiddleware configured: delay=%s delete_commands_only=%s exclude=%s",
            self.delay_seconds,
            self.delete_commands_only,
            self.exclude,
        )

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:

        # Execute handler first
        logging.debug(
            "AutoDelete middleware received event=%s handler=%s", type(event).__name__, getattr(handler, "__name__", handler)
        )
        result = await handler(event, data)

        # Check if we should delete this message
        if isinstance(event, Message) and self._should_delete_message(event):
            # Schedule deletion after delay
            logging.debug(
                "Scheduling auto deletion for message_id=%s delay=%s", event.message_id, self.delay_seconds
            )
            task = asyncio.create_task(
                self._delete_after_delay(event, self.delay_seconds)
            )
            self.deletion_tasks.append(task)
            # cleanup finished tasks to avoid memory leak
            self.deletion_tasks = [t for t in self.deletion_tasks if not t.done()]

        return result

    def _should_delete_message(self, message: Message) -> bool:
        if not message.text:
            logging.debug("Message %s has no text; skipping auto delete", message.message_id)
            return False

        command = self._extract_command(message.text)
        if not command:
            logging.debug("Message %s has no recognised command; skipping auto delete", message.message_id)
            return False

        if any(self._matches_command(message.text, cmd) for cmd in self.exclude):
            logging.debug("Message %s matches exclude list; skipping auto delete", message.message_id)
            return False

        if self.storage:
            should_delete = self.storage.is_enabled(message.chat.id, command)
            logging.debug(
                "Auto delete check for chat=%s command=%s -> %s",
                message.chat.id,
                command,
                should_delete,
            )
            return should_delete

        should_delete = True
        logging.debug("Message %s auto delete default decision: %s", message.message_id, should_delete)
        return should_delete

    @staticmethod
    def _matches_command(text: str, command: str) -> bool:
        if not text.startswith(command):
            return False
        remainder = text[len(command):]
        return remainder == "" or remainder.startswith(" ") or remainder.startswith("@")

    @staticmethod
    def _normalise_command(command: str) -> str:
        command = command.strip()
        if not command.startswith("/"):
            return command
        if "@" in command:
            command = command.split("@", 1)[0]
        return command.lower()

    def _extract_command(self, text: str) -> Optional[str]:
        if not text.startswith("/"):
            return None
        first_part = text.split(maxsplit=1)[0]
        command = first_part.split("@", 1)[0]
        if self.delete_commands_only:
            return command.lower()
        return command.lower()

    async def _delete_after_delay(self, message: Message, delay: int):
        """Delete message after specified delay"""
        try:
            await asyncio.sleep(delay)
            await message.delete()
            logging.info("Auto-deleted message: %s", message.message_id)
        except Exception as e:
            # Handle deletion errors (message might be already deleted)
            logging.warning("Failed to delete message %s: %s", message.message_id, e)
