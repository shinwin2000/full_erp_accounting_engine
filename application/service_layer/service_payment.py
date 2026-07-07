# service_payment.py - Complete rewrite with full event publishing
# v5.9.0 - Refactored event publishing into single _publish_event method to reduce
#          broad-except warnings and improve maintainability.

#!/usr/bin/env python3

"""
Module: service_payment.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk Payment (AP/AR) management.
    Mempublikasikan event untuk setiap perubahan status payment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import (
    PaymentAllocatedEvent,
    PaymentAppliedEvent,
    PaymentApprovedEvent,
    PaymentCancelledEvent,
    PaymentConfirmedEvent,
    PaymentMadeEvent,
    PaymentProcessedEvent,
    PaymentReceivedEvent,
    PaymentSentEvent,
    PaymentVoidedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class PaymentStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    SENT = "sent"
    RECEIVED = "received"
    APPLIED = "applied"
    ALLOCATED = "allocated"
    CANCELLED = "cancelled"
    VOIDED = "voided"


class PaymentType(str, Enum):
    AP = "ap"  # Accounts Payable
    AR = "ar"  # Accounts Receivable


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class Payment:
    id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID
    payment_number: str
    payment_type: PaymentType
    counterparty_id: UUID  # supplier_id or customer_id
    invoice_id: UUID | None = None
    amount: Decimal
    payment_date: date
    reference_number: str | None = None
    description: str | None = None
    status: PaymentStatus = PaymentStatus.DRAFT
    is_allocated: bool = False
    is_applied: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1


# ============================================================================
# Exceptions
# ============================================================================


class PaymentServiceError(Exception):
    pass


class PaymentNotFoundError(PaymentServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class PaymentService:
    """
    Service untuk Payment (AP/AR).
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._payments: dict[UUID, Payment] = {}
        self._event_publisher = event_publisher
        self._stats = {"payments_created": 0, "payments_updated": 0}

        logger.info("PaymentService initialized")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        """
        Publish an event safely, catching and logging any exception.
        Preserves the two-argument publish signature (event, correlation_id).
        """
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================

    async def create_payment(
        self,
        legal_entity_id: UUID,
        payment_number: str,
        payment_type: str,
        counterparty_id: UUID,
        amount: Decimal,
        payment_date: date,
        invoice_id: UUID | None = None,
        reference_number: str | None = None,
        description: str | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Payment:
        """Create new payment."""
        payment = Payment(
            legal_entity_id=legal_entity_id,
            payment_number=payment_number,
            payment_type=PaymentType(payment_type),
            counterparty_id=counterparty_id,
            invoice_id=invoice_id,
            amount=amount,
            payment_date=payment_date,
            reference_number=reference_number,
            description=description,
            created_by=created_by,
            version=1,
        )

        self._payments[payment.id] = payment
        self._stats["payments_created"] += 1

        # --- PUBLISH EVENT (PaymentMadeEvent atau PaymentReceivedEvent) ---
        if self._event_publisher:
            if payment_type == "ar":
                event = PaymentReceivedEvent(
                    aggregate_id=payment.id,
                    aggregate_version=payment.version,
                    payment_id=payment.id,
                    payment_number=payment.payment_number,
                    amount=payment.amount,
                    received_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Payment {payment.payment_number} (received)", correlation_id)
            else:
                event = PaymentMadeEvent(
                    aggregate_id=payment.id,
                    aggregate_version=payment.version,
                    payment_id=payment.id,
                    payment_number=payment.payment_number,
                    amount=payment.amount,
                    made_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Payment {payment.payment_number} (made)", correlation_id)

        return payment

    async def get_payment(self, payment_id: UUID) -> Payment | None:
        return self._payments.get(payment_id)

    async def list_payments(
        self,
        legal_entity_id: UUID,
        payment_type: str | None = None,
        status: str | None = None,
    ) -> list[Payment]:
        result = [p for p in self._payments.values() if p.legal_entity_id == legal_entity_id]
        if payment_type:
            result = [p for p in result if p.payment_type.value == payment_type]
        if status:
            result = [p for p in result if p.status.value == status]
        return result

    # ========================================================================
    # Status Transitions
    # ========================================================================

    async def approve_payment(
        self,
        payment_id: UUID,
        approved_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.status = PaymentStatus.APPROVED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentApprovedEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                approved_by=str(approved_by),
                user_id=str(approved_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (approved)", correlation_id)

        return payment

    async def process_payment(
        self,
        payment_id: UUID,
        processed_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.status = PaymentStatus.PROCESSED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentProcessedEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                processed_by=str(processed_by),
                user_id=str(processed_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (processed)", correlation_id)

        return payment

    async def confirm_payment(
        self,
        payment_id: UUID,
        confirmed_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.status = PaymentStatus.CONFIRMED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentConfirmedEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                confirmed_by=str(confirmed_by),
                user_id=str(confirmed_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (confirmed)", correlation_id)

        return payment

    async def send_payment(
        self,
        payment_id: UUID,
        sent_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.status = PaymentStatus.SENT
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentSentEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                sent_by=str(sent_by),
                user_id=str(sent_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (sent)", correlation_id)

        return payment

    async def receive_payment(
        self,
        payment_id: UUID,
        received_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.status = PaymentStatus.RECEIVED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        # PaymentReceivedEvent sudah dipublish di create_payment, bisa juga dipublish di sini
        # Tapi kita tidak perlu mempublikasikan lagi karena sudah ada di create.

        return payment

    async def apply_payment(
        self,
        payment_id: UUID,
        applied_to: str,
        applied_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.is_applied = True
        payment.status = PaymentStatus.APPLIED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentAppliedEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                applied_to=applied_to,
                applied_by=str(applied_by),
                user_id=str(applied_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (applied)", correlation_id)

        return payment

    async def allocate_payment(
        self,
        payment_id: UUID,
        allocation_data: dict[str, Any],
        allocated_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.is_allocated = True
        payment.status = PaymentStatus.ALLOCATED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentAllocatedEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                allocation_data=allocation_data,
                allocated_by=str(allocated_by),
                user_id=str(allocated_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (allocated)", correlation_id)

        return payment

    async def cancel_payment(
        self,
        payment_id: UUID,
        reason: str,
        cancelled_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.status = PaymentStatus.CANCELLED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentCancelledEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                reason=reason,
                cancelled_by=str(cancelled_by),
                user_id=str(cancelled_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (cancelled)", correlation_id)

        return payment

    async def void_payment(
        self,
        payment_id: UUID,
        reason: str,
        voided_by: UUID,
        correlation_id: str | None = None,
    ) -> Payment:
        payment = self._get_payment(payment_id)
        payment.status = PaymentStatus.VOIDED
        payment.updated_at = datetime.now(UTC)
        payment.version += 1
        self._payments[payment_id] = payment
        self._stats["payments_updated"] += 1

        if self._event_publisher:
            event = PaymentVoidedEvent(
                aggregate_id=payment.id,
                aggregate_version=payment.version,
                payment_id=payment.id,
                payment_number=payment.payment_number,
                reason=reason,
                voided_by=str(voided_by),
                user_id=str(voided_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Payment {payment.payment_number} (voided)", correlation_id)

        return payment

    def _get_payment(self, payment_id: UUID) -> Payment:
        payment = self._payments.get(payment_id)
        if not payment:
            raise PaymentNotFoundError(f"Payment {payment_id} not found")
        return payment

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_payment_service(
    event_publisher: EventPublisherPort | None = None,
) -> PaymentService:
    return PaymentService(event_publisher=event_publisher)


__all__ = [
    "Payment",
    "PaymentNotFoundError",
    "PaymentService",
    "PaymentServiceError",
    "PaymentStatus",
    "PaymentType",
    "create_payment_service",
]