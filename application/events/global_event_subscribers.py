#!/usr/bin/env python3
"""
Module: global_event_subscribers.py
Layer: Application / Events
Responsibility: Handler untuk event-event yang belum memiliki subscriber (P57).
"""

from __future__ import annotations

import logging
from typing import Any

from application.events.handler_registry import HandlerPriority, event_handler_registry

logger = logging.getLogger(__name__)


# ============================================================================
# HANDLER FUNCTIONS
# ============================================================================

async def handle_work_order_completed_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"WorkOrderCompletedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "work_order_id": event_data.get("work_order_id") or event_data.get("id"),
        }
    )


async def handle_account_reactivated_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"AccountReactivatedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "account_id": event_data.get("account_id") or event_data.get("id"),
        }
    )


async def handle_project_activated_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"ProjectActivatedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "project_id": event_data.get("project_id") or event_data.get("id"),
        }
    )


async def handle_intangible_asset_revaluated_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"IntangibleAssetRevaluatedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "asset_id": event_data.get("asset_id") or event_data.get("id"),
            "new_value": event_data.get("new_value"),
        }
    )


async def handle_faktur_rejected_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"FakturRejectedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "faktur_number": event_data.get("faktur_number"),
            "rejection_reason": event_data.get("rejection_reason"),
        }
    )


async def handle_dividend_paid_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"DividendPaidEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "dividend_id": event_data.get("dividend_id") or event_data.get("id"),
            "amount": event_data.get("amount"),
        }
    )


async def handle_time_entry_approved_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"TimeEntryApprovedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "time_entry_id": event_data.get("time_entry_id") or event_data.get("id"),
            "project_id": event_data.get("project_id"),
        }
    )


async def handle_bank_account_updated_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"BankAccountUpdatedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "bank_account_id": event_data.get("bank_account_id") or event_data.get("id"),
            "updated_fields": event_data.get("updated_fields"),
        }
    )


async def handle_role_revoked_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"RoleRevokedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "role_id": event_data.get("role_id") or event_data.get("id"),
            "role_name": event_data.get("role_name"),
            "revoked_by": event_data.get("revoked_by"),
        }
    )


async def handle_production_completed_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"ProductionCompletedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "work_order_id": event_data.get("work_order_id") or event_data.get("id"),
            "completed_quantity": event_data.get("completed_quantity"),
        }
    )


# ============================================================================
# NEW HANDLERS FROM LATEST OUTPUT
# ============================================================================

async def handle_bank_transfer_completed_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"BankTransferCompletedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "transfer_id": event_data.get("transfer_id") or event_data.get("id"),
            "amount": event_data.get("amount"),
        }
    )


async def handle_petty_cash_replenished_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"PettyCashReplenishedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "fund_id": event_data.get("fund_id") or event_data.get("id"),
            "amount": event_data.get("amount"),
        }
    )


async def handle_coa_unlocked_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"COAUnlockedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "coa_id": event_data.get("coa_id") or event_data.get("id"),
        }
    )


async def handle_bank_transaction_recorded_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"BankTransactionRecordedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "transaction_id": event_data.get("transaction_id") or event_data.get("id"),
        }
    )


async def handle_payslip_generated_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"PayslipGeneratedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "payslip_id": event_data.get("payslip_id") or event_data.get("id"),
            "employee_id": event_data.get("employee_id"),
        }
    )


async def handle_account_created_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"AccountCreatedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "account_id": event_data.get("account_id") or event_data.get("id"),
            "account_code": event_data.get("account_code"),
        }
    )


async def handle_domain_event_publisher_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"DomainEventPublisher event processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "correlation_id": getattr(envelope, "correlation_id", "N/A"),
        }
    )


async def handle_journal_rejected_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"JournalRejectedEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "journal_id": event_data.get("journal_id") or event_data.get("id"),
            "rejection_reason": event_data.get("rejection_reason"),
        }
    )


async def handle_capital_withdrawal_cancelled_event(envelope: Any) -> None:
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    logger.info(
        f"CapitalWithdrawalCancelledEvent processed",
        extra={
            "event_id": str(getattr(envelope, "event_id", "N/A")),
            "withdrawal_id": event_data.get("withdrawal_id") or event_data.get("id"),
        }
    )


# ============================================================================
# REGISTRATION FUNCTION
# ============================================================================

def register_global_subscribers() -> None:
    """Daftarkan semua handler ke event_handler_registry."""
    
    # Existing handlers
    event_handler_registry.register("WorkOrderCompletedEvent", handle_work_order_completed_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("AccountReactivatedEvent", handle_account_reactivated_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("ProjectActivatedEvent", handle_project_activated_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("IntangibleAssetRevaluatedEvent", handle_intangible_asset_revaluated_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("FakturRejectedEvent", handle_faktur_rejected_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("DividendPaidEvent", handle_dividend_paid_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("TimeEntryApprovedEvent", handle_time_entry_approved_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("BankAccountUpdatedEvent", handle_bank_account_updated_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("RoleRevokedEvent", handle_role_revoked_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("ProductionCompletedEvent", handle_production_completed_event, priority=HandlerPriority.NORMAL)

    # New handlers
    event_handler_registry.register("BankTransferCompletedEvent", handle_bank_transfer_completed_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("PettyCashReplenishedEvent", handle_petty_cash_replenished_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("COAUnlockedEvent", handle_coa_unlocked_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("BankTransactionRecordedEvent", handle_bank_transaction_recorded_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("PayslipGeneratedEvent", handle_payslip_generated_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("AccountCreatedEvent", handle_account_created_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("DomainEventPublisher", handle_domain_event_publisher_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("JournalRejectedEvent", handle_journal_rejected_event, priority=HandlerPriority.NORMAL)
    event_handler_registry.register("CapitalWithdrawalCancelledEvent", handle_capital_withdrawal_cancelled_event, priority=HandlerPriority.NORMAL)

    logger.info("All global event subscribers registered successfully")