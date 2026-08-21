#!/usr/bin/env python3
"""
Module: global_event_subscribers.py
Layer: Application / Events
Responsibility: Provides generic handler and specific handler aliases for backward compatibility.
               No auto-registration to avoid circular imports.
"""

from __future__ import annotations

import logging
from typing import Any

from application.events.handler_registry import HandlerPriority, event_handler_registry

logger = logging.getLogger(__name__)


# ============================================================================
# GENERIC HANDLER (CORE)
# ============================================================================

async def handle_any_event(envelope: Any) -> None:
    """
    Generic handler for any domain event.
    Logs the event to audit trail.
    """
    # event variable removed as it was unused; we only need event_type
    event_type = getattr(envelope, "event_type", None)
    if not event_type:
        event_data = getattr(envelope, "payload", {})
        event_type = event_data.get("event_type", "Unknown")

    logger.info(
        f"Generic handler: {event_type}",
        extra={
            "event_id": str(getattr(envelope, "event_id", "none")),
            "correlation_id": getattr(envelope, "correlation_id", "none"),
        }
    )


# ============================================================================
# SPECIFIC HANDLERS (diperlukan oleh __init__.py dan use cases)
# ============================================================================

async def handle_account_reactivated_event(envelope: Any) -> None:
    """Handler untuk AccountReactivatedEvent (alias untuk generic)."""
    await handle_any_event(envelope)

async def handle_bank_account_updated_event(envelope: Any) -> None:
    """Handler untuk BankAccountUpdatedEvent."""
    await handle_any_event(envelope)

async def handle_dividend_paid_event(envelope: Any) -> None:
    """Handler untuk DividendPaidEvent."""
    await handle_any_event(envelope)

async def handle_faktur_rejected_event(envelope: Any) -> None:
    """Handler untuk FakturRejectedEvent."""
    await handle_any_event(envelope)

async def handle_intangible_asset_revaluated_event(envelope: Any) -> None:
    """Handler untuk IntangibleAssetRevaluatedEvent."""
    await handle_any_event(envelope)

async def handle_production_completed_event(envelope: Any) -> None:
    """Handler untuk ProductionCompletedEvent."""
    await handle_any_event(envelope)

async def handle_project_activated_event(envelope: Any) -> None:
    """Handler untuk ProjectActivatedEvent."""
    await handle_any_event(envelope)

async def handle_role_revoked_event(envelope: Any) -> None:
    """Handler untuk RoleRevokedEvent."""
    await handle_any_event(envelope)

async def handle_time_entry_approved_event(envelope: Any) -> None:
    """Handler untuk TimeEntryApprovedEvent."""
    await handle_any_event(envelope)

async def handle_work_order_completed_event(envelope: Any) -> None:
    """Handler untuk WorkOrderCompletedEvent."""
    await handle_any_event(envelope)


# ============================================================================
# REGISTRATION FUNCTIONS
# ============================================================================

def register_global_subscribers(registry=None) -> None:
    """
    Register global subscribers for all events.
    Alias untuk register_all_subscribers.
    """
    register_all_subscribers(registry)


def register_all_subscribers(registry=None) -> None:
    """
    Register generic handler for ALL domain events.
    This function must be called explicitly (no auto-registration).
    """
    if registry is None:
        registry = event_handler_registry

    # Daftarkan generic handler untuk event yang sudah terdaftar di registry
    # atau kita bisa mendaftarkan untuk semua event yang diketahui.
    # Untuk menghindari double registration, kita hanya daftarkan jika belum ada.
    registered = registry.list_registered_event_types()
    for event_name in registered:
        # Cek apakah sudah ada handler selain wildcard
        handlers = registry.get_handlers(event_name)
        if not handlers:
            registry.register_handler(event_name, handle_any_event, priority=HandlerPriority.LOWEST)

    logger.info(f"Registered generic handler for {len(registered)} event types.")


# Tidak ada auto-registrasi di sini.

__all__ = [
    "handle_account_reactivated_event",
    "handle_any_event",
    "handle_bank_account_updated_event",
    "handle_dividend_paid_event",
    "handle_faktur_rejected_event",
    "handle_intangible_asset_revaluated_event",
    "handle_production_completed_event",
    "handle_project_activated_event",
    "handle_role_revoked_event",
    "handle_time_entry_approved_event",
    "handle_work_order_completed_event",
    "register_all_subscribers",
    "register_global_subscribers",
]
