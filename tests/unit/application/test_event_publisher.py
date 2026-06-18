#!/usr/bin/env python3
"""
Unit: Event Publisher (Application Layer)
Menguji publisher untuk mendispatch event domain ke event bus.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.events.handler_registry import event_handler_registry
from application.events.publisher_application import (
    ApplicationEventPublisher,
    EventEnvelope,
    PublishMode,
)


class JournalPostedEvent:
    def __init__(self):
        pass

    def to_dict(self) -> dict:
        return {"data": "journal"}


class UnknownEvent:
    pass


class TestEventPublisher:
    @pytest.fixture
    def mock_broker(self):
        broker = AsyncMock()
        broker.send = AsyncMock()
        return broker

    @pytest.fixture
    def mock_outbox(self):
        outbox = AsyncMock()
        outbox.enqueue = AsyncMock(return_value=1)
        return outbox

    @pytest.fixture
    def mock_cache(self):
        cache = AsyncMock()
        cache.exists = AsyncMock(return_value=False)
        cache.setex = AsyncMock()
        return cache

    @pytest.fixture(autouse=True)
    def patch_retry_and_circuit(self):
        # Definisi DummyRetryPolicy di dalam fixture
        class DummyRetryPolicy:
            def __init__(self, **kwargs):
                pass

            async def execute(self, func):
                return await func()

        # Patch retry policy and circuit breaker
        with patch(
            "application.events.publisher_application.RetryPolicy",
            DummyRetryPolicy,
        ), patch(
            "application.events.publisher_application.CircuitBreaker",
            MagicMock(),
        ):
            yield

    @pytest.fixture(autouse=True)
    def clear_registry(self):
        """Bersihkan registry sebelum dan sesudah test."""
        event_handler_registry._handlers.clear()
        yield
        event_handler_registry._handlers.clear()

    # ==========================================================================
    # TESTS
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_event_publisher_dispatch(
        self,
        mock_broker,
        mock_outbox,
        mock_cache,
    ):
        publisher = ApplicationEventPublisher(
            message_broker=mock_broker,
            outbox=mock_outbox,
            cache=mock_cache,
            mode=PublishMode.SYNC,
            enable_circuit_breaker=False,
            enable_idempotency=False,
        )
        event = JournalPostedEvent()
        handler = MagicMock()

        # Fungsi fake yang langsung memanggil handler
        async def fake_trigger_local_handlers(envelope: EventEnvelope):
            handler(envelope)  # panggil langsung

        with patch.object(
            publisher,
            "_trigger_local_handlers",
            new=AsyncMock(side_effect=fake_trigger_local_handlers),
        ):
            await publisher.publish(event)

        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_publisher_no_handler_does_not_crash(
        self,
        mock_broker,
        mock_outbox,
        mock_cache,
    ):
        publisher = ApplicationEventPublisher(
            message_broker=mock_broker,
            outbox=mock_outbox,
            cache=mock_cache,
            mode=PublishMode.SYNC,
            enable_circuit_breaker=False,
            enable_idempotency=False,
        )
        event = UnknownEvent()
        # Tidak perlu handler, publish tidak boleh crash
        await publisher.publish(event)
        assert True

    @pytest.mark.asyncio
    async def test_event_publisher_with_multiple_handlers(
        self,
        mock_broker,
        mock_outbox,
        mock_cache,
    ):
        publisher = ApplicationEventPublisher(
            message_broker=mock_broker,
            outbox=mock_outbox,
            cache=mock_cache,
            mode=PublishMode.SYNC,
            enable_circuit_breaker=False,
            enable_idempotency=False,
        )
        event = JournalPostedEvent()
        handler1 = MagicMock()
        handler2 = MagicMock()

        async def fake_trigger_local_handlers(envelope: EventEnvelope):
            handler1(envelope)
            handler2(envelope)

        with patch.object(
            publisher,
            "_trigger_local_handlers",
            new=AsyncMock(side_effect=fake_trigger_local_handlers),
        ):
            await publisher.publish(event)

        handler1.assert_called_once()
        handler2.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_publisher_async_mode(
        self,
        mock_broker,
        mock_outbox,
        mock_cache,
    ):
        publisher = ApplicationEventPublisher(
            message_broker=mock_broker,
            outbox=mock_outbox,
            cache=mock_cache,
            mode=PublishMode.ASYNC,
            enable_circuit_breaker=False,
            enable_idempotency=False,
        )
        event = JournalPostedEvent()
        handler = MagicMock()

        async def fake_trigger_local_handlers(envelope: EventEnvelope):
            handler(envelope)

        with patch.object(
            publisher,
            "_trigger_local_handlers",
            new=AsyncMock(side_effect=fake_trigger_local_handlers),
        ), patch.object(
            publisher._outbox,
            "enqueue",
            new=AsyncMock(return_value=1),
        ):
            await publisher.publish(event)

        handler.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
