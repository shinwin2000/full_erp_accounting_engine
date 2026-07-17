#!/usr/bin/env python3
"""
tests/application/use_cases/test_handlers.py
Test untuk application/use_cases/handlers.py
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from application.use_cases.handlers import BaseCommandHandler, BaseQueryHandler, audit


class TestBaseCommandHandler:
    def test_construction(self):
        instance = BaseCommandHandler()
        assert isinstance(instance, BaseCommandHandler)

    @pytest.mark.asyncio
    async def test_handle_raises_not_implemented(self):
        """BaseCommandHandler.handle should raise NotImplementedError."""
        instance = BaseCommandHandler()
        with pytest.raises(NotImplementedError):
            await instance.handle(command=MagicMock())

    @pytest.mark.asyncio
    async def test_handle_can_be_overridden(self):
        """Subclass can override handle and return a result."""
        class CustomHandler(BaseCommandHandler):
            async def handle(self, command):
                return "handled"

        handler = CustomHandler()
        result = await handler.handle(command=MagicMock())
        assert result == "handled"


class TestBaseQueryHandler:
    def test_construction(self):
        instance = BaseQueryHandler()
        assert isinstance(instance, BaseQueryHandler)

    @pytest.mark.asyncio
    async def test_handle_raises_not_implemented(self):
        """BaseQueryHandler.handle should raise NotImplementedError."""
        instance = BaseQueryHandler()
        with pytest.raises(NotImplementedError):
            await instance.handle(query=MagicMock())

    @pytest.mark.asyncio
    async def test_handle_can_be_overridden(self):
        """Subclass can override handle and return a result."""
        class CustomHandler(BaseQueryHandler):
            async def handle(self, query):
                return {"result": "queried"}

        handler = CustomHandler()
        result = await handler.handle(query=MagicMock())
        assert result == {"result": "queried"}


def test_audit_returns_callable():
    """audit decorator should return a callable."""
    async def dummy_func():
        return "ok"

    decorated = audit(dummy_func)
    assert callable(decorated)


def test_audit_decorated_function_calls_original():
    """The decorated function should invoke the original function."""
    mock_func = AsyncMock(return_value="result")
    decorated = audit(mock_func)
    # Call the decorated function (assuming it accepts the same arguments)
    # We'll pass no args; if it expects args, we can use dummy.
    try:
        decorated()
    except TypeError:
        # If it requires arguments, pass a dummy MagicMock
        decorated(MagicMock())
    mock_func.assert_called_once()