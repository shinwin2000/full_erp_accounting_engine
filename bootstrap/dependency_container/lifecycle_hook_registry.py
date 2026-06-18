#!/usr/bin/env python3
"""
Module: lifecycle_hook_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Registry untuk lifecycle hooks (startup dan shutdown).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import IntEnum

from infrastructure.telemetry.alert_manager_router import trigger_alert

logger = logging.getLogger(__name__)


class HookPriority(IntEnum):
    """Priority for lifecycle hooks (lower number = higher priority)."""
    HIGHEST = 0
    HIGH = 10
    NORMAL = 50
    LOW = 90
    LOWEST = 100


class LifecycleHookRegistry:
    """
    Registry untuk lifecycle hooks.

    Method Standards:
    - register_startup() - Mendaftar startup hook
    - register_shutdown() - Mendaftar shutdown hook
    - execute_startup() - Eksekusi startup
    - execute_shutdown() - Eksekusi shutdown
    - register_default_hooks() - Registrasi default
    - list_startup_hooks() - Daftar startup hooks
    - list_shutdown_hooks() - Daftar shutdown hooks
    - clear() - Hapus semua hooks
    - remove_startup() - Hapus startup hook
    - remove_shutdown() - Hapus shutdown hook
    """

    def __init__(self):
        self._startup_hooks: list[tuple[Callable[[], Awaitable[None]], HookPriority]] = []
        self._shutdown_hooks: list[tuple[Callable[[], Awaitable[None]], HookPriority]] = []
        self._executed = False
        self._logger = logging.getLogger(f"{__name__}.LifecycleHookRegistry")

    def register_startup(
        self, hook: Callable[[], Awaitable[None]], priority: HookPriority = HookPriority.NORMAL
    ) -> None:
        """Register a startup hook."""
        if not callable(hook):
            raise ValueError("Hook must be callable")
        self._startup_hooks.append((hook, priority))
        self._startup_hooks.sort(key=lambda x: x[1].value)
        self._logger.debug(f"Registered startup hook: {hook.__name__} (priority={priority.name})")

    def register_shutdown(
        self, hook: Callable[[], Awaitable[None]], priority: HookPriority = HookPriority.NORMAL
    ) -> None:
        """Register a shutdown hook."""
        if not callable(hook):
            raise ValueError("Hook must be callable")
        self._shutdown_hooks.append((hook, priority))
        self._shutdown_hooks.sort(key=lambda x: x[1].value)
        self._logger.debug(f"Registered shutdown hook: {hook.__name__} (priority={priority.name})")

    async def execute_startup(self) -> None:
        """Execute all startup hooks."""
        self._logger.info(f"Executing {len(self._startup_hooks)} startup hooks")

        for hook, priority in self._startup_hooks:
            try:
                await hook()
                self._logger.debug(f"Startup hook executed: {hook.__name__}")
            except Exception as e:
                self._logger.error(f"Startup hook {hook.__name__} failed: {e}")
                await trigger_alert(
                    title="Startup Hook Failed",
                    message=f"Startup hook {hook.__name__} failed: {e}",
                    severity="error",
                    source="LifecycleHookRegistry",
                )
                raise

        self._executed = True
        self._logger.info("All startup hooks executed successfully")

    async def execute_shutdown(self) -> None:
        """Execute all shutdown hooks."""
        self._logger.info(f"Executing {len(self._shutdown_hooks)} shutdown hooks")

        for hook, priority in self._shutdown_hooks:
            try:
                await hook()
                self._logger.debug(f"Shutdown hook executed: {hook.__name__}")
            except Exception as e:
                self._logger.error(f"Shutdown hook {hook.__name__} failed: {e}")
                await trigger_alert(
                    title="Shutdown Hook Failed",
                    message=f"Shutdown hook {hook.__name__} failed: {e}",
                    severity="warning",
                    source="LifecycleHookRegistry",
                )

        self._logger.info("All shutdown hooks executed")

    async def register_default_hooks(self) -> None:
        """Register default lifecycle hooks."""

        async def connect_database():
            from infrastructure.database.session_factory_sqlalchemy import init_db
            await init_db()
            self._logger.info("Database connected")

        async def disconnect_database():
            from infrastructure.database.session_factory_sqlalchemy import close_db
            await close_db()
            self._logger.info("Database disconnected")

        self.register_startup(connect_database, HookPriority.HIGHEST)
        self.register_shutdown(disconnect_database, HookPriority.LOWEST)

        async def connect_redis():
            from infrastructure.caching.redis_manager import get_redis_manager
            await get_redis_manager()
            self._logger.info("Redis connected")

        async def disconnect_redis():
            from infrastructure.caching.redis_manager import close_redis
            await close_redis()
            self._logger.info("Redis disconnected")

        self.register_startup(connect_redis, HookPriority.HIGH)
        self.register_shutdown(disconnect_redis, HookPriority.LOW)

        async def start_kafka_producer():
            from infrastructure.message_broker.kafka_producer_wrapper import get_kafka_producer
            await get_kafka_producer()
            self._logger.info("Kafka producer started")

        async def stop_kafka_producer():
            from infrastructure.message_broker.kafka_producer_wrapper import close_kafka_producer
            await close_kafka_producer()
            self._logger.info("Kafka producer stopped")

        self.register_startup(start_kafka_producer, HookPriority.NORMAL)
        self.register_shutdown(stop_kafka_producer, HookPriority.NORMAL)

        async def start_outbox_poller():
            from infrastructure.message_broker.transactional_outbox_poller import start_outbox_poller
            await start_outbox_poller()
            self._logger.info("Outbox poller started")

        async def stop_outbox_poller():
            from infrastructure.message_broker.transactional_outbox_poller import stop_outbox_poller
            await stop_outbox_poller()
            self._logger.info("Outbox poller stopped")

        self.register_startup(start_outbox_poller, HookPriority.LOW)
        self.register_shutdown(stop_outbox_poller, HookPriority.HIGH)

        async def start_event_gate():
            from event_gateway.event_gate_singleton import get_event_gate
            await get_event_gate()
            self._logger.info("Event gate started")

        self.register_startup(start_event_gate, HookPriority.LOW)

        async def start_cache_warmer():
            from infrastructure.caching.warmer_scheduled import start_cache_warmer
            await start_cache_warmer()
            self._logger.info("Cache warmer started")

        async def stop_cache_warmer():
            from infrastructure.caching.warmer_scheduled import stop_cache_warmer
            await stop_cache_warmer()
            self._logger.info("Cache warmer stopped")

        self.register_startup(start_cache_warmer, HookPriority.LOW)
        self.register_shutdown(stop_cache_warmer, HookPriority.NORMAL)

        async def start_metrics_collection():
            from infrastructure.telemetry.journal_posting_latency_metrics import start_metrics_collection
            await start_metrics_collection()
            self._logger.info("Metrics collection started")

        async def stop_metrics_collection():
            from infrastructure.telemetry.journal_posting_latency_metrics import stop_metrics_collection
            await stop_metrics_collection()
            self._logger.info("Metrics collection stopped")

        self.register_startup(start_metrics_collection, HookPriority.NORMAL)
        self.register_shutdown(stop_metrics_collection, HookPriority.NORMAL)

        self._logger.info("Default lifecycle hooks registered")

    def list_startup_hooks(self) -> list[str]:
        """List registered startup hook names."""
        return [hook.__name__ for hook, _ in self._startup_hooks]

    def list_shutdown_hooks(self) -> list[str]:
        """List registered shutdown hook names."""
        return [hook.__name__ for hook, _ in self._shutdown_hooks]

    def clear(self) -> None:
        """Clear all hooks."""
        self._startup_hooks.clear()
        self._shutdown_hooks.clear()
        self._executed = False
        self._logger.info("Lifecycle hooks cleared")

    def remove_startup(self, hook_name: str) -> bool:
        """Remove a startup hook by name."""
        for i, (hook, _) in enumerate(self._startup_hooks):
            if hook.__name__ == hook_name:
                del self._startup_hooks[i]
                self._logger.debug(f"Removed startup hook: {hook_name}")
                return True
        return False

    def remove_shutdown(self, hook_name: str) -> bool:
        """Remove a shutdown hook by name."""
        for i, (hook, _) in enumerate(self._shutdown_hooks):
            if hook.__name__ == hook_name:
                del self._shutdown_hooks[i]
                self._logger.debug(f"Removed shutdown hook: {hook_name}")
                return True
        return False


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_lifecycle_registry: LifecycleHookRegistry | None = None


def get_lifecycle_registry() -> LifecycleHookRegistry:
    """Get singleton instance of LifecycleHookRegistry."""
    global _lifecycle_registry
    if _lifecycle_registry is None:
        _lifecycle_registry = LifecycleHookRegistry()
    return _lifecycle_registry


async def register_default_hooks() -> None:
    """Register default lifecycle hooks."""
    registry = get_lifecycle_registry()
    await registry.register_default_hooks()


__all__ = [
    "HookPriority",
    "LifecycleHookRegistry",
    "get_lifecycle_registry",
    "register_default_hooks",
]