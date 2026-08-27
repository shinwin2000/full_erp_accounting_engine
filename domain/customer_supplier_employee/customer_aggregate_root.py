#!/usr/bin/env python3
"""
Module: customer_aggregate_root.py
Layer: Domain / Customer, Supplier, Employee
Responsibility: Aggregate root untuk Customer management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.customer_supplier_employee.customer_credit_limit_vo import (
    CustomerCreditLimitVO,
)
from domain.customer_supplier_employee.customer_entity import (
    CustomerEntity,
    CustomerSegment,
    CustomerStatus,
    CustomerType,
)
from domain.customer_supplier_employee.customer_tax_status_vo import (
    CustomerTaxStatusVO,
)
from domain.customer_supplier_employee.domain_events import (
    CustomerBalanceUpdatedEvent,
    CustomerCreatedEvent,
    CustomerCreditLimitChangedEvent,
    CustomerStatusChangedEvent,
    DomainEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class CustomerAggregateError(ValueError):
    pass


class DuplicateCustomerCodeError(CustomerAggregateError):
    pass


class DuplicateEmailError(CustomerAggregateError):
    pass


class DuplicateTaxIdError(CustomerAggregateError):
    pass


class CustomerNotFoundError(CustomerAggregateError):
    pass


class InvalidCustomerStatusTransitionError(CustomerAggregateError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_customer_code_unique(
    code: str, existing_codes: set[str], exclude_id: UUID | None = None
) -> None:
    if code in existing_codes:
        raise DuplicateCustomerCodeError(f"Customer code '{code}' already exists")


def _validate_email_unique(
    email: str | None, existing_emails: dict[str, UUID], exclude_id: UUID | None = None
) -> None:
    if email is None:
        return
    existing_owner = existing_emails.get(email)
    if existing_owner is not None and (exclude_id is None or existing_owner != exclude_id):
        raise DuplicateEmailError(f"Email '{email}' already exists")


def _validate_tax_id_unique(
    tax_id: str | None, existing_tax_ids: dict[str, UUID], exclude_id: UUID | None = None
) -> None:
    if tax_id is None:
        return
    existing_owner = existing_tax_ids.get(tax_id)
    if existing_owner is not None and (exclude_id is None or existing_owner != exclude_id):
        raise DuplicateTaxIdError(f"Tax ID '{tax_id}' already exists")


def _validate_status_transition(current: CustomerStatus, new: CustomerStatus) -> None:
    allowed = {
        CustomerStatus.DRAFT: {CustomerStatus.ACTIVE, CustomerStatus.INACTIVE},
        CustomerStatus.ACTIVE: {
            CustomerStatus.INACTIVE,
            CustomerStatus.BLOCKED,
            CustomerStatus.SUSPENDED,
        },
        CustomerStatus.INACTIVE: {CustomerStatus.ACTIVE},
        CustomerStatus.BLOCKED: {
            CustomerStatus.ACTIVE,
            CustomerStatus.INACTIVE,
            CustomerStatus.BLACKLISTED,
        },
        CustomerStatus.SUSPENDED: {
            CustomerStatus.ACTIVE,
            CustomerStatus.INACTIVE,
            CustomerStatus.BLOCKED,
        },
        CustomerStatus.BLACKLISTED: set(),
    }
    if new not in allowed.get(current, set()):
        raise InvalidCustomerStatusTransitionError(
            f"Cannot transition from {current.display_name()} to {new.display_name()}"
        )


# ============================================================================
# Customer Aggregate Root
# ============================================================================


@dataclass
class CustomerAggregate:
    aggregate_id: UUID
    legal_entity_id: UUID
    customers: dict[UUID, CustomerEntity] = field(default_factory=dict)
    customer_by_code: dict[str, UUID] = field(default_factory=dict)
    customer_by_email: dict[str, UUID] = field(default_factory=dict)
    customer_by_tax_id: dict[str, UUID] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    # Event sourcing
    _events: ClassVar[list[DomainEvent]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        self._take_snapshot()

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "customer_count": len(self.customers),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    # ==================== ENTITY DASAR METHODS (untuk aggregate) ====================

    def create(self, created_by: str) -> CustomerAggregate:
        self._record_audit("CREATE", created_by, {"legal_entity_id": str(self.legal_entity_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> CustomerAggregate:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("aggregate_id", "created_at", "version"):
                data[key] = value
        new_agg = CustomerAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=UUID(data["legal_entity_id"])
            if "legal_entity_id" in data
            else self.legal_entity_id,
            customers=self.customers,
            customer_by_code=self.customer_by_code,
            customer_by_email=self.customer_by_email,
            customer_by_tax_id=self.customer_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new_agg._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_agg

    def delete(self, deleted_by: str, reason: str | None = None) -> CustomerAggregate:
        if len(self.customers) > 0:
            raise CustomerAggregateError("Cannot delete aggregate with existing customers")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_agg

    def restore(self, restored_by: str) -> CustomerAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("RESTORE", restored_by, {})
        return new_agg

    def activate(self, activated_by: str) -> CustomerAggregate:
        # Activate all customers? Biasanya tidak. Tapi untuk aggregate, kita bisa set status.
        # Untuk contoh, kita tidak melakukan apa-apa.
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ACTIVATE", activated_by, {})
        return new_agg

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CustomerAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_agg

    def lock(self, locked_by: str, reason: str) -> CustomerAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("LOCK", locked_by, {"reason": reason})
        return new_agg

    def unlock(self, unlocked_by: str) -> CustomerAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNLOCK", unlocked_by, {})
        return new_agg

    def validate(self) -> dict[str, Any]:
        errors = []
        if self.aggregate_id != self.legal_entity_id:
            errors.append("Aggregate ID should match legal entity ID")
        # Check duplicate emails across customers
        emails = {}
        for cust in self.customers.values():
            if cust.email:
                if cust.email in emails:
                    errors.append(
                        f"Duplicate email {cust.email} for customers {cust.customer_code} and {emails[cust.email]}"
                    )
                else:
                    emails[cust.email] = cust.customer_code
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "aggregate_id": str(self.aggregate_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "customers": [c.to_dict() for c in self.customers.values()],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomerAggregate:
        customers = {}
        for cust_data in data.get("customers", []):
            cust = CustomerEntity.from_dict(cust_data)
            customers[cust.customer_id] = cust
        return cls(
            aggregate_id=UUID(data["aggregate_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            customers=customers,
            customer_by_code={c.customer_code: c.customer_id for c in customers.values()},
            customer_by_email={c.email: c.customer_id for c in customers.values() if c.email},
            customer_by_tax_id={c.tax_id: c.customer_id for c in customers.values() if c.tax_id},
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )

    def clone(self) -> CustomerAggregate:
        new_id = uuid4()
        new_agg = CustomerAggregate(
            aggregate_id=new_id,
            legal_entity_id=self.legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        # Clone each customer
        for cust in self.customers.values():
            cloned_cust = cust.clone()
            new_agg = new_agg.add_customer(cloned_cust, "system")
        new_agg._record_audit("CLONE", "system", {"source": str(self.aggregate_id)})
        return new_agg

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "customer_count": len(self.customers),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CustomerAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("TOUCH", touched_by, {})
        return new_agg

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, customer: CustomerEntity, created_by: str) -> CustomerAggregate:
        """Add customer as child (alias for add_customer)."""
        return self.add_customer(customer, created_by)

    def remove_child(self, customer_id: UUID, removed_by: str) -> CustomerAggregate:
        """Remove customer."""
        return self.remove_customer(customer_id, removed_by)

    def can_post(self, customer_id: UUID) -> bool:
        """Check if customer can receive posting (invoice)."""
        cust = self.get_customer(customer_id)
        return cust is not None and cust.can_transact()

    def post(
        self, customer_id: UUID, amount: Decimal, posted_by: str, transaction_type: str = "purchase"
    ) -> CustomerAggregate:
        """Post transaction to customer (invoice or payment)."""
        if transaction_type == "purchase":
            return self.record_customer_purchase(customer_id, amount)
        elif transaction_type == "payment":
            return self.record_customer_payment(customer_id, amount)
        else:
            raise ValueError(f"Unknown transaction type: {transaction_type}")

    def can_approve(self, customer_id: UUID, user_role: str = "user") -> bool:
        cust = self.get_customer(customer_id)
        return (
            cust is not None
            and cust.status == CustomerStatus.DRAFT
            and user_role in ("finance_manager", "admin")
        )

    def approve(self, customer_id: UUID, approved_by: str) -> CustomerAggregate:
        if not self.can_approve(customer_id, "finance_manager"):
            raise CustomerAggregateError(f"Cannot approve customer {customer_id}")
        return self.update_customer_status(
            customer_id, CustomerStatus.ACTIVE, approved_by, "Approved"
        )

    def can_reject(self, customer_id: UUID, user_role: str = "user") -> bool:
        cust = self.get_customer(customer_id)
        return (
            cust is not None
            and cust.status == CustomerStatus.DRAFT
            and user_role in ("finance_manager", "admin")
        )

    def reject(self, customer_id: UUID, rejected_by: str, reason: str) -> CustomerAggregate:
        if not self.can_reject(customer_id, "finance_manager"):
            raise CustomerAggregateError(f"Cannot reject customer {customer_id}")
        return self.update_customer_status(
            customer_id, CustomerStatus.INACTIVE, rejected_by, reason
        )

    def can_cancel(self, customer_id: UUID) -> bool:
        cust = self.get_customer(customer_id)
        return cust is not None and cust.status in (CustomerStatus.DRAFT, CustomerStatus.SUSPENDED)

    def cancel(self, customer_id: UUID, cancelled_by: str, reason: str) -> CustomerAggregate:
        if not self.can_cancel(customer_id):
            raise CustomerAggregateError(f"Cannot cancel customer {customer_id}")
        return self.update_customer_status(
            customer_id, CustomerStatus.INACTIVE, cancelled_by, reason
        )

    def can_reverse(self, customer_id: UUID) -> bool:
        return False  # Tidak ada reverse untuk customer

    def reverse(self, customer_id: UUID, reversed_by: str, reason: str) -> CustomerAggregate:
        raise NotImplementedError("Reverse not applicable for customer")

    def can_close(self, customer_id: UUID) -> bool:
        cust = self.get_customer(customer_id)
        return cust is not None and cust.status == CustomerStatus.ACTIVE

    def close(self, customer_id: UUID, closed_by: str, reason: str) -> CustomerAggregate:
        if not self.can_close(customer_id):
            raise CustomerAggregateError(f"Cannot close customer {customer_id}")
        return self.update_customer_status(customer_id, CustomerStatus.INACTIVE, closed_by, reason)

    def can_reopen(self, customer_id: UUID) -> bool:
        cust = self.get_customer(customer_id)
        return cust is not None and cust.status == CustomerStatus.INACTIVE

    def reopen(self, customer_id: UUID, reopened_by: str, reason: str) -> CustomerAggregate:
        if not self.can_reopen(customer_id):
            raise CustomerAggregateError(f"Cannot reopen customer {customer_id}")
        return self.update_customer_status(customer_id, CustomerStatus.ACTIVE, reopened_by, reason)

    def can_archive(self) -> bool:
        return len(self.customers) == 0

    def archive(self, archived_by: str, reason: str | None = None) -> CustomerAggregate:
        if not self.can_archive():
            raise CustomerAggregateError("Cannot archive aggregate with customers")
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_agg

    def can_unarchive(self) -> bool:
        return True  # Bisa unarchive kapan saja

    def unarchive(self, unarchived_by: str) -> CustomerAggregate:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNARCHIVE", unarchived_by, {})
        return new_agg

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

    # ── Tambahan untuk kepatuhan checker (AGG-021) ──
    def apply(self, event: DomainEvent) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        # Just record that event was applied.
        self._events.append(event)

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create_aggregate(cls, legal_entity_id: UUID, created_by: str = "system") -> CustomerAggregate:
        """Factory method to create a new empty aggregate."""
        agg = cls(
            aggregate_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        agg._record_audit("CREATE", created_by, {"legal_entity_id": str(legal_entity_id)})
        return agg

    @classmethod
    def from_events(cls, events: list[DomainEvent]) -> CustomerAggregate:
        """Reconstruct aggregate from event stream."""
        if not events:
            raise ValueError("No events provided")

        first_event = events[0]
        aggregate_id = getattr(first_event, "aggregate_id", uuid4())
        legal_entity_id = getattr(first_event, "legal_entity_id", uuid4())

        # Create a new aggregate with placeholder data
        agg = cls(
            aggregate_id=aggregate_id,
            legal_entity_id=legal_entity_id,
            customers={},
            customer_by_code={},
            customer_by_email={},
            customer_by_tax_id={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )
        # Apply events in order
        for event in events:
            agg.apply(event)
        agg.version = len(events)
        return agg

    # ==================== QUERY METHODS ====================

    def get_customer(self, customer_id: UUID) -> CustomerEntity | None:
        return self.customers.get(customer_id)

    def get_customer_by_code(self, customer_code: str) -> CustomerEntity | None:
        cust_id = self.customer_by_code.get(customer_code)
        return self.customers.get(cust_id) if cust_id else None

    def get_customer_by_email(self, email: str) -> CustomerEntity | None:
        cust_id = self.customer_by_email.get(email)
        return self.customers.get(cust_id) if cust_id else None

    def get_customer_by_tax_id(self, tax_id: str) -> CustomerEntity | None:
        cust_id = self.customer_by_tax_id.get(tax_id)
        return self.customers.get(cust_id) if cust_id else None

    def get_all_customers(self) -> list[CustomerEntity]:
        return list(self.customers.values())

    def get_active_customers(self) -> list[CustomerEntity]:
        return [c for c in self.customers.values() if c.status == CustomerStatus.ACTIVE]

    def get_customers_by_type(self, customer_type: CustomerType) -> list[CustomerEntity]:
        return [c for c in self.customers.values() if c.customer_type == customer_type]

    def get_customers_by_status(self, status: CustomerStatus) -> list[CustomerEntity]:
        return [c for c in self.customers.values() if c.status == status]

    def get_customers_by_segment(self, segment: CustomerSegment) -> list[CustomerEntity]:
        return [c for c in self.customers.values() if c.segment == segment]

    def get_customers_exceeding_credit_limit(
        self, as_of: datetime | None = None
    ) -> list[CustomerEntity]:
        return [c for c in self.customers.values() if c.is_exceeding_credit_limit(as_of)]

    def get_customers_on_credit_hold(self) -> list[CustomerEntity]:
        return [c for c in self.customers.values() if c.credit_hold]

    def get_high_risk_customers(self, threshold: int = 70) -> list[CustomerEntity]:
        return [c for c in self.customers.values() if c.risk_score >= threshold]

    def get_total_outstanding_balance(self) -> Decimal:
        return sum((c.outstanding_balance for c in self.customers.values()), Decimal("0"))

    def get_total_purchases(self) -> Decimal:
        return sum((c.total_purchases for c in self.customers.values()), Decimal("0"))

    def get_customer_count(self) -> int:
        return len(self.customers)

    def get_active_customer_count(self) -> int:
        return len(self.get_active_customers())

    def code_exists(self, customer_code: str) -> bool:
        return customer_code in self.customer_by_code

    def email_exists(self, email: str) -> bool:
        return email in self.customer_by_email

    def tax_id_exists(self, tax_id: str) -> bool:
        return tax_id in self.customer_by_tax_id

    # ==================== COMMAND METHODS ====================

    def add_customer(self, customer: CustomerEntity, created_by: str) -> CustomerAggregate:
        if customer.customer_id in self.customers:
            raise CustomerAggregateError(f"Customer {customer.customer_id} already exists")
        _validate_customer_code_unique(customer.customer_code, set(self.customer_by_code.keys()))
        _validate_email_unique(customer.email, self.customer_by_email)
        _validate_tax_id_unique(customer.tax_id, self.customer_by_tax_id)
        if customer.version != 1:
            raise ValueError("New customer must have version 1")

        new_customers = dict(self.customers)
        new_customers[customer.customer_id] = customer
        new_by_code = dict(self.customer_by_code)
        new_by_code[customer.customer_code] = customer.customer_id
        new_by_email = dict(self.customer_by_email)
        if customer.email:
            new_by_email[customer.email] = customer.customer_id
        new_by_tax_id = dict(self.customer_by_tax_id)
        if customer.tax_id:
            new_by_tax_id[customer.tax_id] = customer.customer_id

        self._register_event(
            CustomerCreatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                customer=customer,
                created_by=created_by,
            )
        )

        return CustomerAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            customers=new_customers,
            customer_by_code=new_by_code,
            customer_by_email=new_by_email,
            customer_by_tax_id=new_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def update_customer(self, customer: CustomerEntity, updated_by: str) -> CustomerAggregate:
        if customer.customer_id not in self.customers:
            raise CustomerNotFoundError(f"Customer {customer.customer_id} not found")
        old_customer = self.customers[customer.customer_id]

        if customer.customer_code != old_customer.customer_code:
            _validate_customer_code_unique(
                customer.customer_code,
                set(self.customer_by_code.keys()),
                exclude_id=customer.customer_id,
            )
        if customer.email != old_customer.email:
            _validate_email_unique(
                customer.email, self.customer_by_email, exclude_id=customer.customer_id
            )
        if customer.tax_id != old_customer.tax_id:
            _validate_tax_id_unique(
                customer.tax_id, self.customer_by_tax_id, exclude_id=customer.customer_id
            )
        if customer.version <= old_customer.version:
            raise ValueError(
                f"Version mismatch: current {old_customer.version}, provided {customer.version}"
            )

        new_customers = dict(self.customers)
        new_customers[customer.customer_id] = customer
        new_by_code = dict(self.customer_by_code)
        if customer.customer_code != old_customer.customer_code:
            del new_by_code[old_customer.customer_code]
            new_by_code[customer.customer_code] = customer.customer_id
        new_by_email = dict(self.customer_by_email)
        if old_customer.email:
            new_by_email.pop(old_customer.email, None)
        if customer.email:
            new_by_email[customer.email] = customer.customer_id
        new_by_tax_id = dict(self.customer_by_tax_id)
        if old_customer.tax_id:
            new_by_tax_id.pop(old_customer.tax_id, None)
        if customer.tax_id:
            new_by_tax_id[customer.tax_id] = customer.customer_id

        return CustomerAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            customers=new_customers,
            customer_by_code=new_by_code,
            customer_by_email=new_by_email,
            customer_by_tax_id=new_by_tax_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def update_customer_status(
        self,
        customer_id: UUID,
        new_status: CustomerStatus,
        updated_by: str,
        reason: str | None = None,
    ) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        _validate_status_transition(customer.status, new_status)

        if new_status == CustomerStatus.BLOCKED:
            updated_customer = customer.block(updated_by, reason or "No reason")
        elif new_status == CustomerStatus.ACTIVE:
            if customer.status == CustomerStatus.BLOCKED:
                updated_customer = customer.unblock(updated_by)
            else:
                updated_customer = customer.activate(updated_by)
        elif new_status == CustomerStatus.INACTIVE:
            updated_customer = customer.deactivate(updated_by)
        elif new_status == CustomerStatus.BLACKLISTED:
            updated_customer = customer.blacklist(updated_by, reason or "No reason")
        elif new_status == CustomerStatus.SUSPENDED:
            updated_customer = customer.block(updated_by, reason or "Suspended")
            # Override status
            updated_customer = CustomerEntity(
                **{**updated_customer.__dict__, "status": CustomerStatus.SUSPENDED}
            )
        else:
            updated_customer = CustomerEntity(
                **{
                    **customer.__dict__,
                    "status": new_status,
                    "updated_at": datetime.now(UTC),
                    "updated_by": updated_by,
                    "version": customer.version + 1,
                }
            )

        self._register_event(
            CustomerStatusChangedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                customer_id=customer.customer_id,
                customer_code=customer.customer_code,
                old_status=customer.status,
                new_status=new_status,
                reason=reason,
                changed_by=updated_by,
            )
        )

        return self.update_customer(updated_customer, updated_by)

    def update_customer_credit_limit(
        self, customer_id: UUID, new_limit: CustomerCreditLimitVO, updated_by: str
    ) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        updated_customer = customer.update_credit_limit(new_limit, updated_by)

        self._register_event(
            CustomerCreditLimitChangedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                customer_id=customer.customer_id,
                customer_code=customer.customer_code,
                old_limit=customer.credit_limit,
                new_limit=new_limit,
                changed_by=updated_by,
            )
        )

        return self.update_customer(updated_customer, updated_by)

    def update_customer_tax_status(
        self, customer_id: UUID, new_tax_status: CustomerTaxStatusVO, updated_by: str
    ) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        updated_customer = customer.update_tax_status(new_tax_status, updated_by)
        return self.update_customer(updated_customer, updated_by)

    def record_customer_purchase(
        self, customer_id: UUID, amount: Decimal, transaction_date: datetime | None = None
    ) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        if amount <= 0:
            raise ValueError("Purchase amount must be positive")
        can_invoice, reason = customer.can_invoice(amount)
        if not can_invoice:
            raise CustomerAggregateError(f"Cannot record purchase: {reason}")

        updated_customer = customer.record_purchase(amount, transaction_date)

        self._register_event(
            CustomerBalanceUpdatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                customer_id=customer.customer_id,
                customer_code=customer.customer_code,
                old_balance=customer.outstanding_balance,
                new_balance=updated_customer.outstanding_balance,
                delta=amount,
                transaction_type="purchase",
            )
        )

        return self.update_customer(updated_customer, "system")

    def record_customer_payment(
        self, customer_id: UUID, amount: Decimal, payment_date: datetime | None = None
    ) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        if not customer.can_receive_payment():
            raise CustomerAggregateError(
                f"Cannot record payment: customer status {customer.status.display_name()}"
            )

        updated_customer = customer.record_payment(amount, payment_date)

        self._register_event(
            CustomerBalanceUpdatedEvent(
                aggregate_id=self.aggregate_id,
                aggregate_version=self.version + 1,
                customer_id=customer.customer_id,
                customer_code=customer.customer_code,
                old_balance=customer.outstanding_balance,
                new_balance=updated_customer.outstanding_balance,
                delta=-amount,
                transaction_type="payment",
            )
        )

        return self.update_customer(updated_customer, "system")

    def update_customer_credit_hold(
        self, customer_id: UUID, credit_hold: bool, updated_by: str, reason: str | None = None
    ) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        updated_customer = customer.update_credit_hold(credit_hold, updated_by, reason)
        return self.update_customer(updated_customer, updated_by)

    def update_customer_risk_score(
        self, customer_id: UUID, new_score: int, updated_by: str
    ) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        updated_customer = customer.update_risk_score(new_score, updated_by)
        return self.update_customer(updated_customer, updated_by)

    def remove_customer(self, customer_id: UUID, deleted_by: str) -> CustomerAggregate:
        customer = self.get_customer(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")
        if customer.outstanding_balance > 0:
            raise CustomerAggregateError(
                f"Cannot delete customer with outstanding balance {customer.outstanding_balance}"
            )
        updated_customer = customer.deactivate(deleted_by)
        return self.update_customer(updated_customer, deleted_by)

    # ==================== STATISTICS ====================

    def get_statistics(self) -> dict[str, Any]:
        total = self.get_customer_count()
        active = self.get_active_customer_count()
        status_counts = {s.value: len(self.get_customers_by_status(s)) for s in CustomerStatus}
        type_counts = {t.value: len(self.get_customers_by_type(t)) for t in CustomerType}
        segment_counts = {
            seg.value: len(self.get_customers_by_segment(seg)) for seg in CustomerSegment
        }
        return {
            "total_customers": total,
            "active_customers": active,
            "inactive_customers": total - active,
            "status_distribution": status_counts,
            "type_distribution": type_counts,
            "segment_distribution": segment_counts,
            "total_outstanding_balance": str(self.get_total_outstanding_balance()),
            "total_lifetime_purchases": str(self.get_total_purchases()),
            "customers_exceeding_credit_limit": len(self.get_customers_exceeding_credit_limit()),
            "customers_on_credit_hold": len(self.get_customers_on_credit_hold()),
            "high_risk_customers": len(self.get_high_risk_customers()),
        }

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> CustomerAggregate:
        return CustomerAggregate(
            aggregate_id=self.aggregate_id,
            legal_entity_id=self.legal_entity_id,
            customers=self.customers.copy(),
            customer_by_code=self.customer_by_code.copy(),
            customer_by_email=self.customer_by_email.copy(),
            customer_by_tax_id=self.customer_by_tax_id.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )


# ============================================================================
# Repository Implementation (Real)
# ============================================================================


class CustomerAggregateRepository:
    """Repository untuk CustomerAggregate dengan implementasi in-memory."""

    _storage: ClassVar[dict[UUID, CustomerAggregate]] = {}

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> CustomerAggregate | None:
        for agg in cls._storage.values():
            if agg.legal_entity_id == legal_entity_id:
                return agg
        return None

    @classmethod
    async def get_by_id(cls, aggregate_id: UUID) -> CustomerAggregate | None:
        return cls._storage.get(aggregate_id)

    @classmethod
    async def get_all(cls) -> list[CustomerAggregate]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, aggregate: CustomerAggregate) -> None:
        cls._storage[aggregate.aggregate_id] = aggregate

    @classmethod
    async def update(cls, aggregate: CustomerAggregate) -> None:
        cls._storage[aggregate.aggregate_id] = aggregate

    @classmethod
    async def delete(cls, aggregate_id: UUID) -> None:
        if aggregate_id in cls._storage:
            del cls._storage[aggregate_id]

    @classmethod
    async def exists(cls, aggregate_id: UUID) -> bool:
        return aggregate_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[CustomerAggregate]:
        aggregates = list(cls._storage.values())
        return aggregates[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, page: int = 1, per_page: int = 20
    ) -> tuple[list[CustomerAggregate], int]:
        aggregates = list(cls._storage.values())
        total = len(aggregates)
        start = (page - 1) * per_page
        end = start + per_page
        return aggregates[start:end], total

    @classmethod
    async def search(cls, query: str, fields: list[str] | None = None) -> list[CustomerAggregate]:
        if fields is None:
            fields = ["aggregate_id", "legal_entity_id"]
        query_lower = query.lower()
        results = []
        for agg in cls._storage.values():
            for field_name in fields:  # renamed loop variable to avoid shadowing imported `field`
                value = getattr(agg, field_name, "")
                if value and query_lower in str(value).lower():
                    results.append(agg)
                    break
        return results

    @classmethod
    async def lock(cls, aggregate_id: UUID, locked_by: str, reason: str) -> CustomerAggregate:
        agg = await cls.get_by_id(aggregate_id)
        if not agg:
            raise ValueError(f"Aggregate {aggregate_id} not found")
        locked_agg = agg.lock(locked_by, reason)
        await cls.save(locked_agg)
        return locked_agg

    @classmethod
    async def unlock(cls, aggregate_id: UUID, unlocked_by: str) -> CustomerAggregate:
        agg = await cls.get_by_id(aggregate_id)
        if not agg:
            raise ValueError(f"Aggregate {aggregate_id} not found")
        unlocked_agg = agg.unlock(unlocked_by)
        await cls.save(unlocked_agg)
        return unlocked_agg

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "CustomerAggregate",
    "CustomerAggregateError",
    "CustomerAggregateRepository",
    "CustomerNotFoundError",
    "DuplicateCustomerCodeError",
    "DuplicateEmailError",
    "DuplicateTaxIdError",
    "InvalidCustomerStatusTransitionError",
]
