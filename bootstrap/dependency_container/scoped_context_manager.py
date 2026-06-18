#!/usr/bin/env python3
"""
Module: scoped_context_manager.py
Layer: Bootstrap (Dependency Container)
Responsibility: Manajer untuk scoped context (per request).
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import asynccontextmanager
from typing import TypeVar

from bootstrap.dependency_container.ioc_container import IoCContainer, get_container
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

T = TypeVar("T")

_current_scope: contextvars.ContextVar[ScopedContext | None] = contextvars.ContextVar(
    "current_scope", default=None
)


class ScopedContext:
    """
    Scoped context untuk dependency injection per request.

    Method Standards:
    - resolve() - Resolusi dependency dalam scope
    - current() - Mendapatkan scope saat ini
    - close() - Menutup scope
    - is_closed() - Cek status
    """

    def __init__(self, parent: IoCContainer | None = None):
        self._container = (parent or get_container()).create_scope()
        self._parent_scope = _current_scope.get()
        self._token: contextvars.Token | None = None
        self._closed = False
        self._logger = logging.getLogger(f"{__name__}.ScopedContext")

    @property
    def container(self) -> IoCContainer:
        """Get scoped container."""
        return self._container

    async def resolve(self, interface: type[T], **kwargs) -> T:
        """Resolve dependency from scoped container."""
        if self._closed:
            raise RuntimeError("Scoped context is closed")
        return await self._container.resolve_async(interface, **kwargs)

    def __enter__(self):
        """Enter context (sync)."""
        self._token = _current_scope.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context (sync)."""
        self._close()

    async def __aenter__(self):
        """Enter context (async)."""
        self._token = _current_scope.set(self)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context (async)."""
        self._close()

    def _close(self) -> None:
        """Close the scoped context."""
        if self._closed:
            return
        self._container.clear_scoped()
        if self._token:
            _current_scope.reset(self._token)
        self._closed = True
        self._logger.debug("Scoped context closed")

    def close(self) -> None:
        """Public close method."""
        self._close()

    def is_closed(self) -> bool:
        """Check if context is closed."""
        return self._closed

    @classmethod
    def current(cls) -> ScopedContext | None:
        """Get current scoped context."""
        return _current_scope.get()


@asynccontextmanager
async def scoped_context():
    """Async context manager for scoped dependency injection."""
    scope = ScopedContext()
    async with scope:
        yield scope


def current_scope() -> ScopedContext | None:
    """Get current scoped context (for FastAPI dependency)."""
    return ScopedContext.current()


class ScopedContextMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware untuk scoped context per request."""

    async def dispatch(self, request: Request, call_next):
        async with scoped_context():
            response = await call_next(request)
            return response


def scoped(func):
    """Decorator to run a function within a scoped context."""

    async def wrapper(*args, **kwargs):
        async with scoped_context():
            return await func(*args, **kwargs)

    return wrapper


__all__ = [
    "ScopedContext",
    "ScopedContextMiddleware",
    "current_scope",
    "scoped",
    "scoped_context",
]