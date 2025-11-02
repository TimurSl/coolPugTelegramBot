"""Application-wide middleware package."""

from .filter_middleware import FilterMessageMiddleware

__all__ = ["FilterMessageMiddleware"]
