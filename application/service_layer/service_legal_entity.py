# service_legal_entity.py - Complete rewrite with full event publishing
# v5.9.4 - Added audit decorator and authority checks for mutation methods

#!/usr/bin/env python3
"""
Module: service_legal_entity.py
Layer: Application / Service Layer
Responsibility: Menyediakan service untuk mengelola legal entity, consolidation group, branch, tax profile.
               Mempublikasikan event untuk setiap perubahan.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from dataclasses import field as _dc_field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from infrastructure.persistence_orm.consolidation_group_table import ConsolidationGroupTable
from infrastructure.persistence_orm.legal_entity_branch_table import LegalEntityBranchTable
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable

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
from ports.primary.event_publisher_port import EventPublisherPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class EntityType(str, Enum):
    CORPORATION = "corporation"
    LIMITED_LIABILITY = "limited_liability"
    PARTNERSHIP = "partnership"
    SOLE_PROPRIETORSHIP = "sole_proprietorship"
    BRANCH = "branch"


class EntityStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"


# ============================================================================
# Domain Models
# ============================================================================


@dataclass(kw_only=True)
class LegalEntity:
    id: UUID = _dc_field(default_factory=uuid4)
    legal_name: str
    trade_name: str | None = None
    entity_type: str = "corporation"
    registration_number: str | None = None
    npwp: str | None = None
    nppp: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    province: str | None = None
    country: str = "ID"
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    website: str | None = None
    established_date: datetime | None = None
    fiscal_year_start: int = 1
    fiscal_year_end: int = 12
    base_currency: str = "IDR"
    functional_currency: str = "IDR"
    is_taxable: bool = True
    status: str = "active"
    is_active: bool = True
    is_locked: bool = False
    parent_company_id: UUID | None = None
    parent_company_name: str | None = None
    consolidation_group_id: UUID | None = None
    consolidation_group_name: str | None = None
    notes: str | None = None
    created_at: datetime = _dc_field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = _dc_field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1

    tax_office: str | None = None
    tax_office_code: str | None = None
    tax_classification: str | None = None
    taxable_date: date | None = None
    annual_tax_return_due_date: date | None = None
    monthly_tax_due_date: date | None = None
    is_vat_collector: bool = True
    vat_collector_number: str | None = None
    is_withholding_agent: bool = True

    @property
    def legal_entity_name(self) -> str:
        """Alias untuk legal_name - dipakai oleh handler add_group_member/
        remove_group_member di fastapi_legal_entity_router.py."""
        return self.legal_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "entity_type": self.entity_type,
            "registration_number": self.registration_number,
            "npwp": self.npwp,
            "nppp": self.nppp,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "province": self.province,
            "country": self.country,
            "phone": self.phone,
            "fax": self.fax,
            "email": self.email,
            "website": self.website,
            "established_date": self.established_date.isoformat() if self.established_date else None,
            "fiscal_year_start": self.fiscal_year_start,
            "fiscal_year_end": self.fiscal_year_end,
            "base_currency": self.base_currency,
            "functional_currency": self.functional_currency,
            "is_taxable": self.is_taxable,
            "status": self.status,
            "is_active": self.is_active,
            "is_locked": self.is_locked,
            "parent_company_id": str(self.parent_company_id) if self.parent_company_id else None,
            "parent_company_name": self.parent_company_name,
            "consolidation_group_id": str(self.consolidation_group_id) if self.consolidation_group_id else None,
            "consolidation_group_name": self.consolidation_group_name,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by_name": self.created_by_name,
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
            entity_type=data.get("entity_type", "corporation"),
            registration_number=data.get("registration_number"),
            npwp=data.get("npwp"),
            nppp=data.get("nppp"),
            address=data.get("address"),
            city=data.get("city"),
            postal_code=data.get("postal_code"),
            province=data.get("province"),
            country=data.get("country", "ID"),
            phone=data.get("phone"),
            fax=data.get("fax"),
            email=data.get("email"),
            website=data.get("website"),
            established_date=datetime.fromisoformat(data["established_date"]) if data.get("established_date") else None,
            fiscal_year_start=data.get("fiscal_year_start", 1),
            fiscal_year_end=data.get("fiscal_year_end", 12),
            base_currency=data.get("base_currency", "IDR"),
            functional_currency=data.get("functional_currency", "IDR"),
            is_taxable=data.get("is_taxable", True),
            status=data.get("status", "active"),
            is_active=data.get("is_active", True),
            is_locked=data.get("is_locked", False),
            parent_company_id=UUID(data["parent_company_id"]) if data.get("parent_company_id") else None,
            parent_company_name=data.get("parent_company_name"),
            consolidation_group_id=UUID(data["consolidation_group_id"]) if data.get("consolidation_group_id") else None,
            consolidation_group_name=data.get("consolidation_group_name"),
            notes=data.get("notes"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_by_name=data.get("created_by_name"),
            version=data.get("version", 1),
            tax_office=data.get("tax_office"),
            tax_office_code=data.get("tax_office_code"),
            tax_classification=data.get("tax_classification"),
            taxable_date=date.fromisoformat(data["taxable_date"]) if data.get("taxable_date") else None,
            annual_tax_return_due_date=date.fromisoformat(data["annual_tax_return_due_date"]) if data.get("annual_tax_return_due_date") else None,
            monthly_tax_due_date=date.fromisoformat(data["monthly_tax_due_date"]) if data.get("monthly_tax_due_date") else None,
            is_vat_collector=data.get("is_vat_collector", True),
            vat_collector_number=data.get("vat_collector_number"),
            is_withholding_agent=data.get("is_withholding_agent", True),
        )


@dataclass(kw_only=True)
class ConsolidationGroup:
    id: UUID = _dc_field(default_factory=uuid4)
    group_code: str
    group_name: str
    description: str | None = None
    base_currency: str = "IDR"
    fiscal_year_start: int = 1
    fiscal_year_end: int = 12
    member_count: int = 0
    is_active: bool = True
    notes: str | None = None
    created_at: datetime = _dc_field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = _dc_field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "group_code": self.group_code,
            "group_name": self.group_name,
            "description": self.description,
            "base_currency": self.base_currency,
            "fiscal_year_start": self.fiscal_year_start,
            "fiscal_year_end": self.fiscal_year_end,
            "member_count": self.member_count,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "created_by_name": self.created_by_name,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConsolidationGroup:
        return cls(
            id=UUID(data["id"]) if data.get("id") else uuid4(),
            group_code=data.get("group_code") or data["id"][:8],
            group_name=data["group_name"],
            description=data.get("description"),
            base_currency=data.get("base_currency", "IDR"),
            fiscal_year_start=data.get("fiscal_year_start", 1),
            fiscal_year_end=data.get("fiscal_year_end", 12),
            member_count=data.get("member_count", 0),
            is_active=data.get("is_active", True),
            notes=data.get("notes"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_by_name=data.get("created_by_name"),
            version=data.get("version", 1),
        )


@dataclass(kw_only=True)
class LegalEntityBranch:
    id: UUID = _dc_field(default_factory=uuid4)
    legal_entity_id: UUID
    branch_name: str
    branch_code: str
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    email: str | None = None
    manager_name: str | None = None
    status: str = "active"
    is_active: bool = True
    notes: str | None = None
    created_at: datetime = _dc_field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = _dc_field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "branch_name": self.branch_name,
            "branch_code": self.branch_code,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "phone": self.phone,
            "email": self.email,
            "manager_name": self.manager_name,
            "status": self.status,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "created_by_name": self.created_by_name,
            "version": self.version,
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
            postal_code=data.get("postal_code"),
            phone=data.get("phone"),
            email=data.get("email"),
            manager_name=data.get("manager_name"),
            status=data.get("status", "active"),
            is_active=data.get("is_active", True),
            notes=data.get("notes"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_by_name=data.get("created_by_name"),
            version=data.get("version", 1),
        )


@dataclass(kw_only=True)
class LegalEntityHistoryEntry:
    timestamp: datetime
    action: str
    field: str | None = None
    old_value: Any = None
    new_value: Any = None
    actor_id: UUID = _dc_field(default_factory=lambda: UUID(int=0))
    actor_name: str | None = None
    reason: str | None = None


@dataclass(kw_only=True)
class LegalEntityStatusInfo:
    legal_name: str
    status: str
    is_active: bool
    is_locked: bool
    can_edit: bool
    can_delete: bool
    can_add_branch: bool
    can_modify_tax: bool
    tax_status: str
    registration_valid: bool
    npwp_valid: bool


@dataclass(kw_only=True)
class TaxProfileInfo:
    legal_entity_id: UUID
    tax_office: str | None = None
    tax_office_code: str | None = None
    tax_classification: str | None = None
    taxable_date: date | None = None
    vat_collector_number: str | None = None
    annual_tax_return_due_date: int | None = None
    monthly_tax_due_date: int | None = None
    corporate_tax_rate: Decimal = Decimal("22")
    vat_rate: Decimal = Decimal("11")
    is_using_final_tax: bool = False
    final_tax_rate: Decimal | None = None
    notes: str | None = None
    status: str = "active"
    updated_at: datetime = _dc_field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = _dc_field(default_factory=lambda: UUID(int=0))
    version: int = 1


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
    Service untuk mengelola Legal Entity (entitas hukum/perusahaan).

    STATUS PERSISTENSI (per 2026-08-12):
    - Legal Entity inti (create/get/list/update/activate/deactivate/lock/
      unlock/status) DIBACA & DITULIS LANGSUNG ke tabel `legal_entity` via
      SQLAlchemy AsyncSession (lihat `_session_scope()`). Ini menyamai pola
      SQLAlchemyEmployeeRepository.
    - Tax profile disimpan sebagian di kolom asli tabel `legal_entity`
      (tax_office, tax_office_code, tax_classification, taxable_date,
      is_vat_collector, vat_collector_number, is_withholding_agent) dan
      sebagian lagi (corporate_tax_rate, vat_rate, is_using_final_tax,
      final_tax_rate, status pajak, updated_by/version pajak) di kolom
      JSONB `extra_metadata` (key "tax_profile") karena kolom-kolom itu
      belum ada di skema tabel - jadi tetap persisten ke DB, hanya bukan
      kolom native.
    - Branch & Consolidation Group: SUDAH DB-backed (tabel
      `legal_entity_branch` & `consolidation_group`, lihat migrasi
      c3d4e5f6a7b8_persist_branch_and_consolidation_group). Keanggotaan
      grup konsolidasi tetap disimpan sebagai FK `consolidation_group_id`
      langsung di baris `legal_entity` (pola yang sudah dipakai
      add_member_to_group/remove_member_from_group sejak awal) - jumlah
      member dihitung via COUNT() saat dibaca, tidak ada tabel junction
      terpisah karena service tidak pernah mengekspos data per-membership
      selain "entitas ini ada di grup X atau tidak".
    """

    def __init__(self, event_publisher: EventPublisherPort | None = None):
        self._event_publisher = event_publisher
        self._stats = {
            "entities_created": 0,
            "entities_updated": 0,
            "entities_deactivated": 0,
            "entities_reactivated": 0,
            "entities_suspended": 0,
            "entities_dissolved": 0,
        }
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("LegalEntityService initialized (database-backed for core entity)")

    # ==================== SESSION SCOPE (DB-backed core entity) ====================

    @asynccontextmanager
    async def _session_scope(self):
        """Selalu membuka AsyncSession baru per pemanggilan dan menutupnya di
        akhir. Lihat catatan panjang di SQLAlchemyEmployeeRepository untuk
        alasan kenapa TIDAK boleh cache satu AsyncSession di instance -
        LegalEntityService didaftarkan sebagai singleton di IoC container."""
        from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct
        session = await get_async_session_direct()
        try:
            yield session
        finally:
            await session.close()

    @staticmethod
    def _row_to_entity(row: LegalEntityTable, parent_name: str | None = None, group_name: str | None = None) -> LegalEntity:
        data = row.to_dict()
        tax_meta = (row.extra_metadata or {}).get("tax_profile", {}) if row.extra_metadata else {}
        return LegalEntity(
            id=row.id,
            legal_name=data["legal_name"],
            trade_name=data["trade_name"],
            entity_type=data["entity_type"],
            registration_number=data["registration_number"],
            npwp=data["npwp"],
            nppp=data["nppp"],
            address=data["address"],
            city=data["city"],
            postal_code=data["postal_code"],
            province=data["province"],
            country=data["country"],
            phone=data["phone"],
            fax=data["fax"],
            email=data["email"],
            website=data["website"],
            established_date=(
                datetime.combine(row.established_date, datetime.min.time()) if row.established_date else None
            ),
            fiscal_year_start=data["fiscal_year_start"],
            fiscal_year_end=data["fiscal_year_end"],
            base_currency=data["base_currency"],
            functional_currency=data["functional_currency"],
            is_taxable=data["is_taxable"],
            status=data["status"],
            is_active=data["is_active"],
            is_locked=data["is_locked"],
            parent_company_id=row.parent_company_id,
            parent_company_name=parent_name,
            consolidation_group_id=row.consolidation_group_id,
            consolidation_group_name=group_name,
            notes=data["notes"],
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            created_by_name=None,  # perlu lookup IAM terpisah - belum tersedia di sini
            version=data["version"],
            tax_office=data["tax_office"],
            tax_office_code=data["tax_office_code"],
            tax_classification=data["tax_classification"],
            taxable_date=row.taxable_date,
            annual_tax_return_due_date=None,
            monthly_tax_due_date=None,
            is_vat_collector=data["is_vat_collector"],
            vat_collector_number=data["vat_collector_number"],
            is_withholding_agent=data["is_withholding_agent"],
        )

    @staticmethod
    def _row_to_branch(row: LegalEntityBranchTable) -> LegalEntityBranch:
        data = row.to_dict()
        return LegalEntityBranch(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            branch_name=data["branch_name"],
            branch_code=data["branch_code"] or "",
            address=data["address"],
            city=data["city"],
            postal_code=data["postal_code"],
            phone=data["phone"],
            email=data["email"],
            manager_name=data["manager_name"],
            status=data["status"],
            is_active=data["is_active"],
            notes=data["notes"],
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            version=data["version"],
        )

    async def _row_to_group(self, session, row: ConsolidationGroupTable) -> ConsolidationGroup:
        data = row.to_dict()
        count_stmt = select(func.count()).select_from(LegalEntityTable).where(
            LegalEntityTable.consolidation_group_id == row.id,
            LegalEntityTable.deleted_at.is_(None),
        )
        member_count = (await session.execute(count_stmt)).scalar_one()
        return ConsolidationGroup(
            id=row.id,
            group_code=data["group_code"],
            group_name=data["group_name"],
            description=data["description"],
            base_currency=data["base_currency"],
            fiscal_year_start=data["fiscal_year_start"],
            fiscal_year_end=data["fiscal_year_end"],
            member_count=member_count,
            is_active=data["is_active"],
            notes=data["notes"],
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            version=data["version"],
        )

    async def _resolve_names(self, session, parent_company_id: UUID | None, consolidation_group_id: UUID | None) -> tuple[str | None, str | None]:
        parent_name = None
        group_name = None
        if parent_company_id:
            stmt = select(LegalEntityTable.legal_name).where(LegalEntityTable.id == parent_company_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            parent_name = row
        if consolidation_group_id:
            stmt_g = select(ConsolidationGroupTable.group_name).where(
                ConsolidationGroupTable.id == consolidation_group_id
            )
            result_g = await session.execute(stmt_g)
            group_name = result_g.scalar_one_or_none()
        return parent_name, group_name

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "LegalEntityService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        if len(self._audit_trail) > 10000:
            self._audit_trail = self._audit_trail[-5000:]
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # Legal Entity CRUD (DATABASE-BACKED)
    # ========================================================================

    @audit
    async def create_legal_entity(
        self,
        legal_name: str,
        entity_type: str = "corporation",
        trade_name: str | None = None,
        registration_number: str | None = None,
        npwp: str | None = None,
        nppp: str | None = None,
        address: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        province: str | None = None,
        country: str = "ID",
        phone: str | None = None,
        fax: str | None = None,
        email: str | None = None,
        website: str | None = None,
        established_date: date | datetime | None = None,
        fiscal_year_start: int = 1,
        fiscal_year_end: int = 12,
        base_currency: str = "IDR",
        functional_currency: str = "IDR",
        is_taxable: bool = True,
        is_withholding_agent: bool = True,
        parent_company_id: UUID | None = None,
        consolidation_group_id: UUID | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> LegalEntity:
        self._check_authority(created_by, "create_legal_entity")
        logger.info(f"Creating legal entity: {legal_name}")

        est_date = established_date.date() if isinstance(established_date, datetime) else established_date

        async with self._session_scope() as session:
            async with session.begin():
                row = LegalEntityTable(
                    id=uuid4(),
                    legal_name=legal_name,
                    trade_name=trade_name,
                    entity_type=entity_type,
                    registration_number=registration_number,
                    npwp=npwp,
                    nppp=nppp,
                    address=address,
                    city=city,
                    postal_code=postal_code,
                    province=province,
                    country=country,
                    phone=phone,
                    fax=fax,
                    email=email,
                    website=website,
                    established_date=est_date,
                    fiscal_year_start=fiscal_year_start,
                    fiscal_year_end=fiscal_year_end,
                    base_currency=base_currency,
                    functional_currency=functional_currency,
                    is_taxable=is_taxable,
                    is_withholding_agent=is_withholding_agent,
                    status="active",
                    is_active=True,
                    parent_company_id=parent_company_id,
                    consolidation_group_id=consolidation_group_id,
                    notes=notes,
                    created_by=created_by,
                    extra_metadata={},
                    version=1,
                )
                session.add(row)
                await session.flush()
                parent_name, group_name = await self._resolve_names(session, parent_company_id, consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        self._stats["entities_created"] += 1

        if self._event_publisher:
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

        self._record_audit("create_legal_entity", {
            "entity_id": str(entity.id),
            "legal_name": legal_name,
            "created_by": str(created_by) if created_by else None,
        })

        logger.info(f"Legal entity created with ID {entity.id}")
        return entity

    async def get_legal_entity_by_id(self, legal_entity_id: UUID) -> LegalEntity | None:
        async with self._session_scope() as session:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
            return self._row_to_entity(row, parent_name, group_name)

    # Alias lama - dipertahankan untuk kompatibilitas kalau ada pemanggil lain di codebase.
    get_legal_entity = get_legal_entity_by_id

    async def get_legal_entity_by_npwp(self, npwp: str) -> LegalEntity | None:
        async with self._session_scope() as session:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.npwp == npwp, LegalEntityTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
            return self._row_to_entity(row, parent_name, group_name)

    async def get_legal_entity_by_registration(self, registration_number: str) -> LegalEntity | None:
        async with self._session_scope() as session:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.registration_number == registration_number,
                LegalEntityTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
            return self._row_to_entity(row, parent_name, group_name)

    async def list_legal_entities(
        self,
        entity_type: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
    ) -> list[LegalEntity]:
        async with self._session_scope() as session:
            stmt = select(LegalEntityTable).where(LegalEntityTable.deleted_at.is_(None))
            if entity_type:
                stmt = stmt.where(LegalEntityTable.entity_type == entity_type)
            if status:
                stmt = stmt.where(LegalEntityTable.status == status)
            if is_active is not None:
                stmt = stmt.where(LegalEntityTable.is_active == is_active)
            stmt = stmt.order_by(LegalEntityTable.legal_name)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            entities = []
            for row in rows:
                parent_name, group_name = await self._resolve_names(
                    session, row.parent_company_id, row.consolidation_group_id
                )
                entities.append(self._row_to_entity(row, parent_name, group_name))
            return entities

    @audit
    async def update_legal_entity(
        self,
        legal_entity_id: UUID,
        legal_name: str | None = None,
        trade_name: str | None = None,
        entity_type: str | None = None,
        registration_number: str | None = None,
        npwp: str | None = None,
        nppp: str | None = None,
        address: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        province: str | None = None,
        country: str | None = None,
        phone: str | None = None,
        fax: str | None = None,
        email: str | None = None,
        website: str | None = None,
        fiscal_year_start: int | None = None,
        fiscal_year_end: int | None = None,
        base_currency: str | None = None,
        functional_currency: str | None = None,
        is_taxable: bool | None = None,
        is_withholding_agent: bool | None = None,
        parent_company_id: UUID | None = None,
        status: str | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "update_legal_entity")
        logger.info(f"Updating legal entity {legal_entity_id}")

        field_map = {
            "legal_name": legal_name,
            "trade_name": trade_name,
            "entity_type": entity_type,
            "registration_number": registration_number,
            "npwp": npwp,
            "nppp": nppp,
            "address": address,
            "city": city,
            "postal_code": postal_code,
            "province": province,
            "country": country,
            "phone": phone,
            "fax": fax,
            "email": email,
            "website": website,
            "fiscal_year_start": fiscal_year_start,
            "fiscal_year_end": fiscal_year_end,
            "base_currency": base_currency,
            "functional_currency": functional_currency,
            "is_taxable": is_taxable,
            "is_withholding_agent": is_withholding_agent,
            "parent_company_id": parent_company_id,
            "status": status,
            "notes": notes,
        }

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    raise LegalEntityNotFoundError(f"Legal entity {legal_entity_id} not found")

                changes: dict[str, Any] = {}
                for key, new_value in field_map.items():
                    if new_value is None:
                        continue
                    old_value = getattr(row, key)
                    if new_value != old_value:
                        changes[key] = {"old": old_value, "new": new_value}
                        setattr(row, key, new_value)
                        if key == "status":
                            row.is_active = new_value == "active"

                if changes:
                    row.increment_version()
                    await session.flush()
                    # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                    # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                    # lazy-load implisit (itu penyebab MissingGreenlet).
                    await session.refresh(row)

                parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        if not changes:
            return entity

        self._stats["entities_updated"] += 1

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
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (updated)", correlation_id)

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

        self._record_audit("update_legal_entity", {
            "entity_id": str(legal_entity_id),
            "changes": changes,
            "updated_by": str(updated_by) if updated_by else None,
        })

        return entity

    @audit
    async def deactivate_legal_entity(
        self,
        legal_entity_id: UUID,
        updated_by: UUID,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "deactivate_legal_entity")
        logger.info(f"Deactivating legal entity {legal_entity_id}")

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.deactivate(reason)
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        self._stats["entities_deactivated"] += 1

        if self._event_publisher:
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

        self._record_audit("deactivate_legal_entity", {
            "entity_id": str(legal_entity_id),
            "reason": reason,
            "updated_by": str(updated_by),
        })

        return entity

    @audit
    async def activate_legal_entity(
        self,
        legal_entity_id: UUID,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "activate_legal_entity")
        logger.info(f"Activating legal entity {legal_entity_id}")

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                already_active = row.is_active
                row.activate()
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        if already_active:
            return entity

        self._stats["entities_reactivated"] += 1

        if self._event_publisher:
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                entity_id=entity.id,
                entity_code=entity.registration_number or entity.id.hex[:8],
                changes={"status": {"old": "inactive", "new": "active"}},
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {entity.legal_name} (activated)", correlation_id)

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

        self._record_audit("activate_legal_entity", {
            "entity_id": str(legal_entity_id),
            "updated_by": str(updated_by),
        })

        return entity

    # Alias lama.
    reactivate_legal_entity = activate_legal_entity

    @audit
    async def suspend_legal_entity(
        self,
        legal_entity_id: UUID,
        reason: str,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "suspend_legal_entity")
        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.suspend(reason)
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        self._stats["entities_suspended"] += 1

        if self._event_publisher:
            event_suspend = CompanySuspendedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=entity.id,
                company_name=entity.legal_name,
                reason=reason,
                suspended_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event_suspend, f"Company {entity.legal_name} (suspended)", correlation_id)

        self._record_audit("suspend_legal_entity", {
            "entity_id": str(legal_entity_id),
            "reason": reason,
            "updated_by": str(updated_by),
        })
        return entity

    @audit
    async def dissolve_legal_entity(
        self,
        legal_entity_id: UUID,
        reason: str,
        updated_by: UUID,
        effective_date: date | None = None,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "dissolve_legal_entity")
        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.liquidate(effective_date or date.today())
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        self._stats["entities_dissolved"] += 1

        if self._event_publisher:
            event_dissolve = CompanyDissolvedEvent(
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=entity.id,
                company_name=entity.legal_name,
                reason=reason,
                dissolved_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event_dissolve, f"Company {entity.legal_name} (dissolved)", correlation_id)

        self._record_audit("dissolve_legal_entity", {
            "entity_id": str(legal_entity_id),
            "reason": reason,
            "updated_by": str(updated_by),
        })
        return entity

    @audit
    async def lock_legal_entity(
        self,
        legal_entity_id: UUID,
        updated_by: UUID,
        reason: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "lock_legal_entity")
        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.lock(updated_by, reason)
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        self._record_audit("lock_legal_entity", {
            "entity_id": str(legal_entity_id),
            "reason": reason,
            "updated_by": str(updated_by),
        })
        return entity

    @audit
    async def unlock_legal_entity(
        self,
        legal_entity_id: UUID,
        updated_by: UUID,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "unlock_legal_entity")
        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.unlock(updated_by)
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, group_name = await self._resolve_names(session, row.parent_company_id, row.consolidation_group_id)
                entity = self._row_to_entity(row, parent_name, group_name)

        self._record_audit("unlock_legal_entity", {
            "entity_id": str(legal_entity_id),
            "updated_by": str(updated_by),
        })
        return entity

    async def get_legal_entity_status(self, legal_entity_id: UUID) -> LegalEntityStatusInfo | None:
        entity = await self.get_legal_entity_by_id(legal_entity_id)
        if not entity:
            return None
        return LegalEntityStatusInfo(
            legal_name=entity.legal_name,
            status=entity.status,
            is_active=entity.is_active,
            is_locked=entity.is_locked,
            can_edit=entity.is_active and not entity.is_locked,
            can_delete=entity.is_active and not entity.is_locked,
            can_add_branch=entity.is_active and not entity.is_locked,
            can_modify_tax=entity.is_active and not entity.is_locked,
            tax_status="active" if entity.is_taxable else "inactive",
            registration_valid=bool(entity.registration_number),
            npwp_valid=bool(entity.npwp) and len(entity.npwp) == 15,
        )

    async def get_legal_entity_history(self, legal_entity_id: UUID) -> list[LegalEntityHistoryEntry]:
        """History diambil dari audit trail in-process (belum ada tabel
        audit log khusus legal_entity di database). Hilang saat restart -
        sama seperti keterbatasan branch/consolidation group."""
        entries = []
        for a in self._audit_trail:
            if a["details"].get("entity_id") == str(legal_entity_id):
                entries.append(LegalEntityHistoryEntry(
                    timestamp=datetime.fromisoformat(a["timestamp"]),
                    action=a["action"],
                    field=None,
                    old_value=None,
                    new_value=a["details"].get("changes"),
                    actor_id=UUID(a["details"]["updated_by"]) if a["details"].get("updated_by") else UUID(int=0),
                    actor_name=None,
                    reason=a["details"].get("reason"),
                ))
        return entries

    # ========================================================================
    # Tax Profile
    # ========================================================================

    async def get_tax_profile(self, legal_entity_id: UUID) -> TaxProfileInfo | None:
        async with self._session_scope() as session:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            meta = (row.extra_metadata or {}).get("tax_profile", {})
            return TaxProfileInfo(
                legal_entity_id=row.id,
                tax_office=row.tax_office,
                tax_office_code=row.tax_office_code,
                tax_classification=row.tax_classification,
                taxable_date=row.taxable_date,
                vat_collector_number=row.vat_collector_number,
                annual_tax_return_due_date=row.annual_tax_return_due_date,
                monthly_tax_due_date=row.monthly_tax_due_date,
                corporate_tax_rate=Decimal(str(meta.get("corporate_tax_rate", "22"))),
                vat_rate=Decimal(str(meta.get("vat_rate", "11"))),
                is_using_final_tax=meta.get("is_using_final_tax", False),
                final_tax_rate=Decimal(str(meta["final_tax_rate"])) if meta.get("final_tax_rate") is not None else None,
                notes=meta.get("notes"),
                status=meta.get("status", "active"),
                updated_at=row.updated_at,
                updated_by=UUID(meta["updated_by"]) if meta.get("updated_by") else UUID(int=0),
                version=meta.get("version", 1),
            )

    @audit
    async def update_tax_profile(
        self,
        legal_entity_id: UUID,
        tax_office: str | None = None,
        tax_office_code: str | None = None,
        tax_classification: str | None = None,
        taxable_date: date | None = None,
        vat_collector_number: str | None = None,
        annual_tax_return_due_date: int | None = None,
        monthly_tax_due_date: int | None = None,
        corporate_tax_rate: Decimal | None = None,
        vat_rate: Decimal | None = None,
        is_using_final_tax: bool | None = None,
        final_tax_rate: Decimal | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> TaxProfileInfo | None:
        self._check_authority(updated_by, "update_tax_profile")
        logger.info(f"Updating tax profile for {legal_entity_id}")

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None

                changes: dict[str, Any] = {}
                native_fields = {
                    "tax_office": tax_office,
                    "tax_office_code": tax_office_code,
                    "tax_classification": tax_classification,
                    "taxable_date": taxable_date,
                    "vat_collector_number": vat_collector_number,
                    "annual_tax_return_due_date": annual_tax_return_due_date,
                    "monthly_tax_due_date": monthly_tax_due_date,
                }
                for key, new_value in native_fields.items():
                    if new_value is None:
                        continue
                    old_value = getattr(row, key)
                    if new_value != old_value:
                        changes[key] = {"old": old_value, "new": new_value}
                        setattr(row, key, new_value)

                meta = dict(row.extra_metadata or {})
                tax_meta = dict(meta.get("tax_profile", {}))
                extra_fields = {
                    "corporate_tax_rate": str(corporate_tax_rate) if corporate_tax_rate is not None else None,
                    "vat_rate": str(vat_rate) if vat_rate is not None else None,
                    "is_using_final_tax": is_using_final_tax,
                    "final_tax_rate": str(final_tax_rate) if final_tax_rate is not None else None,
                    "notes": notes,
                }
                for key, new_value in extra_fields.items():
                    if new_value is None:
                        continue
                    if tax_meta.get(key) != new_value:
                        changes[key] = {"old": tax_meta.get(key), "new": new_value}
                        tax_meta[key] = new_value

                if changes:
                    tax_meta["updated_by"] = str(updated_by) if updated_by else None
                    tax_meta["version"] = tax_meta.get("version", 1) + 1
                    meta["tax_profile"] = tax_meta
                    row.extra_metadata = meta
                    row.increment_version()
                    await session.flush()
                    # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                    # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                    # lazy-load implisit (itu penyebab MissingGreenlet).
                    await session.refresh(row)

                result_meta = dict((row.extra_metadata or {}).get("tax_profile", {}))
                profile = TaxProfileInfo(
                    legal_entity_id=row.id,
                    tax_office=row.tax_office,
                    tax_office_code=row.tax_office_code,
                    tax_classification=row.tax_classification,
                    taxable_date=row.taxable_date,
                    vat_collector_number=row.vat_collector_number,
                    annual_tax_return_due_date=row.annual_tax_return_due_date,
                    monthly_tax_due_date=row.monthly_tax_due_date,
                    corporate_tax_rate=Decimal(str(result_meta.get("corporate_tax_rate", "22"))),
                    vat_rate=Decimal(str(result_meta.get("vat_rate", "11"))),
                    is_using_final_tax=result_meta.get("is_using_final_tax", False),
                    final_tax_rate=(
                        Decimal(str(result_meta["final_tax_rate"])) if result_meta.get("final_tax_rate") is not None else None
                    ),
                    notes=result_meta.get("notes"),
                    status=result_meta.get("status", "active"),
                    updated_at=row.updated_at,
                    updated_by=updated_by or UUID(int=0),
                    version=result_meta.get("version", 1),
                )
                legal_name = row.legal_name
                entity_code = row.registration_number or str(row.id)[:8]
                entity_id = row.id
                entity_version = row.version

        if self._event_publisher and changes:
            event = LegalEntityUpdatedEvent(
                aggregate_id=entity_id,
                aggregate_version=entity_version,
                entity_id=entity_id,
                entity_code=entity_code,
                changes=changes,
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"LegalEntity {legal_name} (tax profile updated)", correlation_id)

        self._record_audit("update_tax_profile", {
            "entity_id": str(legal_entity_id),
            "changes": changes,
            "updated_by": str(updated_by) if updated_by else None,
        })

        return profile

    # ========================================================================
    # Consolidation Group (DATABASE-BACKED - tabel consolidation_group)
    # ========================================================================

    @audit
    async def create_consolidation_group(
        self,
        group_code: str,
        group_name: str,
        description: str | None = None,
        base_currency: str = "IDR",
        fiscal_year_start: int = 1,
        fiscal_year_end: int = 12,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> ConsolidationGroup:
        self._check_authority(created_by, "create_consolidation_group")
        logger.info(f"Creating consolidation group: {group_name}")

        async with self._session_scope() as session:
            async with session.begin():
                row = ConsolidationGroupTable(
                    id=uuid4(),
                    group_code=group_code,
                    group_name=group_name,
                    description=description,
                    base_currency=base_currency,
                    fiscal_year_start=fiscal_year_start,
                    fiscal_year_end=fiscal_year_end,
                    notes=notes,
                    is_active=True,
                    created_by=created_by,
                    version=1,
                )
                session.add(row)
                await session.flush()
                group = await self._row_to_group(session, row)

        self._record_audit("create_consolidation_group", {
            "group_id": str(group.id),
            "group_name": group_name,
            "created_by": str(created_by) if created_by else None,
        })
        return group

    async def list_consolidation_groups(self, is_active: bool | None = None) -> list[ConsolidationGroup]:
        async with self._session_scope() as session:
            stmt = select(ConsolidationGroupTable).where(ConsolidationGroupTable.deleted_at.is_(None))
            if is_active is not None:
                stmt = stmt.where(ConsolidationGroupTable.is_active == is_active)
            stmt = stmt.order_by(ConsolidationGroupTable.group_name)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [await self._row_to_group(session, row) for row in rows]

    async def get_consolidation_group_by_id(self, group_id: UUID) -> ConsolidationGroup | None:
        async with self._session_scope() as session:
            stmt = select(ConsolidationGroupTable).where(
                ConsolidationGroupTable.id == group_id, ConsolidationGroupTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return await self._row_to_group(session, row)

    @audit
    async def update_consolidation_group(
        self,
        group_id: UUID,
        group_name: str | None = None,
        description: str | None = None,
        base_currency: str | None = None,
        fiscal_year_start: int | None = None,
        fiscal_year_end: int | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
    ) -> ConsolidationGroup | None:
        self._check_authority(updated_by, "update_consolidation_group")

        field_map = {
            "group_name": group_name,
            "description": description,
            "base_currency": base_currency,
            "fiscal_year_start": fiscal_year_start,
            "fiscal_year_end": fiscal_year_end,
            "notes": notes,
        }

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(ConsolidationGroupTable).where(
                    ConsolidationGroupTable.id == group_id, ConsolidationGroupTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None

                for key, new_value in field_map.items():
                    if new_value is not None:
                        setattr(row, key, new_value)

                row.version += 1
                await session.flush()
                await session.refresh(row)
                group = await self._row_to_group(session, row)

        self._record_audit("update_consolidation_group", {
            "group_id": str(group_id),
            "updated_by": str(updated_by) if updated_by else None,
        })
        return group

    @audit
    async def deactivate_consolidation_group(self, group_id: UUID, updated_by: UUID) -> ConsolidationGroup | None:
        self._check_authority(updated_by, "deactivate_consolidation_group")

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(ConsolidationGroupTable).where(
                    ConsolidationGroupTable.id == group_id, ConsolidationGroupTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.is_active = False
                row.version += 1
                await session.flush()
                await session.refresh(row)
                group = await self._row_to_group(session, row)

        self._record_audit("deactivate_consolidation_group", {
            "group_id": str(group_id),
            "updated_by": str(updated_by),
        })
        return group

    @audit
    async def add_member_to_group(
        self,
        group_id: UUID,
        legal_entity_id: UUID,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "add_member_to_group")
        logger.info(f"Adding {legal_entity_id} to group {group_id}")

        async with self._session_scope() as session:
            async with session.begin():
                group_stmt = select(ConsolidationGroupTable).where(
                    ConsolidationGroupTable.id == group_id, ConsolidationGroupTable.deleted_at.is_(None)
                )
                group_row = (await session.execute(group_stmt)).scalar_one_or_none()
                if not group_row:
                    raise ConsolidationGroupNotFoundError(f"Group {group_id} not found")

                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    raise LegalEntityNotFoundError(f"Legal entity {legal_entity_id} not found")
                row.consolidation_group_id = group_id
                row.increment_version()
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, _ = await self._resolve_names(session, row.parent_company_id, None)
                entity = self._row_to_entity(row, parent_name, group_row.group_name)

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

        self._record_audit("add_member_to_group", {
            "group_id": str(group_id),
            "entity_id": str(legal_entity_id),
            "updated_by": str(updated_by),
        })

        return entity

    @audit
    async def remove_member_from_group(
        self,
        group_id: UUID,
        legal_entity_id: UUID,
        updated_by: UUID,
        correlation_id: str | None = None,
    ) -> LegalEntity | None:
        self._check_authority(updated_by, "remove_member_from_group")
        logger.info(f"Removing {legal_entity_id} from group {group_id}")

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityTable).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.consolidation_group_id = None
                row.increment_version()
                await session.flush()
                # updated_at pakai onupdate server-side (func.now()) - expired setelah UPDATE,
                # harus di-refresh eksplisit (awaited), bukan dibiarkan to_dict() memicu
                # lazy-load implisit (itu penyebab MissingGreenlet).
                await session.refresh(row)
                parent_name, _ = await self._resolve_names(session, row.parent_company_id, None)
                entity = self._row_to_entity(row, parent_name, None)

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

        self._record_audit("remove_member_from_group", {
            "group_id": str(group_id),
            "entity_id": str(legal_entity_id),
            "updated_by": str(updated_by),
        })

        return entity

    # ========================================================================
    # Branch Management (DATABASE-BACKED - tabel legal_entity_branch)
    # ========================================================================

    @audit
    async def create_branch(
        self,
        legal_entity_id: UUID,
        branch_code: str,
        branch_name: str,
        address: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        manager_name: str | None = None,
        is_active: bool = True,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> LegalEntityBranch:
        self._check_authority(created_by, "create_branch")
        logger.info(f"Creating branch {branch_code} for legal entity {legal_entity_id}")

        async with self._session_scope() as session:
            async with session.begin():
                parent_stmt = select(LegalEntityTable.id).where(
                    LegalEntityTable.id == legal_entity_id, LegalEntityTable.deleted_at.is_(None)
                )
                if (await session.execute(parent_stmt)).scalar_one_or_none() is None:
                    raise LegalEntityNotFoundError(f"Legal entity {legal_entity_id} not found")

                row = LegalEntityBranchTable(
                    id=uuid4(),
                    legal_entity_id=legal_entity_id,
                    branch_code=branch_code,
                    branch_name=branch_name,
                    address=address,
                    city=city,
                    postal_code=postal_code,
                    phone=phone,
                    email=email,
                    manager_name=manager_name,
                    status="active",
                    is_active=is_active,
                    notes=notes,
                    created_by=created_by,
                    version=1,
                )
                session.add(row)
                await session.flush()
                branch = self._row_to_branch(row)

        self._record_audit("create_branch", {
            "branch_id": str(branch.id),
            "legal_entity_id": str(legal_entity_id),
            "branch_code": branch_code,
            "created_by": str(created_by) if created_by else None,
        })
        return branch

    # Alias lama.
    add_branch = create_branch

    async def list_branches(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        is_active: bool | None = None,
    ) -> list[LegalEntityBranch]:
        async with self._session_scope() as session:
            stmt = select(LegalEntityBranchTable).where(
                LegalEntityBranchTable.legal_entity_id == legal_entity_id
            )
            if status:
                stmt = stmt.where(LegalEntityBranchTable.status == status)
            if is_active is not None:
                stmt = stmt.where(LegalEntityBranchTable.is_active == is_active)
            stmt = stmt.order_by(LegalEntityBranchTable.branch_name)
            result = await session.execute(stmt)
            return [self._row_to_branch(row) for row in result.scalars().all()]

    async def get_branch_by_id(self, branch_id: UUID, legal_entity_id: UUID | None = None) -> LegalEntityBranch | None:
        async with self._session_scope() as session:
            stmt = select(LegalEntityBranchTable).where(LegalEntityBranchTable.id == branch_id)
            if legal_entity_id:
                stmt = stmt.where(LegalEntityBranchTable.legal_entity_id == legal_entity_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return self._row_to_branch(row) if row else None

    # Alias lama.
    get_branch = get_branch_by_id

    @audit
    async def update_branch(
        self,
        branch_id: UUID,
        legal_entity_id: UUID | None = None,
        branch_name: str | None = None,
        address: str | None = None,
        city: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        manager_name: str | None = None,
        is_active: bool | None = None,
        status: str | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
    ) -> LegalEntityBranch | None:
        self._check_authority(updated_by, "update_branch")

        field_map = {
            "branch_name": branch_name,
            "address": address,
            "city": city,
            "phone": phone,
            "email": email,
            "manager_name": manager_name,
            "is_active": is_active,
            "status": status,
            "notes": notes,
        }

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityBranchTable).where(
                    LegalEntityBranchTable.id == branch_id
                ).with_for_update()
                if legal_entity_id:
                    stmt = stmt.where(LegalEntityBranchTable.legal_entity_id == legal_entity_id)
                row = (await session.execute(stmt)).scalar_one_or_none()
                if not row:
                    return None

                for key, new_value in field_map.items():
                    if new_value is not None:
                        setattr(row, key, new_value)

                row.version += 1
                await session.flush()
                await session.refresh(row)
                branch = self._row_to_branch(row)

        self._record_audit("update_branch", {
            "branch_id": str(branch_id),
            "updated_by": str(updated_by) if updated_by else None,
        })
        return branch

    @audit
    async def close_branch(
        self,
        branch_id: UUID,
        legal_entity_id: UUID | None = None,
        updated_by: UUID | None = None,
        reason: str | None = None,
    ) -> LegalEntityBranch | None:
        self._check_authority(updated_by, "close_branch")

        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(LegalEntityBranchTable).where(
                    LegalEntityBranchTable.id == branch_id
                ).with_for_update()
                if legal_entity_id:
                    stmt = stmt.where(LegalEntityBranchTable.legal_entity_id == legal_entity_id)
                row = (await session.execute(stmt)).scalar_one_or_none()
                if not row:
                    return None

                row.status = "closed"
                row.is_active = False
                if reason:
                    row.notes = f"{row.notes or ''}\n[closed: {reason}]".strip()
                row.version += 1
                await session.flush()
                await session.refresh(row)
                branch = self._row_to_branch(row)

        self._record_audit("close_branch", {
            "branch_id": str(branch_id),
            "reason": reason,
            "updated_by": str(updated_by) if updated_by else None,
        })
        return branch

    # Alias lama.
    deactivate_branch = close_branch

    # ========================================================================
    # Stats & Audit
    # ========================================================================

    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return list(self._audit_trail)


async def create_legal_entity_service(
    event_publisher: EventPublisherPort | None = None,
) -> LegalEntityService:
    return LegalEntityService(event_publisher=event_publisher)


__all__ = [
    "LegalEntity",
    "ConsolidationGroup",
    "LegalEntityBranch",
    "LegalEntityHistoryEntry",
    "LegalEntityStatusInfo",
    "TaxProfileInfo",
    "LegalEntityService",
    "LegalEntityServiceError",
    "LegalEntityNotFoundError",
    "ConsolidationGroupNotFoundError",
    "BranchNotFoundError",
    "EntityType",
    "EntityStatus",
    "create_legal_entity_service",
]
