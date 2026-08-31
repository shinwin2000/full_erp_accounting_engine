#!/usr/bin/env python3
"""
Module: financial_obligation.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Kewajiban keuangan (hutang, kontrak) yang timbul dari event.
               Mendefinisikan struktur data untuk kewajiban keuangan seperti
               hutang usaha, hutang pajak, hutang bank, dan kewajiban kontraktual
               lainnya. Mencatat timeline, jumlah, dan status kewajiban.

               All monetary amounts are stored as Decimal with explicit currency
               to satisfy precision checks. Money value objects are used where
               needed for currency-awareness.
"""
# ruff: noqa: UP006, UP035

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


class ObligationType(Enum):
    ACCOUNTS_PAYABLE = auto()
    ACCRUED_EXPENSES = auto()
    DEFERRED_REVENUE = auto()
    VAT_PAYABLE = auto()
    INCOME_TAX_PAYABLE = auto()
    WITHHOLDING_TAX_PAYABLE = auto()
    BANK_LOAN = auto()
    BOND_PAYABLE = auto()
    LEASE_LIABILITY = auto()
    PURCHASE_COMMITMENT = auto()
    PERFORMANCE_OBLIGATION = auto()
    WARRANTY_OBLIGATION = auto()
    OTHER_PAYABLES = auto()


class ObligationStatus(Enum):
    INCURRED = auto()
    CURRENT = auto()
    PAST_DUE = auto()
    PARTIALLY_PAID = auto()
    SETTLED = auto()
    CANCELLED = auto()
    WRITTEN_OFF = auto()


@dataclass(frozen=True)
class PaymentSchedule:
    """
    Payment schedule for a financial obligation.

    Monetary amounts are stored as Decimal with explicit currency
    to satisfy precision checks. The remaining amount is exposed as Money
    for compatibility with other domain objects.
    """

    due_date: datetime
    amount: Decimal
    currency: str = "IDR"
    paid_amount: Decimal = field(default_factory=lambda: Decimal(0))
    paid_at: datetime | None = None
    payment_reference: str | None = None

    @property
    def is_paid(self) -> bool:
        return self.paid_amount >= self.amount

    @property
    def remaining(self) -> Money:
        remaining = self.amount - self.paid_amount
        return Money(remaining, self.currency)

    def record_payment(self, amount: Money, reference: str, paid_at: datetime) -> PaymentSchedule:
        if amount.currency != self.currency:
            raise ValueError(f"Currency mismatch: {amount.currency}")
        new_paid = self.paid_amount + amount.amount
        return PaymentSchedule(
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=new_paid,
            paid_at=paid_at,
            payment_reference=reference,
        )


@dataclass(frozen=True)
class FinancialObligation:
    """
    Financial obligation entity.

    All monetary amounts use Money value object (Decimal internally).
    """

    obligation_id: UUID
    obligation_type: ObligationType
    source_event_id: UUID
    legal_entity_id: UUID
    counterparty_id: UUID | None
    original_amount: Money
    outstanding_amount: Money
    incurred_date: datetime
    due_date: datetime | None
    status: ObligationStatus
    description: str
    contract_reference: str | None = None
    interest_rate: Decimal | None = None
    payment_schedule: list[PaymentSchedule] = field(default_factory=list)
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.obligation_id}|{self.obligation_type.value}|{self.source_event_id}|"
            f"{self.legal_entity_id}|{self.original_amount.amount}|{self.outstanding_amount.amount}|"
            f"{self.status.value}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")
        if self.incurred_date.tzinfo is None:
            object.__setattr__(self, "incurred_date", self.incurred_date.replace(tzinfo=UTC))
        if self.due_date and self.due_date.tzinfo is None:
            object.__setattr__(self, "due_date", self.due_date.replace(tzinfo=UTC))

    @property
    def is_overdue(self) -> bool:
        if self.due_date and self.status not in (
            ObligationStatus.SETTLED,
            ObligationStatus.CANCELLED,
        ):
            return datetime.now(UTC) > self.due_date
        return False

    @property
    def days_overdue(self) -> int:
        if self.is_overdue and self.due_date:
            return (datetime.now(UTC) - self.due_date).days
        return 0

    @property
    def is_fully_settled(self) -> bool:
        return self.status == ObligationStatus.SETTLED or self.outstanding_amount.amount <= 0

    def record_payment(
        self, amount: Money, payment_reference: str, paid_at: datetime
    ) -> FinancialObligation:
        if amount.currency != self.outstanding_amount.currency:
            raise ValueError(f"Currency mismatch: {amount.currency}")
        new_outstanding = self.outstanding_amount.amount - amount.amount
        new_schedule = list(self.payment_schedule)
        for i, item in enumerate(new_schedule):
            if not item.is_paid:
                updated_item = item.record_payment(amount, payment_reference, paid_at)
                new_schedule[i] = updated_item
                break
        new_status = (
            ObligationStatus.SETTLED if new_outstanding <= 0 else ObligationStatus.PARTIALLY_PAID
        )
        return FinancialObligation(
            obligation_id=self.obligation_id,
            obligation_type=self.obligation_type,
            source_event_id=self.source_event_id,
            legal_entity_id=self.legal_entity_id,
            counterparty_id=self.counterparty_id,
            original_amount=self.original_amount,
            outstanding_amount=Money(new_outstanding, amount.currency),
            incurred_date=self.incurred_date,
            due_date=self.due_date,
            status=new_status,
            description=self.description,
            contract_reference=self.contract_reference,
            interest_rate=self.interest_rate,
            payment_schedule=new_schedule,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            cryptographic_hash=self.cryptographic_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": str(self.obligation_id),
            "obligation_type": self.obligation_type.name,
            "source_event_id": str(self.source_event_id),
            "legal_entity_id": str(self.legal_entity_id),
            "counterparty_id": str(self.counterparty_id) if self.counterparty_id else None,
            "original_amount": str(self.original_amount.amount),
            "original_currency": self.original_amount.currency,
            "outstanding_amount": str(self.outstanding_amount.amount),
            "outstanding_currency": self.outstanding_amount.currency,
            "incurred_date": self.incurred_date.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status.name,
            "description": self.description,
            "contract_reference": self.contract_reference,
            "notes": self.notes[:200],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class _FallbackObligationStorage:
    def __init__(self):
        self._obligations: dict[UUID, dict[str, Any]] = {}

    def save(self, obligation: FinancialObligation) -> None:
        self._obligations[obligation.obligation_id] = obligation.to_dict()

    def get(self, obligation_id: UUID) -> dict[str, Any] | None:
        return self._obligations.get(obligation_id)

    def get_all(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        return [
            o
            for o in self._obligations.values()
            if o.get("legal_entity_id") == str(legal_entity_id)
        ]


class FinancialObligationService:
    _instance: FinancialObligationService | None = None
    _lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> FinancialObligationService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._storage = _FallbackObligationStorage()
        self._cache: dict[UUID, FinancialObligation] = {}

    def create_obligation(
        self,
        obligation_type: ObligationType,
        source_event_id: UUID,
        legal_entity_id: UUID,
        amount: Money,
        incurred_date: datetime,
        due_date: datetime | None,
        description: str,
        counterparty_id: UUID | None = None,
        contract_reference: str | None = None,
        payment_schedule: list[PaymentSchedule] | None = None,
    ) -> FinancialObligation:
        obligation = FinancialObligation(
            obligation_id=uuid4(),
            obligation_type=obligation_type,
            source_event_id=source_event_id,
            legal_entity_id=legal_entity_id,
            counterparty_id=counterparty_id,
            original_amount=amount,
            outstanding_amount=amount,
            incurred_date=incurred_date,
            due_date=due_date,
            status=ObligationStatus.INCURRED,
            description=description,
            contract_reference=contract_reference,
            payment_schedule=payment_schedule or [],
            cryptographic_hash="",
        )
        obligation = FinancialObligation(
            obligation_id=obligation.obligation_id,
            obligation_type=obligation.obligation_type,
            source_event_id=obligation.source_event_id,
            legal_entity_id=obligation.legal_entity_id,
            counterparty_id=obligation.counterparty_id,
            original_amount=obligation.original_amount,
            outstanding_amount=obligation.outstanding_amount,
            incurred_date=obligation.incurred_date,
            due_date=obligation.due_date,
            status=obligation.status,
            description=obligation.description,
            contract_reference=obligation.contract_reference,
            interest_rate=obligation.interest_rate,
            payment_schedule=obligation.payment_schedule,
            notes=obligation.notes,
            created_at=obligation.created_at,
            updated_at=obligation.updated_at,
            cryptographic_hash=obligation.compute_hash(),
        )
        self._storage.save(obligation)
        self._cache[obligation.obligation_id] = obligation
        logger.info(f"Financial obligation created: {obligation_type.name} - {amount}")
        return obligation

    def get_obligation(self, obligation_id: UUID) -> FinancialObligation | None:
        if obligation_id in self._cache:
            return self._cache[obligation_id]
        data = self._storage.get(obligation_id)
        if not data:
            return None
        obligation = self._reconstruct(data)
        self._cache[obligation_id] = obligation
        return obligation

    def _reconstruct(self, data: dict[str, Any]) -> FinancialObligation:
        return FinancialObligation(
            obligation_id=UUID(data["obligation_id"]),
            obligation_type=ObligationType[data["obligation_type"]],
            source_event_id=UUID(data["source_event_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            counterparty_id=UUID(data["counterparty_id"]) if data.get("counterparty_id") else None,
            original_amount=Money(
                Decimal(data["original_amount"]), data.get("original_currency", "IDR")
            ),
            outstanding_amount=Money(
                Decimal(data["outstanding_amount"]), data.get("outstanding_currency", "IDR")
            ),
            incurred_date=datetime.fromisoformat(data["incurred_date"]),
            due_date=datetime.fromisoformat(data["due_date"]) if data.get("due_date") else None,
            status=ObligationStatus[data["status"]],
            description=data["description"],
            contract_reference=data.get("contract_reference"),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def get_outstanding_obligations(self, legal_entity_id: UUID) -> list[FinancialObligation]:
        result = []
        for data in self._storage.get_all(legal_entity_id):
            ob = self._reconstruct(data)
            if not ob.is_fully_settled:
                result.append(ob)
        return result

    def get_overdue_obligations(self, legal_entity_id: UUID) -> list[FinancialObligation]:
        result = []
        for data in self._storage.get_all(legal_entity_id):
            ob = self._reconstruct(data)
            if ob.is_overdue and not ob.is_fully_settled:
                result.append(ob)
        return result

    def get_aging_summary(self, legal_entity_id: UUID) -> dict[str, Decimal]:
        today = datetime.now(UTC)
        aging = {
            "current": Decimal(0),
            "1_30_days": Decimal(0),
            "31_60_days": Decimal(0),
            "61_90_days": Decimal(0),
            "over_90_days": Decimal(0),
        }
        for ob in self.get_outstanding_obligations(legal_entity_id):
            if not ob.due_date:
                aging["current"] += ob.outstanding_amount.amount
                continue
            days_overdue = (today - ob.due_date).days if ob.due_date < today else 0
            if days_overdue <= 0:
                aging["current"] += ob.outstanding_amount.amount
            elif days_overdue <= 30:
                aging["1_30_days"] += ob.outstanding_amount.amount
            elif days_overdue <= 60:
                aging["31_60_days"] += ob.outstanding_amount.amount
            elif days_overdue <= 90:
                aging["61_90_days"] += ob.outstanding_amount.amount
            else:
                aging["over_90_days"] += ob.outstanding_amount.amount
        return aging

    def get_total_outstanding(self, legal_entity_id: UUID) -> Money:
        total = sum(
            (ob.outstanding_amount.amount for ob in self.get_outstanding_obligations(legal_entity_id)),
            Decimal(0)
        )
        return Money(total, "IDR")

    def update_obligation(self, obligation: FinancialObligation) -> None:
        self._storage.save(obligation)
        self._cache[obligation.obligation_id] = obligation

    def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        all_obs = [self._reconstruct(d) for d in self._storage.get_all(legal_entity_id)]
        total = len(all_obs)
        if total == 0:
            return {"total_obligations": 0}
        by_status: dict[str, int] = {}
        for o in all_obs:
            by_status[o.status.name] = by_status.get(o.status.name, 0) + 1
        return {
            "legal_entity_id": str(legal_entity_id),
            "total_obligations": total,
            "by_status": by_status,
            "total_outstanding": str(self.get_total_outstanding(legal_entity_id).amount),
            "overdue_count": len([o for o in all_obs if o.is_overdue]),
        }


_financial_obligation_service_instance: FinancialObligationService | None = None


def get_financial_obligation_service() -> FinancialObligationService:
    global _financial_obligation_service_instance
    if _financial_obligation_service_instance is None:
        _financial_obligation_service_instance = FinancialObligationService()
    return _financial_obligation_service_instance


__all__ = [
    "FinancialObligation",
    "FinancialObligationService",
    "ObligationStatus",
    "ObligationType",
    "PaymentSchedule",
    "get_financial_obligation_service",
]
