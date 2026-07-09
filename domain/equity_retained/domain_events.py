#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Equity & Retained Earnings
Responsibility: Domain events untuk Equity & Retained Earnings aggregates.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.equity_retained.capital_contribution_entity import (
    CapitalContributionEntity,
)
from domain.equity_retained.capital_withdrawal_entity import (
    CapitalWithdrawalEntity,
)
from domain.equity_retained.dividend_declaration_entity import (
    DividendDeclarationEntity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    # Capital Contribution events
    CAPITAL_CONTRIBUTION_RECORDED = "capital_contribution_recorded"
    CAPITAL_CONTRIBUTION_APPROVED = "capital_contribution_approved"
    CAPITAL_CONTRIBUTION_POSTED = "capital_contribution_posted"
    CAPITAL_CONTRIBUTION_CANCELLED = "capital_contribution_cancelled"

    # Capital Withdrawal events
    CAPITAL_WITHDRAWAL_RECORDED = "capital_withdrawal_recorded"
    CAPITAL_WITHDRAWAL_APPROVED = "capital_withdrawal_approved"
    CAPITAL_WITHDRAWAL_POSTED = "capital_withdrawal_posted"
    CAPITAL_WITHDRAWAL_CANCELLED = "capital_withdrawal_cancelled"

    # Retained Earnings events
    RETAINED_EARNINGS_UPDATED = "retained_earnings_updated"
    RETAINED_EARNINGS_ADJUSTED = "retained_earnings_adjusted"
    RETAINED_EARNINGS_TRANSFER = "retained_earnings_transfer"

    # Dividend events
    DIVIDEND_DECLARED = "dividend_declared"
    DIVIDEND_APPROVED = "dividend_approved"
    DIVIDEND_PAID = "dividend_paid"
    DIVIDEND_PARTIALLY_PAID = "dividend_partially_paid"
    DIVIDEND_CANCELLED = "dividend_cancelled"

    def display_name(self) -> str:
        names = {
            DomainEventType.CAPITAL_CONTRIBUTION_RECORDED: "Capital Contribution Recorded",
            DomainEventType.CAPITAL_CONTRIBUTION_APPROVED: "Capital Contribution Approved",
            DomainEventType.CAPITAL_CONTRIBUTION_POSTED: "Capital Contribution Posted",
            DomainEventType.CAPITAL_CONTRIBUTION_CANCELLED: "Capital Contribution Cancelled",
            DomainEventType.CAPITAL_WITHDRAWAL_RECORDED: "Capital Withdrawal Recorded",
            DomainEventType.CAPITAL_WITHDRAWAL_APPROVED: "Capital Withdrawal Approved",
            DomainEventType.CAPITAL_WITHDRAWAL_POSTED: "Capital Withdrawal Posted",
            DomainEventType.CAPITAL_WITHDRAWAL_CANCELLED: "Capital Withdrawal Cancelled",
            DomainEventType.RETAINED_EARNINGS_UPDATED: "Retained Earnings Updated",
            DomainEventType.RETAINED_EARNINGS_ADJUSTED: "Retained Earnings Adjusted",
            DomainEventType.RETAINED_EARNINGS_TRANSFER: "Retained Earnings Transfer",
            DomainEventType.DIVIDEND_DECLARED: "Dividend Declared",
            DomainEventType.DIVIDEND_APPROVED: "Dividend Approved",
            DomainEventType.DIVIDEND_PAID: "Dividend Paid",
            DomainEventType.DIVIDEND_PARTIALLY_PAID: "Dividend Partially Paid",
            DomainEventType.DIVIDEND_CANCELLED: "Dividend Cancelled",
        }
        return names.get(self, self.value)


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event di Equity & Retained Earnings.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_type: Tipe agregat (default "EquityAggregate").
        aggregate_version: Versi agregat saat event terjadi.
        occurred_at: Waktu kejadian (UTC).
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
        causation_id: ID penyebab event (opsional).
    """
    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_type: str
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "EquityAggregate"),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# Capital Contribution Events
# ============================================================================


@dataclass(frozen=True)
class CapitalContributionRecordedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika kontribusi modal baru dicatat.

    Attributes:
        aggregate_id: ID agregat kontribusi modal.
        aggregate_version: Versi agregat.
        contribution: Entity CapitalContribution.
        recorded_by: User ID pencatat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        contribution: CapitalContributionEntity,
        recorded_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "contribution_id": str(contribution.contribution_id),
            "contribution_number": contribution.contribution_number,
            "contribution_type": contribution.contribution_type.value,
            "shareholder_id": str(contribution.shareholder_id),
            "shareholder_name": contribution.shareholder_name,
            "amount": str(contribution.amount),
            "currency": contribution.currency,
            "contribution_date": contribution.contribution_date.isoformat(),
            "share_percentage": str(contribution.share_percentage)
            if contribution.share_percentage
            else None,
            "status": contribution.status.value,
            "recorded_by": recorded_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_CONTRIBUTION_RECORDED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CapitalContributionApprovedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika kontribusi modal disetujui.

    Attributes:
        aggregate_id: ID agregat kontribusi modal.
        aggregate_version: Versi agregat.
        contribution: Entity CapitalContribution.
        approved_by: User ID yang menyetujui.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        contribution: CapitalContributionEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "contribution_id": str(contribution.contribution_id),
            "contribution_number": contribution.contribution_number,
            "amount": str(contribution.amount),
            "approved_by": approved_by,
            "approval_reference": contribution.approval_reference,
            "approved_at": contribution.approved_at.isoformat()
            if contribution.approved_at
            else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_CONTRIBUTION_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CapitalContributionPostedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika kontribusi modal diposting ke GL.

    Attributes:
        aggregate_id: ID agregat kontribusi modal.
        aggregate_version: Versi agregat.
        contribution: Entity CapitalContribution.
        posted_by: User ID yang memposting.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        contribution: CapitalContributionEntity,
        posted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "contribution_id": str(contribution.contribution_id),
            "contribution_number": contribution.contribution_number,
            "amount": str(contribution.amount),
            "posted_by": posted_by,
            "posted_at": contribution.posted_at.isoformat() if contribution.posted_at else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_CONTRIBUTION_POSTED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CapitalContributionCancelledEvent(DomainEvent):
    """
    Event yang diterbitkan ketika kontribusi modal dibatalkan.

    Attributes:
        aggregate_id: ID agregat kontribusi modal.
        aggregate_version: Versi agregat.
        contribution: Entity CapitalContribution.
        cancelled_by: User ID pembatalan.
        reason: Alasan pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        contribution: CapitalContributionEntity,
        cancelled_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "contribution_id": str(contribution.contribution_id),
            "contribution_number": contribution.contribution_number,
            "amount": str(contribution.amount),
            "cancelled_by": cancelled_by,
            "reason": reason,
            "cancelled_at": contribution.cancelled_at.isoformat()
            if contribution.cancelled_at
            else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_CONTRIBUTION_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Capital Withdrawal Events
# ============================================================================


@dataclass(frozen=True)
class CapitalWithdrawalRecordedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika penarikan modal baru dicatat.

    Attributes:
        aggregate_id: ID agregat penarikan modal.
        aggregate_version: Versi agregat.
        withdrawal: Entity CapitalWithdrawal.
        recorded_by: User ID pencatat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        withdrawal: CapitalWithdrawalEntity,
        recorded_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "withdrawal_id": str(withdrawal.withdrawal_id),
            "withdrawal_number": withdrawal.withdrawal_number,
            "withdrawal_type": withdrawal.withdrawal_type.value,
            "shareholder_id": str(withdrawal.shareholder_id),
            "shareholder_name": withdrawal.shareholder_name,
            "amount": str(withdrawal.amount),
            "net_amount": str(withdrawal.net_amount),
            "currency": withdrawal.currency,
            "withdrawal_date": withdrawal.withdrawal_date.isoformat(),
            "tax_withheld_amount": str(withdrawal.tax_withheld_amount),
            "status": withdrawal.status.value,
            "recorded_by": recorded_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_WITHDRAWAL_RECORDED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CapitalWithdrawalApprovedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika penarikan modal disetujui.

    Attributes:
        aggregate_id: ID agregat penarikan modal.
        aggregate_version: Versi agregat.
        withdrawal: Entity CapitalWithdrawal.
        approved_by: User ID yang menyetujui.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        withdrawal: CapitalWithdrawalEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "withdrawal_id": str(withdrawal.withdrawal_id),
            "withdrawal_number": withdrawal.withdrawal_number,
            "amount": str(withdrawal.amount),
            "approved_by": approved_by,
            "approval_reference": withdrawal.approval_reference,
            "approved_at": withdrawal.approved_at.isoformat() if withdrawal.approved_at else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_WITHDRAWAL_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CapitalWithdrawalPostedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika penarikan modal diposting ke GL.

    Attributes:
        aggregate_id: ID agregat penarikan modal.
        aggregate_version: Versi agregat.
        withdrawal: Entity CapitalWithdrawal.
        posted_by: User ID yang memposting.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        withdrawal: CapitalWithdrawalEntity,
        posted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "withdrawal_id": str(withdrawal.withdrawal_id),
            "withdrawal_number": withdrawal.withdrawal_number,
            "amount": str(withdrawal.amount),
            "net_amount": str(withdrawal.net_amount),
            "posted_by": posted_by,
            "posted_at": withdrawal.posted_at.isoformat() if withdrawal.posted_at else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_WITHDRAWAL_POSTED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CapitalWithdrawalCancelledEvent(DomainEvent):
    """
    Event yang diterbitkan ketika penarikan modal dibatalkan.

    Attributes:
        aggregate_id: ID agregat penarikan modal.
        aggregate_version: Versi agregat.
        withdrawal: Entity CapitalWithdrawal.
        cancelled_by: User ID pembatalan.
        reason: Alasan pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        withdrawal: CapitalWithdrawalEntity,
        cancelled_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "withdrawal_id": str(withdrawal.withdrawal_id),
            "withdrawal_number": withdrawal.withdrawal_number,
            "amount": str(withdrawal.amount),
            "cancelled_by": cancelled_by,
            "reason": reason,
            "cancelled_at": withdrawal.cancelled_at.isoformat()
            if withdrawal.cancelled_at
            else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CAPITAL_WITHDRAWAL_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Retained Earnings Events
# ============================================================================


@dataclass(frozen=True)
class RetainedEarningsUpdatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika saldo laba ditahan diperbarui.

    Attributes:
        aggregate_id: ID agregat laba ditahan.
        aggregate_version: Versi agregat.
        legal_entity_id: ID entitas legal.
        period: Periode akuntansi.
        net_income: Laba bersih periode.
        new_balance: Saldo baru laba ditahan.
        updated_by: User ID pembaru.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        period: str,
        net_income: Decimal,
        new_balance: Decimal,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period": period,
            "net_income": str(net_income),
            "new_balance": str(new_balance),
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.RETAINED_EARNINGS_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class RetainedEarningsAdjustedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika laba ditahan disesuaikan (koreksi).

    Attributes:
        aggregate_id: ID agregat laba ditahan.
        aggregate_version: Versi agregat.
        legal_entity_id: ID entitas legal.
        period: Periode akuntansi.
        adjustment: Jumlah penyesuaian.
        description: Deskripsi penyesuaian.
        new_balance: Saldo baru laba ditahan.
        updated_by: User ID pembaru.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        period: str,
        adjustment: Decimal,
        description: str,
        new_balance: Decimal,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period": period,
            "adjustment": str(adjustment),
            "description": description,
            "new_balance": str(new_balance),
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.RETAINED_EARNINGS_ADJUSTED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class RetainedEarningsTransferEvent(DomainEvent):
    """
    Event yang diterbitkan ketika terjadi transfer ke/dari laba ditahan.

    Attributes:
        aggregate_id: ID agregat laba ditahan.
        aggregate_version: Versi agregat.
        legal_entity_id: ID entitas legal.
        period: Periode akuntansi.
        amount: Jumlah transfer.
        transfer_type: Jenis transfer (misal "DIVIDEND", "CAPITALIZE").
        new_balance: Saldo baru laba ditahan.
        updated_by: User ID pembaru.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        period: str,
        amount: Decimal,
        transfer_type: str,
        new_balance: Decimal,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period": period,
            "amount": str(amount),
            "transfer_type": transfer_type,
            "new_balance": str(new_balance),
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.RETAINED_EARNINGS_TRANSFER,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Dividend Events
# ============================================================================


@dataclass(frozen=True)
class DividendDeclaredEvent(DomainEvent):
    """
    Event yang diterbitkan ketika dividen dideklarasikan.

    Attributes:
        aggregate_id: ID agregat dividen.
        aggregate_version: Versi agregat.
        dividend: Entity DividendDeclaration.
        declared_by: User ID yang mendeklarasikan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        dividend: DividendDeclarationEntity,
        declared_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "dividend_id": str(dividend.dividend_id),
            "dividend_number": dividend.dividend_number,
            "dividend_type": dividend.dividend_type.value,
            "total_amount": str(dividend.total_amount),
            "currency": dividend.currency,
            "declaration_date": dividend.declaration_date.isoformat(),
            "record_date": dividend.record_date.isoformat(),
            "payment_date": dividend.payment_date.isoformat(),
            "shareholder_count": len(dividend.allocations),
            "status": dividend.status.value,
            "declared_by": declared_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DIVIDEND_DECLARED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class DividendApprovedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika dividen disetujui.

    Attributes:
        aggregate_id: ID agregat dividen.
        aggregate_version: Versi agregat.
        dividend: Entity DividendDeclaration.
        approved_by: User ID yang menyetujui.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        dividend: DividendDeclarationEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "dividend_id": str(dividend.dividend_id),
            "dividend_number": dividend.dividend_number,
            "total_amount": str(dividend.total_amount),
            "approved_by": approved_by,
            "approved_at": dividend.approved_at.isoformat() if dividend.approved_at else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DIVIDEND_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class DividendPaidEvent(DomainEvent):
    """
    Event yang diterbitkan ketika dividen dibayar (sebagian atau penuh).

    Attributes:
        aggregate_id: ID agregat dividen.
        aggregate_version: Versi agregat.
        dividend: Entity DividendDeclaration.
        paid_amount: Jumlah yang dibayarkan.
        paid_by: User ID pembayar.
        total_paid: Total yang sudah dibayar (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        dividend: DividendDeclarationEntity,
        paid_amount: Decimal,
        paid_by: str,
        total_paid: Decimal | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "dividend_id": str(dividend.dividend_id),
            "dividend_number": dividend.dividend_number,
            "paid_amount": str(paid_amount),
            "total_paid": str(total_paid) if total_paid else str(dividend.total_paid),
            "paid_by": paid_by,
            "paid_at": dividend.paid_at.isoformat() if dividend.paid_at else None,
            "status": dividend.status.value,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DIVIDEND_PAID,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class DividendPartiallyPaidEvent(DomainEvent):
    """
    Event yang diterbitkan ketika dividen dibayar sebagian (masih ada sisa).

    Attributes:
        aggregate_id: ID agregat dividen.
        aggregate_version: Versi agregat.
        dividend: Entity DividendDeclaration.
        paid_amount: Jumlah yang dibayarkan.
        paid_by: User ID pembayar.
        total_paid: Total yang sudah dibayar.
        unpaid_amount: Sisa yang belum dibayar.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        dividend: DividendDeclarationEntity,
        paid_amount: Decimal,
        paid_by: str,
        total_paid: Decimal,
        unpaid_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "dividend_id": str(dividend.dividend_id),
            "dividend_number": dividend.dividend_number,
            "paid_amount": str(paid_amount),
            "total_paid": str(total_paid),
            "unpaid_amount": str(unpaid_amount),
            "paid_by": paid_by,
            "paid_at": dividend.paid_at.isoformat() if dividend.paid_at else None,
            "status": dividend.status.value,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DIVIDEND_PARTIALLY_PAID,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class DividendCancelledEvent(DomainEvent):
    """
    Event yang diterbitkan ketika dividen dibatalkan.

    Attributes:
        aggregate_id: ID agregat dividen.
        aggregate_version: Versi agregat.
        dividend: Entity DividendDeclaration.
        cancelled_by: User ID pembatalan.
        reason: Alasan pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        dividend: DividendDeclarationEntity,
        cancelled_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "dividend_id": str(dividend.dividend_id),
            "dividend_number": dividend.dividend_number,
            "total_amount": str(dividend.total_amount),
            "cancelled_by": cancelled_by,
            "reason": reason,
            "cancelled_at": dividend.cancelled_at.isoformat() if dividend.cancelled_at else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.DIVIDEND_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_type="EquityAggregate",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Domain Event Publisher
# ============================================================================


class DomainEventPublisher:
    """
    Publisher untuk domain event Equity & Retained Earnings.
    Menyimpan event yang dipublikasikan untuk keperluan testing/replay.
    """
    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        """Publikasikan satu event."""
        cls._published_events.append(event)
        logger.info(f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}")

    @classmethod
    async def publish_many(cls, events: list[DomainEvent]) -> None:
        """Publikasikan banyak event."""
        for event in events:
            await cls.publish(event)

    @classmethod
    def get_published_events(cls) -> list[DomainEvent]:
        """Dapatkan semua event yang sudah dipublikasikan."""
        return cls._published_events.copy()

    @classmethod
    def clear(cls) -> None:
        """Hapus semua event yang sudah dipublikasikan."""
        cls._published_events.clear()


# ============================================================================
# Helper Functions
# ============================================================================


def deserialize_domain_event(json_str: str) -> DomainEvent:
    """
    Deserialize JSON string menjadi DomainEvent.

    Args:
        json_str: String JSON yang berisi event.

    Returns:
        DomainEvent: Objek DomainEvent yang sudah direkonstruksi.
    """
    data = json.loads(json_str)
    event_type = DomainEventType(data["event_type"])
    return DomainEvent.from_dict(data)


def serialize_domain_event(event: DomainEvent) -> str:
    """
    Serialize DomainEvent menjadi JSON string.

    Args:
        event: DomainEvent yang akan diserialisasi.

    Returns:
        str: String JSON representasi event.
    """
    return event.to_json()


__all__ = [
    "CapitalContributionApprovedEvent",
    "CapitalContributionCancelledEvent",
    "CapitalContributionPostedEvent",
    "CapitalContributionRecordedEvent",
    "CapitalWithdrawalApprovedEvent",
    "CapitalWithdrawalCancelledEvent",
    "CapitalWithdrawalPostedEvent",
    "CapitalWithdrawalRecordedEvent",
    "DividendApprovedEvent",
    "DividendCancelledEvent",
    "DividendDeclaredEvent",
    "DividendPaidEvent",
    "DividendPartiallyPaidEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "RetainedEarningsAdjustedEvent",
    "RetainedEarningsTransferEvent",
    "RetainedEarningsUpdatedEvent",
    "deserialize_domain_event",
    "serialize_domain_event",
]