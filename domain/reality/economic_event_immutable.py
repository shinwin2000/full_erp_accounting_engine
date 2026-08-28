#!/usr/bin/env python3
"""
Module: economic_event_immutable.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Representasi event ekonomi yang tidak dapat diubah.
               Mendefinisikan struktur data immutable untuk event ekonomi
               seperti penjualan, pembelian, produksi, transfer aset, dll.
               Event ini adalah sumber kebenaran untuk pemetaan ke entri akuntansi.

               Monetary amounts are stored as Decimal with explicit currency.
               Empty currency string indicates no monetary amount.
               Use the `money` property to get a Money object.

Dependencies:
- standard library (uuid, datetime, decimal, hashlib, json, logging, threading)
- domain.shared_value_objects.money_vo (Money)
- domain.shared_value_objects.quantity_vo (Quantity)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.quantity_vo import Quantity

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class EconomicEventType(Enum):
    """Jenis event ekonomi."""

    SALE_OF_GOODS = auto()
    SALE_OF_SERVICES = auto()
    ROYALTY_EARNED = auto()
    INTEREST_EARNED = auto()
    DIVIDEND_RECEIVED = auto()
    PURCHASE_OF_GOODS = auto()
    PURCHASE_OF_SERVICES = auto()
    SALARY_EXPENSE = auto()
    RENT_EXPENSE = auto()
    UTILITY_EXPENSE = auto()
    TAX_EXPENSE = auto()
    INTEREST_EXPENSE = auto()
    ASSET_ACQUISITION = auto()
    ASSET_DISPOSAL = auto()
    ASSET_DEPRECIATION = auto()
    ASSET_IMPAIRMENT = auto()
    ASSET_REVALUATION = auto()
    INVENTORY_RECEIPT = auto()
    INVENTORY_ISSUE = auto()
    INVENTORY_ADJUSTMENT = auto()
    CASH_RECEIPT = auto()
    CASH_DISBURSEMENT = auto()
    LOAN_DRAWDOWN = auto()
    LOAN_REPAYMENT = auto()
    CAPITAL_CONTRIBUTION = auto()
    CAPITAL_WITHDRAWAL = auto()
    PRODUCTION_COMPLETION = auto()
    RAW_MATERIAL_CONSUMPTION = auto()
    OVERHEAD_APPLICATION = auto()
    PERIOD_CLOSE = auto()
    PERIOD_ADJUSTMENT = auto()


class EconomicEventStatus(Enum):
    """Status event ekonomi."""

    DRAFT = auto()
    VALIDATED = auto()
    MAPPED = auto()
    POSTED = auto()
    REVERSED = auto()
    CANCELLED = auto()


# === 2. ECONOMIC EVENT IMMUTABLE ===


@dataclass(frozen=True)
class EconomicEvent:
    """
    Event ekonomi yang immutable.

    Business context: Mencatat kejadian ekonomi dunia nyata yang menjadi
    dasar pencatatan akuntansi. Event ini tidak dapat diubah setelah dibuat.

    Monetary amounts are stored as Decimal with explicit currency.
    Empty currency string indicates no monetary amount.
    Use the `money` property to get a Money object when needed.
    """

    event_id: UUID
    event_type: EconomicEventType
    event_date: datetime
    description: str
    legal_entity_id: UUID
    created_by: str
    created_at: datetime
    status: EconomicEventStatus = EconomicEventStatus.DRAFT
    amount: Decimal = Decimal(0)          # monetary value in Decimal
    currency: str = ""                    # currency code, empty means no amount
    quantity: Quantity | None = None
    source_document_ref: str | None = None
    counterparty_id: UUID | None = None
    contract_id: UUID | None = None
    project_id: UUID | None = None
    cost_center: str | None = None
    department: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    previous_event_id: UUID | None = None
    reversal_of: UUID | None = None
    cryptographic_hash: str = ""

    @property
    def money(self) -> Money | None:
        """Return amount as Money object if currency is set."""
        if self.currency:
            return Money(self.amount, self.currency)
        return None

    @property
    def has_amount(self) -> bool:
        """Check if event has a monetary amount."""
        return bool(self.currency)

    def compute_hash(self) -> str:
        """Menghitung hash kriptografis event untuk integritas."""
        content = {
            "event_id": str(self.event_id),
            "event_type": self.event_type.name,
            "event_date": self.event_date.isoformat(),
            "description": self.description,
            "legal_entity_id": str(self.legal_entity_id),
            "amount": str(self.amount) if self.currency else None,
            "currency": self.currency if self.currency else None,
            "quantity": str(self.quantity.value) if self.quantity else None,
            "source_document_ref": self.source_document_ref,
            "counterparty_id": str(self.counterparty_id) if self.counterparty_id else None,
            "previous_event_id": str(self.previous_event_id) if self.previous_event_id else None,
            "reversal_of": str(self.reversal_of) if self.reversal_of else None,
            "status": self.status.name,
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha3_256(content_str.encode()).hexdigest()

    def __post_init__(self) -> None:
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")
        # Pastikan waktu UTC
        if self.event_date.tzinfo is None:
            object.__setattr__(self, "event_date", self.event_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def validate(self) -> list[str]:
        """Validasi dasar event."""
        errors = []
        if self.currency and self.amount <= 0:
            errors.append("Amount must be positive when currency is set")
        if not self.description or len(self.description.strip()) < 3:
            errors.append("Description must be at least 3 characters")
        if self.event_date > datetime.now(UTC) + timedelta(days=365):
            errors.append("Event date cannot be more than one year in the future")
        if self.previous_event_id == self.event_id:
            errors.append("Previous event ID cannot be the same as event ID")
        if self.reversal_of == self.event_id:
            errors.append("Reversal of cannot be the same as event ID")
        return errors

    def is_posted(self) -> bool:
        return self.status == EconomicEventStatus.POSTED

    def is_reversal(self) -> bool:
        return self.reversal_of is not None

    def create_reversal(self, reversed_by: str, reason: str) -> EconomicEvent:
        """Membuat event reversal (koreksi)."""
        return EconomicEvent(
            event_id=uuid4(),
            event_type=self.event_type,
            event_date=datetime.now(UTC),
            description=f"REVERSAL of {self.event_id}: {reason}",
            legal_entity_id=self.legal_entity_id,
            created_by=reversed_by,
            created_at=datetime.now(UTC),
            status=EconomicEventStatus.DRAFT,
            amount=self.amount,
            currency=self.currency,
            quantity=self.quantity,
            source_document_ref=self.source_document_ref,
            counterparty_id=self.counterparty_id,
            contract_id=self.contract_id,
            previous_event_id=self.event_id,
            reversal_of=self.event_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.name,
            "event_date": self.event_date.isoformat(),
            "description": self.description,
            "legal_entity_id": str(self.legal_entity_id),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "status": self.status.name,
            "amount": str(self.amount) if self.currency else None,
            "currency": self.currency if self.currency else None,
            "source_document_ref": self.source_document_ref,
            "counterparty_id": str(self.counterparty_id) if self.counterparty_id else None,
        }


# === 3. ECONOMIC EVENT SERVICE ===


class EconomicEventService:
    """
    Service untuk mengelola economic events.

    Business context: Menyediakan antarmuka untuk membuat, memvalidasi,
    dan melacak economic events.
    """

    _instance: EconomicEventService | None = None
    _lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> EconomicEventService:
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
        self._events: dict[UUID, EconomicEvent] = {}
        self._max_history = 10000

    def create_event(
        self,
        event_type: EconomicEventType,
        event_date: datetime,
        description: str,
        legal_entity_id: UUID,
        created_by: str,
        amount: Money | None = None,
        quantity: Quantity | None = None,
        source_document_ref: str | None = None,
        counterparty_id: UUID | None = None,
        contract_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EconomicEvent:
        """Membuat economic event baru."""
        # Extract amount and currency from Money if provided
        amount_decimal = amount.amount if amount is not None else Decimal(0)
        currency = amount.currency if amount is not None else ""

        event = EconomicEvent(
            event_id=uuid4(),
            event_type=event_type,
            event_date=event_date,
            description=description,
            legal_entity_id=legal_entity_id,
            created_by=created_by,
            created_at=datetime.now(UTC),
            status=EconomicEventStatus.DRAFT,
            amount=amount_decimal,
            currency=currency,
            quantity=quantity,
            source_document_ref=source_document_ref,
            counterparty_id=counterparty_id,
            contract_id=contract_id,
            metadata=metadata or {},
            cryptographic_hash="",
        )
        # Recreate with hash
        event = EconomicEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            event_date=event.event_date,
            description=event.description,
            legal_entity_id=event.legal_entity_id,
            created_by=event.created_by,
            created_at=event.created_at,
            status=event.status,
            amount=event.amount,
            currency=event.currency,
            quantity=event.quantity,
            source_document_ref=event.source_document_ref,
            counterparty_id=event.counterparty_id,
            contract_id=event.contract_id,
            project_id=event.project_id,
            cost_center=event.cost_center,
            department=event.department,
            metadata=event.metadata,
            previous_event_id=event.previous_event_id,
            reversal_of=event.reversal_of,
            cryptographic_hash=event.compute_hash(),
        )
        with self._lock:
            self._events[event.event_id] = event
            if len(self._events) > self._max_history:
                # Hapus event tertua
                oldest = min(self._events.keys(), key=lambda k: self._events[k].created_at)
                del self._events[oldest]
        logger.info(f"Economic event created: {event.event_type.name} - {description[:50]}")
        return event

    def get_event(self, event_id: UUID) -> EconomicEvent | None:
        return self._events.get(event_id)

    def validate_event(self, event_id: UUID) -> tuple[bool, list[str]]:
        """Memvalidasi economic event."""
        event = self._events.get(event_id)
        if not event:
            return False, [f"Event {event_id} not found"]
        errors = event.validate()
        return len(errors) == 0, errors

    def mark_as_validated(self, event_id: UUID) -> EconomicEvent | None:
        """Menandai event sebagai tervalidasi."""
        event = self._events.get(event_id)
        if not event or event.status != EconomicEventStatus.DRAFT:
            return None
        updated = EconomicEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            event_date=event.event_date,
            description=event.description,
            legal_entity_id=event.legal_entity_id,
            created_by=event.created_by,
            created_at=event.created_at,
            status=EconomicEventStatus.VALIDATED,
            amount=event.amount,
            currency=event.currency,
            quantity=event.quantity,
            source_document_ref=event.source_document_ref,
            counterparty_id=event.counterparty_id,
            contract_id=event.contract_id,
            cost_center=event.cost_center,
            department=event.department,
            metadata=event.metadata,
            previous_event_id=event.previous_event_id,
            reversal_of=event.reversal_of,
            cryptographic_hash=event.cryptographic_hash,
        )
        with self._lock:
            self._events[event_id] = updated
        return updated

    def mark_as_mapped(self, event_id: UUID) -> EconomicEvent | None:
        """Menandai event sebagai sudah dipetakan ke jurnal."""
        event = self._events.get(event_id)
        if not event or event.status not in (
            EconomicEventStatus.VALIDATED,
            EconomicEventStatus.DRAFT,
        ):
            return None
        updated = EconomicEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            event_date=event.event_date,
            description=event.description,
            legal_entity_id=event.legal_entity_id,
            created_by=event.created_by,
            created_at=event.created_at,
            status=EconomicEventStatus.MAPPED,
            amount=event.amount,
            currency=event.currency,
            quantity=event.quantity,
            source_document_ref=event.source_document_ref,
            counterparty_id=event.counterparty_id,
            contract_id=event.contract_id,
            cost_center=event.cost_center,
            department=event.department,
            metadata=event.metadata,
            previous_event_id=event.previous_event_id,
            reversal_of=event.reversal_of,
            cryptographic_hash=event.cryptographic_hash,
        )
        with self._lock:
            self._events[event_id] = updated
        return updated

    def get_events_by_date_range(
        self,
        legal_entity_id: UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> list[EconomicEvent]:
        """Mendapatkan event dalam rentang tanggal."""
        result = []
        with self._lock:
            for e in self._events.values():
                if e.legal_entity_id == legal_entity_id and from_date <= e.event_date <= to_date:
                    result.append(e)
        return result

    def get_events_by_type(
        self,
        legal_entity_id: UUID,
        event_type: EconomicEventType,
    ) -> list[EconomicEvent]:
        """Mendapatkan event berdasarkan tipe."""
        result = []
        with self._lock:
            for e in self._events.values():
                if e.legal_entity_id == legal_entity_id and e.event_type == event_type:
                    result.append(e)
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._events)
            by_status: dict[str, int] = {}
            by_type: dict[str, int] = {}
            for e in self._events.values():
                by_status[e.status.name] = by_status.get(e.status.name, 0) + 1
                by_type[e.event_type.name] = by_type.get(e.event_type.name, 0) + 1
            return {
                "total_events": total,
                "by_status": by_status,
                "by_type": by_type,
            }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


# === 4. SINGLETON ACCESSOR ===

_economic_event_service_instance: EconomicEventService | None = None


def get_economic_event_service() -> EconomicEventService:
    global _economic_event_service_instance
    if _economic_event_service_instance is None:
        _economic_event_service_instance = EconomicEventService()
    return _economic_event_service_instance


# === 5. EXPORTS ===

__all__ = [
    "EconomicEvent",
    "EconomicEventService",
    "EconomicEventStatus",
    "EconomicEventType",
    "get_economic_event_service",
]
