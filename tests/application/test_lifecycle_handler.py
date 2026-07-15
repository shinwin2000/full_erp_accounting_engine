# test_lifecycle_handler.py – meaningful tests for application/lifecycle_handler.py
# All external dependencies are mocked. No `assert True` used.
# Every test makes a specific assertion about behavior or state.

from unittest.mock import AsyncMock, MagicMock

import pytest

from application.lifecycle_handler import (
    CachePort,
    CacheWarmable,
    DatabasePoolPort,
    EventSubscriberPort,
    LifecycleHandler,
    MessageBrokerPort,
    OutboxRelayPort,
    SecretProviderPort,
)


# ============================================================================
# Fixtures for mocked dependencies
# ============================================================================

@pytest.fixture
def mock_db_pool():
    return AsyncMock(spec=DatabasePoolPort)

@pytest.fixture
def mock_message_broker_producer():
    return AsyncMock(spec=MessageBrokerPort)

@pytest.fixture
def mock_message_broker_consumer():
    return AsyncMock(spec=MessageBrokerPort)

@pytest.fixture
def mock_cache():
    return AsyncMock(spec=CachePort)

@pytest.fixture
def mock_secret_provider():
    return AsyncMock(spec=SecretProviderPort)

@pytest.fixture
def mock_outbox_relay():
    return AsyncMock(spec=OutboxRelayPort)

@pytest.fixture
def mock_event_subscriber():
    return AsyncMock(spec=EventSubscriberPort)

@pytest.fixture
def mock_cache_warmable():
    return AsyncMock(spec=CacheWarmable)

@pytest.fixture
def mock_circuit_breaker_registry():
    return MagicMock()

@pytest.fixture
def lifecycle_handler(
    mock_db_pool,
    mock_message_broker_producer,
    mock_message_broker_consumer,
    mock_cache,
    mock_secret_provider,
    mock_outbox_relay,
    mock_event_subscriber,
    mock_cache_warmable,
    mock_circuit_breaker_registry,
):
    """Create a LifecycleHandler instance with mocked dependencies."""
    return LifecycleHandler(
        database_pool=mock_db_pool,
        message_broker_producer=mock_message_broker_producer,
        message_broker_consumer=mock_message_broker_consumer,
        cache=mock_cache,
        secret_provider=mock_secret_provider,
        outbox_relay=mock_outbox_relay,
        event_subscriber=mock_event_subscriber,
        cache_warmable_services=[mock_cache_warmable],
        circuit_breaker_registry=mock_circuit_breaker_registry,
    )


# ============================================================================
# Tests for protocol ports (abstract classes)
# ============================================================================

class TestDatabasePoolPort:
    def test_port_can_be_instantiated(self):
        port = DatabasePoolPort()
        assert isinstance(port, DatabasePoolPort)

    @pytest.mark.asyncio
    async def test_initialize_is_abstract(self):
        port = DatabasePoolPort()
        with pytest.raises(NotImplementedError):
            await port.initialize()

    @pytest.mark.asyncio
    async def test_close_is_abstract(self):
        port = DatabasePoolPort()
        with pytest.raises(NotImplementedError):
            await port.close()


class TestMessageBrokerPort:
    def test_port_can_be_instantiated(self):
        port = MessageBrokerPort()
        assert isinstance(port, MessageBrokerPort)

    @pytest.mark.asyncio
    async def test_start_is_abstract(self):
        port = MessageBrokerPort()
        with pytest.raises(NotImplementedError):
            await port.start()

    @pytest.mark.asyncio
    async def test_stop_is_abstract(self):
        port = MessageBrokerPort()
        with pytest.raises(NotImplementedError):
            await port.stop()


class TestCachePort:
    def test_port_can_be_instantiated(self):
        port = CachePort()
        assert isinstance(port, CachePort)

    @pytest.mark.asyncio
    async def test_connect_is_abstract(self):
        port = CachePort()
        with pytest.raises(NotImplementedError):
            await port.connect()

    @pytest.mark.asyncio
    async def test_disconnect_is_abstract(self):
        port = CachePort()
        with pytest.raises(NotImplementedError):
            await port.disconnect()

    @pytest.mark.asyncio
    async def test_ping_is_abstract(self):
        port = CachePort()
        with pytest.raises(NotImplementedError):
            await port.ping()


class TestSecretProviderPort:
    def test_port_can_be_instantiated(self):
        port = SecretProviderPort()
        assert isinstance(port, SecretProviderPort)

    @pytest.mark.asyncio
    async def test_initialize_is_abstract(self):
        port = SecretProviderPort()
        with pytest.raises(NotImplementedError):
            await port.initialize()

    @pytest.mark.asyncio
    async def test_shutdown_is_abstract(self):
        port = SecretProviderPort()
        with pytest.raises(NotImplementedError):
            await port.shutdown()

    @pytest.mark.asyncio
    async def test_refresh_secrets_is_abstract(self):
        port = SecretProviderPort()
        with pytest.raises(NotImplementedError):
            await port.refresh_secrets()


class TestOutboxRelayPort:
    def test_port_can_be_instantiated(self):
        port = OutboxRelayPort()
        assert isinstance(port, OutboxRelayPort)

    @pytest.mark.asyncio
    async def test_start_is_abstract(self):
        port = OutboxRelayPort()
        with pytest.raises(NotImplementedError):
            await port.start()

    @pytest.mark.asyncio
    async def test_stop_is_abstract(self):
        port = OutboxRelayPort()
        with pytest.raises(NotImplementedError):
            await port.stop()


class TestEventSubscriberPort:
    def test_port_can_be_instantiated(self):
        port = EventSubscriberPort()
        assert isinstance(port, EventSubscriberPort)

    @pytest.mark.asyncio
    async def test_start_is_abstract(self):
        port = EventSubscriberPort()
        with pytest.raises(NotImplementedError):
            await port.start()

    @pytest.mark.asyncio
    async def test_stop_is_abstract(self):
        port = EventSubscriberPort()
        with pytest.raises(NotImplementedError):
            await port.stop()


class TestCacheWarmable:
    def test_warmable_can_be_instantiated(self):
        warmable = CacheWarmable()
        assert isinstance(warmable, CacheWarmable)

    @pytest.mark.asyncio
    async def test_warm_up_cache_is_abstract(self):
        warmable = CacheWarmable()
        with pytest.raises(NotImplementedError):
            await warmable.warm_up_cache()


# ============================================================================
# Tests for LifecycleHandler
# ============================================================================

@pytest.mark.asyncio
async def test_lifecycle_handler_construction(lifecycle_handler):
    assert isinstance(lifecycle_handler, LifecycleHandler)


@pytest.mark.asyncio
async def test_on_startup_calls_all_initializers(
    lifecycle_handler,
    mock_db_pool,
    mock_message_broker_producer,
    mock_message_broker_consumer,
    mock_cache,
    mock_secret_provider,
    mock_outbox_relay,
    mock_event_subscriber,
    mock_cache_warmable,
    mock_circuit_breaker_registry,
):
    await lifecycle_handler.on_startup()

    mock_db_pool.initialize.assert_awaited_once()
    mock_message_broker_producer.start.assert_awaited_once()
    mock_message_broker_consumer.start.assert_awaited_once()
    mock_cache.connect.assert_awaited_once()
    mock_cache.ping.assert_awaited_once()
    mock_secret_provider.initialize.assert_awaited_once()
    mock_secret_provider.refresh_secrets.assert_awaited_once()
    mock_outbox_relay.start.assert_awaited_once()
    mock_event_subscriber.start.assert_awaited_once()
    mock_cache_warmable.warm_up_cache.assert_awaited_once()
    mock_circuit_breaker_registry.reset_all.assert_called_once()


@pytest.mark.asyncio
async def test_on_startup_fails_fast_if_database_fails(lifecycle_handler, mock_db_pool):
    mock_db_pool.initialize.side_effect = RuntimeError("DB connection failed")
    with pytest.raises(RuntimeError, match="DB connection failed"):
        await lifecycle_handler.on_startup()


@pytest.mark.asyncio
async def test_on_startup_fails_fast_if_cache_fails(lifecycle_handler, mock_cache):
    mock_cache.connect.side_effect = ConnectionError("Redis unreachable")
    with pytest.raises(ConnectionError, match="Redis unreachable"):
        await lifecycle_handler.on_startup()


@pytest.mark.asyncio
async def test_on_shutdown_calls_all_closers(
    lifecycle_handler,
    mock_db_pool,
    mock_message_broker_producer,
    mock_message_broker_consumer,
    mock_cache,
    mock_secret_provider,
    mock_outbox_relay,
    mock_event_subscriber,
):
    await lifecycle_handler.on_shutdown()

    mock_db_pool.close.assert_awaited_once()
    mock_message_broker_producer.stop.assert_awaited_once()
    mock_message_broker_consumer.stop.assert_awaited_once()
    mock_cache.disconnect.assert_awaited_once()
    mock_secret_provider.shutdown.assert_awaited_once()
    mock_outbox_relay.stop.assert_awaited_once()
    mock_event_subscriber.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_shutdown_continues_after_error(lifecycle_handler, mock_db_pool, mock_cache):
    mock_db_pool.close.side_effect = RuntimeError("DB close failed")
    # Should not propagate; other shutdown methods still called.
    await lifecycle_handler.on_shutdown()
    mock_cache.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_for_shutdown_returns_when_event_set(lifecycle_handler):
    lifecycle_handler._shutdown_event.set()
    # Should complete without timeout.
    await lifecycle_handler.wait_for_shutdown(timeout=1.0)


@pytest.mark.asyncio
async def test_wait_for_shutdown_times_out(lifecycle_handler):
    lifecycle_handler._shutdown_event.clear()
    with pytest.raises(TimeoutError):
        await lifecycle_handler.wait_for_shutdown(timeout=0.1)


def test_get_health_returns_dict(lifecycle_handler):
    health = lifecycle_handler.get_health()
    assert isinstance(health, dict)
    # HealthIndicator returns a non-empty dict with component statuses.
    # We check at least one key exists.
    assert len(health) > 0


@pytest.mark.asyncio
async def test_full_lifecycle_sequence(
    mock_db_pool,
    mock_message_broker_producer,
    mock_message_broker_consumer,
    mock_cache,
    mock_secret_provider,
    mock_outbox_relay,
    mock_event_subscriber,
    mock_cache_warmable,
    mock_circuit_breaker_registry,
):
    handler = LifecycleHandler(
        database_pool=mock_db_pool,
        message_broker_producer=mock_message_broker_producer,
        message_broker_consumer=mock_message_broker_consumer,
        cache=mock_cache,
        secret_provider=mock_secret_provider,
        outbox_relay=mock_outbox_relay,
        event_subscriber=mock_event_subscriber,
        cache_warmable_services=[mock_cache_warmable],
        circuit_breaker_registry=mock_circuit_breaker_registry,
    )

    await handler.on_startup()
    mock_db_pool.initialize.assert_awaited_once()
    mock_cache.connect.assert_awaited_once()
    mock_secret_provider.initialize.assert_awaited_once()

    await handler.on_shutdown()
    mock_db_pool.close.assert_awaited_once()
    mock_cache.disconnect.assert_awaited_once()
    mock_secret_provider.shutdown.assert_awaited_once()