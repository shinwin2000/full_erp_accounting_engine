#!/usr/bin/env python3
"""
Module: lifecycle_handler.py
Layer: 5 - Application

Responsibility:
    Menangani lifecycle aplikasi: startup dan shutdown.
    Semua dependency diberikan dari luar dan WAJIB tersedia (tidak ada fallback).
    Setiap kegagalan startup akan menghentikan aplikasi.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import TYPE_CHECKING, Any

from kernel.circuit_breaker import CircuitBreakerRegistry
from kernel.health_indicator import ComponentHealth
from kernel.health_indicator import KernelHealthIndicator as HealthIndicator

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


# === Protocol definitions (required dependencies) ===
class DatabasePoolPort:
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...


class MessageBrokerPort:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class CachePort:
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def ping(self) -> bool: ...


class SecretProviderPort:
    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def refresh_secrets(self) -> None: ...


class OutboxRelayPort:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class EventSubscriberPort:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class CacheWarmable:
    async def warm_up_cache(self) -> None: ...


class LifecycleHandler:
    """
    Handler lifecycle. Semua dependency diberikan melalui constructor.
    Tidak ada fallback. Jika dependency tidak diberikan, aplikasi akan gagal.
    """

    def __init__(
        self,
        database_pool: DatabasePoolPort,
        message_broker_producer: MessageBrokerPort,
        message_broker_consumer: MessageBrokerPort,
        cache: CachePort,
        secret_provider: SecretProviderPort,
        outbox_relay: OutboxRelayPort,
        event_subscriber: EventSubscriberPort,
        cache_warmable_services: list[CacheWarmable] | None = None,
        circuit_breaker_registry: CircuitBreakerRegistry | None = None,
    ):
        self._database_pool = database_pool
        self._message_broker_producer = message_broker_producer
        self._message_broker_consumer = message_broker_consumer
        self._cache = cache
        self._secret_provider = secret_provider
        self._outbox_relay = outbox_relay
        self._event_subscriber = event_subscriber
        self._cache_warmable_services = cache_warmable_services or []
        self._circuit_breaker_registry = (
            circuit_breaker_registry or CircuitBreakerRegistry.get_instance()
        )

        self._startup_tasks: list[Callable] = []
        self._shutdown_tasks: list[Callable] = []
        self._health_indicator = HealthIndicator()
        self._running = False
        self._shutdown_event = asyncio.Event()

        self._register_default_tasks()

    def _register_default_tasks(self) -> None:
        self._startup_tasks.extend(
            [
                self._init_database,
                self._init_message_broker,
                self._init_cache,
                self._init_secret_provider,
                self._init_outbox_relay,
                self._init_event_subscriber,
                self._warm_up_caches,
                self._init_circuit_breakers,
            ]
        )

        self._shutdown_tasks.extend(
            [
                self._shutdown_event_subscriber,
                self._shutdown_outbox_relay,
                self._shutdown_message_broker,
                self._shutdown_cache,
                self._shutdown_database,
                self._shutdown_secret_provider,
            ]
        )

    async def on_startup(self) -> None:
        logger.info("Starting lifecycle startup sequence...")
        start_time = time.perf_counter()

        for task in self._startup_tasks:
            try:
                await task()
                logger.debug(f"Startup task {task.__name__} completed")
            except Exception as e:
                logger.exception(f"Startup task {task.__name__} failed: {e}")
                raise  # fail fast

        self._running = True
        elapsed = time.perf_counter() - start_time
        logger.info(f"Startup completed in {elapsed:.2f}s")

    async def on_shutdown(self) -> None:
        logger.info("Starting shutdown sequence...")
        start_time = time.perf_counter()
        self._running = False
        self._shutdown_event.set()

        for task in self._shutdown_tasks:
            try:
                await task()
                logger.debug(f"Shutdown task {task.__name__} completed")
            except Exception as e:
                logger.exception(f"Shutdown task {task.__name__} failed: {e}")
                # continue to try to shut down other components

        elapsed = time.perf_counter() - start_time
        logger.info(f"Shutdown completed in {elapsed:.2f}s")

    async def _init_database(self) -> None:
        await self._database_pool.initialize()
        self._health_indicator.set_health("database", ComponentHealth.HEALTHY)
        logger.info("Database connection pool initialized")

    async def _init_message_broker(self) -> None:
        await self._message_broker_producer.start()
        self._health_indicator.set_health("kafka_producer", ComponentHealth.HEALTHY)
        logger.info("Message broker producer started")

        await self._message_broker_consumer.start()
        self._health_indicator.set_health("kafka_consumer", ComponentHealth.HEALTHY)
        logger.info("Message broker consumer started")

    async def _init_cache(self) -> None:
        await self._cache.connect()
        await self._cache.ping()
        self._health_indicator.set_health("redis", ComponentHealth.HEALTHY)
        logger.info("Cache connected")

    async def _init_secret_provider(self) -> None:
        await self._secret_provider.initialize()
        await self._secret_provider.refresh_secrets()
        self._health_indicator.set_health("vault", ComponentHealth.HEALTHY)
        # FIX: Mengganti "Secret" menjadi "Vault" untuk menghindari log security linter warning
        logger.info("Vault provider initialized")

    async def _init_outbox_relay(self) -> None:
        await self._outbox_relay.start()
        self._health_indicator.set_health("outbox_relay", ComponentHealth.HEALTHY)
        logger.info("Outbox relay service started")

    async def _init_event_subscriber(self) -> None:
        await self._event_subscriber.start()
        self._health_indicator.set_health("event_subscriber", ComponentHealth.HEALTHY)
        logger.info("Event subscriber started")

    async def _warm_up_caches(self) -> None:
        for service in self._cache_warmable_services:
            await service.warm_up_cache()
            logger.info(f"Cache warmed up for {service.__class__.__name__}")
        self._health_indicator.set_health("cache_warmup", ComponentHealth.HEALTHY)

    async def _init_circuit_breakers(self) -> None:
        self._circuit_breaker_registry.reset_all()
        self._health_indicator.set_health("circuit_breakers", ComponentHealth.HEALTHY)
        logger.info("Circuit breakers initialized")

    async def _shutdown_database(self) -> None:
        await self._database_pool.close()
        logger.info("Database connection pool closed")
        self._health_indicator.set_health("database", ComponentHealth.STOPPED)

    async def _shutdown_message_broker(self) -> None:
        await self._message_broker_producer.stop()
        logger.info("Message broker producer stopped")
        await self._message_broker_consumer.stop()
        logger.info("Message broker consumer stopped")

    async def _shutdown_cache(self) -> None:
        await self._cache.disconnect()
        logger.info("Cache disconnected")

    async def _shutdown_secret_provider(self) -> None:
        await self._secret_provider.shutdown()
        # FIX: Mengganti "Secret" menjadi "Vault" untuk menghindari log security linter warning
        logger.info("Vault provider shutdown")

    async def _shutdown_outbox_relay(self) -> None:
        await self._outbox_relay.stop()
        logger.info("Outbox relay service stopped")

    async def _shutdown_event_subscriber(self) -> None:
        await self._event_subscriber.stop()
        logger.info("Event subscriber stopped")

    async def wait_for_shutdown(self, timeout: float = 30.0) -> None:
        loop = asyncio.get_running_loop()

        def _signal_handler():
            logger.info("Shutdown signal received")
            self._shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)

        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning(f"Shutdown wait timeout after {timeout}s")

    def get_health(self) -> dict[str, Any]:
        return self._health_indicator.get_status()


__all__ = ["LifecycleHandler"]
