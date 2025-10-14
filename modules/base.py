import logging
from abc import ABC
from typing import Optional

from aiogram import Router


class Module(ABC):
    """
    Base class for bot modules.
    Designed to be optional and non-intrusive for legacy modules.

    Implementers may override lifecycle hooks and use the provided Router.
    """

    def __init__(self, name: str, priority: int = 100):
        self.name: str = name
        self.priority: int = priority
        self.router: Router = Router(name=name)
        self.enabled: bool = True
        logging.debug("Initialised module base '%s' with priority %s", name, priority)

    def get_router(self) -> Optional[Router]:
        """Return module's router (can be None if not used)."""
        logging.debug("Module '%s' returning router instance", self.name)
        return self.router

    async def register(self, container):
        """
        Register handlers, middlewares, or resolve dependencies using the container.
        Override in subclasses as needed.
        """
        logging.debug("Module '%s' register() not overridden; skipping", self.name)
        return None

    async def on_startup(self, container):
        """Called after the router is included into Dispatcher."""
        logging.debug("Module '%s' on_startup() not overridden; skipping", self.name)
        return None

    async def on_shutdown(self):
        """Called on application shutdown if needed."""
        logging.debug("Module '%s' on_shutdown() not overridden; skipping", self.name)
        return None

    def enable(self):
        """Enable the module"""
        logging.debug("Module '%s' enabled", self.name)
        self.enabled = True

    def disable(self):
        """Disable the module"""
        logging.debug("Module '%s' disabled", self.name)
        self.enabled = False

