"""Core bot orchestration logic."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot_core.dependency_injector import DependencyContainer
from bot_core.module_loader import ModuleLoader
from middleware.cleaner_middleware import AutoDeleteCommandMiddleware
from middleware.command_restriction_middleware import CommandRestrictionMiddleware
from middleware.collector_middleware import CollectorMiddleware
from middleware.logging_middleware import setup_middlewares as setup_logging_middleware
from middleware.roleplay_middleware import RoleplayMiddleware
from modules.autodelete.storage import AutoDeleteStorage
from modules.collector.storage import UserStorage


class ModularBot:
    """Main bot orchestrator that wires middleware, storage and modules together."""

    def __init__(self, bot_token: str) -> None:
        logging.debug("Initialising ModularBot components")

        # Bot setup
        self.bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()
        self.container = DependencyContainer()
        self.module_loader = ModuleLoader(self.dp, self.container)
        self.router = Router()

        self.command_restriction = CommandRestrictionMiddleware()
        logging.debug("Registering CommandRestrictionMiddleware")
        self.dp.message.middleware(self.command_restriction)

        self.auto_delete_storage = AutoDeleteStorage()
        self.auto_delete = AutoDeleteCommandMiddleware(
            delay_seconds=2,
            storage=self.auto_delete_storage,
            exclude=["/autodelete", "/autodeletelist"],
        )
        logging.debug(
            "Registering AutoDeleteCommandMiddleware with storage=%s exclude=%s",
            type(self.auto_delete_storage).__name__,
            self.auto_delete.exclude,
        )
        self.dp.message.middleware(self.auto_delete)

        self.collector_storage = UserStorage()
        logging.debug("Registering CollectorMiddleware")
        self.dp.message.middleware(CollectorMiddleware(self.collector_storage))

        logging.debug("Registering RoleplayMiddleware")
        self.dp.message.middleware(RoleplayMiddleware())
        setup_logging_middleware(self.dp, self.container)

    async def start(self) -> None:
        """Start the bot with all modules loaded."""

        logging.info("Starting modular bot...")
        logging.debug("Beginning module loading sequence")

        await self.module_loader.load_all_modules()

        logging.info("Bot started successfully, entering polling loop")
        await self.dp.start_polling(self.bot)

