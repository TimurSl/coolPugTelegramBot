import logging
from typing import Any


class DependencyContainer:
    """Simple dependency injection container."""

    def __init__(self):
        self.services = {}
        logging.debug("DependencyContainer initialised")

    def register(self, service_name: str, service_instance: Any):
        """Register a service in the container"""
        logging.debug("Registering service '%s' (%s)", service_name, type(service_instance).__name__)
        self.services[service_name] = service_instance

    def get(self, service_name: str) -> Any:
        """Get a service from the container"""
        service = self.services.get(service_name)
        logging.debug("Resolving service '%s' -> %s", service_name, type(service).__name__ if service else None)
        return service

    def inject_dependencies(self, target_object: Any):
        """Inject dependencies into target object"""
        required = getattr(target_object, "required_services", [])
        logging.debug("Injecting dependencies into %s; required=%s", type(target_object).__name__, required)
        for name in required:
            if name in self.services:
                setattr(target_object, name, self.services[name])
                logging.debug("Injected '%s' into %s", name, type(target_object).__name__)
            else:
                logging.warning(
                    "Requested dependency '%s' not registered for %s", name, type(target_object).__name__
                )

