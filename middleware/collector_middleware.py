import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from modules.collector.storage import UserStorage
from modules.collector.utils import UserCollector


class CollectorMiddleware(BaseMiddleware):
    def __init__(self, storage: UserStorage):
        super().__init__()
        self.storage = storage
        UserCollector.storage = storage
        logging.debug("CollectorMiddleware initialised with storage=%s", type(storage).__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        logging.debug("CollectorMiddleware intercepted event=%s", type(event).__name__)

        # Логика: если это сообщение от юзера → сохранить
        if isinstance(event, Message):
            chat_id = getattr(event.chat, "id", None)
            if event.from_user:
                logging.debug(
                    "Recording collector data for message_id=%s chat_id=%s user_id=%s",
                    getattr(event, "message_id", None),
                    chat_id,
                    event.from_user.id,
                )
                UserCollector.record_activity(
                    chat_id=chat_id,
                    user_id=event.from_user.id,
                    username=event.from_user.username,
                    display_name=event.from_user.full_name,
                    occurred_at=getattr(event, "date", None),
                )
            else:
                logging.debug(
                    "Message %s has no from_user to record",
                    getattr(event, "message_id", None),
                )

        # Передаём управление дальше (команды и хэндлеры будут работать)
        result = await handler(event, data)
        logging.debug("CollectorMiddleware finished processing event=%s", type(event).__name__)
        return result

