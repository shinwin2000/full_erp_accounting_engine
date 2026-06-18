#!/usr/bin/env python3
"""
Module: financial_entitlement.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Hak keuangan (piutang, klaim) yang timbul dari event.
               Mendefinisikan struktur data untuk hak keuangan seperti
               piutang usaha, tagihan kepada pelanggan, klaim asuransi,
               dan hak kontraktual lainnya yang memberikan manfaat ekonomi
               di masa depan.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- domain.shared_value_objects.money_vo (Money)
- reality.economic_event_immutable (EconomicEvent)

Audit: Setiap perubahan status entitlement dictat.
"""

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


# === 1. CONSTANTS & ENUMS ===


class EntitlementType(Enum):
    """Jenis hak keuangan."""

    ACCOUNTS_RECEIVABLE = auto()
    ACCRUED_REVENUE = auto()
    UNBILLED_REVENUE = auto()
    LOAN_RECEIVABLE = auto()
    INTEREST_RECEIVABLE = auto()
    DIVIDEND_RECEIVABLE = auto()
    INSURANCE_CLAIM = auto()
    TAX_REFUND_CLAIM = auto()
    WARRANTY_CLAIM = auto()
    PERFORMANCE_RIGHT = auto()
    RIGHT_OF_USE = auto()
    OTHER_RECEIVABLES = auto()


class EntitlementStatus(Enum):
    """Status hak keuangan."""

    ACCRUED = auto()
    CURRENT = auto()
    PAST_DUE = auto()
    PARTIALLY_COLLECTED = auto()
    COLLECTED = auto()
    WRITTEN_OFF = auto()
    DISPUTED = auto()


class CollectionRisk(Enum):
    """Tingkat risiko penagihan."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DOUBTFUL = "doubtful"
    LOSS = "loss"


# === 2. FALLBACK STORAGE (jika repository belum ada) ===


class _FallbackEntitlementStorage:
    """Fallback storage untuk entitlement jika infrastruktur belum tersedia."""

    def __init__(self):
        self._entitlements: dict[UUID, dict[str, Any]] = {}
        self._by_customer: dict[UUID, list[UUID]] = {}

    def save(self, entitlement: FinancialEntitlement) -> None:
        self._entitlements[entitlement.entitlement_id] = entitlement.to_dict()
        if entitlement.customer_id:
            if entitlement.customer_id not in self._by_customer:
                self._by_customer[entitlement.customer_id] = []
            if entitlement.entitlement_id not in self._by_customer[entitlement.customer_id]:
                self._by_customer[entitlement.customer_id].append(entitlement.entitlement_id)

    def get(self, entitlement_id: UUID) -> dict[str, Any] | None:
        return self._entitlements.get(entitlement_id)

    def get_by_customer(self, customer_id: UUID) -> list[UUID]:
        return self._by_customer.get(customer_id, [])

    def get_all(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        return [
            e for e in self._entitlements.values() if e.get("legal_entity_id") == legal_entity_id
        ]

    def update(self, entitlement: FinancialEntitlement) -> None:
        self._entitlements[entitlement.entitlement_id] = entitlement.to_dict()


# === 3. FINANCIAL ENTITLEMENT (IMMUTABLE) ===


@dataclass(frozen=True)
class FinancialEntitlement:
    """
    Hak keuangan (piutang/klaim).

    Business context: Mencatat hak yang timbul dari transaksi penjualan,
    pinjaman, atau kontrak. Melacak jatuh tempo dan koleksi.
    """

    entitlement_id: UUID
    entitlement_type: EntitlementType
    source_event_id: UUID
    legal_entity_id: UUID
    customer_id: UUID | None
    original_amount: Money
    outstanding_amount: Money
    incurred_date: datetime
    due_date: datetime | None
    status: EntitlementStatus
    risk: CollectionRisk
    description: str
    invoice_number: str | None = None
    contract_reference: str | None = None
    interest_rate: Decimal | None = None
    allowance_for_doubtful: Money = field(default_factory=lambda: Money(Decimal(0), "IDR"))
    collection_notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.entitlement_id}|{self.entitlement_type.value}|{self.source_event_id}|"
            f"{self.legal_entity_id}|{self.original_amount.amount}|{self.outstanding_amount.amount}|"
            f"{self.status.value}|{self.risk.value}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")
        # Ensure timezone-aware
        if self.incurred_date.tzinfo is None:
            object.__setattr__(self, "incurred_date", self.incurred_date.replace(tzinfo=UTC))
        if self.due_date and self.due_date.tzinfo is None:
            object.__setattr__(self, "due_date", self.due_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        # Ensure allowance currency matches
        if self.allowance_for_doubtful.currency != self.outstanding_amount.currency:
            raise ValueError("Allowance currency must match outstanding currency")

    @property
    def is_overdue(self) -> bool:
        if self.due_date and self.status not in (
            EntitlementStatus.COLLECTED,
            EntitlementStatus.WRITTEN_OFF,
        ):
            return datetime.now(UTC) > self.due_date
        return False

    @property
    def days_overdue(self) -> int:
        if self.is_overdue and self.due_date:
            return (datetime.now(UTC) - self.due_date).days
        return 0

    @property
    def is_fully_collected(self) -> bool:
        return self.status == EntitlementStatus.COLLECTED or self.outstanding_amount.amount <= 0

    @property
    def net_realizable_value(self) -> Money:
        """Nilai realisasi bersih setelah penyisihan."""
        net = self.outstanding_amount.amount - self.allowance_for_doubtful.amount
        return Money(max(Decimal(0), net), self.outstanding_amount.currency)

    def record_collection(
        self, amount: Money, payment_reference: str, collected_at: datetime
    ) -> FinancialEntitlement:
        """Mencatat penerimaan pembayaran."""
        if amount.currency != self.outstanding_amount.currency:
            raise ValueError(f"Currency mismatch: {amount.currency}")
        new_outstanding = self.outstanding_amount.amount - amount.amount
        if new_outstanding <= 0:
            new_status = EntitlementStatus.COLLECTED
        else:
            new_status = EntitlementStatus.PARTIALLY_COLLECTED
        return FinancialEntitlement(
            entitlement_id=self.entitlement_id,
            entitlement_type=self.entitlement_type,
            source_event_id=self.source_event_id,
            legal_entity_id=self.legal_entity_id,
            customer_id=self.customer_id,
            original_amount=self.original_amount,
            outstanding_amount=Money(new_outstanding, amount.currency),
            incurred_date=self.incurred_date,
            due_date=self.due_date,
            status=new_status,
            risk=self.risk,
            description=self.description,
            invoice_number=self.invoice_number,
            contract_reference=self.contract_reference,
            interest_rate=self.interest_rate,
            allowance_for_doubtful=self.allowance_for_doubtful,
            collection_notes=f"{self.collection_notes}\nCollection {amount} on {collected_at.date()}: {payment_reference}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            cryptographic_hash=self.cryptographic_hash,
        )

    def update_risk(self, new_risk: CollectionRisk, reason: str) -> FinancialEntitlement:
        """Memperbarui tingkat risiko penagihan."""
        return FinancialEntitlement(
            entitlement_id=self.entitlement_id,
            entitlement_type=self.entitlement_type,
            source_event_id=self.source_event_id,
            legal_entity_id=self.legal_entity_id,
            customer_id=self.customer_id,
            original_amount=self.original_amount,
            outstanding_amount=self.outstanding_amount,
            incurred_date=self.incurred_date,
            due_date=self.due_date,
            status=self.status,
            risk=new_risk,
            description=self.description,
            invoice_number=self.invoice_number,
            contract_reference=self.contract_reference,
            interest_rate=self.interest_rate,
            allowance_for_doubtful=self.allowance_for_doubtful,
            collection_notes=f"{self.collection_notes}\nRisk updated to {new_risk.value}: {reason}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            cryptographic_hash=self.cryptographic_hash,
        )

    def provision_bad_debt(self, amount: Money, reason: str) -> FinancialEntitlement:
        """Mencatat penyisihan piutang tak tertagih."""
        new_allowance = self.allowance_for_doubtful.amount + amount.amount
        new_status = (
            EntitlementStatus.WRITTEN_OFF
            if amount.amount >= self.outstanding_amount.amount
            else self.status
        )
        return FinancialEntitlement(
            entitlement_id=self.entitlement_id,
            entitlement_type=self.entitlement_type,
            source_event_id=self.source_event_id,
            legal_entity_id=self.legal_entity_id,
            customer_id=self.customer_id,
            original_amount=self.original_amount,
            outstanding_amount=self.outstanding_amount,
            incurred_date=self.incurred_date,
            due_date=self.due_date,
            status=new_status,
            risk=CollectionRisk.DOUBTFUL,
            description=self.description,
            invoice_number=self.invoice_number,
            contract_reference=self.contract_reference,
            interest_rate=self.interest_rate,
            allowance_for_doubtful=Money(new_allowance, amount.currency),
            collection_notes=f"{self.collection_notes}\nProvision for bad debt: {reason}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            cryptographic_hash=self.cryptographic_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entitlement_id": str(self.entitlement_id),
            "entitlement_type": self.entitlement_type.name,
            "source_event_id": str(self.source_event_id),
            "legal_entity_id": str(self.legal_entity_id),
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "original_amount": str(self.original_amount.amount),
            "original_currency": self.original_amount.currency,
            "outstanding_amount": str(self.outstanding_amount.amount),
            "outstanding_currency": self.outstanding_amount.currency,
            "incurred_date": self.incurred_date.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status.name,
            "risk": self.risk.value,
            "description": self.description,
            "invoice_number": self.invoice_number,
            "contract_reference": self.contract_reference,
            "allowance_amount": str(self.allowance_for_doubtful.amount),
            "collection_notes": self.collection_notes[:200],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# === 4. FINANCIAL ENTITLEMENT SERVICE ===


class FinancialEntitlementService:
    """
    Service untuk mengelola hak keuangan.

    Business context: Mencatat, melacak, dan memperbarui piutang dan
    hak keuangan lainnya.
    """

    _instance: FinancialEntitlementService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> FinancialEntitlementService:
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
        self._storage = _FallbackEntitlementStorage()
        self._cache: dict[UUID, FinancialEntitlement] = {}

    def create_entitlement(
        self,
        entitlement_type: EntitlementType,
        source_event_id: UUID,
        legal_entity_id: UUID,
        amount: Money,
        incurred_date: datetime,
        due_date: datetime | None,
        description: str,
        customer_id: UUID | None = None,
        invoice_number: str | None = None,
        contract_reference: str | None = None,
        risk: CollectionRisk = CollectionRisk.LOW,
    ) -> FinancialEntitlement:
        """
        Membuat hak keuangan baru.
        """
        entitlement = FinancialEntitlement(
            entitlement_id=uuid4(),
            entitlement_type=entitlement_type,
            source_event_id=source_event_id,
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            original_amount=amount,
            outstanding_amount=amount,
            incurred_date=incurred_date,
            due_date=due_date,
            status=EntitlementStatus.ACCRUED,
            risk=risk,
            description=description,
            invoice_number=invoice_number,
            contract_reference=contract_reference,
            cryptographic_hash="",
        )
        entitlement = FinancialEntitlement(
            entitlement_id=entitlement.entitlement_id,
            entitlement_type=entitlement.entitlement_type,
            source_event_id=entitlement.source_event_id,
            legal_entity_id=entitlement.legal_entity_id,
            customer_id=entitlement.customer_id,
            original_amount=entitlement.original_amount,
            outstanding_amount=entitlement.outstanding_amount,
            incurred_date=entitlement.incurred_date,
            due_date=entitlement.due_date,
            status=entitlement.status,
            risk=entitlement.risk,
            description=entitlement.description,
            invoice_number=entitlement.invoice_number,
            contract_reference=entitlement.contract_reference,
            interest_rate=entitlement.interest_rate,
            allowance_for_doubtful=entitlement.allowance_for_doubtful,
            collection_notes=entitlement.collection_notes,
            created_at=entitlement.created_at,
            updated_at=entitlement.updated_at,
            cryptographic_hash=entitlement.compute_hash(),
        )
        self._storage.save(entitlement)
        self._cache[entitlement.entitlement_id] = entitlement
        logger.info(f"Financial entitlement created: {entitlement_type.name} - {amount}")
        return entitlement

    def get_entitlement(self, entitlement_id: UUID) -> FinancialEntitlement | None:
        if entitlement_id in self._cache:
            return self._cache[entitlement_id]
        data = self._storage.get(entitlement_id)
        if not data:
            return None
        # Reconstruct from dict
        entitlement = self._reconstruct(data)
        self._cache[entitlement_id] = entitlement
        return entitlement

    def _reconstruct(self, data: dict[str, Any]) -> FinancialEntitlement:
        return FinancialEntitlement(
            entitlement_id=UUID(data["entitlement_id"]),
            entitlement_type=EntitlementType[data["entitlement_type"]],
            source_event_id=UUID(data["source_event_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            customer_id=UUID(data["customer_id"]) if data.get("customer_id") else None,
            original_amount=Money(
                Decimal(data["original_amount"]), data.get("original_currency", "IDR")
            ),
            outstanding_amount=Money(
                Decimal(data["outstanding_amount"]), data.get("outstanding_currency", "IDR")
            ),
            incurred_date=datetime.fromisoformat(data["incurred_date"]),
            due_date=datetime.fromisoformat(data["due_date"]) if data.get("due_date") else None,
            status=EntitlementStatus[data["status"]],
            risk=CollectionRisk(data["risk"]),
            description=data["description"],
            invoice_number=data.get("invoice_number"),
            contract_reference=data.get("contract_reference"),
            allowance_for_doubtful=Money(
                Decimal(data.get("allowance_amount", 0)), data.get("outstanding_currency", "IDR")
            ),
            collection_notes=data.get("collection_notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def get_outstanding_entitlements(
        self,
        legal_entity_id: UUID,
        as_of: datetime | None = None,
    ) -> list[FinancialEntitlement]:
        as_of = as_of or datetime.now(UTC)
        all_data = self._storage.get_all(legal_entity_id)
        result = []
        for data in all_data:
            ent = self._reconstruct(data)
            if not ent.is_fully_collected and ent.incurred_date <= as_of:
                result.append(ent)
        return result

    def get_overdue_entitlements(self, legal_entity_id: UUID) -> list[FinancialEntitlement]:
        result = []
        for data in self._storage.get_all(legal_entity_id):
            ent = self._reconstruct(data)
            if ent.is_overdue and not ent.is_fully_collected:
                result.append(ent)
        return result

    def get_entitlements_by_customer(self, customer_id: UUID) -> list[FinancialEntitlement]:
        entitlement_ids = self._storage.get_by_customer(customer_id)
        return [self.get_entitlement(eid) for eid in entitlement_ids if self.get_entitlement(eid)]

    def get_aging_summary(self, legal_entity_id: UUID) -> dict[str, Decimal]:
        today = datetime.now(UTC)
        aging = {
            "current": Decimal(0),
            "1_30_days": Decimal(0),
            "31_60_days": Decimal(0),
            "61_90_days": Decimal(0),
            "over_90_days": Decimal(0),
        }
        for ent in self.get_outstanding_entitlements(legal_entity_id):
            if not ent.due_date:
                aging["current"] += ent.outstanding_amount.amount
                continue
            days_overdue = (today - ent.due_date).days if ent.due_date < today else 0
            if days_overdue <= 0:
                aging["current"] += ent.outstanding_amount.amount
            elif days_overdue <= 30:
                aging["1_30_days"] += ent.outstanding_amount.amount
            elif days_overdue <= 60:
                aging["31_60_days"] += ent.outstanding_amount.amount
            elif days_overdue <= 90:
                aging["61_90_days"] += ent.outstanding_amount.amount
            else:
                aging["over_90_days"] += ent.outstanding_amount.amount
        return aging

    def get_total_outstanding(self, legal_entity_id: UUID) -> Money:
        total = sum(
            ent.outstanding_amount.amount
            for ent in self.get_outstanding_entitlements(legal_entity_id)
        )
        return Money(total, "IDR")

    def calculate_bad_debt_provision(
        self,
        legal_entity_id: UUID,
        provision_percentages: dict[str, Decimal],
    ) -> Decimal:
        aging = self.get_aging_summary(legal_entity_id)
        provision = Decimal(0)
        for category, percentage in provision_percentages.items():
            amount = aging.get(category, Decimal(0))
            provision += amount * percentage
        return provision

    def update_entitlement(self, entitlement: FinancialEntitlement) -> None:
        self._storage.save(entitlement)
        self._cache[entitlement.entitlement_id] = entitlement

    def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        all_ents = [self._reconstruct(d) for d in self._storage.get_all(legal_entity_id)]
        total = len(all_ents)
        if total == 0:
            return {"total_entitlements": 0}
        by_status = {}
        by_risk = {}
        for e in all_ents:
            by_status[e.status.name] = by_status.get(e.status.name, 0) + 1
            by_risk[e.risk.value] = by_risk.get(e.risk.value, 0) + 1
        return {
            "legal_entity_id": str(legal_entity_id),
            "total_entitlements": total,
            "by_status": by_status,
            "by_risk": by_risk,
            "total_outstanding": str(self.get_total_outstanding(legal_entity_id).amount),
            "overdue_count": len([e for e in all_ents if e.is_overdue]),
        }


# === 5. SINGLETON ACCESSOR ===

_financial_entitlement_service_instance: FinancialEntitlementService | None = None


def get_financial_entitlement_service() -> FinancialEntitlementService:
    """Mendapatkan instance singleton FinancialEntitlementService."""
    global _financial_entitlement_service_instance
    if _financial_entitlement_service_instance is None:
        _financial_entitlement_service_instance = FinancialEntitlementService()
    return _financial_entitlement_service_instance


# === 6. EXPORTS ===

__all__ = [
    "CollectionRisk",
    "EntitlementStatus",
    "EntitlementType",
    "FinancialEntitlement",
    "FinancialEntitlementService",
    "get_financial_entitlement_service",
]
