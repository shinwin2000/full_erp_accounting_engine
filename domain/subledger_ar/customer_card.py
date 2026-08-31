#!/usr/bin/env python3
"""
Module: customer_card.py
Layer: Domain / Subledger AR
Responsibility: Kartu piutang per pelanggan (mutasi).

Metode yang ditambahkan:
- Entity dasar untuk Mutation dan CustomerCard: create, update, delete, restore,
  activate, deactivate, lock, unlock, validate, to_dict, from_dict, clone,
  snapshot, version, audit_trail, touch.
- Business: add_invoice, add_payment, apply_credit_note, get_aging_bucket,
  get_mutations_by_date_range, get_balance_on_date.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.subledger_ar.aging_bucket_vo import AgingBucket, AgingBucketVO
from domain.subledger_ar.invoice_entity import InvoiceEntity
from domain.subledger_ar.payment_entity import PaymentEntity

logger = logging.getLogger(__name__)


# === 1. MUTATION TYPE ===
class MutationType(Enum):
    INVOICE = "invoice"
    PAYMENT = "payment"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    ADJUSTMENT = "adjustment"

    def display_name(self) -> str:
        names = {
            MutationType.INVOICE: "Faktur",
            MutationType.PAYMENT: "Pembayaran",
            MutationType.CREDIT_NOTE: "Nota Kredit",
            MutationType.DEBIT_NOTE: "Nota Debit",
            MutationType.ADJUSTMENT: "Penyesuaian",
        }
        return names.get(self, self.value)


# === 2. MUTATION ENTITY ===
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

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "mutation_id": str(self.mutation_id),
            "type": self.mutation_type.value,
            "balance": str(self.balance),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "mutation_id": str(self.mutation_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.debit < 0:
            errors.append("Debit cannot be negative")
        if self.credit < 0:
            errors.append("Credit cannot be negative")
        if self.debit == 0 and self.credit == 0:
            errors.append("Debit or credit must be non-zero")
        if self.balance < 0:
            errors.append("Balance cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

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
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mutation:
        instance = cls(
            mutation_id=UUID(data["mutation_id"]),
            mutation_type=MutationType(data["mutation_type"]),
            reference_id=UUID(data["reference_id"]),
            reference_number=data["reference_number"],
            date=datetime.fromisoformat(data["date"]),
            debit=Decimal(data["debit"]),
            credit=Decimal(data["credit"]),
            balance=Decimal(data["balance"]),
            description=data["description"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> Mutation:
        new_id = uuid4()
        new = Mutation(
            mutation_id=new_id,
            mutation_type=self.mutation_type,
            reference_id=self.reference_id,
            reference_number=self.reference_number,
            date=self.date,
            debit=self.debit,
            credit=self.credit,
            balance=self.balance,
            description=self.description,
            created_at=datetime.now(UTC),
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "mutation_id": str(self.mutation_id),
            "type": self.mutation_type.value,
            "balance": str(self.balance),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Mutation:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. CUSTOMER CARD ===
@dataclass
class CustomerCard:
    customer_id: UUID
    customer_name: str
    legal_entity_id: UUID
    outstanding_balance: Decimal
    currency: str
    mutations: list[Mutation] = field(default_factory=list)
    credit_limit: Decimal = Decimal(0)
    credit_limit_currency: str = "IDR"
    risk_rating: str = "LOW"  # LOW, MEDIUM, HIGH
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "customer_id": str(self.customer_id),
            "outstanding_balance": str(self.outstanding_balance),
            "mutations_count": len(self.mutations),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "customer_id": str(self.customer_id),
                "details": details,
            }
        )

    # ==================== FACTORY METHODS ====================
    @classmethod
    def create_from_invoice(cls, invoice: InvoiceEntity) -> CustomerCard:
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.INVOICE,
            reference_id=invoice.invoice_id,
            reference_number=invoice.invoice_number,
            date=invoice.issue_date,
            debit=invoice.amount,
            credit=Decimal(0),
            balance=invoice.amount,
            description=f"Invoice {invoice.invoice_number}",
            created_at=datetime.now(UTC),
        )
        card = cls(
            customer_id=invoice.customer_id,
            customer_name=invoice.customer_name,
            legal_entity_id=invoice.customer_id,  # Placeholder, perlu diganti dengan legal_entity yang benar
            outstanding_balance=invoice.amount,
            currency=invoice.currency,
            mutations=[mutation],
        )
        # ── AUDIT TRAIL ──
        card._record_audit(
            "CREATE_FROM_INVOICE",
            "system",
            {
                "invoice_id": str(invoice.invoice_id),
                "invoice_number": invoice.invoice_number,
                "amount": str(invoice.amount),
                "customer_id": str(invoice.customer_id),
            }
        )
        return card

    # ==================== BUSINESS METHODS ====================
    def add_invoice(self, invoice: InvoiceEntity) -> CustomerCard:
        new_balance = self.outstanding_balance + invoice.amount
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.INVOICE,
            reference_id=invoice.invoice_id,
            reference_number=invoice.invoice_number,
            date=invoice.issue_date,
            debit=invoice.amount,
            credit=Decimal(0),
            balance=new_balance,
            description=f"Invoice {invoice.invoice_number}",
            created_at=datetime.now(UTC),
        )
        new_mutations = [*self.mutations, mutation]
        new_card = CustomerCard(
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=new_mutations,
            credit_limit=self.credit_limit,
            credit_limit_currency=self.credit_limit_currency,
            risk_rating=self.risk_rating,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new_card._record_audit("ADD_INVOICE", "system", {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "amount": str(invoice.amount),
        })
        return new_card

    def add_payment(self, payment: PaymentEntity) -> CustomerCard:
        new_balance = self.outstanding_balance - payment.amount
        if new_balance < 0:
            new_balance = Decimal(0)
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
        new_mutations = [*self.mutations, mutation]
        new_card = CustomerCard(
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=new_mutations,
            credit_limit=self.credit_limit,
            credit_limit_currency=self.credit_limit_currency,
            risk_rating=self.risk_rating,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new_card._record_audit("ADD_PAYMENT", "system", {
            "payment_id": str(payment.payment_id),
            "payment_number": payment.payment_number,
            "amount": str(payment.amount),
        })
        return new_card

    def apply_credit_note(self, amount: Decimal) -> CustomerCard:
        new_balance = self.outstanding_balance - amount
        if new_balance < 0:
            new_balance = Decimal(0)
        mutation = Mutation(
            mutation_id=uuid4(),
            mutation_type=MutationType.CREDIT_NOTE,
            reference_id=UUID(int=0),  # Placeholder
            reference_number="CREDIT_NOTE",
            date=datetime.now(UTC),
            debit=Decimal(0),
            credit=amount,
            balance=new_balance,
            description=f"Credit note applied: {amount}",
            created_at=datetime.now(UTC),
        )
        new_mutations = [*self.mutations, mutation]
        new_card = CustomerCard(
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=new_balance,
            currency=self.currency,
            mutations=new_mutations,
            credit_limit=self.credit_limit,
            credit_limit_currency=self.credit_limit_currency,
            risk_rating=self.risk_rating,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new_card._record_audit("APPLY_CREDIT_NOTE", "system", {"amount": str(amount)})
        return new_card

    def get_aging_bucket(self, as_of: datetime) -> AgingBucketVO:
        # Simplified: in production, iterate through invoices
        if self.outstanding_balance == 0:
            return AgingBucketVO(AgingBucket.CURRENT, Decimal(0))
        # Assume all current for simplicity
        return AgingBucketVO(AgingBucket.CURRENT, self.outstanding_balance)

    def get_mutations_by_date_range(self, from_date: datetime, to_date: datetime) -> list[Mutation]:
        return [m for m in self.mutations if from_date <= m.date <= to_date]

    def get_balance_on_date(self, as_of: datetime) -> Decimal:
        balance = Decimal(0)
        for mutation in sorted(self.mutations, key=lambda m: m.date):
            if mutation.date <= as_of:
                balance = mutation.balance
        return balance

    def is_credit_limit_exceeded(self, additional_amount: Decimal = Decimal(0)) -> bool:
        if self.credit_limit <= 0:
            return False
        return (self.outstanding_balance + additional_amount) > self.credit_limit

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> CustomerCard:
        self._record_audit("CREATE", created_by, {"customer_id": str(self.customer_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> CustomerCard:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("customer_id", "created_at", "mutations", "version"):
                data[key] = value
        new_card = CustomerCard(
            customer_id=self.customer_id,
            customer_name=data.get("customer_name", self.customer_name),
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=Decimal(data.get("outstanding_balance", self.outstanding_balance)),
            currency=data.get("currency", self.currency),
            mutations=self.mutations,  # mutations tidak berubah via update
            credit_limit=Decimal(data.get("credit_limit", self.credit_limit)),
            credit_limit_currency=data.get("credit_limit_currency", self.credit_limit_currency),
            risk_rating=data.get("risk_rating", self.risk_rating),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new_card._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_card

    def delete(self, deleted_by: str, reason: str | None = None) -> CustomerCard:
        new_card = self._copy()
        new_card.outstanding_balance = Decimal(0)
        new_card.mutations = []
        new_card.updated_at = datetime.now(UTC)
        new_card.version = self.version + 1
        new_card._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_card

    def restore(self, restored_by: str) -> CustomerCard:
        # Restore from deleted state - requires original mutations to be stored elsewhere
        new_card = self._copy()
        new_card.updated_at = datetime.now(UTC)
        new_card.version = self.version + 1
        new_card._record_audit("RESTORE", restored_by, {})
        return new_card

    def activate(self, activated_by: str) -> CustomerCard:
        new_card = self._copy()
        new_card.updated_at = datetime.now(UTC)
        new_card.version = self.version + 1
        new_card._record_audit("ACTIVATE", activated_by, {})
        return new_card

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CustomerCard:
        new_card = self._copy()
        new_card.updated_at = datetime.now(UTC)
        new_card.version = self.version + 1
        new_card._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_card

    def lock(self, locked_by: str, reason: str) -> CustomerCard:
        new_card = self._copy()
        new_card.updated_at = datetime.now(UTC)
        new_card.version = self.version + 1
        new_card._record_audit("LOCK", locked_by, {"reason": reason})
        return new_card

    def unlock(self, unlocked_by: str) -> CustomerCard:
        new_card = self._copy()
        new_card.updated_at = datetime.now(UTC)
        new_card.version = self.version + 1
        new_card._record_audit("UNLOCK", unlocked_by, {})
        return new_card

    def validate(self) -> dict[str, Any]:
        errors = []
        if self.outstanding_balance < 0:
            errors.append("Outstanding balance cannot be negative")
        if self.credit_limit < 0:
            errors.append("Credit limit cannot be negative")
        if self.risk_rating not in ("LOW", "MEDIUM", "HIGH"):
            errors.append("Risk rating must be LOW, MEDIUM, or HIGH")
        for mutation in self.mutations:
            res = mutation.validate()
            if not res["is_valid"]:
                errors.extend([f"Mutation {mutation.mutation_id}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "legal_entity_id": str(self.legal_entity_id),
            "outstanding_balance": str(self.outstanding_balance),
            "currency": self.currency,
            "credit_limit": str(self.credit_limit),
            "credit_limit_currency": self.credit_limit_currency,
            "risk_rating": self.risk_rating,
            "mutations": [m.to_dict() for m in self.mutations],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomerCard:
        mutations = [Mutation.from_dict(m) for m in data.get("mutations", [])]
        instance = cls(
            customer_id=UUID(data["customer_id"]),
            customer_name=data["customer_name"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            outstanding_balance=Decimal(data["outstanding_balance"]),
            currency=data["currency"],
            mutations=mutations,
            credit_limit=Decimal(data.get("credit_limit", "0")),
            credit_limit_currency=data.get("credit_limit_currency", "IDR"),
            risk_rating=data.get("risk_rating", "LOW"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )
        return instance

    def clone(self) -> CustomerCard:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = CustomerCard(
            customer_id=new_id,
            customer_name=f"{self.customer_name}_COPY",
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=Decimal(0),
            currency=self.currency,
            mutations=[],
            credit_limit=self.credit_limit,
            credit_limit_currency=self.credit_limit_currency,
            risk_rating=self.risk_rating,
            created_at=now,
            updated_at=now,
            version=1,
        )
        cloned._record_audit("CLONE", "system", {"source": str(self.customer_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "customer_id": str(self.customer_id),
            "outstanding_balance": str(self.outstanding_balance),
            "mutations_count": len(self.mutations),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CustomerCard:
        new_card = self._copy()
        new_card.updated_at = datetime.now(UTC)
        new_card.version = self.version + 1
        new_card._record_audit("TOUCH", touched_by, {})
        return new_card

    # ==================== PRIVATE HELPERS ====================
    def _copy(self) -> CustomerCard:
        return CustomerCard(
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            legal_entity_id=self.legal_entity_id,
            outstanding_balance=self.outstanding_balance,
            currency=self.currency,
            mutations=self.mutations.copy(),
            credit_limit=self.credit_limit,
            credit_limit_currency=self.credit_limit_currency,
            risk_rating=self.risk_rating,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )


# === 4. CUSTOMER CARD REPOSITORY PROTOCOL ===
class CustomerCardRepository:
    async def get_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> CustomerCard | None:
        raise NotImplementedError

    async def get_all_by_legal_entity(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CustomerCard]:
        raise NotImplementedError

    async def save(self, card: CustomerCard) -> None:
        raise NotImplementedError

    async def delete(self, customer_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    # Repository standard methods
    async def add(self, card: CustomerCard) -> None:
        await self.save(card)

    async def update(self, card: CustomerCard) -> None:
        await self.save(card)

    async def exists(self, customer_id: UUID, legal_entity_id: UUID) -> bool:
        raise NotImplementedError

    async def get_by_id(self, customer_id: UUID, legal_entity_id: UUID) -> CustomerCard | None:
        return await self.get_by_customer(customer_id, legal_entity_id)

    async def get_all(self, legal_entity_id: UUID) -> list[CustomerCard]:
        return await self.get_all_by_legal_entity(legal_entity_id)

    async def search(self, legal_entity_id: UUID, criteria: dict[str, Any]) -> list[CustomerCard]:
        raise NotImplementedError

    async def count(self, legal_entity_id: UUID) -> int:
        raise NotImplementedError

    async def list_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CustomerCard]:
        return await self.get_all_by_legal_entity(legal_entity_id, limit, offset)

    async def paginate(
        self, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[CustomerCard], int]:
        offset = (page - 1) * per_page
        items = await self.list_all(legal_entity_id, limit=per_page, offset=offset)
        total = await self.count(legal_entity_id)
        return items, total


# === 5. EXPORTS ===
__all__ = [
    "CustomerCard",
    "CustomerCardRepository",
    "Mutation",
    "MutationType",
]
