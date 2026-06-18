#!/usr/bin/env python3
"""
Module: correlation_id_injector.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengelola correlation ID untuk tracing end-to-end request.
               Correlation ID disimpan dalam contextvars sehingga dapat diakses
               di seluruh stack tanpa perlu passing parameter eksplisit.
               Digunakan untuk menghubungkan log, trace, dan audit record.
Dependencies:
- contextvars, asyncio, uuid
- infrastructure.telemetry.structured_json_logging
Audit: Correlation ID digunakan untuk tracing dan debugging.
       Tidak mengandung informasi sensitif.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from uuid import uuid4

# DO NOT import get_logger at module level to avoid circular import
# Instead, create a simple logger or lazy import
logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Context variable untuk correlation ID
_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Context variable untuk user ID
_user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

# Context variable untuk legal entity ID
_legal_entity_id_ctx: ContextVar[str | None] = ContextVar("legal_entity_id", default=None)

# Context variable untuk request path
_request_path_ctx: ContextVar[str | None] = ContextVar("request_path", default=None)

# Context variable untuk method
_method_ctx: ContextVar[str | None] = ContextVar("method", default=None)


# ============================================================================
# CORRELATION ID MANAGER
# ============================================================================


class CorrelationIdInjector:
    """
    Manager untuk correlation ID.

    Fitur:
    - Set correlation ID dari context
    - Get current correlation ID
    - Generate new correlation ID
    - Clear correlation ID
    - Context manager untuk scope
    """

    @staticmethod
    def set(correlation_id: str) -> None:
        """Set correlation ID for current context."""
        _correlation_id_ctx.set(correlation_id)
        # Use simple logging to avoid circular import
        logging.getLogger(__name__).debug(f"Correlation ID set: {correlation_id}")

    @staticmethod
    def get() -> str | None:
        """Get current correlation ID."""
        return _correlation_id_ctx.get()

    @staticmethod
    def generate() -> str:
        """Generate a new correlation ID."""
        return str(uuid4())

    @staticmethod
    def get_or_generate() -> str:
        """Get current correlation ID or generate new one."""
        corr_id = _correlation_id_ctx.get()
        if corr_id is None:
            corr_id = CorrelationIdInjector.generate()
            _correlation_id_ctx.set(corr_id)
        return corr_id

    @staticmethod
    def clear() -> None:
        """Clear correlation ID for current context."""
        _correlation_id_ctx.set(None)
        logging.getLogger(__name__).debug("Correlation ID cleared")

    @staticmethod
    def reset() -> None:
        """Reset all context variables."""
        _correlation_id_ctx.set(None)
        _user_id_ctx.set(None)
        _legal_entity_id_ctx.set(None)
        _request_path_ctx.set(None)
        _method_ctx.set(None)
        logging.getLogger(__name__).debug("All context variables reset")


# ============================================================================
# USER CONTEXT
# ============================================================================


class UserContextInjector:
    """
    Manager untuk user context (user_id, legal_entity_id).
    """

    @staticmethod
    def set_user_id(user_id: str | None) -> None:
        """Set user ID for current context."""
        _user_id_ctx.set(user_id)

    @staticmethod
    def get_user_id() -> str | None:
        """Get current user ID."""
        return _user_id_ctx.get()

    @staticmethod
    def set_legal_entity_id(legal_entity_id: str | None) -> None:
        """Set legal entity ID for current context."""
        _legal_entity_id_ctx.set(legal_entity_id)

    @staticmethod
    def get_legal_entity_id() -> str | None:
        """Get current legal entity ID."""
        return _legal_entity_id_ctx.get()

    @staticmethod
    def set_request_info(path: str, method: str) -> None:
        """Set request path and method for current context."""
        _request_path_ctx.set(path)
        _method_ctx.set(method)

    @staticmethod
    def get_request_path() -> str | None:
        """Get current request path."""
        return _request_path_ctx.get()

    @staticmethod
    def get_method() -> str | None:
        """Get current request method."""
        return _method_ctx.get()


# ============================================================================
# CONTEXT MANAGER
# ============================================================================


class CorrelationIdScope:
    """
    Context manager untuk scope dengan correlation ID.

    Usage:
        with CorrelationIdScope(correlation_id="abc-123"):
            # All logs/traces in this block will have this correlation_id
            do_something()
    """

    def __init__(self, correlation_id: str | None = None):
        self._correlation_id = correlation_id or CorrelationIdInjector.generate()
        self._previous_correlation_id: str | None = None

    def __enter__(self):
        self._previous_correlation_id = CorrelationIdInjector.get()
        CorrelationIdInjector.set(self._correlation_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        CorrelationIdInjector.set(self._previous_correlation_id)

    @property
    def correlation_id(self) -> str:
        return self._correlation_id


class RequestContextScope:
    """
    Context manager untuk request context (correlation_id, user_id, legal_entity_id).
    """

    def __init__(
        self,
        correlation_id: str | None = None,
        user_id: str | None = None,
        legal_entity_id: str | None = None,
        path: str | None = None,
        method: str | None = None,
    ):
        self._correlation_id = correlation_id or CorrelationIdInjector.generate()
        self._user_id = user_id
        self._legal_entity_id = legal_entity_id
        self._path = path
        self._method = method
        self._previous = {}

    def __enter__(self):
        self._previous = {
            "correlation_id": CorrelationIdInjector.get(),
            "user_id": UserContextInjector.get_user_id(),
            "legal_entity_id": UserContextInjector.get_legal_entity_id(),
            "path": UserContextInjector.get_request_path(),
            "method": UserContextInjector.get_method(),
        }

        CorrelationIdInjector.set(self._correlation_id)
        UserContextInjector.set_user_id(self._user_id)
        UserContextInjector.set_legal_entity_id(self._legal_entity_id)
        UserContextInjector.set_request_info(self._path, self._method)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        CorrelationIdInjector.set(self._previous["correlation_id"])
        UserContextInjector.set_user_id(self._previous["user_id"])
        UserContextInjector.set_legal_entity_id(self._previous["legal_entity_id"])
        UserContextInjector.set_request_info(self._previous["path"], self._previous["method"])

    @property
    def correlation_id(self) -> str:
        return self._correlation_id


# ============================================================================
# ASYNC MIDDLEWARE
# ============================================================================


class CorrelationIdMiddleware:
    """
    ASGI middleware untuk inject correlation ID ke request context.

    Usage:
        app.add_middleware(CorrelationIdMiddleware)
    """

    def __init__(self, app, header_name: str = "X-Correlation-ID"):
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract correlation ID from header
        headers = dict(scope.get("headers", []))
        correlation_id = headers.get(self.header_name.encode())
        if correlation_id:
            correlation_id = correlation_id.decode()
        else:
            correlation_id = CorrelationIdInjector.generate()

        # Set context
        token = _correlation_id_ctx.set(correlation_id)

        try:
            await self.app(scope, receive, send)
        finally:
            _correlation_id_ctx.reset(token)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def get_current_correlation_id() -> str | None:
    """Get current correlation ID (convenience function)."""
    return CorrelationIdInjector.get()


def get_current_user_id() -> str | None:
    """Get current user ID (convenience function)."""
    return UserContextInjector.get_user_id()


def get_current_legal_entity_id() -> str | None:
    """Get current legal entity ID (convenience function)."""
    return UserContextInjector.get_legal_entity_id()


def set_current_correlation_id(correlation_id: str) -> None:
    """Set current correlation ID."""
    CorrelationIdInjector.set(correlation_id)


def generate_correlation_id() -> str:
    """Generate new correlation ID."""
    return CorrelationIdInjector.generate()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CorrelationIdInjector",
    "CorrelationIdMiddleware",
    "CorrelationIdScope",
    "RequestContextScope",
    "UserContextInjector",
    "generate_correlation_id",
    "get_current_correlation_id",
    "get_current_legal_entity_id",
    "get_current_user_id",
    "set_current_correlation_id",
]
