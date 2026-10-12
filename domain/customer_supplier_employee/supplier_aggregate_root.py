#!/usr/bin/env python3
"""
Module: supplier_aggregate_root.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Aggregate root untuk Supplier management (domain murni).

PERBAIKAN (2026-10-12):
- _events, _audit_trail, _snapshots dari ClassVar -> instance field.
- SupplierAggregateRepository (in-memory) DIHAPUS dari file ini.
  Implementasi nyata ada di adapter SQLAlchemy.
- Immutable-style: setiap mutation mengembalikan instance baru.

Catatan: File ini HANYA berisi domain logic. Tidak ada repository
implementasi nyata di sini.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.customer_supplier_employee.domain_events import (
    DomainEvent,
    SupplierCreatedEvent,
    SupplierPaymentTermsChangedEvent,
    SupplierWithholdingCategoryChangedEvent,
)
from domain.customer_supplier_employee.supplier_entity import (
    SupplierEntity,
    SupplierStatus,
    SupplierType,
)
from domain.customer_supplier_employee.supplier_withholding_category_vo import (
    SupplierWithholdingCategoryVO,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class SupplierAggregateError(ValueError):
    pass


class DuplicateSupplierCodeError(SupplierAggregateError):
    pass


class DuplicateSupplierTaxIdError(SupplierAggregateError):
    pass


class SupplierNotFoundError(SupplierAggregateError):
    pass


class InvalidSupplierStatusTransitionError(SupplierAggregateError):
    pass


class InvalidPaymentTermsError(SupplierAggregateError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_supplier_code_unique(
    code: str, existing_codes: set[str], exclude_id: UUID | None = None
) -> None:
    if code in existing_codes:
        raise DuplicateSupplierCodeError(f"Supplier code '{code}' already exists")


def _validate_tax_id_unique(
    tax_id: str | None,
    existing_tax_ids: dict[str, UUID],
    exclude_id: UUID | None = None,
) -> None:
    if tax_id is None:
        return
    existing_owner = existing_tax_ids.get(tax_id)
    if existing_owner is not None and (
        exclude_id is None or existing_owner != exclude_id
    ):
        raise DuplicateSupplierTaxIdError(f"Tax ID '{tax_id}' already exists")


def _validate_payment_terms(days: int) -> None:
    if days < 0:
        raise InvalidPaymentTermsError(f"Payment terms cannot be negative: {days}")
    if days > 180:
        raise InvalidPaymentTermsError(f"Payment terms cannot exceed 180 days: {days}")


def _validate_status_transition(current: SupplierStatus, new: SupplierStatus) -> None:
    allowed = {
        SupplierStatus.ACTIVE: {
            SupplierStatus.INACTIVE,
            SupplierStatus.BLOCKED,
            SupplierStatus.SUSPENDED,
            SupplierStatus.BLACKLISTED,
        },
        SupplierStatus.INACTIVE: {SupplierStatus.ACTIVE},
        SupplierStatus.BLOCKED: {
            SupplierStatus.ACTIVE,
            SupplierStatus.INACTIVE,
            SupplierStatus.BLACKLISTED,
        },
        SupplierStatus.SUSPENDED: {
            SupplierStatus.ACTIVE,
            SupplierStatus.INACTIVE,
            SupplierStatus.BLOCKED,
        },
        SupplierStatus.BLACKLISTED: set(),
        SupplierStatus.DRAFT: {SupplierStatus.ACTIVE, SupplierStatus.INACTIVE},
    }
    if new not in allowed.get(current, set()):
        raise InvalidSupplierStatusTransitionError(
            f"Cannot transition from {current.display_name()} to {new.display_name()}"
        )


# ============================================================================
# Supplier Aggregate Root
# ============================================================================


@dataclass
class SupplierAggregate:
    aggregate_id: UUID
    legal_entity_id: UUID
    suppliers: dict[UUID, SupplierEntity] = field(default_factory=dict)
    supplier_by_code: dict[str, UUID] = field(default_factory=dict)
    supplier_by_tax_id: dict[str, UUID] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    # Instance-level (bukan ClassVar!)
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        self._take_snapshot()

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "supplier_count": len(self.suppliers),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(
        self, action: str, performed_by: str, details: dict[str, Any]
    ) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "details": details,
        }
        self._audit_trail.append(entry)
        if len(self._audit_trail) > 1000:
            self._audit_trail.pop(0)

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    # ==================== EVENT METHODS ====================

    def register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    def apply(self, event: DomainEvent) -> None:
        """Event sourcing placeholder."""
        self._events.append(event)

    # ==================== QUERY METHODS ====================

    def get_supplier(self, supplier_id: UUID) -> SupplierEntity | None:
        return self.suppliers.get(supplier_id)

    def get_supplier_by_code(self, supplier_code: str) -> SupplierEntity | None:
        supp_id = self.supplier_by_code.get(supplier_code)
        return self.suppliers.get(supp_id) if supp_id else None

    def get_supplier_by_tax_id(self, tax_id: str) -> SupplierEntity | None:
        supp_id = self.supplier_by_tax_id.get(tax_id)
        return self.suppliers.get(supp_id) if supp_id else None

    def get_all_suppliers(self) -> list[SupplierEntity]:
        return list(self.suppliers.values())

    def get_active_suppliers(self) -> list[SupplierEntity]:
        return [s for s in self.suppliers.values() if s.status == SupplierStatus.ACTIVE]

    def get_suppliers_by_type(self, supplier_type: SupplierType) -> list[SupplierEntity]:
        return [s for s in self.suppliers.values() if s.supplier_type == supplier_type]

    def get_suppliers_by_status(self, status: SupplierStatus) -> list[SupplierEntity]:
        return [s for s in self.suppliers.values() if s.status == status]

    def get_suppliers_with_withholding(self) -> list[SupplierEntity]:
        return [
            s for s in self.suppliers.values() if s.withholding_category.should_withhold
        ]

    def get_total_outstanding_balance(self) -> Decimal:
        return sum(
            (s.outstanding_balance for s in self.suppliers.values()), Decimal("0")
        )

    def get_total_purchases(self) -> Decimal:
        return sum((s.total_purchases for s in self.suppliers.values()), Decimal("0"))

    def get_supplier_count(self) -> int:
        return len(self.suppliers)

    def get_active_supplier_count(self) -> int:
        return len(self.get_active_suppliers())

    def code_exists(self, supplier_code: str) -> bool:
        return supplier_code in self.supplier_by_code

    def tax_id_exists(self, tax_id: str) -> bool:
        return tax_id in self.supplier_by_tax_id

    # ==================== COMMAND METHODS ====================

    def add_supplier(
        self, supplier: SupplierEntity, created_by: str
    ) -> SupplierAggregate:
        if supplier.supplier_id in self.suppliers:
            raise SupplierAggregateError(
                f"Supplier {supplier.supplier_id} already exists"
            )
        _validate_supplier_code_unique(
            supplier.supplier_code, set(self.supplier_by_code.keys())
        )
        _validate_tax_id_unique(supplier.tax_id, self.supplier_by_tax_id)
        _validate_payment_terms(supplier.payment_terms_days)
        if supplier.version != 1:
            raise ValueError("New supplier must have version 1")

        new_suppliers = dict(self.suppliers)
        new_suppliers[supplier.supplier_id] = supplier
        new_by_code = dict(self.supplier_by_code)
        new_by_code[supplier.supplier_code] = supplier.supplier_id
        new_by_tax_id = dict(self.supplier_by_tax_id)
        if supplier.tax_id:
            new_by_tax_id[supplier.tax_id] = supplier.supplier_id

        self._register_event(
            SupplierCreatedEvent.create(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                supplier=supplier,
                created_by=created_by,
            )
        )

        return SupplierAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            suppliers=new_suppliers,
            supplier_by_code=new_by_code,
            supplier_by_tax_id=new_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            _events=self._events.copy(),
            _audit_trail=self._audit_trail.copy(),
            _snapshots=self._snapshots.copy(),
        )

    def update_supplier(
        self, supplier: SupplierEntity, updated_by: str
    ) -> SupplierAggregate:
        if supplier.supplier_id not in self.suppliers:
            raise SupplierNotFoundError(f"Supplier {supplier.supplier_id} not found")
        old_supplier = self.suppliers[supplier.supplier_id]

        if supplier.supplier_code != old_supplier.supplier_code:
            _validate_supplier_code_unique(
                supplier.supplier_code,
                set(self.supplier_by_code.keys()),
                exclude_id=supplier.supplier_id,
            )
        if supplier.tax_id != old_supplier.tax_id:
            _validate_tax_id_unique(
                supplier.tax_id,
                self.supplier_by_tax_id,
                exclude_id=supplier.supplier_id,
            )
        _validate_payment_terms(supplier.payment_terms_days)
        if supplier.version <= old_supplier.version:
            raise ValueError(
                f"Version mismatch: current {old_supplier.version}, "
                f"provided {supplier.version}"
            )

        new_suppliers = dict(self.suppliers)
        new_suppliers[supplier.supplier_id] = supplier
        new_by_code = dict(self.supplier_by_code)
        if supplier.supplier_code != old_supplier.supplier_code:
            new_by_code.pop(old_supplier.supplier_code, None)
            new_by_code[supplier.supplier_code] = supplier.supplier_id
        new_by_tax_id = dict(self.supplier_by_tax_id)
        if old_supplier.tax_id:
            new_by_tax_id.pop(old_supplier.tax_id, None)
        if supplier.tax_id:
            new_by_tax_id[supplier.tax_id] = supplier.supplier_id

        return SupplierAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            suppliers=new_suppliers,
            supplier_by_code=new_by_code,
            supplier_by_tax_id=new_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            _events=self._events.copy(),
            _audit_trail=self._audit_trail.copy(),
            _snapshots=self._snapshots.copy(),
        )

    def update_supplier_status(
        self,
        supplier_id: UUID,
        new_status: SupplierStatus,
        updated_by: str,
        reason: str | None = None,
    ) -> SupplierAggregate:
        supplier = self.get_supplier(supplier_id)
        if supplier is None:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        _validate_status_transition(supplier.status, new_status)

        if new_status == SupplierStatus.BLOCKED:
            updated = supplier.block(updated_by, reason or "No reason")
        elif new_status == SupplierStatus.ACTIVE:
            if supplier.status == SupplierStatus.BLOCKED:
                updated = supplier.unblock(updated_by)
            else:
                updated = supplier.activate(updated_by)
        elif new_status == SupplierStatus.INACTIVE:
            updated = supplier.deactivate(updated_by)
        elif new_status == SupplierStatus.BLACKLISTED:
            updated = supplier.blacklist(updated_by, reason or "No reason")
        elif new_status == SupplierStatus.SUSPENDED:
            updated = supplier.suspend(updated_by, reason or "Suspended")
        else:
            updated = supplier  # fallback: no-op

        return self.update_supplier(updated, updated_by)

    def update_supplier_payment_terms(
        self, supplier_id: UUID, new_payment_terms_days: int, updated_by: str
    ) -> SupplierAggregate:
        supplier = self.get_supplier(supplier_id)
        if supplier is None:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        _validate_payment_terms(new_payment_terms_days)
        updated = supplier.update_payment_terms(new_payment_terms_days, updated_by)
        self._register_event(
            SupplierPaymentTermsChangedEvent.create(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                supplier_id=supplier.supplier_id,
                supplier_code=supplier.supplier_code,
                old_terms=supplier.payment_terms_days,
                new_terms=new_payment_terms_days,
                changed_by=updated_by,
            )
        )
        return self.update_supplier(updated, updated_by)

    def update_supplier_withholding_category(
        self,
        supplier_id: UUID,
        new_category: SupplierWithholdingCategoryVO,
        updated_by: str,
    ) -> SupplierAggregate:
        supplier = self.get_supplier(supplier_id)
        if supplier is None:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        old_article = supplier.withholding_category.article.value
        new_article = new_category.article.value
        updated = supplier.update_withholding_category(new_category, updated_by)
        self._register_event(
            SupplierWithholdingCategoryChangedEvent.create(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                supplier_id=supplier.supplier_id,
                supplier_code=supplier.supplier_code,
                old_article=old_article,
                new_article=new_article,
                old_rate=float(supplier.withholding_category.rate),
                new_rate=float(new_category.rate),
                changed_by=updated_by,
            )
        )
        return self.update_supplier(updated, updated_by)

    def record_supplier_purchase(
        self, supplier_id: UUID, amount: Decimal, transaction_date: date | None = None
    ) -> SupplierAggregate:
        supplier = self.get_supplier(supplier_id)
        if supplier is None:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        if amount <= 0:
            raise ValueError("Purchase amount must be positive")
        updated = supplier.record_purchase(amount, transaction_date)
        return self.update_supplier(updated, "system")

    def record_supplier_payment(
        self, supplier_id: UUID, amount: Decimal, payment_date: date | None = None
    ) -> SupplierAggregate:
        supplier = self.get_supplier(supplier_id)
        if supplier is None:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        updated = supplier.record_payment(amount, payment_date)
        return self.update_supplier(updated, "system")

    def remove_supplier(self, supplier_id: UUID, deleted_by: str) -> SupplierAggregate:
        supplier = self.get_supplier(supplier_id)
        if supplier is None:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        if supplier.outstanding_balance > 0:
            raise SupplierAggregateError(
                f"Cannot delete supplier with outstanding balance "
                f"{supplier.outstanding_balance}"
            )
        updated = supplier.deactivate(deleted_by)
        return self.update_supplier(updated, deleted_by)

    # ==================== STATISTICS ====================

    def get_statistics(self) -> dict[str, Any]:
        total = self.get_supplier_count()
        active = self.get_active_supplier_count()
        status_counts = {
            s.value: len(self.get_suppliers_by_status(s)) for s in SupplierStatus
        }
        return {
            "total_suppliers": total,
            "active_suppliers": active,
            "inactive_suppliers": total - active,
            "status_distribution": status_counts,
            "total_outstanding_balance": str(self.get_total_outstanding_balance()),
            "total_lifetime_purchases": str(self.get_total_purchases()),
        }

    # ==================== SERIALIZATION ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "suppliers": [s.to_dict() for s in self.suppliers.values()],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SupplierAggregate:
        suppliers: dict[UUID, SupplierEntity] = {}
        for supp_data in data.get("suppliers", []):
            supp = SupplierEntity.from_dict(supp_data)
            suppliers[supp.supplier_id] = supp
        return cls(
            aggregate_id=UUID(data["aggregate_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            suppliers=suppliers,
            supplier_by_code={
                s.supplier_code: s.supplier_id for s in suppliers.values()
            },
            supplier_by_tax_id={
                s.tax_id: s.supplier_id for s in suppliers.values() if s.tax_id
            },
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "supplier_count": len(self.suppliers),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SupplierAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("TOUCH", touched_by, {})
        return new_agg

    def _copy(self) -> SupplierAggregate:
        return SupplierAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            suppliers=self.suppliers.copy(),
            supplier_by_code=self.supplier_by_code.copy(),
            supplier_by_tax_id=self.supplier_by_tax_id.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
            _events=self._events.copy(),
            _audit_trail=self._audit_trail.copy(),
            _snapshots=self._snapshots.copy(),
        )

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create_aggregate(
        cls, legal_entity_id: UUID, created_by: str = "system"
    ) -> SupplierAggregate:
        agg = cls(
            aggregate_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        agg._record_audit(
            "CREATE", created_by, {"legal_entity_id": str(legal_entity_id)}
        )
        return agg

    @classmethod
    def from_events(cls, events: list[DomainEvent]) -> SupplierAggregate:
        if not events:
            raise ValueError("No events provided")
        first_event = events[0]
        aggregate_id = first_event.aggregate_id
        legal_entity_id_str = first_event.event_data.get("legal_entity_id")
        legal_entity_id = (
            UUID(legal_entity_id_str) if legal_entity_id_str else uuid4()
        )
        agg = cls(
            aggregate_id=aggregate_id,
            legal_entity_id=legal_entity_id,
            suppliers={},
            supplier_by_code={},
            supplier_by_tax_id={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        for event in events:
            agg.apply(event)
        agg.version = len(events)
        return agg


__all__ = [
    "DuplicateSupplierCodeError",
    "DuplicateSupplierTaxIdError",
    "InvalidPaymentTermsError",
    "InvalidSupplierStatusTransitionError",
    "SupplierAggregate",
    "SupplierAggregateError",
    "SupplierNotFoundError",
]
