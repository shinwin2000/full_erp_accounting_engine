# service_capital.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_capital.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk Capital, Dividend, dan Retained Earnings.
    Mempublikasikan semua event terkait.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import (
    CapitalContributionApprovedEvent,
    CapitalContributionCancelledEvent,
    CapitalContributionPostedEvent,
    CapitalContributionRecordedEvent,
    CapitalWithdrawalApprovedEvent,
    CapitalWithdrawalCancelledEvent,
    CapitalWithdrawalPostedEvent,
    CapitalWithdrawalRecordedEvent,
    DividendApprovedEvent,
    DividendCancelledEvent,
    DividendDeclaredEvent,
    DividendPaidEvent,
    DividendPartiallyPaidEvent,
    RetainedEarningsAdjustedEvent,
    RetainedEarningsTransferEvent,
    RetainedEarningsUpdatedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CapitalContributionRequest:
    legal_entity_id: UUID
    amount: Decimal
    contribution_date: date
    description: str | None = None
    contributor_id: UUID | None = None
    contribution_type: str = "CASH"


@dataclass(kw_only=True)
class CapitalContributionResponse:
    contribution_id: UUID
    legal_entity_id: UUID
    amount: Decimal
    contribution_date: date
    status: str
    created_at: datetime


@dataclass(kw_only=True)
class DividendDeclarationRequest:
    legal_entity_id: UUID
    total_amount: Decimal
    declaration_date: date
    payment_date: date | None = None
    description: str | None = None
    declared_by: UUID | None = None


@dataclass(kw_only=True)
class DividendResponse:
    dividend_id: UUID
    legal_entity_id: UUID
    total_amount: Decimal
    paid_amount: Decimal
    declaration_date: date
    status: str
    created_at: datetime


# ============================================================================
# Exceptions
# ============================================================================


class CapitalServiceError(Exception):
    pass


# ============================================================================
# Main Service
# ============================================================================


class CapitalService:
    """
    Service untuk Capital, Dividend, dan Retained Earnings.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._event_publisher = event_publisher
        self._stats = {
            "contributions": 0,
            "withdrawals": 0,
            "dividends": 0,
            "retained_earnings": 0,
        }
        logger.info("CapitalService initialized")

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
    # Capital Contribution
    # ========================================================================

    async def record_capital_contribution(
        self,
        request: CapitalContributionRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CapitalContributionResponse:
        """Record a capital contribution."""
        contribution_id = uuid4()

        # --- PUBLISH RECORDED EVENT ---
        if self._event_publisher:
            event = CapitalContributionRecordedEvent(
                aggregate_id=contribution_id,
                aggregate_version=1,
                contribution_id=contribution_id,
                legal_entity_id=request.legal_entity_id,
                amount=request.amount,
                contribution_date=request.contribution_date,
                contributor_id=str(request.contributor_id) if request.contributor_id else None,
                recorded_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Contribution {contribution_id}", correlation_id)

        self._stats["contributions"] += 1
        return CapitalContributionResponse(
            contribution_id=contribution_id,
            legal_entity_id=request.legal_entity_id,
            amount=request.amount,
            contribution_date=request.contribution_date,
            status="RECORDED",
            created_at=datetime.now(UTC),
        )

    async def approve_capital_contribution(
        self,
        contribution_id: UUID,
        approved_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Approve a capital contribution."""
        if self._event_publisher:
            event = CapitalContributionApprovedEvent(
                aggregate_id=contribution_id,
                aggregate_version=1,
                contribution_id=contribution_id,
                approved_by=str(approved_by),
                user_id=str(approved_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Contribution {contribution_id} (approve)", correlation_id)

    async def post_capital_contribution(
        self,
        contribution_id: UUID,
        posted_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Post capital contribution to GL."""
        if self._event_publisher:
            event = CapitalContributionPostedEvent(
                aggregate_id=contribution_id,
                aggregate_version=1,
                contribution_id=contribution_id,
                posted_by=str(posted_by),
                user_id=str(posted_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Contribution {contribution_id} (post)", correlation_id)

    async def cancel_capital_contribution(
        self,
        contribution_id: UUID,
        reason: str,
        cancelled_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Cancel a capital contribution."""
        if self._event_publisher:
            event = CapitalContributionCancelledEvent(
                aggregate_id=contribution_id,
                aggregate_version=1,
                contribution_id=contribution_id,
                reason=reason,
                cancelled_by=str(cancelled_by),
                user_id=str(cancelled_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Contribution {contribution_id} (cancel)", correlation_id)

    # ========================================================================
    # Capital Withdrawal
    # ========================================================================

    async def record_capital_withdrawal(
        self,
        legal_entity_id: UUID,
        amount: Decimal,
        withdrawal_date: date,
        description: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Record a capital withdrawal."""
        if self._event_publisher:
            event = CapitalWithdrawalRecordedEvent(
                aggregate_id=uuid4(),
                aggregate_version=1,
                legal_entity_id=legal_entity_id,
                amount=amount,
                withdrawal_date=withdrawal_date,
                recorded_by=str(user_id) if user_id else "system",
                user_id=str(user_id) if user_id else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Withdrawal for {legal_entity_id}", correlation_id)

        self._stats["withdrawals"] += 1

    async def approve_capital_withdrawal(
        self,
        withdrawal_id: UUID,
        approved_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Approve a capital withdrawal."""
        if self._event_publisher:
            event = CapitalWithdrawalApprovedEvent(
                aggregate_id=withdrawal_id,
                aggregate_version=1,
                withdrawal_id=withdrawal_id,
                approved_by=str(approved_by),
                user_id=str(approved_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Withdrawal {withdrawal_id} (approve)", correlation_id)

    async def post_capital_withdrawal(
        self,
        withdrawal_id: UUID,
        posted_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Post capital withdrawal to GL."""
        if self._event_publisher:
            event = CapitalWithdrawalPostedEvent(
                aggregate_id=withdrawal_id,
                aggregate_version=1,
                withdrawal_id=withdrawal_id,
                posted_by=str(posted_by),
                user_id=str(posted_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Withdrawal {withdrawal_id} (post)", correlation_id)

    async def cancel_capital_withdrawal(
        self,
        withdrawal_id: UUID,
        reason: str,
        cancelled_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Cancel a capital withdrawal."""
        if self._event_publisher:
            event = CapitalWithdrawalCancelledEvent(
                aggregate_id=withdrawal_id,
                aggregate_version=1,
                withdrawal_id=withdrawal_id,
                reason=reason,
                cancelled_by=str(cancelled_by),
                user_id=str(cancelled_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Capital Withdrawal {withdrawal_id} (cancel)", correlation_id)

    # ========================================================================
    # Dividend
    # ========================================================================

    async def declare_dividend(
        self,
        request: DividendDeclarationRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> DividendResponse:
        """Declare a dividend."""
        dividend_id = uuid4()

        # --- PUBLISH DECLARED EVENT ---
        if self._event_publisher:
            event = DividendDeclaredEvent(
                aggregate_id=dividend_id,
                aggregate_version=1,
                dividend_id=dividend_id,
                legal_entity_id=request.legal_entity_id,
                total_amount=request.total_amount,
                declaration_date=request.declaration_date,
                payment_date=request.payment_date,
                declared_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Dividend {dividend_id} (declare)", correlation_id)

        self._stats["dividends"] += 1
        return DividendResponse(
            dividend_id=dividend_id,
            legal_entity_id=request.legal_entity_id,
            total_amount=request.total_amount,
            paid_amount=Decimal("0"),
            declaration_date=request.declaration_date,
            status="DECLARED",
            created_at=datetime.now(UTC),
        )

    async def approve_dividend(
        self,
        dividend_id: UUID,
        approved_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Approve a dividend."""
        if self._event_publisher:
            event = DividendApprovedEvent(
                aggregate_id=dividend_id,
                aggregate_version=1,
                dividend_id=dividend_id,
                approved_by=str(approved_by),
                user_id=str(approved_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Dividend {dividend_id} (approve)", correlation_id)

    async def pay_dividend(
        self,
        dividend_id: UUID,
        amount: Decimal,
        paid_by: UUID,
        is_full: bool = True,
        correlation_id: str | None = None,
    ) -> None:
        """Pay dividend (full or partial)."""
        if is_full:
            if self._event_publisher:
                event = DividendPaidEvent(
                    aggregate_id=dividend_id,
                    aggregate_version=1,
                    dividend_id=dividend_id,
                    amount=amount,
                    paid_by=str(paid_by),
                    user_id=str(paid_by),
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Dividend {dividend_id} (full payment)", correlation_id)
        else:
            if self._event_publisher:
                event = DividendPartiallyPaidEvent(
                    aggregate_id=dividend_id,
                    aggregate_version=1,
                    dividend_id=dividend_id,
                    amount=amount,
                    paid_by=str(paid_by),
                    user_id=str(paid_by),
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Dividend {dividend_id} (partial payment)", correlation_id)

    async def cancel_dividend(
        self,
        dividend_id: UUID,
        reason: str,
        cancelled_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Cancel a dividend."""
        if self._event_publisher:
            event = DividendCancelledEvent(
                aggregate_id=dividend_id,
                aggregate_version=1,
                dividend_id=dividend_id,
                reason=reason,
                cancelled_by=str(cancelled_by),
                user_id=str(cancelled_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Dividend {dividend_id} (cancel)", correlation_id)

    # ========================================================================
    # Retained Earnings
    # ========================================================================

    async def adjust_retained_earnings(
        self,
        legal_entity_id: UUID,
        amount: Decimal,
        adjustment_date: date,
        description: str,
        adjusted_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Adjust retained earnings."""
        if self._event_publisher:
            event = RetainedEarningsAdjustedEvent(
                aggregate_id=legal_entity_id,
                aggregate_version=1,
                legal_entity_id=legal_entity_id,
                amount=amount,
                adjustment_date=adjustment_date,
                description=description,
                adjusted_by=str(adjusted_by),
                user_id=str(adjusted_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Retained Earnings {legal_entity_id} (adjust)", correlation_id)

        self._stats["retained_earnings"] += 1

    async def transfer_retained_earnings(
        self,
        from_legal_entity_id: UUID,
        to_legal_entity_id: UUID,
        amount: Decimal,
        transfer_date: date,
        transferred_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Transfer retained earnings between entities."""
        if self._event_publisher:
            event = RetainedEarningsTransferEvent(
                aggregate_id=from_legal_entity_id,
                aggregate_version=1,
                from_legal_entity_id=from_legal_entity_id,
                to_legal_entity_id=to_legal_entity_id,
                amount=amount,
                transfer_date=transfer_date,
                transferred_by=str(transferred_by),
                user_id=str(transferred_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Retained Earnings transfer {from_legal_entity_id}->{to_legal_entity_id}", correlation_id)

    async def update_retained_earnings(
        self,
        legal_entity_id: UUID,
        new_balance: Decimal,
        as_of_date: date,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Update retained earnings balance."""
        if self._event_publisher:
            event = RetainedEarningsUpdatedEvent(
                aggregate_id=legal_entity_id,
                aggregate_version=1,
                legal_entity_id=legal_entity_id,
                new_balance=new_balance,
                as_of_date=as_of_date,
                updated_by=str(updated_by),
                user_id=str(updated_by),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Retained Earnings {legal_entity_id} (update)", correlation_id)

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_capital_service(
    event_publisher: EventPublisherPort | None = None,
) -> CapitalService:
    return CapitalService(event_publisher=event_publisher)


__all__ = [
    "CapitalContributionRequest",
    "CapitalContributionResponse",
    "CapitalService",
    "CapitalServiceError",
    "DividendDeclarationRequest",
    "DividendResponse",
    "create_capital_service",
]