# service_legal_entity.py - Complete rewrite with full event publishing
# v5.9.0 - Refactored event publishing into single _publish_event method to reduce
#          broad-except warnings and improve maintainability.

#!/usr/bin/env python3
"""
Module: service_legal_entity.py
Layer: Application / Service Layer
Responsibility: Menyediakan service untuk mengelola legal entity, consolidation group, branch, tax profile.
               Mempublikasikan event untuk setiap perubahan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from ports.primary.event_publisher_port import EventPublisherPort

# Import domain events
from application.events import (
    CompanyAddressUpdatedEvent,
    CompanyContactUpdatedEvent,
    CompanyDissolvedEvent,
    CompanyReactivatedEvent,
    CompanyRegisteredEvent,
    CompanySuspendedEvent,
    LegalEntityCreatedEvent,
    LegalEntityDeactivatedEvent,
    LegalEntityUpdatedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class EntityType(str, Enum):
    """Type of legal entity."""

    CORPORATION = "corporation"
    LIMITED_LIABILITY = "limited_liability"
    PARTNERSHIP = "partnership"
    SOLE_PROPRIETORSHIP = "sole_proprietorship"
    BRANCH = "branch"


class EntityStatus(str, Enum):
    """Status of legal entity."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class LegalEntity:
    """Legal entity model."""

    id: UUID = field(default_factory=uuid4)
    legal_name: str
    trade_name: str | None = None
    entity_type: EntityType = EntityType.CORPORATION
    registration_number: str | None = None
    npwp: str | None = None  # Tax ID
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str = "ID"
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    established_date: datetime | None = None
    fiscal_year_start: int = 1
    fiscal_year_end: int = 12
    base_currency: str = "IDR"
    functional_currency: str = "IDR"
    status: EntityStatus = EntityStatus.ACTIVE
    is_active: bool = True
    parent_company_id: UUID | None = None
    consolidation_group_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1

    # Tax profile fields
    tax_office: str | None = None
    tax_office_code: str | None = None
    tax_classification: str | None = None
    taxable_date: date | None = None
    annual_tax_return_due_date: date | None = None
    monthly_tax_due_date: date | None = None
    is_vat_collector: bool = True
    vat_collector_number: str | None = None
    is_withholding_agent: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "entity_type": self.entity_type.value,
            "registration_number": self.registration_number,
            "npwp": self.npwp,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "established_date": self.established_date.isoformat()
            if self.established_date
            else None,
            "fiscal_year_start": self.fiscal_year_start,
            "fiscal_year_end": self.fiscal_year_end,
            "base_currency": self.base_currency,
            "functional_currency": self.functional_currency,
            "status": self.status.value,
            "is_active": self.is_active,
            "parent_company_id": str(self.parent_company_id) if self.parent_company_id else None,
            "consolidation_group_id": str(self.consolidation_group_id)
            if self.consolidation_group_id
            else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tax_office": self.tax_office,
            "tax_office_code": self.tax_office_code,
            "tax_classification": self.tax_classification,
            "taxable_date": self.taxable_date.isoformat() if self.taxable_date else None,
            "is_vat_collector": self.is_vat_collector,
            "vat_collector_number": self.vat_collector_number,
            "is_withholding_agent": self.is_withholding_agent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalEntity:
        return cls(
            id=UUID(data["id"]) if data.get("id") else uuid4(),
            legal_name=data["legal_name"],
            trade_name=data.get("trade_name"),
            entity_type=EntityType(data.get("entity_type", "corporation")),
            registration_number=data.get("registration_number"),
            npwp=data.get("npwp"),
            address=data.get("address"),
            city=data.get("city"),
            postal_code=data.get("postal_code"),
            country=data.get("country", "ID"),
            phone=data.get("phone"),
            email=data.get("email"),
            website=data.get("website"),
            established_date=datetime.fromisoformat(data["established_date"])
            if data.get("established_date")
            else None,
            fiscal_year_start=data.get("fiscal_year_start", 1),
            fiscal_year_end=data.get("fiscal_year_end", 12),
            base_currency=data.get("base_currency", "IDR"),
            functional_currency=data.get("functional_currency", "IDR"),
            status=EntityStatus(data.get("status", "active")),
            is_active=data.get("is_active", True),
            parent_company_id=UUID(data["parent_company_id"])
            if data.get("parent_company_id")
            else None,
            consolidation_group_id=UUID(data["consolidation_group_id"])
            if data.get("consolidation_group_id")
            else None,
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            version=data.get("version", 1),
            tax_office=data.get("tax_office"),
            tax_office_code=data.get("tax_office_code"),
            tax_classification=data.get("tax_classification"),
            taxable_date=date.fromisoformat(data["taxable_date"])
            if data.get("taxable_date")
            else None,
            annual_tax_return_due_date=date.fromisoformat(data["annual_tax_return_due_date"])
            if data.get("annual_tax_return_due_date")
            else None,
            monthly_tax_due_date=date.fromisoformat(data["monthly_tax_due_date"])
            if data.get("monthly_tax_due_date")
            else None,
            is_vat_collector=data.get("is_vat_collector", True),
            vat_collector_number=data.get("vat_collector_number"),
            is_withholding_agent=data.get("is_withholding_agent", True),
        )


@dataclass(kw_only=True)
class ConsolidationGroup:
    """Consolidation group model."""

    id: UUID = field(default_factory=uuid4)
    group_name: str
    description: str | None = None
    base_currency: str = "IDR"
    fiscal_year_start: int = 1
    fiscal_year_end: int = 12
    member_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "group_name": self.group_name,
            "description": self.description,
            "base_currency": self.base_currency,
            "fiscal_year_start": self.fiscal_year_start,
            "fiscal_year_end": self.fiscal_year_end,
            "member_count": self.member_count,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConsolidationGroup:
        return cls(
            id=UUID(data["id"]) if data.get("id") else uuid4(),
            group_name=data["group_name"],
            description=data.get("description"),
            base_currency=data.get("base_currency", "IDR"),
            fiscal_year_start=data.get("fiscal_year_start", 1),
            fiscal_year_end=data.get("fiscal_year_end", 12),
            member_count=data.get("member_count", 0),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
        )


@dataclass(kw_only=True)
class LegalEntityBranch:
    """Legal entity branch model."""

    id: UUID = field(default_factory=uuid4)
    legal_entity_id: UUID
    branch_name: str
    branch_code: str
    address: str | None = None
    city: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "branch_name": self.branch_name,
            "branch_code": self.branch_code,
            "address": self.address,
            "city": self.city,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalEntityBranch:
        return cls(
            id=UUID(data["id"]) if data.get("id") else uuid4(),
            legal_entity_id=UUID(data["legal_entity_id"]),
            branch_name=data["branch_name"],
            branch_code=data["branch_code"],
            address=data.get("address"),
            city=data.get("city"),
            is_active=data.get("is_active", True),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
        )


# ============================================================================
# Exceptions
# ============================================================================


class LegalEntityServiceError(Exception):
    pass


class LegalEntityNotFoundError(LegalEntityServiceError):
    pass


class ConsolidationGroupNotFoundError(LegalEntityServiceError):
    pass


class BranchNotFoundError(LegalEntityServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class LegalEntityService:
    """
    Service layer untuk operasi legal entity.
    Mempublikasikan event untuk setiap perubahan.
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._entities: dict[UUID, LegalEntity] = {}
        self._groups: dict[UUID, ConsolidationGroup] = {}
        self._branches: dict[UUID, LegalEntityBranch] = {}
        self._event_publisher = event_publisher
        self._stats = {
            "entities_created": 0,
            "entities_updated": 0,
            "entities_deactivated": 0,
            "entities_reactivated": 0,
            "entities_suspended": 0,
            "entities_dissolved": 0,
        }

        logger.info("LegalEntityService initialized")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        """
        Publish an event safely, catching and logging any exception.
        Preserves the two-argument publish signature (event, correlation_id).
        """
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # Legal Entity CRUD
    # ========================================================================

    async def create_legal_entity(
        self,
        legal_name: str,
        entity_type: str = "corporation",
        trade_name: str | None = None,
        registration_number: str | None = None,
        npwp: str | None = None,
        address: str | None = None,
        city: str | None = None,
        country: str = "ID",
        base_currency: str = "IDR",
        functional_currency: str = "IDR",
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> LegalEntity:
        """Create new legal entity."""
        logger.info(f"Creating legal entity: {legal_name}")

        entity = LegalEntity(
            legal_name=legal_name,
            trade_name=trade_name,
            entity_type=EntityType(entity_type),
            registration_number=registration_number,
            npwp=npwp,
            address=address,
            city=city,
            country=country,
            base_currency=base_currency,
            functional_currency=functional_currency,
            created_by=created_by,
            version=1,
        )

        self._entities[entity.id] = entity
        self._stats["entities_created"] += 1

        # --- PUBLISH EVENTS ---
        if self._event_publisher:
            # LegalEntityCreatedEvent
            event = LegalEntityCreatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                entity_code=entity.registration_number or entity.id.hex[:8],
                entity_name=entity.legal_name,
                parent_id=entity.parent_company_id,
                currency=entity.base_currency,
                created_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (created)", correlation_id)

            # CompanyRegisteredEvent
            event_company = CompanyRegisteredEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=entity.id,
                company_name=entity.legal_name,
                registration_number=entity.registration_number,
                npwp=entity.npwp,
                address=entity.address,
                country=entity.country,
                registered_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event_company, f"Company {entity.legal_name} (registered)", correlation_id)

        logger.info(f"Legal entity created with ID {entity.id}")
        return entity

    async def get_legal_entity(self, legal_entity_id: UUID) -> LegalEntity | None:
        """Get legal entity by ID."""
        return self._entities.get(legal_entity_id)

    async def list_legal_entities(
        self,
        entity_type: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
    ) -> list[LegalEntity]:
        """List legal entities with filters."""
        result = list(self._entities.values())

        if entity_type:
            result = [e for e in result if e.entity_type.value == entity_type]
        if status:
            result = [e for e in result if e.status.value == status]
        if is_active is not None:
            result = [e for e in result if e.is_active == is_active]

        return result

    async def update_legal_entity(
        self,
        legal_entity_id: UUID,
        legal_name: str | None = None,
        trade_name: str | None = None,
        address: str | None = None,
        city: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        """Update legal entity."""
        logger.info(f"Updating legal entity {legal_entity_id}")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            raise LegalEntityNotFoundError(f"Legal entity {legal_entity_id} not found")

        changes = {}
        if legal_name is not None and legal_name != entity.legal_name:
            changes["legal_name"] = {"old": entity.legal_name, "new": legal_name}
            entity.legal_name = legal_name
        if trade_name is not None and trade_name != entity.trade_name:
            changes["trade_name"] = {"old": entity.trade_name, "new": trade_name}
            entity.trade_name = trade_name
        if address is not None and address != entity.address:
            changes["address"] = {"old": entity.address, "new": address}
            entity.address = address
        if city is not None and city != entity.city:
            changes["city"] = {"old": entity.city, "new": city}
            entity.city = city
        if phone is not None and phone != entity.phone:
            changes["phone"] = {"old": entity.phone, "new": phone}
            entity.phone = phone
        if email is not None and email != entity.email:
            changes["email"] = {"old": entity.email, "new": email}
            entity.email = email

        if not changes:
            return entity

        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        self._entities[legal_entity_id] = entity
        self._stats["entities_updated"] += 1

        # --- PUBLISH EVENTS ---
        if self._event_publisher:
            # LegalEntityUpdatedEvent
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                entity_code=entity.registration_number or entity.id.hex[:8],
                changes=changes,
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (updated)", correlation_id)

            # CompanyAddressUpdatedEvent if address changed
            if "address" in changes or "city" in changes:
                event_addr = CompanyAddressUpdatedEvent(
                    aggregate_id=entity.id,
                    aggregate_version=entity.version,
                    company_id=entity.id,
                    company_name=entity.legal_name,
                    old_address=changes.get("address", {}).get("old") if "address" in changes else None,
                    new_address=entity.address,
                    old_city=changes.get("city", {}).get("old") if "city" in changes else None,
                    new_city=entity.city,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event_addr, f"Company {entity.legal_name} (address updated)", correlation_id)

            # CompanyContactUpdatedEvent if phone or email changed
            if "phone" in changes or "email" in changes:
                event_contact = CompanyContactUpdatedEvent(
                    aggregate_id=entity.id,
                    aggregate_version=entity.version,
                    company_id=entity.id,
                    company_name=entity.legal_name,
                    old_phone=changes.get("phone", {}).get("old") if "phone" in changes else None,
                    new_phone=entity.phone,
                    old_email=changes.get("email", {}).get("old") if "email" in changes else None,
                    new_email=entity.email,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event_contact, f"Company {entity.legal_name} (contact updated)", correlation_id)

        return entity

    async def deactivate_legal_entity(
        self,
        legal_entity_id: UUID,
        updated_by: UUID,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Deactivate legal entity."""
        logger.info(f"Deactivating legal entity {legal_entity_id}")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            return False

        old_status = entity.status
        entity.is_active = False
        entity.status = EntityStatus.INACTIVE
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        self._entities[legal_entity_id] = entity
        self._stats["entities_deactivated"] += 1

        # --- PUBLISH EVENTS ---
        if self._event_publisher:
            # LegalEntityDeactivatedEvent
            event = LegalEntityDeactivatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                reason=reason or "Deactivated",
                deactivated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (deactivated)", correlation_id)

            # CompanySuspendedEvent (since deactivation is like suspension)
            event_suspend = CompanySuspendedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=entity.id,
                company_name=entity.legal_name,
                reason=reason or "Deactivated",
                suspended_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event_suspend, f"Company {entity.legal_name} (suspended)", correlation_id)

        return True

    async def reactivate_legal_entity(
        self,
        legal_entity_id: UUID,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Reactivate a deactivated legal entity."""
        logger.info(f"Reactivating legal entity {legal_entity_id}")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            return False

        if entity.is_active:
            return True

        entity.is_active = True
        entity.status = EntityStatus.ACTIVE
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        self._entities[legal_entity_id] = entity
        self._stats["entities_reactivated"] += 1

        # --- PUBLISH EVENTS ---
        if self._event_publisher:
            # LegalEntity reactivation (via update event)
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                entity_code=entity.registration_number or entity.id.hex[:8],
                changes={"status": {"old": "INACTIVE", "new": "ACTIVE"}},
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (reactivated)", correlation_id)

            # CompanyReactivatedEvent
            event_react = CompanyReactivatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=entity.id,
                company_name=entity.legal_name,
                reactivated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event_react, f"Company {entity.legal_name} (reactivated)", correlation_id)

        return True

    async def suspend_legal_entity(
        self,
        legal_entity_id: UUID,
        reason: str,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Suspend a legal entity."""
        logger.info(f"Suspending legal entity {legal_entity_id}")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            return False

        entity.status = EntityStatus.SUSPENDED
        entity.is_active = False
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        self._entities[legal_entity_id] = entity
        self._stats["entities_suspended"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CompanySuspendedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=entity.id,
                company_name=entity.legal_name,
                reason=reason,
                suspended_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Company {entity.legal_name} (suspended)", correlation_id)

        return True

    async def dissolve_legal_entity(
        self,
        legal_entity_id: UUID,
        reason: str,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Dissolve a legal entity (permanent)."""
        logger.info(f"Dissolving legal entity {legal_entity_id}")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            return False

        entity.status = EntityStatus.DISSOLVED
        entity.is_active = False
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        self._entities[legal_entity_id] = entity
        self._stats["entities_dissolved"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CompanyDissolvedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=entity.id,
                company_name=entity.legal_name,
                reason=reason,
                dissolved_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Company {entity.legal_name} (dissolved)", correlation_id)

        return True

    # ========================================================================
    # Tax Profile
    # ========================================================================

    async def update_tax_profile(
        self,
        legal_entity_id: UUID,
        npwp: str | None = None,
        tax_office: str | None = None,
        tax_office_code: str | None = None,
        tax_classification: str | None = None,
        is_vat_collector: bool | None = None,
        vat_collector_number: str | None = None,
        is_withholding_agent: bool | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        """Update tax profile."""
        logger.info(f"Updating tax profile for {legal_entity_id}")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            return None

        changes = {}
        if npwp is not None and npwp != entity.npwp:
            changes["npwp"] = {"old": entity.npwp, "new": npwp}
            entity.npwp = npwp
        if tax_office is not None and tax_office != entity.tax_office:
            changes["tax_office"] = {"old": entity.tax_office, "new": tax_office}
            entity.tax_office = tax_office
        if tax_office_code is not None and tax_office_code != entity.tax_office_code:
            changes["tax_office_code"] = {"old": entity.tax_office_code, "new": tax_office_code}
            entity.tax_office_code = tax_office_code
        if tax_classification is not None and tax_classification != entity.tax_classification:
            changes["tax_classification"] = {"old": entity.tax_classification, "new": tax_classification}
            entity.tax_classification = tax_classification
        if is_vat_collector is not None and is_vat_collector != entity.is_vat_collector:
            changes["is_vat_collector"] = {"old": entity.is_vat_collector, "new": is_vat_collector}
            entity.is_vat_collector = is_vat_collector
        if vat_collector_number is not None and vat_collector_number != entity.vat_collector_number:
            changes["vat_collector_number"] = {"old": entity.vat_collector_number, "new": vat_collector_number}
            entity.vat_collector_number = vat_collector_number
        if is_withholding_agent is not None and is_withholding_agent != entity.is_withholding_agent:
            changes["is_withholding_agent"] = {"old": entity.is_withholding_agent, "new": is_withholding_agent}
            entity.is_withholding_agent = is_withholding_agent

        if not changes:
            return entity

        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        self._entities[legal_entity_id] = entity
        self._stats["entities_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                entity_code=entity.registration_number or entity.id.hex[:8],
                changes=changes,
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (tax profile updated)", correlation_id)

        return entity

    # ========================================================================
    # Consolidation Group
    # ========================================================================

    async def create_consolidation_group(
        self,
        group_name: str,
        description: str | None = None,
        base_currency: str = "IDR",
        created_by: UUID | None = None,
    ) -> ConsolidationGroup:
        """Create consolidation group."""
        logger.info(f"Creating consolidation group: {group_name}")

        group = ConsolidationGroup(
            group_name=group_name,
            description=description,
            base_currency=base_currency,
            created_by=created_by,
            version=1,
        )

        self._groups[group.id] = group
        return group

    async def list_consolidation_groups(self) -> list[ConsolidationGroup]:
        """List consolidation groups."""
        return list(self._groups.values())

    async def add_member_to_group(
        self,
        group_id: UUID,
        legal_entity_id: UUID,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Add member to consolidation group."""
        logger.info(f"Adding {legal_entity_id} to group {group_id}")

        group = self._groups.get(group_id)
        if not group:
            raise ConsolidationGroupNotFoundError(f"Group {group_id} not found")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            raise LegalEntityNotFoundError(f"Legal entity {legal_entity_id} not found")

        entity.consolidation_group_id = group_id
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        group.member_count += 1

        self._entities[legal_entity_id] = entity
        self._groups[group_id] = group

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                entity_code=entity.registration_number or entity.id.hex[:8],
                changes={"consolidation_group_id": {"old": None, "new": str(group_id)}},
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (added to group)", correlation_id)

        return True

    async def remove_member_from_group(
        self,
        group_id: UUID,
        legal_entity_id: UUID,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Remove member from consolidation group."""
        logger.info(f"Removing {legal_entity_id} from group {group_id}")

        entity = self._entities.get(legal_entity_id)
        if not entity:
            return False

        entity.consolidation_group_id = None
        entity.updated_at = datetime.now(UTC)
        entity.version += 1
        self._entities[legal_entity_id] = entity

        group = self._groups.get(group_id)
        if group:
            group.member_count = max(0, group.member_count - 1)
            self._groups[group_id] = group

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                entity_code=entity.registration_number or entity.id.hex[:8],
                changes={"consolidation_group_id": {"old": str(group_id), "new": None}},
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (removed from group)", correlation_id)

        return True

    # ========================================================================
    # Branch Management
    # ========================================================================

    async def add_branch(
        self,
        legal_entity_id: UUID,
        branch_name: str,
        branch_code: str,
        address: str | None = None,
        city: str | None = None,
        is_active: bool = True,
        created_by: UUID | None = None,
    ) -> LegalEntityBranch:
        """Add branch to legal entity."""
        logger.info(f"Adding branch {branch_code} to {legal_entity_id}")

        branch = LegalEntityBranch(
            legal_entity_id=legal_entity_id,
            branch_name=branch_name,
            branch_code=branch_code,
            address=address,
            city=city,
            is_active=is_active,
            created_by=created_by,
            version=1,
        )

        self._branches[branch.id] = branch
        return branch

    async def get_branch(self, branch_id: UUID) -> LegalEntityBranch | None:
        """Get branch by ID."""
        return self._branches.get(branch_id)

    async def list_branches(self, legal_entity_id: UUID) -> list[LegalEntityBranch]:
        """List branches of a legal entity."""
        return [b for b in self._branches.values() if b.legal_entity_id == legal_entity_id]

    async def update_branch(
        self,
        branch_id: UUID,
        branch_name: str | None = None,
        address: str | None = None,
        city: str | None = None,
        is_active: bool | None = None,
        updated_by: UUID | None = None,
    ) -> LegalEntityBranch | None:
        """Update branch."""
        branch = self._branches.get(branch_id)
        if not branch:
            raise BranchNotFoundError(f"Branch {branch_id} not found")

        if branch_name:
            branch.branch_name = branch_name
        if address:
            branch.address = address
        if city:
            branch.city = city
        if is_active is not None:
            branch.is_active = is_active

        branch.version += 1
        self._branches[branch_id] = branch
        return branch

    async def deactivate_branch(self, branch_id: UUID, updated_by: UUID) -> bool:
        """Deactivate branch."""
        branch = self._branches.get(branch_id)
        if not branch:
            return False

        branch.is_active = False
        branch.version += 1
        self._branches[branch_id] = branch
        return True

    # ========================================================================
    # Stats
    # ========================================================================

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_legal_entity_service(
    event_publisher: EventPublisherPort | None = None,
) -> LegalEntityService:
    return LegalEntityService(event_publisher=event_publisher)


__all__ = [
    "BranchNotFoundError",
    "ConsolidationGroup",
    "ConsolidationGroupNotFoundError",
    "EntityStatus",
    "EntityType",
    "LegalEntity",
    "LegalEntityBranch",
    "LegalEntityNotFoundError",
    "LegalEntityService",
    "LegalEntityServiceError",
    "create_legal_entity_service",
]