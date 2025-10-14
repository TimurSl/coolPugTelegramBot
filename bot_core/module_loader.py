"""Dynamic module loader for CoolPugBot."""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path

from utils.path_utils import get_home_dir


DISABLED_MODULES = {"entertaiment"}


class ModuleLoader:
    """
    Implements dynamic module loading with support for
    - Legacy router.py modules exposing a global `router` and optional `priority`
    - New Module-based modules exposing `module` instance or `get_module()` factory
    """

    def __init__(self, dispatcher, container):
        self.dispatcher = dispatcher
        self.container = container
        self.loaded_modules = []  # list of dicts: {name, priority, type, instance/router}

    async def load_all_modules(self):
        """Dynamically load all modules from modules/ directory with optional priority"""
        modules_dir = Path(get_home_dir()) / "modules"
        candidates = []

        logging.debug("Scanning '%s' for router modules", modules_dir)

        for module_path in modules_dir.glob("*/router.py"):
            module_name = module_path.parent.name
            if module_name in DISABLED_MODULES:
                logging.info("Skipping disabled module '%s'", module_name)
                continue
            logging.debug("Discovered module candidate '%s' at '%s'", module_name, module_path)
            try:
                module_import_path = f"modules.{module_name}.router"
                module_spec = importlib.import_module(module_import_path)
                logging.debug("Imported module '%s'", module_import_path)

                # default priority from legacy export
                priority = getattr(module_spec, "priority", 100)

                # try resolving instance to read its priority for better sorting
                try:
                    instance = await self._resolve_module_instance(module_spec)
                except Exception as exc:
                    logging.exception(
                        "Error while resolving module instance for '%s': %s",
                        module_name,
                        exc,
                    )
                    instance = None
                if instance is not None:
                    priority = getattr(instance, "priority", priority)
                    logging.debug(
                        "Resolved module instance for '%s' with priority %s",
                        module_name,
                        priority,
                    )

                # store instance to avoid double instantiation later
                candidates.append((priority, module_name, module_spec, instance))
            except ImportError as e:
                logging.exception("Failed to pre-import module '%s': %s", module_name, e)

        # sort by priority (lower number = higher priority)
        candidates.sort(key=lambda x: x[0])
        logging.debug("Module load order: %s", [name for _, name, _, _ in candidates])

        # load in priority order
        for priority, module_name, module_spec, instance in candidates:
            await self._include_module(module_name, module_spec, priority, instance)

    async def _resolve_module_instance(self, module_spec):
        """
        Try to resolve a Module instance from the given module_spec.
        Supports:
        - exported variable `module`
        - factory function `get_module(container)` (sync or async)
        - class `Module` (from our base) with optional container arg
        Returns the instance or None if not applicable.
        """
        # direct instance
        if hasattr(module_spec, "module"):
            logging.debug("Module '%s' exposes direct instance", module_spec.__name__)
            return getattr(module_spec, "module")

        # factory function
        get_module_fn = getattr(module_spec, "get_module", None)
        if callable(get_module_fn):
            try:
                if inspect.iscoroutinefunction(get_module_fn):
                    try:
                        return await get_module_fn(self.container)
                    except TypeError:
                        logging.debug(
                            "Factory for '%s' does not accept container, retrying without it",
                            module_spec.__name__,
                        )
                        return await get_module_fn()
                else:
                    try:
                        return get_module_fn(self.container)
                    except TypeError:
                        logging.debug(
                            "Factory for '%s' does not accept container, retrying without it",
                            module_spec.__name__,
                        )
                        return get_module_fn()
            except Exception as e:
                logging.exception(
                    "Error calling get_module() factory for '%s': %s",
                    module_spec.__name__,
                    e,
                )

        # class named Module
        ModuleClass = getattr(module_spec, "Module", None)
        if inspect.isclass(ModuleClass):
            try:
                try:
                    return ModuleClass(self.container)
                except TypeError:
                    logging.debug(
                        "Class '%s.Module' does not accept container, instantiating without it",
                        module_spec.__name__,
                    )
                    return ModuleClass()
            except Exception as e:
                logging.exception(
                    "Error instantiating Module class for '%s': %s",
                    module_spec.__name__,
                    e,
                )

        return None

    async def _include_module(self, module_name: str, module_spec, priority: int, instance=None):
        """Include module into dispatcher, supporting both legacy and new Module API."""
        try:
            # Try Module-based first
            module_instance = (
                instance if instance is not None else await self._resolve_module_instance(module_spec)
            )
            logging.debug(
                "Including module '%s' (priority=%s, instance=%s)",
                module_name,
                priority,
                bool(module_instance),
            )
            if module_instance is not None:
                # dependency injection hook, if provided by container
                inject = getattr(self.container, "inject_dependencies", None)
                if callable(inject):
                    try:
                        inject(module_instance)
                    except Exception as e:
                        logging.exception(
                            "Error injecting dependencies into module '%s': %s",
                            module_name,
                            e,
                        )

                # derive router and priority
                router = None
                if hasattr(module_instance, "get_router"):
                    router = module_instance.get_router()
                elif hasattr(module_instance, "router"):
                    router = module_instance.router

                mod_priority = getattr(module_instance, "priority", priority)

                # register and include
                if hasattr(module_instance, "register") and inspect.iscoroutinefunction(
                    module_instance.register
                ):
                    logging.debug("Awaiting async register() for module '%s'", module_name)
                    await module_instance.register(self.container)
                elif hasattr(module_instance, "register"):
                    try:
                        logging.debug("Calling sync register() for module '%s'", module_name)
                        module_instance.register(self.container)
                    except Exception as e:
                        logging.exception(
                            "Error in module.register() for '%s': %s",
                            module_name,
                            e,
                        )

                if router is not None:
                    self.dispatcher.include_router(router)

                # call startup hook
                if hasattr(module_instance, "on_startup") and inspect.iscoroutinefunction(
                    module_instance.on_startup
                ):
                    logging.debug("Awaiting async on_startup() for module '%s'", module_name)
                    await module_instance.on_startup(self.container)
                elif hasattr(module_instance, "on_startup"):
                    try:
                        logging.debug("Calling sync on_startup() for module '%s'", module_name)
                        module_instance.on_startup(self.container)
                    except Exception as e:
                        logging.exception(
                            "Error in module.on_startup() for '%s': %s",
                            module_name,
                            e,
                        )

                self.loaded_modules.append(
                    {
                        "name": module_name,
                        "priority": mod_priority,
                        "type": "module",
                        "instance": module_instance,
                    }
                )
                logging.info(
                    "Module '%s' loaded successfully (priority=%s)",
                    module_name,
                    mod_priority,
                )
                return

            # Legacy router-based
            if hasattr(module_spec, "router"):
                self.dispatcher.include_router(module_spec.router)
                self.loaded_modules.append(
                    {
                        "name": module_name,
                        "priority": priority,
                        "type": "legacy",
                        "router": module_spec.router,
                    }
                )
                logging.info(
                    "Legacy module '%s' loaded successfully (priority=%s)",
                    module_name,
                    priority,
                )
            else:
                logging.warning("Module '%s' has no router or module instance", module_name)
        except Exception as e:
            logging.exception("Failed to include module '%s': %s", module_name, e)

    async def shutdown(self):
        """Call shutdown hook for all loaded Module-based modules."""
        for item in self.loaded_modules:
            if item.get("type") == "module":
                instance = item.get("instance")
                if instance is None:
                    continue
                try:
                    on_shutdown = getattr(instance, "on_shutdown", None)
                    if callable(on_shutdown):
                        if inspect.iscoroutinefunction(on_shutdown):
                            logging.debug(
                                "Awaiting async on_shutdown() for module '%s'",
                                item.get("name"),
                            )
                            await on_shutdown()
                        else:
                            logging.debug(
                                "Calling sync on_shutdown() for module '%s'",
                                item.get("name"),
                            )
                            on_shutdown()
                except Exception as e:
                    name = item.get("name", "<unknown>")
                    logging.exception(
                        "Error during shutdown of module '%s': %s",
                        name,
                        e,
                    )

