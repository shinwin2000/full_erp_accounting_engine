#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Legal Entity
Responsibility: Event domain: CompanyRegistered, TaxProfileUpdated, dll.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.legal_entity.company_entity import CompanyEntity
from domain.legal_entity.company_tax_profile_vo import CompanyTaxProfileVO


class DomainEventType(Enum):
    COMPANY_REGISTERED = "company_registered"
    COMPANY_SUSPENDED = "company_suspended"
    COMPANY_REACTIVATED = "company_reactivated"
    COMPANY_DISSOLVED = "company_dissolved"
    TAX_PROFILE_UPDATED = "tax_profile_updated"
    COMPANY_ADDRESS_UPDATED = "company_address_updated"
    COMPANY_CONTACT_UPDATED = "company_contact_updated"
    PKP_STATUS_CHANGED = "pkp_status_changed"
    # Additional events for LegalEntity aggregate
    LEGAL_ENTITY_CREATED = "legal_entity_created"
    LEGAL_ENTITY_DEACTIVATED = "legal_entity_deactivated"
    LEGAL_ENTITY_UPDATED = "legal_entity_updated"

    @classmethod
    def from_string(cls, value: str) -> DomainEventType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.COMPANY_REGISTERED


@dataclass
class DomainEvent:
    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType.from_string(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        return cls.from_dict(json.loads(json_str))

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ----------------------------------------------------------------------
# CompanyRegisteredEvent
# ----------------------------------------------------------------------


@dataclass
class CompanyRegisteredEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        company: CompanyEntity,
        legal_entity_data: dict[str, Any],  # dictionary of LegalEntity relevant fields
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "company_id": str(company.company_id),
            "legal_entity_id": legal_entity_data.get("entity_id"),
            "trade_name": company.trade_name,
            "legal_name": company.legal_name,
            "entity_type": legal_entity_data.get("entity_type"),
            "npwp": str(company.npwp),
            "address": company.address,
            "city": company.city,
            "province": company.province,
            "country": company.country,
            "is_pkp": company.pkp_status,
            "functional_currency": legal_entity_data.get("functional_currency", "IDR"),
            "fiscal_year_type": legal_entity_data.get("fiscal_year_type"),
            "established_date": company.established_date.isoformat()
            if company.established_date
            else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COMPANY_REGISTERED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# CompanySuspendedEvent
# ----------------------------------------------------------------------


@dataclass
class CompanySuspendedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_data: dict[str, Any],
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": legal_entity_data.get("entity_id"),
            "entity_code": legal_entity_data.get("entity_code"),
            "entity_name": legal_entity_data.get("entity_name"),
            "previous_status": "ACTIVE",
            "new_status": "SUSPENDED",
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COMPANY_SUSPENDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# CompanyReactivatedEvent
# ----------------------------------------------------------------------


@dataclass
class CompanyReactivatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_data: dict[str, Any],
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": legal_entity_data.get("entity_id"),
            "entity_code": legal_entity_data.get("entity_code"),
            "entity_name": legal_entity_data.get("entity_name"),
            "previous_status": "SUSPENDED",
            "new_status": "ACTIVE",
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COMPANY_REACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# CompanyDissolvedEvent
# ----------------------------------------------------------------------


@dataclass
class CompanyDissolvedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_data: dict[str, Any],
        effective_date: datetime,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": legal_entity_data.get("entity_id"),
            "entity_code": legal_entity_data.get("entity_code"),
            "entity_name": legal_entity_data.get("entity_name"),
            "previous_status": legal_entity_data.get("status", "ACTIVE"),
            "new_status": "DISSOLVED",
            "effective_date": effective_date.isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COMPANY_DISSOLVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# TaxProfileUpdatedEvent (tidak butuh LegalEntity, hanya ID)
# ----------------------------------------------------------------------


@dataclass
class TaxProfileUpdatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        old_profile: CompanyTaxProfileVO,
        new_profile: CompanyTaxProfileVO,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "old_profile": old_profile.to_dict(),
            "new_profile": new_profile.to_dict(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TAX_PROFILE_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# CompanyAddressUpdatedEvent
# ----------------------------------------------------------------------


@dataclass
class CompanyAddressUpdatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        company: CompanyEntity,
        old_address: str,
        old_city: str,
        old_province: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "company_id": str(company.company_id),
            "old_address": old_address,
            "old_city": old_city,
            "old_province": old_province,
            "new_address": company.address,
            "new_city": company.city,
            "new_province": company.province,
            "new_postal_code": company.postal_code,
            "new_country": company.country,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COMPANY_ADDRESS_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# CompanyContactUpdatedEvent
# ----------------------------------------------------------------------


@dataclass
class CompanyContactUpdatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        company: CompanyEntity,
        old_phone: str | None,
        old_email: str | None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "company_id": str(company.company_id),
            "old_phone": old_phone,
            "old_email": old_email,
            "new_phone": company.phone,
            "new_email": company.email,
            "new_website": company.website,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COMPANY_CONTACT_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# PKPStatusChangedEvent
# ----------------------------------------------------------------------


@dataclass
class PKPStatusChangedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        company: CompanyEntity,
        old_status: bool,
        registration_date: datetime,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "company_id": str(company.company_id),
            "old_pkp_status": old_status,
            "new_pkp_status": company.pkp_status,
            "registration_date": registration_date.isoformat() if registration_date else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PKP_STATUS_CHANGED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# LegalEntityAggregate Events (added for completeness)
# ----------------------------------------------------------------------

@dataclass
class LegalEntityCreated(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.LEGAL_ENTITY_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class LegalEntityDeactivated(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.LEGAL_ENTITY_DEACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class LegalEntityUpdated(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        updated_fields: list[str],
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "updated_fields": updated_fields,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.LEGAL_ENTITY_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ----------------------------------------------------------------------
# Publisher
# ----------------------------------------------------------------------


class DomainEventPublisher:
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)


# Aliases
CompanyRegistered = CompanyRegisteredEvent
CompanySuspended = CompanySuspendedEvent
CompanyReactivated = CompanyReactivatedEvent
CompanyDissolved = CompanyDissolvedEvent
TaxProfileUpdated = TaxProfileUpdatedEvent
CompanyAddressUpdated = CompanyAddressUpdatedEvent
CompanyContactUpdated = CompanyContactUpdatedEvent
PKPStatusChanged = PKPStatusChangedEvent

# LegalEntity event aliases
LegalEntityCreatedEvent = LegalEntityCreated
LegalEntityDeactivatedEvent = LegalEntityDeactivated
LegalEntityUpdatedEvent = LegalEntityUpdated

__all__ = [
    "CompanyAddressUpdated",
    "CompanyAddressUpdatedEvent",
    "CompanyContactUpdated",
    "CompanyContactUpdatedEvent",
    "CompanyDissolved",
    "CompanyDissolvedEvent",
    "CompanyReactivated",
    "CompanyReactivatedEvent",
    "CompanyRegistered",
    "CompanyRegisteredEvent",
    "CompanySuspended",
    "CompanySuspendedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "PKPStatusChanged",
    "PKPStatusChangedEvent",
    "TaxProfileUpdated",
    "TaxProfileUpdatedEvent",
    # LegalEntity aggregate events
    "LegalEntityCreated",
    "LegalEntityDeactivated",
    "LegalEntityUpdated",
    "LegalEntityCreatedEvent",
    "LegalEntityDeactivatedEvent",
    "LegalEntityUpdatedEvent",
]
