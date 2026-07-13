#!/usr/bin/env python3
"""
Module: vendor_card.py
Layer: 6 - Domain / Subledger AP
Responsibility: Kartu hutang per pemasok (mutasi).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.subledger_ap.aging_bucket_vo import AgingBucket, AgingBucketVO, AgingCalculator
from domain.subledger_ap.invoice_entity import APInvoiceEntity
from domain.subledger_ap.payment_entity import APPaymentEntity

logger = logging.getLogger(__name__)


class MutationType(Enum):
    INVOICE = "invoice"
    PAYMENT = "payment"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    ADJUSTMENT = "adjustment"

    @classmethod
    def from_string(cls, value: str) -> MutationType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.ADJUSTMENT


@dataclass
class Mutation:
    mutation_id: UUID
    mutation_type: MutationType
    reference_id: UUID
    reference_number: str
    date: datetime
    debit: Decimal
    credit: Decimal
    balance: Decimal
    description: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_id": str(self.mutation_id),
            "mutation_type": self.mutation_type.value,
            "reference_id": str(self.reference_id),
            "reference_number": self.reference_number,
            "date": self.date.isoformat(),
            "debit": str(self.debit),
            "credit": str(self.credit),
            "balance": str(self.balance),
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mutation:
        return cls(
            mutation_id=UUID(data["mutation_id"]),
            mutation_type=MutationType.from_string(data["mutation_type"]),
            reference_id=UUID(data["reference_id"]),
            reference_number=data["reference_number"],
            date=datetime.fromisoformat(data["date"]),
            debit=Decimal(data["debit"]),
            credit=Decimal(data["credit"]),
            balance=Decimal(data["balance"]),
            description=data["description"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass
class VendorCard:
    vendor_id: UUID
    vendor_name: str
    legal_entity_id: UUID
    outstanding_balance: Decimal
    currency: str
    mutations: list[Mutation] = field(default_factory=list)
    payment_terms_days: int = 30
    credit_limit: Decimal = Decimal(0)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.outstanding_balance < 0:
            raise ValueError(f"Outstanding balance cannot be negative: {self.outstanding_balance}")
        if self.payment_terms_days < 0:
            raise ValueError(f"Payment terms days cannot be negative: {self.payment_terms_days}")
        if self.credit_limit < 0:
            raise ValueError(f"Credit limit cannot be negative: {self.credit_limit}")
        if self.created_at.tzinfo is None:
            self.created_at = self.created_at.replace(tzinfo=UTC)
        if self.updated_at.tzinfo is None:
            self.updated_at = self.updated_at.replace(tzinfo=UTC)
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")

    def _record_audit(self, action: str, user_id: str, details: dict | None = None) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "user_id": user_id,
                "details": details or {},
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    @classmethod
    def create_from_invoice(cls, invoice: APInvoiceEntity) -> VendorCard:
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.INVOICE,
            reference_id=invoice.invoice_id,
            reference_number=invoice.invoice_number,
            date=invoice.invoice_date,
            debit=invoice.amount,
            credit=Decimal(0),
            balance=invoice.amount,
            description=f"Invoice {invoice.invoice_number}",
            created_at=datetime.now(UTC),
        )
        card = cls(
            vendor_id=invoice.vendor_id,
            vendor_name=invoice.vendor_name,
            legal_entity_id=invoice.legal_entity_id
            if hasattr(invoice, "legal_entity_id")
            else UUID(int=0),
            outstanding_balance=invoice.amount,
            currency=invoice.currency,
            mutations=[mutation],
            payment_terms_days=30,
        )
        # ── AUDIT TRAIL ──
        card._record_audit(
            "CREATE_FROM_INVOICE",
            getattr(invoice, "created_by", "system"),
            {
                "invoice_id": str(invoice.invoice_id),
                "invoice_number": invoice.invoice_number,
                "amount": str(invoice.amount),
                "vendor_id": str(invoice.vendor_id),
            }
        )
        return card

    def add_invoice(self, invoice: APInvoiceEntity) -> VendorCard:
        new_balance = self.outstanding_balance + invoice.amount
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.INVOICE,
            reference_id=invoice.invoice_id,
            reference_number=invoice.invoice_number,
            date=invoice.invoice_date,
            debit=invoice.amount,
            credit=Decimal(0),
            balance=new_balance,
            description=f"Invoice {invoice.invoice_number}",
            created_at=datetime.now(UTC),
        )
        self._record_audit(
            "invoice_added",
            invoice.created_by,
            {"invoice_number": invoice.invoice_number, "amount": str(invoice.amount)},
        )
        return VendorCard(
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=self.mutations + [mutation],
            payment_terms_days=self.payment_terms_days,
            credit_limit=self.credit_limit,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def add_payment(self, payment: APPaymentEntity) -> VendorCard:
        new_balance = max(Decimal(0), self.outstanding_balance - payment.amount)
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.PAYMENT,
            reference_id=payment.payment_id,
            reference_number=payment.payment_number,
            date=payment.payment_date,
            debit=Decimal(0),
            credit=payment.amount,
            balance=new_balance,
            description=f"Payment {payment.payment_number}",
            created_at=datetime.now(UTC),
        )
        self._record_audit(
            "payment_added",
            payment.created_by,
            {"payment_number": payment.payment_number, "amount": str(payment.amount)},
        )
        return VendorCard(
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=self.mutations + [mutation],
            payment_terms_days=self.payment_terms_days,
            credit_limit=self.credit_limit,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def apply_credit_note(
        self, amount: Decimal, credit_note_id: UUID, credit_note_number: str
    ) -> VendorCard:
        new_balance = max(Decimal(0), self.outstanding_balance - amount)
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.CREDIT_NOTE,
            reference_id=credit_note_id,
            reference_number=credit_note_number,
            date=datetime.now(UTC),
            debit=Decimal(0),
            credit=amount,
            balance=new_balance,
            description=f"Credit note {credit_note_number}",
            created_at=datetime.now(UTC),
        )
        self._record_audit(
            "credit_note_applied",
            "system",
            {"credit_note_number": credit_note_number, "amount": str(amount)},
        )
        return VendorCard(
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=self.mutations + [mutation],
            payment_terms_days=self.payment_terms_days,
            credit_limit=self.credit_limit,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def apply_debit_note(
        self, amount: Decimal, debit_note_id: UUID, debit_note_number: str
    ) -> VendorCard:
        new_balance = self.outstanding_balance + amount
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.DEBIT_NOTE,
            reference_id=debit_note_id,
            reference_number=debit_note_number,
            date=datetime.now(UTC),
            debit=amount,
            credit=Decimal(0),
            balance=new_balance,
            description=f"Debit note {debit_note_number}",
            created_at=datetime.now(UTC),
        )
        self._record_audit(
            "debit_note_applied",
            "system",
            {"debit_note_number": debit_note_number, "amount": str(amount)},
        )
        return VendorCard(
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=self.mutations + [mutation],
            payment_terms_days=self.payment_terms_days,
            credit_limit=self.credit_limit,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def adjust_balance(
        self, adjustment_amount: Decimal, reason: str, adjusted_by: str
    ) -> VendorCard:
        new_balance = self.outstanding_balance + adjustment_amount
        if new_balance < 0:
            raise ValueError(f"Adjustment would make balance negative: {new_balance}")
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.ADJUSTMENT,
            reference_id=self.vendor_id,
            reference_number=reason[:50],
            date=datetime.now(UTC),
            debit=adjustment_amount if adjustment_amount > 0 else Decimal(0),
            credit=-adjustment_amount if adjustment_amount < 0 else Decimal(0),
            balance=new_balance,
            description=f"Adjustment: {reason}",
            created_at=datetime.now(UTC),
        )
        self._record_audit(
            "balance_adjusted", adjusted_by, {"reason": reason, "amount": str(adjustment_amount)}
        )
        return VendorCard(
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=self.mutations + [mutation],
            payment_terms_days=self.payment_terms_days,
            credit_limit=self.credit_limit,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def get_aging_bucket(self, as_of: datetime) -> AgingBucketVO:
        total = self.outstanding_balance
        if total == 0:
            return AgingBucketVO(AgingBucket.CURRENT, Decimal(0), self.currency)

        # Simplified: find the oldest unpaid invoice's aging
        oldest_due_date = None
        # In production, would iterate through invoices
        if oldest_due_date:
            bucket = AgingCalculator.calculate_bucket(oldest_due_date, as_of)
            return AgingBucketVO(bucket, total, self.currency)
        return AgingBucketVO(AgingBucket.CURRENT, total, self.currency)

    def get_mutations_by_date_range(self, from_date: datetime, to_date: datetime) -> list[Mutation]:
        return [m for m in self.mutations if from_date <= m.date <= to_date]

    def get_balance_on_date(self, as_of: datetime) -> Decimal:
        balance = Decimal(0)
        for mutation in sorted(self.mutations, key=lambda m: m.date):
            if mutation.date <= as_of:
                balance = mutation.balance
        return balance

    def is_over_credit_limit(self, additional_amount: Decimal = Decimal(0)) -> bool:
        if self.credit_limit <= 0:
            return False
        return self.outstanding_balance + additional_amount > self.credit_limit

    def get_utilization_percentage(self) -> float:
        if self.credit_limit <= 0:
            return 0.0
        return float(self.outstanding_balance / self.credit_limit * 100)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "legal_entity_id": str(self.legal_entity_id),
            "outstanding_balance": str(self.outstanding_balance),
            "currency": self.currency,
            "payment_terms_days": self.payment_terms_days,
            "credit_limit": str(self.credit_limit),
            "utilization_percentage": self.get_utilization_percentage(),
            "is_over_credit_limit": self.is_over_credit_limit(),
            "mutations_count": len(self.mutations),
            "mutations": [m.to_dict() for m in self.mutations[-50:]],  # Last 50 mutations
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VendorCard:
        mutations = [Mutation.from_dict(m) for m in data.get("mutations", [])]
        return cls(
            vendor_id=UUID(data["vendor_id"]),
            vendor_name=data["vendor_name"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            outstanding_balance=Decimal(data["outstanding_balance"]),
            currency=data["currency"],
            mutations=mutations,
            payment_terms_days=data.get("payment_terms_days", 30),
            credit_limit=Decimal(data.get("credit_limit", "0")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )


class VendorCardRepository:
    async def get_by_vendor(self, vendor_id: UUID, legal_entity_id: UUID) -> VendorCard | None:
        raise NotImplementedError

    async def get_all_by_legal_entity(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[VendorCard]:
        raise NotImplementedError

    async def get_by_outstanding_range(
        self, legal_entity_id: UUID, min_balance: Decimal, max_balance: Decimal
    ) -> list[VendorCard]:
        raise NotImplementedError

    async def save(self, card: VendorCard) -> None:
        raise NotImplementedError

    async def delete(self, vendor_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "Mutation",
    "MutationType",
    "VendorCard",
    "VendorCardRepository",
]
