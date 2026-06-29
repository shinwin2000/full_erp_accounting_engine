# service_supplier.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_supplier.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk mengelola Supplier/Vendor.
    Mempublikasikan event untuk setiap perubahan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import (
    SupplierCreatedEvent,
    SupplierPaymentTermsChangedEvent,
    SupplierWithholdingCategoryChangedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class SupplierStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"


class WithholdingCategory(str, Enum):
    """Kategori pemotongan pajak untuk supplier."""
    NONE = "none"
    PPH23 = "pph23"
    PPH22 = "pph22"
    PPH4_2 = "pph4_2"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class Supplier:
    id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID
    supplier_code: str
    name: str
    npwp: str | None = None
    address: str | None = None
    city: str | None = None
    country: str = "ID"
    phone: str | None = None
    email: str | None = None
    contact_person: str | None = None
    payment_terms_days: int = 30
    credit_limit: Decimal = Decimal("0")
    withholding_category: str = "none"
    is_active: bool = True
    status: SupplierStatus = SupplierStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1


# ============================================================================
# Exceptions
# ============================================================================


class SupplierServiceError(Exception):
    pass


class SupplierNotFoundError(SupplierServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class SupplierService:
    """
    Service untuk mengelola Supplier.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._suppliers: dict[UUID, Supplier] = {}
        self._event_publisher = event_publisher
        self._stats = {"suppliers_created": 0, "suppliers_updated": 0}

        logger.info("SupplierService initialized")

    async def create_supplier(
        self,
        legal_entity_id: UUID,
        supplier_code: str,
        name: str,
        npwp: str | None = None,
        address: str | None = None,
        city: str | None = None,
        country: str = "ID",
        phone: str | None = None,
        email: str | None = None,
        contact_person: str | None = None,
        payment_terms_days: int = 30,
        credit_limit: Decimal = Decimal("0"),
        withholding_category: str = "none",
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Supplier:
        """Create new supplier."""
        # Check duplicate code
        for s in self._suppliers.values():
            if s.legal_entity_id == legal_entity_id and s.supplier_code == supplier_code:
                raise SupplierServiceError(f"Supplier code {supplier_code} already exists")

        supplier = Supplier(
            legal_entity_id=legal_entity_id,
            supplier_code=supplier_code,
            name=name,
            npwp=npwp,
            address=address,
            city=city,
            country=country,
            phone=phone,
            email=email,
            contact_person=contact_person,
            payment_terms_days=payment_terms_days,
            credit_limit=credit_limit,
            withholding_category=withholding_category,
            created_by=created_by,
            version=1,
        )

        self._suppliers[supplier.id] = supplier
        self._stats["suppliers_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            try:
                event = SupplierCreatedEvent(
                    aggregate_id=supplier.id,
                    aggregate_version=supplier.version,
                    supplier_id=supplier.id,
                    supplier_code=supplier.supplier_code,
                    supplier_name=supplier.name,
                    npwp=supplier.npwp,
                    legal_entity_id=supplier.legal_entity_id,
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published SupplierCreatedEvent for {supplier.supplier_code}")
            except Exception as e:
                logger.warning(f"Failed to publish SupplierCreatedEvent: {e}")

        logger.info(f"Supplier created: {supplier.supplier_code} - {supplier.name}")
        return supplier

    async def get_supplier(self, supplier_id: UUID) -> Supplier | None:
        return self._suppliers.get(supplier_id)

    async def list_suppliers(
        self,
        legal_entity_id: UUID,
        is_active: bool | None = None,
        status: str | None = None,
    ) -> list[Supplier]:
        result = [s for s in self._suppliers.values() if s.legal_entity_id == legal_entity_id]
        if is_active is not None:
            result = [s for s in result if s.is_active == is_active]
        if status:
            result = [s for s in result if s.status.value == status]
        return result

    async def update_supplier(
        self,
        supplier_id: UUID,
        name: str | None = None,
        address: str | None = None,
        city: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        contact_person: str | None = None,
        payment_terms_days: int | None = None,
        credit_limit: Decimal | None = None,
        is_active: bool | None = None,
        status: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Supplier:
        """Update supplier details."""
        supplier = self._suppliers.get(supplier_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")

        changes = {}

        if name is not None and name != supplier.name:
            changes["name"] = {"old": supplier.name, "new": name}
            supplier.name = name
        if address is not None and address != supplier.address:
            changes["address"] = {"old": supplier.address, "new": address}
            supplier.address = address
        if city is not None and city != supplier.city:
            changes["city"] = {"old": supplier.city, "new": city}
            supplier.city = city
        if phone is not None and phone != supplier.phone:
            changes["phone"] = {"old": supplier.phone, "new": phone}
            supplier.phone = phone
        if email is not None and email != supplier.email:
            changes["email"] = {"old": supplier.email, "new": email}
            supplier.email = email
        if contact_person is not None and contact_person != supplier.contact_person:
            changes["contact_person"] = {"old": supplier.contact_person, "new": contact_person}
            supplier.contact_person = contact_person

        if payment_terms_days is not None and payment_terms_days != supplier.payment_terms_days:
            changes["payment_terms_days"] = {"old": supplier.payment_terms_days, "new": payment_terms_days}
            supplier.payment_terms_days = payment_terms_days
            # --- PUBLISH PAYMENT TERMS CHANGED EVENT ---
            if self._event_publisher:
                try:
                    event = SupplierPaymentTermsChangedEvent(
                        aggregate_id=supplier.id,
                        aggregate_version=supplier.version + 1,
                        supplier_id=supplier.id,
                        supplier_code=supplier.supplier_code,
                        old_terms=changes["payment_terms_days"]["old"],
                        new_terms=changes["payment_terms_days"]["new"],
                        updated_by=str(updated_by) if updated_by else "system",
                        user_id=str(updated_by) if updated_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event, correlation_id)
                    logger.debug("Published SupplierPaymentTermsChangedEvent")
                except Exception as e:
                    logger.warning(f"Failed to publish SupplierPaymentTermsChangedEvent: {e}")

        if credit_limit is not None and credit_limit != supplier.credit_limit:
            changes["credit_limit"] = {"old": supplier.credit_limit, "new": credit_limit}
            supplier.credit_limit = credit_limit

        if is_active is not None and is_active != supplier.is_active:
            changes["is_active"] = {"old": supplier.is_active, "new": is_active}
            supplier.is_active = is_active

        if status is not None and status != supplier.status.value:
            changes["status"] = {"old": supplier.status.value, "new": status}
            supplier.status = SupplierStatus(status)

        if not changes:
            return supplier

        supplier.updated_at = datetime.now(UTC)
        supplier.version += 1
        self._suppliers[supplier_id] = supplier
        self._stats["suppliers_updated"] += 1

        # --- PUBLISH GENERAL UPDATE EVENT ---
        # (SupplierUpdatedEvent mungkin tidak ada di registry, kita publish yang ada)

        return supplier

    async def update_withholding_category(
        self,
        supplier_id: UUID,
        withholding_category: str,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> Supplier:
        """Update withholding category for supplier."""
        supplier = self._suppliers.get(supplier_id)
        if not supplier:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")

        if supplier.withholding_category == withholding_category:
            return supplier

        old_category = supplier.withholding_category
        supplier.withholding_category = withholding_category
        supplier.updated_at = datetime.now(UTC)
        supplier.version += 1
        self._suppliers[supplier_id] = supplier
        self._stats["suppliers_updated"] += 1

        # --- PUBLISH WITHHOLDING CATEGORY CHANGED EVENT ---
        if self._event_publisher:
            try:
                event = SupplierWithholdingCategoryChangedEvent(
                    aggregate_id=supplier.id,
                    aggregate_version=supplier.version,
                    supplier_id=supplier.id,
                    supplier_code=supplier.supplier_code,
                    old_category=old_category,
                    new_category=withholding_category,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug("Published SupplierWithholdingCategoryChangedEvent")
            except Exception as e:
                logger.warning(f"Failed to publish SupplierWithholdingCategoryChangedEvent: {e}")

        return supplier

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_supplier_service(
    event_publisher: EventPublisherPort | None = None,
) -> SupplierService:
    return SupplierService(event_publisher=event_publisher)


__all__ = [
    "Supplier",
    "SupplierNotFoundError",
    "SupplierService",
    "SupplierServiceError",
    "SupplierStatus",
    "WithholdingCategory",
    "create_supplier_service",
]