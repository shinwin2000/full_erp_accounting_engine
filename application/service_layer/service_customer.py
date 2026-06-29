# service_customer.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_customer.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk mengelola Customer.
    Mempublikasikan event untuk setiap perubahan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import (
    CustomerBalanceUpdatedEvent,
    CustomerCreatedEvent,
    CustomerCreditLimitChangedEvent,
    CustomerStatusChangedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class CustomerStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class Customer:
    id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID
    customer_code: str
    name: str
    npwp: str | None = None
    address: str | None = None
    city: str | None = None
    country: str = "ID"
    phone: str | None = None
    email: str | None = None
    contact_person: str | None = None
    credit_limit: Decimal = Decimal("0")
    current_balance: Decimal = Decimal("0")
    is_active: bool = True
    status: CustomerStatus = CustomerStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1


# ============================================================================
# Exceptions
# ============================================================================


class CustomerServiceError(Exception):
    pass


class CustomerNotFoundError(CustomerServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class CustomerService:
    """
    Service untuk mengelola Customer.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._customers: dict[UUID, Customer] = {}
        self._event_publisher = event_publisher
        self._stats = {"customers_created": 0, "customers_updated": 0}

        logger.info("CustomerService initialized")

    async def create_customer(
        self,
        legal_entity_id: UUID,
        customer_code: str,
        name: str,
        npwp: str | None = None,
        address: str | None = None,
        city: str | None = None,
        country: str = "ID",
        phone: str | None = None,
        email: str | None = None,
        contact_person: str | None = None,
        credit_limit: Decimal = Decimal("0"),
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Customer:
        """Create new customer."""
        for c in self._customers.values():
            if c.legal_entity_id == legal_entity_id and c.customer_code == customer_code:
                raise CustomerServiceError(f"Customer code {customer_code} already exists")

        customer = Customer(
            legal_entity_id=legal_entity_id,
            customer_code=customer_code,
            name=name,
            npwp=npwp,
            address=address,
            city=city,
            country=country,
            phone=phone,
            email=email,
            contact_person=contact_person,
            credit_limit=credit_limit,
            created_by=created_by,
            version=1,
        )

        self._customers[customer.id] = customer
        self._stats["customers_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = CustomerCreatedEvent(
                    aggregate_id=customer.id,
                    aggregate_version=customer.version,
                    customer_id=customer.id,
                    customer_code=customer.customer_code,
                    customer_name=customer.name,
                    npwp=customer.npwp,
                    legal_entity_id=customer.legal_entity_id,
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published CustomerCreatedEvent for {customer.customer_code}")
            except Exception as e:
                logger.warning(f"Failed to publish CustomerCreatedEvent: {e}")

        return customer

    async def get_customer(self, customer_id: UUID) -> Customer | None:
        return self._customers.get(customer_id)

    async def list_customers(
        self,
        legal_entity_id: UUID,
        is_active: bool | None = None,
        status: str | None = None,
    ) -> list[Customer]:
        result = [c for c in self._customers.values() if c.legal_entity_id == legal_entity_id]
        if is_active is not None:
            result = [c for c in result if c.is_active == is_active]
        if status:
            result = [c for c in result if c.status.value == status]
        return result

    async def update_customer(
        self,
        customer_id: UUID,
        name: str | None = None,
        address: str | None = None,
        city: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        contact_person: str | None = None,
        is_active: bool | None = None,
        status: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Customer:
        """Update customer details."""
        customer = self._customers.get(customer_id)
        if not customer:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")

        changes = {}

        if name is not None and name != customer.name:
            changes["name"] = {"old": customer.name, "new": name}
            customer.name = name
        if address is not None and address != customer.address:
            changes["address"] = {"old": customer.address, "new": address}
            customer.address = address
        if city is not None and city != customer.city:
            changes["city"] = {"old": customer.city, "new": city}
            customer.city = city
        if phone is not None and phone != customer.phone:
            changes["phone"] = {"old": customer.phone, "new": phone}
            customer.phone = phone
        if email is not None and email != customer.email:
            changes["email"] = {"old": customer.email, "new": email}
            customer.email = email
        if contact_person is not None and contact_person != customer.contact_person:
            changes["contact_person"] = {"old": customer.contact_person, "new": contact_person}
            customer.contact_person = contact_person

        if is_active is not None and is_active != customer.is_active:
            changes["is_active"] = {"old": customer.is_active, "new": is_active}
            customer.is_active = is_active
        if status is not None and status != customer.status.value:
            changes["status"] = {"old": customer.status.value, "new": status}
            customer.status = CustomerStatus(status)

        if not changes:
            return customer

        customer.updated_at = datetime.now(UTC)
        customer.version += 1
        self._customers[customer_id] = customer
        self._stats["customers_updated"] += 1

        # --- PUBLISH EVENT (CustomerStatusChangedEvent) ---
        if "status" in changes and self._event_publisher:
            try:
                event = CustomerStatusChangedEvent(
                    aggregate_id=customer.id,
                    aggregate_version=customer.version,
                    customer_id=customer.id,
                    customer_code=customer.customer_code,
                    old_status=changes["status"]["old"],
                    new_status=changes["status"]["new"],
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug("Published CustomerStatusChangedEvent")
            except Exception as e:
                logger.warning(f"Failed to publish CustomerStatusChangedEvent: {e}")

        return customer

    async def update_credit_limit(
        self,
        customer_id: UUID,
        new_limit: Decimal,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> Customer:
        """Update customer credit limit."""
        customer = self._customers.get(customer_id)
        if not customer:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")

        if customer.credit_limit == new_limit:
            return customer

        old_limit = customer.credit_limit
        customer.credit_limit = new_limit
        customer.updated_at = datetime.now(UTC)
        customer.version += 1
        self._customers[customer_id] = customer
        self._stats["customers_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = CustomerCreditLimitChangedEvent(
                    aggregate_id=customer.id,
                    aggregate_version=customer.version,
                    customer_id=customer.id,
                    customer_code=customer.customer_code,
                    old_limit=old_limit,
                    new_limit=new_limit,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug("Published CustomerCreditLimitChangedEvent")
            except Exception as e:
                logger.warning(f"Failed to publish CustomerCreditLimitChangedEvent: {e}")

        return customer

    async def update_balance(
        self,
        customer_id: UUID,
        delta: Decimal,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> Decimal:
        """Update customer balance (add delta)."""
        customer = self._customers.get(customer_id)
        if not customer:
            raise CustomerNotFoundError(f"Customer {customer_id} not found")

        new_balance = customer.current_balance + delta
        customer.current_balance = new_balance
        customer.updated_at = datetime.now(UTC)
        customer.version += 1
        self._customers[customer_id] = customer
        self._stats["customers_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = CustomerBalanceUpdatedEvent(
                    aggregate_id=customer.id,
                    aggregate_version=customer.version,
                    customer_id=customer.id,
                    customer_code=customer.customer_code,
                    old_balance=customer.current_balance - delta,
                    new_balance=new_balance,
                    delta=delta,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug("Published CustomerBalanceUpdatedEvent")
            except Exception as e:
                logger.warning(f"Failed to publish CustomerBalanceUpdatedEvent: {e}")

        return new_balance

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_customer_service(
    event_publisher: EventPublisherPort | None = None,
) -> CustomerService:
    return CustomerService(event_publisher=event_publisher)


__all__ = [
    "Customer",
    "CustomerNotFoundError",
    "CustomerService",
    "CustomerServiceError",
    "CustomerStatus",
    "create_customer_service",
]