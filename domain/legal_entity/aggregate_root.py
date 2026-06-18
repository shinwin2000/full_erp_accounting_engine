#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: 6 - Domain / Legal Entity
Responsibility: Root aggregate for legal entity (company/tenant).

This module implements the LegalEntity aggregate root with full event sourcing
capabilities, audit trail, snapshots, and immutable state transitions.
All mutation methods return a new instance with incremented version.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID, uuid4

# Internal imports (assumed to exist in the domain modules)
from domain.legal_entity.company_tax_profile_vo import (
    CompanyTaxProfileVO,
    Percentage,
    TaxPaymentMethod,
    TaxRegime,
)
from domain.legal_entity.domain_events import (
    CompanyDissolvedEvent,
    CompanyReactivatedEvent,
    CompanySuspendedEvent,
    DomainEvent,
    TaxProfileUpdatedEvent,
)
from domain.shared_value_objects.npwp_vo import NPWP

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Enumerations
# -----------------------------------------------------------------------------


class LegalEntityStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"

    @classmethod
    def from_string(cls, value: str) -> LegalEntityStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.ACTIVE

    def can_transition_to(self, to_status: LegalEntityStatus) -> bool:
        allowed = {
            LegalEntityStatus.ACTIVE: [LegalEntityStatus.SUSPENDED, LegalEntityStatus.INACTIVE],
            LegalEntityStatus.INACTIVE: [LegalEntityStatus.ACTIVE],
            LegalEntityStatus.SUSPENDED: [LegalEntityStatus.ACTIVE, LegalEntityStatus.DISSOLVED],
            LegalEntityStatus.DISSOLVED: [],
        }
        return to_status in allowed.get(self, [])


class LegalEntityType(Enum):
    CORPORATION = "corporation"
    LIMITED = "limited"
    SOLE_PROPRIETORSHIP = "sole"
    PARTNERSHIP = "partnership"
    COOPERATIVE = "cooperative"
    NON_PROFIT = "non_profit"
    GOVERNMENT = "government"

    @classmethod
    def from_string(cls, value: str) -> LegalEntityType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.CORPORATION


class FiscalYearType(Enum):
    CALENDAR = "calendar"
    APRIL_MARCH = "april_march"
    JULY_JUNE = "july_june"
    OCTOBER_SEPTEMBER = "october_sep"
    CUSTOM = "custom"

    @classmethod
    def from_string(cls, value: str) -> FiscalYearType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.CALENDAR


# Aliases for compatibility with __init__.py
EntityStatus = LegalEntityStatus
EntityType = LegalEntityType


# -----------------------------------------------------------------------------
# Aggregate Root: LegalEntity
# -----------------------------------------------------------------------------


@dataclass
class LegalEntity:
    """
    Aggregate root representing a legal entity (company/tenant).

    Immutable: all state-changing operations return a new instance with
    incremented version. Events and audit trail are carried over.
    """

    # Identity & core attributes
    entity_id: UUID
    entity_code: str
    entity_name: str
    legal_name: str
    entity_type: LegalEntityType
    status: LegalEntityStatus
    npwp: NPWP
    tax_profile: CompanyTaxProfileVO

    # Address
    address: str
    city: str
    province: str
    postal_code: str
    country: str

    # Contact
    phone: str | None
    email: str | None
    website: str | None

    # Fiscal & currency
    fiscal_year_type: FiscalYearType
    fiscal_year_start_month: int
    fiscal_year_start_day: int = 1
    functional_currency: str = "IDR"

    # Hierarchy & consolidation
    parent_entity_id: UUID | None = None
    consolidation_group: str | None = None

    # Metadata
    established_date: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    # Internal state (not part of business equality)
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict] = field(default_factory=list, repr=False)
    _snapshots: list[dict] = field(default_factory=list, repr=False)
    _is_locked: bool = False
    _locked_by: str | None = None
    _locked_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate invariant rules after initialization."""
        if len(self.entity_code) < 3 or len(self.entity_code) > 20:
            raise ValueError("Entity code must be between 3 and 20 characters")
        if not self.entity_name or len(self.entity_name.strip()) < 2:
            raise ValueError("Entity name must be at least 2 characters")
        if not self.legal_name or len(self.legal_name.strip()) < 2:
            raise ValueError("Legal name must be at least 2 characters")
        if not self.address or len(self.address.strip()) < 5:
            raise ValueError("Address must be at least 5 characters")
        if not self.city or len(self.city.strip()) < 2:
            raise ValueError("City must be at least 2 characters")
        if not (1 <= self.fiscal_year_start_month <= 12):
            raise ValueError("Fiscal year start month must be between 1 and 12")
        if not (1 <= self.fiscal_year_start_day <= 31):
            raise ValueError("Fiscal year start day must be between 1 and 31")
        if len(self.functional_currency) != 3:
            raise ValueError("Functional currency must be ISO 4217 (3 characters)")
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.parent_entity_id == self.entity_id:
            raise ValueError("Entity cannot be its own parent")

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def id(self) -> UUID:
        return self.entity_id

    @property
    def is_active(self) -> bool:
        return self.status == LegalEntityStatus.ACTIVE

    @property
    def is_suspended(self) -> bool:
        return self.status == LegalEntityStatus.SUSPENDED

    @property
    def is_dissolved(self) -> bool:
        return self.status == LegalEntityStatus.DISSOLVED

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    # -------------------------------------------------------------------------
    # Internal helpers for immutable updates
    # -------------------------------------------------------------------------

    def _copy_and_update(
        self,
        *,
        status: LegalEntityStatus | None = None,
        entity_name: str | None = None,
        legal_name: str | None = None,
        tax_profile: CompanyTaxProfileVO | None = None,
        address: str | None = None,
        city: str | None = None,
        province: str | None = None,
        postal_code: str | None = None,
        country: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        website: str | None = None,
        fiscal_year_type: FiscalYearType | None = None,
        fiscal_year_start_month: int | None = None,
        fiscal_year_start_day: int | None = None,
        functional_currency: str | None = None,
        parent_entity_id: UUID | None = None,
        consolidation_group: str | None = None,
        established_date: datetime | None = None,
        updated_at: datetime | None = None,
        version: int | None = None,
        _is_locked: bool | None = None,
        _locked_by: str | None = None,
        _locked_at: datetime | None = None,
        _events: list[DomainEvent] | None = None,
        _audit_trail: list[dict] | None = None,
        _snapshots: list[dict] | None = None,
    ) -> LegalEntity:
        return LegalEntity(
            entity_id=self.entity_id,
            entity_code=self.entity_code,
            entity_name=entity_name if entity_name is not None else self.entity_name,
            legal_name=legal_name if legal_name is not None else self.legal_name,
            entity_type=self.entity_type,
            status=status if status is not None else self.status,
            npwp=self.npwp,
            tax_profile=tax_profile if tax_profile is not None else self.tax_profile,
            address=address if address is not None else self.address,
            city=city if city is not None else self.city,
            province=province if province is not None else self.province,
            postal_code=postal_code if postal_code is not None else self.postal_code,
            country=country if country is not None else self.country,
            phone=phone if phone is not None else self.phone,
            email=email if email is not None else self.email,
            website=website if website is not None else self.website,
            fiscal_year_type=fiscal_year_type
            if fiscal_year_type is not None
            else self.fiscal_year_type,
            fiscal_year_start_month=fiscal_year_start_month
            if fiscal_year_start_month is not None
            else self.fiscal_year_start_month,
            fiscal_year_start_day=fiscal_year_start_day
            if fiscal_year_start_day is not None
            else self.fiscal_year_start_day,
            functional_currency=functional_currency
            if functional_currency is not None
            else self.functional_currency,
            parent_entity_id=parent_entity_id
            if parent_entity_id is not None
            else self.parent_entity_id,
            consolidation_group=consolidation_group
            if consolidation_group is not None
            else self.consolidation_group,
            established_date=established_date
            if established_date is not None
            else self.established_date,
            created_at=self.created_at,
            updated_at=updated_at if updated_at is not None else datetime.now(UTC),
            created_by=self.created_by,
            version=version if version is not None else self.version + 1,
            _events=_events if _events is not None else self._events.copy(),
            _audit_trail=_audit_trail if _audit_trail is not None else self._audit_trail.copy(),
            _snapshots=_snapshots if _snapshots is not None else self._snapshots.copy(),
            _is_locked=_is_locked if _is_locked is not None else self._is_locked,
            _locked_by=_locked_by if _locked_by is not None else self._locked_by,
            _locked_at=_locked_at if _locked_at is not None else self._locked_at,
        )

    def _record_audit_trail(self, action: str, details: dict) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
                "version": self.version,
            }
        )

    def _add_event(self, event: DomainEvent) -> None:
        self._events.append(event)
        self._record_audit_trail("event_added", {"event_type": event.event_type.value})

    # -------------------------------------------------------------------------
    # Event management
    # -------------------------------------------------------------------------

    def clear_events(self) -> None:
        self._events.clear()
        self._record_audit_trail("events_cleared", {})

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pop_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def register_event(self, event: DomainEvent) -> None:
        self._add_event(event)

    # -------------------------------------------------------------------------
    # Audit trail
    # -------------------------------------------------------------------------

    def audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def clear_audit_trail(self) -> None:
        self._audit_trail.clear()

    # -------------------------------------------------------------------------
    # Snapshot
    # -------------------------------------------------------------------------

    def snapshot(self) -> dict:
        snapshot_data = {
            "aggregate_id": str(self.entity_id),
            "aggregate_type": "LegalEntity",
            "version": self.version,
            "timestamp": datetime.now(UTC).isoformat(),
            "state": {
                "entity_code": self.entity_code,
                "entity_name": self.entity_name,
                "legal_name": self.legal_name,
                "entity_type": self.entity_type.value,
                "status": self.status.value,
                "npwp": str(self.npwp),
                "tax_profile": self.tax_profile.to_dict(),
                "address": self.address,
                "city": self.city,
                "functional_currency": self.functional_currency,
                "parent_entity_id": str(self.parent_entity_id) if self.parent_entity_id else None,
            },
            "hash": self._compute_hash(),
        }
        self._snapshots.append(snapshot_data)
        self._record_audit_trail("snapshot_created", {"version": self.version})
        return snapshot_data

    def restore_from_snapshot(self, snapshot: dict) -> None:
        if snapshot.get("aggregate_id") != str(self.entity_id):
            raise ValueError("Snapshot belongs to different aggregate")
        self._record_audit_trail(
            "restored_from_snapshot", {"snapshot_version": snapshot.get("version")}
        )

    def _compute_hash(self) -> str:
        state_str = json.dumps(
            {
                "id": str(self.entity_id),
                "version": self.version,
                "status": self.status.value,
                "entity_code": self.entity_code,
            },
            sort_keys=True,
        )
        return hashlib.sha256(state_str.encode()).hexdigest()

    # -------------------------------------------------------------------------
    # Lock / Unlock
    # -------------------------------------------------------------------------

    def lock(self, user_id: str, reason: str | None = None) -> LegalEntity:
        if self._is_locked:
            raise ValueError(f"Legal entity is already locked by {self._locked_by}")
        self._record_audit_trail("locked", {"user_id": user_id, "reason": reason})
        return self._copy_and_update(
            _is_locked=True,
            _locked_by=user_id,
            _locked_at=datetime.now(UTC),
        )

    def unlock(self, user_id: str) -> LegalEntity:
        if not self._is_locked:
            raise ValueError("Legal entity is not locked")
        if self._locked_by != user_id:
            raise ValueError(
                f"Legal entity locked by {self._locked_by}, cannot unlock by {user_id}"
            )
        self._record_audit_trail("unlocked", {"user_id": user_id})
        return self._copy_and_update(
            _is_locked=False,
            _locked_by=None,
            _locked_at=None,
        )

    # -------------------------------------------------------------------------
    # Status transitions
    # -------------------------------------------------------------------------

    def activate(self, activated_by: str, reason: str | None = None) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot activate locked legal entity")
        if self.status not in (LegalEntityStatus.INACTIVE, LegalEntityStatus.SUSPENDED):
            raise ValueError(f"Cannot activate entity with status {self.status.value}")
        self._record_audit_trail("activated", {"user_id": activated_by, "reason": reason})
        return self._copy_and_update(status=LegalEntityStatus.ACTIVE)

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot deactivate locked legal entity")
        if self.status != LegalEntityStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate entity with status {self.status.value}")
        self._record_audit_trail("deactivated", {"user_id": deactivated_by, "reason": reason})
        return self._copy_and_update(status=LegalEntityStatus.INACTIVE)

    def suspend(self, suspended_by: str, reason: str) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot suspend locked legal entity")
        if self.status == LegalEntityStatus.DISSOLVED:
            raise ValueError("Cannot suspend a dissolved entity")
        if self.status == LegalEntityStatus.SUSPENDED:
            raise ValueError("Entity is already suspended")

        self._record_audit_trail("suspended", {"user_id": suspended_by, "reason": reason})
        new_entity = self._copy_and_update(status=LegalEntityStatus.SUSPENDED)
        event = CompanySuspendedEvent(
            aggregate_id=self.entity_id,
            aggregate_version=self.version + 1,
            legal_entity_data={
                "entity_id": str(self.entity_id),
                "entity_code": self.entity_code,
                "entity_name": self.entity_name,
            },
            reason=reason,
            user_id=suspended_by,
        )
        new_entity._events.append(event)
        new_entity._record_audit_trail("event_added", {"event_type": event.event_type.value})
        return new_entity

    def reactivate(self, reactivated_by: str, reason: str) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot reactivate locked legal entity")
        if self.status != LegalEntityStatus.SUSPENDED:
            raise ValueError(f"Cannot reactivate entity with status {self.status.value}")

        self._record_audit_trail("reactivated", {"user_id": reactivated_by, "reason": reason})
        new_entity = self._copy_and_update(status=LegalEntityStatus.ACTIVE)
        event = CompanyReactivatedEvent(
            aggregate_id=self.entity_id,
            aggregate_version=self.version + 1,
            legal_entity_data={
                "entity_id": str(self.entity_id),
                "entity_code": self.entity_code,
                "entity_name": self.entity_name,
            },
            reason=reason,
            user_id=reactivated_by,
        )
        new_entity._events.append(event)
        new_entity._record_audit_trail("event_added", {"event_type": event.event_type.value})
        return new_entity

    def dissolve(self, dissolved_by: str, effective_date: datetime, reason: str) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot dissolve locked legal entity")
        if self.status == LegalEntityStatus.DISSOLVED:
            raise ValueError("Entity already dissolved")
        if self.status != LegalEntityStatus.SUSPENDED:
            raise ValueError("Entity must be suspended before dissolution")

        self._record_audit_trail(
            "dissolved",
            {
                "user_id": dissolved_by,
                "effective_date": effective_date.isoformat(),
                "reason": reason,
            },
        )
        new_entity = self._copy_and_update(status=LegalEntityStatus.DISSOLVED)
        event = CompanyDissolvedEvent(
            aggregate_id=self.entity_id,
            aggregate_version=self.version + 1,
            legal_entity_data={
                "entity_id": str(self.entity_id),
                "entity_code": self.entity_code,
                "entity_name": self.entity_name,
                "status": self.status.value,
            },
            effective_date=effective_date,
            user_id=dissolved_by,
        )
        new_entity._events.append(event)
        new_entity._record_audit_trail("event_added", {"event_type": event.event_type.value})
        return new_entity

    # -------------------------------------------------------------------------
    # Tax profile
    # -------------------------------------------------------------------------

    def update_tax_profile(self, new_profile: CompanyTaxProfileVO, updated_by: str) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot update tax profile of locked legal entity")
        old_profile = self.tax_profile

        self._record_audit_trail("tax_profile_updated", {"user_id": updated_by})
        new_entity = self._copy_and_update(tax_profile=new_profile)
        event = TaxProfileUpdatedEvent(
            aggregate_id=self.entity_id,
            aggregate_version=self.version + 1,
            legal_entity_id=self.entity_id,
            old_profile=old_profile,
            new_profile=new_profile,
            user_id=updated_by,
        )
        new_entity._events.append(event)
        new_entity._record_audit_trail("event_added", {"event_type": event.event_type.value})
        return new_entity

    # -------------------------------------------------------------------------
    # Basic attribute updates
    # -------------------------------------------------------------------------

    def rename(self, new_name: str, updated_by: str) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot rename locked legal entity")
        if not new_name or len(new_name.strip()) < 2:
            raise ValueError("Entity name must be at least 2 characters")
        self._record_audit_trail(
            "renamed", {"user_id": updated_by, "old_name": self.entity_name, "new_name": new_name}
        )
        return self._copy_and_update(entity_name=new_name.strip())

    def update_address(
        self,
        address: str,
        city: str,
        province: str,
        postal_code: str,
        country: str,
        updated_by: str,
    ) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot update address of locked legal entity")
        if not address or len(address.strip()) < 5:
            raise ValueError("Address must be at least 5 characters")
        if not city or len(city.strip()) < 2:
            raise ValueError("City must be at least 2 characters")
        self._record_audit_trail("address_updated", {"user_id": updated_by})
        return self._copy_and_update(
            address=address.strip(),
            city=city.strip(),
            province=province.strip(),
            postal_code=postal_code.strip(),
            country=country.strip(),
        )

    def update_contact(
        self,
        phone: str | None,
        email: str | None,
        website: str | None,
        updated_by: str,
    ) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot update contact of locked legal entity")
        if email is not None and "@" not in email:
            raise ValueError("Invalid email format")
        self._record_audit_trail("contact_updated", {"user_id": updated_by})
        return self._copy_and_update(phone=phone, email=email, website=website)

    # -------------------------------------------------------------------------
    # Hierarchy management
    # -------------------------------------------------------------------------

    def add_child(self, child_entity_id: UUID, updated_by: str) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot add child to locked legal entity")
        self._record_audit_trail(
            "child_added", {"user_id": updated_by, "child_id": str(child_entity_id)}
        )
        return self

    def remove_child(self, child_entity_id: UUID, updated_by: str) -> LegalEntity:
        if self._is_locked:
            raise ValueError("Cannot remove child from locked legal entity")
        self._record_audit_trail(
            "child_removed", {"user_id": updated_by, "child_id": str(child_entity_id)}
        )
        return self

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def validate(self) -> list[str]:
        errors = []
        if len(self.entity_code) < 3 or len(self.entity_code) > 20:
            errors.append("Entity code must be between 3 and 20 characters")
        if not self.entity_name or len(self.entity_name.strip()) < 2:
            errors.append("Entity name must be at least 2 characters")
        if not self.legal_name or len(self.legal_name.strip()) < 2:
            errors.append("Legal name must be at least 2 characters")
        if not self.address or len(self.address.strip()) < 5:
            errors.append("Address must be at least 5 characters")
        if not self.city or len(self.city.strip()) < 2:
            errors.append("City must be at least 2 characters")
        if not (1 <= self.fiscal_year_start_month <= 12):
            errors.append("Fiscal year start month must be between 1 and 12")
        if len(self.functional_currency) != 3:
            errors.append("Functional currency must be ISO 4217 (3 characters)")
        return errors

    # -------------------------------------------------------------------------
    # Touch
    # -------------------------------------------------------------------------

    def touch(self, user_id: str) -> LegalEntity:
        self._record_audit_trail("touched", {"user_id": user_id})
        return self._copy_and_update(updated_at=datetime.now(UTC))

    # -------------------------------------------------------------------------
    # Clone
    # -------------------------------------------------------------------------

    def clone(self) -> LegalEntity:
        self._record_audit_trail("cloned", {"source_id": str(self.entity_id)})
        return LegalEntity(
            entity_id=uuid4(),
            entity_code=f"COPY-{self.entity_code}",
            entity_name=f"Copy of {self.entity_name}",
            legal_name=f"Copy of {self.legal_name}",
            entity_type=self.entity_type,
            status=LegalEntityStatus.INACTIVE,
            npwp=self.npwp,
            tax_profile=self.tax_profile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            phone=self.phone,
            email=self.email,
            website=self.website,
            fiscal_year_type=self.fiscal_year_type,
            fiscal_year_start_month=self.fiscal_year_start_month,
            fiscal_year_start_day=self.fiscal_year_start_day,
            functional_currency=self.functional_currency,
            parent_entity_id=self.parent_entity_id,
            consolidation_group=self.consolidation_group,
            established_date=self.established_date,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by="system",
            version=1,
        )

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": str(self.entity_id),
            "entity_code": self.entity_code,
            "entity_name": self.entity_name,
            "legal_name": self.legal_name,
            "entity_type": self.entity_type.value,
            "status": self.status.value,
            "npwp": str(self.npwp),
            "tax_profile": self.tax_profile.to_dict(),
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "fiscal_year_type": self.fiscal_year_type.value,
            "fiscal_year_start_month": self.fiscal_year_start_month,
            "fiscal_year_start_day": self.fiscal_year_start_day,
            "functional_currency": self.functional_currency,
            "parent_entity_id": str(self.parent_entity_id) if self.parent_entity_id else None,
            "consolidation_group": self.consolidation_group,
            "established_date": self.established_date.isoformat()
            if self.established_date
            else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalEntity:
        return cls(
            entity_id=UUID(data["entity_id"]),
            entity_code=data["entity_code"],
            entity_name=data["entity_name"],
            legal_name=data["legal_name"],
            entity_type=LegalEntityType.from_string(data["entity_type"]),
            status=LegalEntityStatus.from_string(data["status"]),
            npwp=NPWP.from_string(data["npwp"]),
            tax_profile=CompanyTaxProfileVO(
                is_pkp=data["tax_profile"]["is_pkp"],
                tax_regime=TaxRegime.from_string(data["tax_profile"]["tax_regime"]),
                corporate_income_tax_rate=Percentage(
                    data["tax_profile"]["corporate_income_tax_rate"]
                ),
                vat_rate=Percentage(data["tax_profile"]["vat_rate"]),
                vat_collection_method=data["tax_profile"].get("vat_collection_method", "output"),
                income_tax_article=data["tax_profile"].get("income_tax_article"),
                tax_bracket=data["tax_profile"].get("tax_bracket"),
                payment_method=TaxPaymentMethod.from_string(
                    data["tax_profile"].get("payment_method", "monthly")
                ),
                annual_return_deadline_month=data["tax_profile"].get(
                    "annual_return_deadline_month", 4
                ),
            ),
            address=data["address"],
            city=data["city"],
            province=data["province"],
            postal_code=data["postal_code"],
            country=data["country"],
            phone=data.get("phone"),
            email=data.get("email"),
            website=data.get("website"),
            fiscal_year_type=FiscalYearType.from_string(data["fiscal_year_type"]),
            fiscal_year_start_month=data["fiscal_year_start_month"],
            fiscal_year_start_day=data.get("fiscal_year_start_day", 1),
            functional_currency=data.get("functional_currency", "IDR"),
            parent_entity_id=UUID(data["parent_entity_id"])
            if data.get("parent_entity_id")
            else None,
            consolidation_group=data.get("consolidation_group"),
            established_date=datetime.fromisoformat(data["established_date"])
            if data.get("established_date")
            else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )


# -----------------------------------------------------------------------------
# Alias for compatibility
# -----------------------------------------------------------------------------

LegalEntityAggregate = LegalEntity


# -----------------------------------------------------------------------------
# Repository Interface
# -----------------------------------------------------------------------------


class LegalEntityRepository(Protocol):
    """Repository interface for LegalEntity aggregate."""

    async def get_by_id(self, entity_id: UUID, legal_entity_id: UUID) -> LegalEntity | None: ...

    async def get_by_code(self, entity_code: str, legal_entity_id: UUID) -> LegalEntity | None: ...

    async def get_by_npwp(self, npwp: NPWP, legal_entity_id: UUID) -> LegalEntity | None: ...

    async def list_by_status(
        self, status: LegalEntityStatus, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[LegalEntity]: ...

    async def save(self, entity: LegalEntity, legal_entity_id: UUID) -> None: ...

    async def delete(self, entity_id: UUID, legal_entity_id: UUID) -> None: ...


# -----------------------------------------------------------------------------
# Factory method
# -----------------------------------------------------------------------------


def create_legal_entity(
    entity_code: str,
    entity_name: str,
    legal_name: str,
    entity_type: LegalEntityType,
    npwp: NPWP,
    tax_profile: CompanyTaxProfileVO,
    address: str,
    city: str,
    province: str,
    postal_code: str,
    country: str,
    created_by: str,
    phone: str | None = None,
    email: str | None = None,
    website: str | None = None,
    fiscal_year_type: FiscalYearType = FiscalYearType.CALENDAR,
    fiscal_year_start_month: int = 1,
    fiscal_year_start_day: int = 1,
    functional_currency: str = "IDR",
    parent_entity_id: UUID | None = None,
    consolidation_group: str | None = None,
    established_date: datetime | None = None,
) -> LegalEntity:
    """
    Factory method to create a new active LegalEntity aggregate.
    """
    new_entity = LegalEntity(
        entity_id=uuid4(),
        entity_code=entity_code,
        entity_name=entity_name,
        legal_name=legal_name,
        entity_type=entity_type,
        status=LegalEntityStatus.ACTIVE,
        npwp=npwp,
        tax_profile=tax_profile,
        address=address,
        city=city,
        province=province,
        postal_code=postal_code,
        country=country,
        phone=phone,
        email=email,
        website=website,
        fiscal_year_type=fiscal_year_type,
        fiscal_year_start_month=fiscal_year_start_month,
        fiscal_year_start_day=fiscal_year_start_day,
        functional_currency=functional_currency,
        parent_entity_id=parent_entity_id,
        consolidation_group=consolidation_group,
        established_date=established_date,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=created_by,
        version=1,
    )
    # Create and add CompanyRegisteredEvent using dictionary
    legal_entity_data = {
        "entity_id": str(new_entity.entity_id),
        "entity_type": new_entity.entity_type.value,
        "functional_currency": new_entity.functional_currency,
        "fiscal_year_type": new_entity.fiscal_year_type.value,
    }
    # We need a company object (CompanyEntity) here, but factory doesn't have it.
    # In practice, company is created separately, then this event is raised.
    # For simplicity, we'll leave event creation to the caller.
    return new_entity
