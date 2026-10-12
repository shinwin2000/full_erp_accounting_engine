#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Domain events untuk Customer, Supplier, Employee aggregates.

PERBAIKAN (2026-10-12):
- Base DomainEvent tetap @dataclass(frozen=True), tetapi subclass JUGA
  @dataclass(frozen=True) dengan field dideklarasikan eksplisit lewat
  ClassVar[_EVENT_TYPE] dan @classmethod create(). Ini menyelesaikan bug
  "super().__init__ keyword arg pada frozen dataclass" yang membuat
  CustomerCreatedEvent(...) crash saat dibuat lewat keyword.
- Menambahkan _EVENT_REGISTRY untuk deserialisasi yang mempertahankan tipe.
- Semua Decimal di-serialize sebagai string agar presisi terjaga.
- Backward-compat: nama class & alias (CustomerCreated, dll) tetap sama.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    # Customer
    CUSTOMER_CREATED = "customer_created"
    CUSTOMER_UPDATED = "customer_updated"
    CUSTOMER_STATUS_CHANGED = "customer_status_changed"
    CUSTOMER_BLOCKED = "customer_blocked"
    CUSTOMER_UNBLOCKED = "customer_unblocked"
    CUSTOMER_BLACKLISTED = "customer_blacklisted"
    CUSTOMER_DEACTIVATED = "customer_deactivated"
    CUSTOMER_ACTIVATED = "customer_activated"
    CUSTOMER_CREDIT_LIMIT_CHANGED = "customer_credit_limit_changed"
    CUSTOMER_CREDIT_HOLD_CHANGED = "customer_credit_hold_changed"
    CUSTOMER_RISK_SCORE_CHANGED = "customer_risk_score_changed"
    CUSTOMER_TAX_STATUS_CHANGED = "customer_tax_status_changed"
    CUSTOMER_BALANCE_UPDATED = "customer_balance_updated"
    CUSTOMER_PURCHASE_RECORDED = "customer_purchase_recorded"
    CUSTOMER_PAYMENT_RECORDED = "customer_payment_recorded"

    # Supplier
    SUPPLIER_CREATED = "supplier_created"
    SUPPLIER_UPDATED = "supplier_updated"
    SUPPLIER_STATUS_CHANGED = "supplier_status_changed"
    SUPPLIER_BLOCKED = "supplier_blocked"
    SUPPLIER_UNBLOCKED = "supplier_unblocked"
    SUPPLIER_DEACTIVATED = "supplier_deactivated"
    SUPPLIER_ACTIVATED = "supplier_activated"
    SUPPLIER_PAYMENT_TERMS_CHANGED = "supplier_payment_terms_changed"
    SUPPLIER_WITHHOLDING_CATEGORY_CHANGED = "supplier_withholding_category_changed"
    SUPPLIER_BALANCE_UPDATED = "supplier_balance_updated"

    # Employee
    EMPLOYEE_CREATED = "employee_created"
    EMPLOYEE_UPDATED = "employee_updated"
    EMPLOYEE_STATUS_CHANGED = "employee_status_changed"
    EMPLOYEE_RESIGNED = "employee_resigned"
    EMPLOYEE_TERMINATED = "employee_terminated"
    EMPLOYEE_REACTIVATED = "employee_reactivated"
    EMPLOYEE_PTKP_UPDATED = "employee_ptkp_updated"
    EMPLOYEE_BPJS_UPDATED = "employee_bpjs_updated"
    EMPLOYEE_SALARY_UPDATED = "employee_salary_updated"
    EMPLOYEE_DEPARTMENT_CHANGED = "employee_department_changed"


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event. IMMUTABLE.

    Field:
        event_id: UUID unik event.
        event_type: Jenis event.
        aggregate_id: UUID agregat.
        aggregate_type: Tipe agregat.
        aggregate_version: Versi agregat (>= 1).
        occurred_at: Waktu kejadian (UTC).
        event_data: Payload event (dict, JSON-safe).
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
        causation_id: ID penyebab event (opsional).
    """

    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_type: str = "CustomerSupplierEmployee"
    aggregate_version: int = 1
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=UTC))

    # ==================== Serialization ====================

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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """
        Rekonstruksi event dari dict. Jika event_type terdaftar di registry,
        akan mengembalikan subclass spesifiknya; jika tidak, DomainEvent generik.
        """
        event_type_value = data["event_type"]
        try:
            event_type = DomainEventType(event_type_value)
        except ValueError:
            # Event type tidak dikenal -> kembalikan DomainEvent generik
            return cls(
                event_id=UUID(data["event_id"]),
                event_type=DomainEventType.CUSTOMER_UPDATED,  # fallback placeholder
                aggregate_id=UUID(data["aggregate_id"]),
                aggregate_type=data.get("aggregate_type", "CustomerSupplierEmployee"),
                aggregate_version=data.get("aggregate_version", 1),
                occurred_at=datetime.fromisoformat(data["occurred_at"]),
                event_data=data.get("event_data", {}),
                user_id=data.get("user_id"),
                correlation_id=data.get("correlation_id"),
                causation_id=data.get("causation_id"),
            )

        subclass = _EVENT_REGISTRY.get(event_type)
        if subclass is not None and subclass is not DomainEvent:
            # Bangun instance subclass via konstruktor dataclass generik
            return subclass(
                event_id=UUID(data["event_id"]),
                event_type=event_type,
                aggregate_id=UUID(data["aggregate_id"]),
                aggregate_type=data.get("aggregate_type", "CustomerSupplierEmployee"),
                aggregate_version=data.get("aggregate_version", 1),
                occurred_at=datetime.fromisoformat(data["occurred_at"]),
                event_data=data.get("event_data", {}),
                user_id=data.get("user_id"),
                correlation_id=data.get("correlation_id"),
                causation_id=data.get("causation_id"),
            )

        return cls(
            event_id=UUID(data["event_id"]),
            event_type=event_type,
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "CustomerSupplierEmployee"),
            aggregate_version=data.get("aggregate_version", 1),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        return cls.from_dict(json.loads(json_str))

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# Event Registry
# ============================================================================


_EVENT_REGISTRY: dict[DomainEventType, type[DomainEvent]] = {}


def _register_event(event_cls: type[DomainEvent]) -> type[DomainEvent]:
    """Decorator/utility untuk mendaftarkan event class ke registry."""
    ev_type = getattr(event_cls, "_EVENT_TYPE", None)
    if ev_type is not None:
        _EVENT_REGISTRY[ev_type] = event_cls
    return event_cls


# ============================================================================
# Customer Events
# ============================================================================


@dataclass(frozen=True)
class CustomerCreatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika customer baru dibuat.

    Catatan: Gunakan classmethod `create()` untuk membuat instance dari
    CustomerEntity, atau konstruktor dataclass langsung untuk rekonstruksi.
    """
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.CUSTOMER_CREATED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        customer: Any,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> CustomerCreatedEvent:
        event_data = {
            "customer_id": str(customer.customer_id),
            "customer_code": customer.customer_code,
            "customer_name": customer.customer_name,
            "customer_type": customer.customer_type.value,
            "segment": customer.segment.value,
            "status": customer.status.value,
            "tax_id": customer.tax_id,
            "email": customer.email,
            "credit_limit_amount": str(customer.credit_limit.amount),
            "credit_limit_currency": customer.credit_limit.currency,
            "payment_term_days": customer.payment_term.value,
            "created_by": created_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CustomerStatusChangedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.CUSTOMER_STATUS_CHANGED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        customer_id: UUID,
        customer_code: str,
        old_status: Any,
        new_status: Any,
        reason: str | None,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> CustomerStatusChangedEvent:
        event_data = {
            "customer_id": str(customer_id),
            "customer_code": customer_code,
            "old_status": old_status.value if hasattr(old_status, "value") else str(old_status),
            "new_status": new_status.value if hasattr(new_status, "value") else str(new_status),
            "reason": reason,
            "changed_by": changed_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CustomerCreditLimitChangedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.CUSTOMER_CREDIT_LIMIT_CHANGED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        customer_id: UUID,
        customer_code: str,
        old_limit: Any,
        new_limit: Any,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> CustomerCreditLimitChangedEvent:
        event_data = {
            "customer_id": str(customer_id),
            "customer_code": customer_code,
            "old_limit_amount": str(getattr(old_limit, "amount", old_limit)),
            "old_limit_currency": getattr(old_limit, "currency", "IDR"),
            "new_limit_amount": str(getattr(new_limit, "amount", new_limit)),
            "new_limit_currency": getattr(new_limit, "currency", "IDR"),
            "changed_by": changed_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class CustomerBalanceUpdatedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.CUSTOMER_BALANCE_UPDATED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        customer_id: UUID,
        customer_code: str,
        old_balance: Decimal,
        new_balance: Decimal,
        delta: Decimal,
        transaction_type: str,
        transaction_id: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> CustomerBalanceUpdatedEvent:
        event_data = {
            "customer_id": str(customer_id),
            "customer_code": customer_code,
            "old_balance": str(old_balance),
            "new_balance": str(new_balance),
            "delta": str(delta),
            "transaction_type": transaction_type,
            "transaction_id": transaction_id,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Supplier Events
# ============================================================================


@dataclass(frozen=True)
class SupplierCreatedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.SUPPLIER_CREATED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        supplier: Any,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> SupplierCreatedEvent:
        event_data = {
            "supplier_id": str(supplier.supplier_id),
            "supplier_code": supplier.supplier_code,
            "supplier_name": supplier.supplier_name,
            "supplier_type": supplier.supplier_type.value,
            "status": supplier.status.value,
            "tax_id": supplier.tax_id,
            "email": supplier.email,
            "payment_terms_days": supplier.payment_terms_days,
            "withholding_article": supplier.withholding_category.article.value,
            "withholding_rate": str(supplier.withholding_category.rate),
            "created_by": created_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class SupplierPaymentTermsChangedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.SUPPLIER_PAYMENT_TERMS_CHANGED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        supplier_id: UUID,
        supplier_code: str,
        old_terms: int,
        new_terms: int,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> SupplierPaymentTermsChangedEvent:
        event_data = {
            "supplier_id": str(supplier_id),
            "supplier_code": supplier_code,
            "old_payment_terms_days": old_terms,
            "new_payment_terms_days": new_terms,
            "changed_by": changed_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class SupplierWithholdingCategoryChangedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = (
        DomainEventType.SUPPLIER_WITHHOLDING_CATEGORY_CHANGED
    )

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        supplier_id: UUID,
        supplier_code: str,
        old_article: str,
        new_article: str,
        old_rate: float,
        new_rate: float,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> SupplierWithholdingCategoryChangedEvent:
        event_data = {
            "supplier_id": str(supplier_id),
            "supplier_code": supplier_code,
            "old_withholding_article": old_article,
            "new_withholding_article": new_article,
            "old_withholding_rate": old_rate,
            "new_withholding_rate": new_rate,
            "changed_by": changed_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Employee Events
# ============================================================================


@dataclass(frozen=True)
class EmployeeCreatedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.EMPLOYEE_CREATED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        employee_id: UUID,
        employee_code: str,
        employee_name: str,
        legal_entity_id: UUID,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> EmployeeCreatedEvent:
        event_data = {
            "employee_id": str(employee_id),
            "employee_code": employee_code,
            "employee_name": employee_name,
            "legal_entity_id": str(legal_entity_id),
            "created_by": created_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class EmployeeResignedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.EMPLOYEE_RESIGNED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        employee_id: UUID,
        employee_number: str,
        full_name: str,
        resign_date: date,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> EmployeeResignedEvent:
        event_data = {
            "employee_id": str(employee_id),
            "employee_number": employee_number,
            "full_name": full_name,
            "resign_date": resign_date.isoformat(),
            "reason": reason,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class EmployeePTKPUpdatedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.EMPLOYEE_PTKP_UPDATED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        employee_id: UUID,
        employee_number: str,
        old_ptkp: Any,
        new_ptkp: Any,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> EmployeePTKPUpdatedEvent:
        old_status_code = getattr(old_ptkp, "status_code", str(old_ptkp))
        old_ptkp_amount = getattr(old_ptkp, "amount", 0)
        new_status_code = getattr(new_ptkp, "status_code", str(new_ptkp))
        new_ptkp_amount = getattr(new_ptkp, "amount", 0)

        event_data = {
            "employee_id": str(employee_id),
            "employee_number": employee_number,
            "old_ptkp_status": old_status_code,
            "old_ptkp_amount": str(old_ptkp_amount),
            "new_ptkp_status": new_status_code,
            "new_ptkp_amount": str(new_ptkp_amount),
            "updated_by": updated_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class EmployeeBPJSUpdatedEvent(DomainEvent):
    _EVENT_TYPE: ClassVar[DomainEventType] = DomainEventType.EMPLOYEE_BPJS_UPDATED

    @classmethod
    def create(
        cls,
        aggregate_id: UUID,
        aggregate_version: int,
        employee_id: UUID,
        employee_number: str,
        bpjs_type: str,
        membership_number: str,
        is_active: bool,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> EmployeeBPJSUpdatedEvent:
        event_data = {
            "employee_id": str(employee_id),
            "employee_number": employee_number,
            "bpjs_type": bpjs_type,
            "membership_number": membership_number,
            "is_active": is_active,
            "updated_by": updated_by,
        }
        return cls(
            event_id=uuid4(),
            event_type=cls._EVENT_TYPE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# Register semua event class
_register_event(CustomerCreatedEvent)
_register_event(CustomerStatusChangedEvent)
_register_event(CustomerCreditLimitChangedEvent)
_register_event(CustomerBalanceUpdatedEvent)
_register_event(SupplierCreatedEvent)
_register_event(SupplierPaymentTermsChangedEvent)
_register_event(SupplierWithholdingCategoryChangedEvent)
_register_event(EmployeeCreatedEvent)
_register_event(EmployeeResignedEvent)
_register_event(EmployeePTKPUpdatedEvent)
_register_event(EmployeeBPJSUpdatedEvent)


# ============================================================================
# Backward-compatible aliases (nama lama tetap bekerja)
# ============================================================================

CustomerCreated = CustomerCreatedEvent
CustomerStatusChanged = CustomerStatusChangedEvent
CustomerCreditLimitChanged = CustomerCreditLimitChangedEvent
CustomerBalanceUpdated = CustomerBalanceUpdatedEvent

SupplierCreated = SupplierCreatedEvent
SupplierPaymentTermsChanged = SupplierPaymentTermsChangedEvent
SupplierWithholdingCategoryChanged = SupplierWithholdingCategoryChangedEvent

EmployeeCreated = EmployeeCreatedEvent
EmployeeResigned = EmployeeResignedEvent
EmployeePTKPUpdated = EmployeePTKPUpdatedEvent
EmployeeBPJSUpdated = EmployeeBPJSUpdatedEvent


# ============================================================================
# Domain Event Publisher
# ============================================================================


class DomainEventPublisher:
    """
    Publisher in-memory untuk testing. Untuk production, pakai implementasi
    outbox via EventPublisherPort.
    """
    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        cls._published_events.append(event)
        logger.info(
            f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}"
        )

    @classmethod
    async def publish_many(cls, events: list[DomainEvent]) -> None:
        for event in events:
            await cls.publish(event)

    @classmethod
    def get_published_events(cls) -> list[DomainEvent]:
        return cls._published_events.copy()

    @classmethod
    def clear(cls) -> None:
        cls._published_events.clear()


# ============================================================================
# Helper Functions
# ============================================================================


def deserialize_event(data: str | bytes) -> DomainEvent:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return DomainEvent.from_json(data)


def serialize_event(event: DomainEvent) -> str:
    return event.to_json()


__all__ = [
    "CustomerBalanceUpdated",
    "CustomerBalanceUpdatedEvent",
    "CustomerCreated",
    "CustomerCreatedEvent",
    "CustomerCreditLimitChanged",
    "CustomerCreditLimitChangedEvent",
    "CustomerStatusChanged",
    "CustomerStatusChangedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "EmployeeBPJSUpdated",
    "EmployeeBPJSUpdatedEvent",
    "EmployeeCreated",
    "EmployeeCreatedEvent",
    "EmployeePTKPUpdated",
    "EmployeePTKPUpdatedEvent",
    "EmployeeResigned",
    "EmployeeResignedEvent",
    "SupplierCreated",
    "SupplierCreatedEvent",
    "SupplierPaymentTermsChanged",
    "SupplierPaymentTermsChangedEvent",
    "SupplierWithholdingCategoryChanged",
    "SupplierWithholdingCategoryChangedEvent",
    "deserialize_event",
    "serialize_event",
]
