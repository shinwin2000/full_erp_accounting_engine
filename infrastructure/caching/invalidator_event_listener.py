#!/usr/bin/env python3
"""
Module: invalidator_event_listener.py
Layer: Infrastructure (Caching)
Responsibility: Mendengarkan event dari event gateway dan menginvalidasi cache
               yang terkait dengan aggregate yang berubah. Memastikan bahwa
               cache selalu sinkron dengan data terbaru di database.
               Mendukung invalidasi berdasarkan tipe aggregate, ID spesifik,
               atau pattern wildcard.
Dependencies:
- asyncio, logging
- event_gateway.event_gate_singleton (EventGate, EventEnvelope) → lazy import
- infrastructure.caching.redis_manager (RedisManager) → lazy import
- infrastructure.telemetry.structured_json_logging → lazy import

Audit: Setiap invalidasi cache dicatat untuk debugging.
       Invalidasi massal memicu alert.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

# ============================================================================
# CONSTANTS
# ============================================================================

# Default cache key patterns untuk berbagai aggregate type
CACHE_KEY_PATTERNS = {
    "journal": ["journal:*", "journal:{aggregate_id}", "ledger:account:*", "trial_balance:*"],
    "account": ["account:*", "account:code:*", "chart_of_accounts:*", "trial_balance:*"],
    "ar_invoice": [
        "ar_invoice:*",
        "ar_invoice:{aggregate_id}",
        "customer:*:invoices",
        "ar_aging:*",
    ],
    "ap_invoice": [
        "ap_invoice:*",
        "ap_invoice:{aggregate_id}",
        "supplier:*:invoices",
        "ap_aging:*",
    ],
    "inventory_item": [
        "inventory_item:*",
        "inventory_item:code:*",
        "stock_card:*",
        "inventory_valuation:*",
    ],
    "fixed_asset": ["fixed_asset:*", "fixed_asset:{aggregate_id}", "depreciation_schedule:*"],
    "customer": ["customer:*", "customer:code:*", "ar_invoice:customer:*"],
    "supplier": ["supplier:*", "supplier:code:*", "ap_invoice:supplier:*"],
    "employee": ["employee:*", "employee:code:*", "payroll:*"],
    "user": ["user:*", "user:username:*", "user:email:*", "user:permissions:*"],
    "legal_entity": ["legal_entity:*", "legal_entity:npwp:*"],
    "system_setting": ["system_setting:*"],
}

# Event types that trigger cache invalidation
INVALIDATION_EVENTS = [
    "JournalPosted",
    "JournalApproved",
    "JournalReversed",
    "JournalCancelled",
    "AccountCreated",
    "AccountUpdated",
    "AccountDeactivated",
    "ARInvoiceCreated",
    "ARPaymentRecorded",
    "ARInvoiceCancelled",
    "APInvoiceCreated",
    "APPaymentRecorded",
    "APInvoiceCancelled",
    "InventoryItemCreated",
    "InventoryItemUpdated",
    "StockMovementRecorded",
    "FixedAssetAdded",
    "DepreciationRecorded",
    "CustomerCreated",
    "CustomerUpdated",
    "SupplierCreated",
    "SupplierUpdated",
    "EmployeeCreated",
    "EmployeeUpdated",
    "UserCreated",
    "UserUpdated",
    "UserRoleChanged",
    "LegalEntityUpdated",
    "SystemSettingChanged",
]

_logger = None


def _get_logger():
    """Lazy logger initialization from structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = mod.get_logger
        _logger = get_logger_func(__name__)
    return _logger


def _get_event_gate():
    """Lazy import event_gate_singleton.get_event_gate."""
    mod = importlib.import_module("event_gateway.event_gate_singleton")
    return mod.get_event_gate


def _get_event_envelope():
    """Lazy import EventEnvelope for type checking (minimal)."""
    mod = importlib.import_module("event_gateway.event_envelope")
    return mod.EventEnvelope


def _get_redis_manager():
    """Lazy import redis_manager.get_redis_manager."""
    mod = importlib.import_module("infrastructure.caching.redis_manager")
    return mod.get_redis_manager


def _get_alert_trigger():
    """Lazy import alert_manager_router.trigger_alert."""
    mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
    return mod.trigger_alert


# ============================================================================
# CACHE INVALIDATOR
# ============================================================================


class CacheInvalidator:
    """
    Mendengarkan event dan menginvalidasi cache yang terkait.
    """

    def __init__(self, event_gate=None, redis_manager=None):
        self._event_gate = event_gate
        self._redis_manager = redis_manager
        self._subscriptions: dict[str, list[str]] = {}  # event_type -> list of patterns
        self._running = False
        self._task: asyncio.Task | None = None
        self._invalidation_counter = 0
        self._init_subscriptions()

    def _init_subscriptions(self) -> None:
        """Initialize default subscriptions for event types."""
        # Journal events
        self._subscriptions["JournalPosted"] = ["journal:*", "ledger:*", "trial_balance:*"]
        self._subscriptions["JournalApproved"] = ["journal:*"]
        self._subscriptions["JournalReversed"] = ["journal:*", "ledger:*"]
        self._subscriptions["JournalCancelled"] = ["journal:*"]

        # Account events
        self._subscriptions["AccountCreated"] = ["account:*", "chart_of_accounts:*"]
        self._subscriptions["AccountUpdated"] = ["account:*", "chart_of_accounts:*"]
        self._subscriptions["AccountDeactivated"] = ["account:*", "chart_of_accounts:*"]

        # AR events
        self._subscriptions["ARInvoiceCreated"] = ["ar_invoice:*", "customer:*", "ar_aging:*"]
        self._subscriptions["ARPaymentRecorded"] = ["ar_invoice:*", "customer:*", "ar_aging:*"]
        self._subscriptions["ARInvoiceCancelled"] = ["ar_invoice:*", "customer:*", "ar_aging:*"]

        # AP events
        self._subscriptions["APInvoiceCreated"] = ["ap_invoice:*", "supplier:*", "ap_aging:*"]
        self._subscriptions["APPaymentRecorded"] = ["ap_invoice:*", "supplier:*", "ap_aging:*"]
        self._subscriptions["APInvoiceCancelled"] = ["ap_invoice:*", "supplier:*", "ap_aging:*"]

        # Inventory events
        self._subscriptions["InventoryItemCreated"] = ["inventory_item:*", "stock_card:*"]
        self._subscriptions["InventoryItemUpdated"] = ["inventory_item:*", "stock_card:*"]
        self._subscriptions["StockMovementRecorded"] = [
            "inventory_item:*",
            "stock_card:*",
            "inventory_valuation:*",
        ]

        # Fixed asset events
        self._subscriptions["FixedAssetAdded"] = ["fixed_asset:*", "depreciation_schedule:*"]
        self._subscriptions["DepreciationRecorded"] = ["fixed_asset:*", "depreciation_schedule:*"]

        # Master data events
        self._subscriptions["CustomerCreated"] = ["customer:*"]
        self._subscriptions["CustomerUpdated"] = ["customer:*"]
        self._subscriptions["SupplierCreated"] = ["supplier:*"]
        self._subscriptions["SupplierUpdated"] = ["supplier:*"]
        self._subscriptions["EmployeeCreated"] = ["employee:*", "payroll:*"]
        self._subscriptions["EmployeeUpdated"] = ["employee:*", "payroll:*"]

        # IAM events
        self._subscriptions["UserCreated"] = ["user:*"]
        self._subscriptions["UserUpdated"] = ["user:*"]
        self._subscriptions["UserRoleChanged"] = ["user:*", "user:permissions:*"]

        # System events
        self._subscriptions["LegalEntityUpdated"] = ["legal_entity:*"]
        self._subscriptions["SystemSettingChanged"] = ["system_setting:*"]

    async def _get_event_gate(self):
        if self._event_gate is None:
            get_event_gate = _get_event_gate()
            self._event_gate = await get_event_gate()
        return self._event_gate

    async def _get_redis(self):
        if self._redis_manager is None:
            get_redis_manager = _get_redis_manager()
            self._redis_manager = await get_redis_manager()
        return self._redis_manager

    async def start(self) -> None:
        """Start listening to events."""
        if self._running:
            logger = _get_logger()
            logger.warning("Cache invalidator already running")
            return

        event_gate = await self._get_event_gate()

        # Subscribe to all relevant events
        for event_type in INVALIDATION_EVENTS:
            event_gate.subscribe(event_type, self._on_event)
            logger = _get_logger()
            logger.debug(f"Subscribed to {event_type} for cache invalidation")

        self._running = True
        logger = _get_logger()
        logger.info(
            f"Cache invalidator started, subscribed to {len(INVALIDATION_EVENTS)} event types"
        )

    async def stop(self) -> None:
        """Stop listening to events."""
        if not self._running:
            return

        event_gate = await self._get_event_gate()

        # Unsubscribe from all events
        for event_type in INVALIDATION_EVENTS:
            event_gate.unsubscribe(event_type, self._on_event)

        self._running = False
        logger = _get_logger()
        logger.info("Cache invalidator stopped")

    async def _on_event(self, envelope) -> None:
        """
        Callback when an event is received.
        """
        event_type = envelope.event_type
        aggregate_id = str(envelope.aggregate_id)
        aggregate_type = envelope.aggregate_type

        # Get patterns for this event type
        patterns = self._subscriptions.get(event_type, [])

        # Add aggregate-specific patterns
        if aggregate_type in CACHE_KEY_PATTERNS:
            for pattern in CACHE_KEY_PATTERNS[aggregate_type]:
                if "{aggregate_id}" in pattern:
                    pattern = pattern.replace("{aggregate_id}", aggregate_id)
                patterns.append(pattern)

        if not patterns:
            return

        # Invalidate cache
        redis = await self._get_redis()
        invalidated_keys = []

        for pattern in patterns:
            try:
                # Get keys matching pattern
                keys = await redis.keys(pattern)
                if keys:
                    await redis.delete(*keys)
                    invalidated_keys.extend(keys)
                    logger = _get_logger()
                    logger.debug(f"Invalidated {len(keys)} cache keys matching pattern: {pattern}")
            except Exception as e:
                logger = _get_logger()
                logger.error(f"Failed to invalidate pattern {pattern}: {e}")

        self._invalidation_counter += len(invalidated_keys)

        # Alert if too many invalidations (potential cache storm)
        if len(invalidated_keys) > 1000:
            trigger_alert = _get_alert_trigger()
            await trigger_alert(
                title="Large Cache Invalidation",
                message=f"Event {event_type} invalidated {len(invalidated_keys)} cache keys",
                severity="warning",
                source="CacheInvalidator",
            )

        logger = _get_logger()
        logger.debug(f"Invalidated {len(invalidated_keys)} cache keys for event {event_type}")

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Manually invalidate cache by pattern.
        """
        redis = await self._get_redis()
        keys = await redis.keys(pattern)
        if keys:
            await redis.delete(*keys)
            self._invalidation_counter += len(keys)
            logger = _get_logger()
            logger.info(f"Manually invalidated {len(keys)} keys matching pattern: {pattern}")
            return len(keys)
        return 0

    async def invalidate_key(self, key: str) -> bool:
        """
        Manually invalidate a specific cache key.
        """
        redis = await self._get_redis()
        deleted = await redis.delete(key)
        if deleted:
            self._invalidation_counter += 1
            logger = _get_logger()
            logger.debug(f"Manually invalidated key: {key}")
        return deleted > 0

    async def invalidate_by_aggregate(self, aggregate_type: str, aggregate_id: str) -> int:
        """
        Invalidate all cache keys related to an aggregate.
        """
        patterns = CACHE_KEY_PATTERNS.get(aggregate_type, [])
        total = 0
        for pattern in patterns:
            if "{aggregate_id}" in pattern:
                pattern = pattern.replace("{aggregate_id}", aggregate_id)
            total += await self.invalidate_pattern(pattern)
        return total

    async def get_stats(self) -> dict[str, Any]:
        """
        Get invalidation statistics.
        """
        return {
            "running": self._running,
            "total_invalidations": self._invalidation_counter,
            "subscribed_event_types": len(INVALIDATION_EVENTS),
            "patterns_configured": len(self._subscriptions),
        }

    async def add_subscription(self, event_type: str, patterns: list[str]) -> None:
        """
        Add a new subscription for an event type.
        """
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
        self._subscriptions[event_type].extend(patterns)

        # Subscribe to event gate if not already
        if self._running:
            event_gate = await self._get_event_gate()
            event_gate.subscribe(event_type, self._on_event)

        logger = _get_logger()
        logger.info(f"Added cache invalidation subscription for {event_type}: {patterns}")

    async def remove_subscription(self, event_type: str) -> None:
        """
        Remove subscription for an event type.
        """
        if event_type in self._subscriptions:
            del self._subscriptions[event_type]
            logger = _get_logger()
            logger.info(f"Removed cache invalidation subscription for {event_type}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_invalidator: CacheInvalidator | None = None


async def get_cache_invalidator() -> CacheInvalidator:
    """Get singleton instance of CacheInvalidator."""
    global _invalidator
    if _invalidator is None:
        _invalidator = CacheInvalidator()
    return _invalidator


async def start_cache_invalidator() -> None:
    """Start the cache invalidator."""
    invalidator = await get_cache_invalidator()
    await invalidator.start()


async def stop_cache_invalidator() -> None:
    """Stop the cache invalidator."""
    global _invalidator
    if _invalidator:
        await _invalidator.stop()
        _invalidator = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CacheInvalidator",
    "get_cache_invalidator",
    "start_cache_invalidator",
    "stop_cache_invalidator",
]
