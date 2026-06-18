#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Domain events untuk Customer, Supplier, Employee aggregates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.customer_supplier_employee.customer_entity import CustomerEntity, CustomerStatus
from domain.customer_supplier_employee.employee_entity import EmployeeEntity
from domain.customer_supplier_employee.employee_ptkp_status_vo import EmployeePTKPStatusVO
from domain.customer_supplier_employee.supplier_entity import SupplierEntity

# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
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


@dataclass
class DomainEvent:
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

    # ==================== SERIALIZATION METHODS ====================

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
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
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
# Customer Events
# ============================================================================


@dataclass
class CustomerCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        customer: CustomerEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
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
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CUSTOMER_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CustomerStatusChangedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        customer_id: UUID,
        customer_code: str,
        old_status: CustomerStatus,
        new_status: CustomerStatus,
        reason: str | None,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "customer_id": str(customer_id),
            "customer_code": customer_code,
            "old_status": old_status.value,
            "new_status": new_status.value,
            "reason": reason,
            "changed_by": changed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CUSTOMER_STATUS_CHANGED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CustomerCreditLimitChangedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        customer_id: UUID,
        customer_code: str,
        old_limit: Any,  # CustomerCreditLimitVO
        new_limit: Any,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "customer_id": str(customer_id),
            "customer_code": customer_code,
            "old_limit_amount": str(old_limit.amount)
            if hasattr(old_limit, "amount")
            else str(old_limit),
            "old_limit_currency": getattr(old_limit, "currency", "IDR"),
            "new_limit_amount": str(new_limit.amount)
            if hasattr(new_limit, "amount")
            else str(new_limit),
            "new_limit_currency": getattr(new_limit, "currency", "IDR"),
            "changed_by": changed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CUSTOMER_CREDIT_LIMIT_CHANGED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CustomerBalanceUpdatedEvent(DomainEvent):
    def __init__(
        self,
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
    ):
        event_data = {
            "customer_id": str(customer_id),
            "customer_code": customer_code,
            "old_balance": str(old_balance),
            "new_balance": str(new_balance),
            "delta": str(delta),
            "transaction_type": transaction_type,
            "transaction_id": transaction_id,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CUSTOMER_BALANCE_UPDATED,
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


@dataclass
class SupplierCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        supplier: SupplierEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
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
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SUPPLIER_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class SupplierPaymentTermsChangedEvent(DomainEvent):
    def __init__(
        self,
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
    ):
        event_data = {
            "supplier_id": str(supplier_id),
            "supplier_code": supplier_code,
            "old_payment_terms_days": old_terms,
            "new_payment_terms_days": new_terms,
            "changed_by": changed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SUPPLIER_PAYMENT_TERMS_CHANGED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class SupplierWithholdingCategoryChangedEvent(DomainEvent):
    def __init__(
        self,
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
    ):
        event_data = {
            "supplier_id": str(supplier_id),
            "supplier_code": supplier_code,
            "old_withholding_article": old_article,
            "new_withholding_article": new_article,
            "old_withholding_rate": old_rate,
            "new_withholding_rate": new_rate,
            "changed_by": changed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SUPPLIER_WITHHOLDING_CATEGORY_CHANGED,
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


@dataclass
class EmployeeCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        employee: EmployeeEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "employee_id": str(employee.employee_id),
            "employee_number": employee.employee_number,
            "full_name": employee.full_name,
            "employee_type": employee.employee_type.value,
            "gender": employee.gender.value,
            "department": employee.department,
            "position": employee.position,
            "join_date": employee.join_date.isoformat(),
            "basic_salary": str(employee.basic_salary),
            "currency": employee.currency,
            "ptkp_status": employee.ptkp_status.get_status_code(),
            "bpjs_health_membership": employee.bpjs_health.membership_number,
            "bpjs_employment_membership": employee.bpjs_employment.membership_number,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.EMPLOYEE_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class EmployeeResignedEvent(DomainEvent):
    def __init__(
        self,
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
    ):
        event_data = {
            "employee_id": str(employee_id),
            "employee_number": employee_number,
            "full_name": full_name,
            "resign_date": resign_date.isoformat(),
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.EMPLOYEE_RESIGNED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class EmployeePTKPUpdatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        employee_id: UUID,
        employee_number: str,
        old_ptkp: EmployeePTKPStatusVO,
        new_ptkp: EmployeePTKPStatusVO,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "employee_id": str(employee_id),
            "employee_number": employee_number,
            "old_ptkp_status": old_ptkp.get_status_code(),
            "old_ptkp_amount": old_ptkp.get_ptkp_amount(),
            "new_ptkp_status": new_ptkp.get_status_code(),
            "new_ptkp_amount": new_ptkp.get_ptkp_amount(),
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.EMPLOYEE_PTKP_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class EmployeeBPJSUpdatedEvent(DomainEvent):
    def __init__(
        self,
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
    ):
        event_data = {
            "employee_id": str(employee_id),
            "employee_number": employee_number,
            "bpjs_type": bpjs_type,
            "membership_number": membership_number,
            "is_active": is_active,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.EMPLOYEE_BPJS_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Short Aliases for Backward Compatibility
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
# Domain Event Publisher (Real Implementation)
# ============================================================================


class DomainEventPublisher:
    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        cls._published_events.append(event)
        logger.info(f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}")

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
    "DomainEventType",
    "DomainEvent",
    "DomainEventPublisher",
    # Customer events
    "CustomerCreatedEvent",
    "CustomerStatusChangedEvent",
    "CustomerCreditLimitChangedEvent",
    "CustomerBalanceUpdatedEvent",
    "CustomerCreated",
    "CustomerStatusChanged",
    "CustomerCreditLimitChanged",
    "CustomerBalanceUpdated",
    # Supplier events
    "SupplierCreatedEvent",
    "SupplierPaymentTermsChangedEvent",
    "SupplierWithholdingCategoryChangedEvent",
    "SupplierCreated",
    "SupplierPaymentTermsChanged",
    "SupplierWithholdingCategoryChanged",
    # Employee events
    "EmployeeCreatedEvent",
    "EmployeeResignedEvent",
    "EmployeePTKPUpdatedEvent",
    "EmployeeBPJSUpdatedEvent",
    "EmployeeCreated",
    "EmployeeResigned",
    "EmployeePTKPUpdated",
    "EmployeeBPJSUpdated",
    # Helpers
    "deserialize_event",
    "serialize_event",
]
