#!/usr/bin/env python3
"""
Module: fastapi_legal_entity_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Legal Entity (entitas hukum):
               perusahaan, cabang, grup konsolidasi, profil pajak, tahun fiskal,
               registrasi perizinan, dan dokumen legal.

Method Standards (ERP):
- create_legal_entity() / update_legal_entity() / delete_legal_entity() / get_legal_entity()
- activate_legal_entity() / deactivate_legal_entity() / suspend_legal_entity()
- create_consolidation_group() / update_consolidation_group() / delete_consolidation_group()
- add_member_to_group() / remove_member_from_group()
- create_branch() / update_branch() / delete_branch() / get_branch()
- update_tax_profile() / get_tax_profile()
- update_fiscal_year() / get_fiscal_year()
- get_legal_entity_status() / get_legal_entity_history()
- get_legal_entity_by_npwp() / get_legal_entity_by_registration()
- audit_trail_legal_entity() / can_transition_legal_entity()
- register_legal_entity_event() / get_legal_entity_events()
- version_legal_entity()
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class LegalEntityType(str, Enum):
    """Jenis entitas hukum."""

    CORPORATION = "corporation"  # Perseroan Terbatas (PT)
    BRANCH = "branch"  # Cabang
    REPRESENTATIVE_OFFICE = "representative_office"  # Kantor Perwakilan
    PARTNERSHIP = "partnership"  # Firma (Fa) / CV
    SOLE_PROPRIETORSHIP = "sole_proprietorship"  # Perorangan (UD)
    COOPERATIVE = "cooperative"  # Koperasi
    FOUNDATION = "foundation"  # Yayasan
    CONSOLIDATION_GROUP = "consolidation_group"  # Grup Konsolidasi


class LegalEntityStatus(str, Enum):
    """Status entitas hukum."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"  # Dibubarkan
    BANKRUPT = "bankrupt"  # Pailit
    MERGED = "merged"  # Bergabung
    LOCKED = "locked"
    ARCHIVED = "archived"


class BranchStatus(str, Enum):
    """Status cabang."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    CLOSED = "closed"
    SUSPENDED = "suspended"


class TaxStatus(str, Enum):
    """Status pajak."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


# Default fiscal year settings
DEFAULT_FISCAL_YEAR_START_MONTH = 1  # January
DEFAULT_FISCAL_YEAR_END_MONTH = 12  # December
DEFAULT_BASE_CURRENCY = "IDR"
DEFAULT_FUNCTIONAL_CURRENCY = "IDR"
DEFAULT_TAX_RATE_PPN = Decimal("11")
DEFAULT_TAX_RATE_PPH_BADAN = Decimal("22")


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class LegalEntityCreateSchema(BaseModel):
    """Schema untuk membuat entitas hukum baru."""

    model_config = ConfigDict(from_attributes=True)

    legal_name: str = Field(..., min_length=3, max_length=200, description="Nama legal")
    trade_name: str | None = Field(None, max_length=200, description="Nama dagang")
    entity_type: LegalEntityType = Field(..., description="Jenis entitas")
    registration_number: str | None = Field(
        None, max_length=50, description="Nomor registrasi (NIB)"
    )
    npwp: str | None = Field(None, min_length=15, max_length=15, description="NPWP")
    nppp: str | None = Field(None, max_length=30, description="NPPP (untuk PKP)")
    address: str | None = Field(None, max_length=500, description="Alamat")
    city: str | None = Field(None, max_length=100, description="Kota")
    postal_code: str | None = Field(None, max_length=20, description="Kode pos")
    province: str | None = Field(None, max_length=100, description="Provinsi")
    country: str = Field("ID", max_length=2, description="Kode negara")
    phone: str | None = Field(None, max_length=20, description="Telepon")
    fax: str | None = Field(None, max_length=20, description="Fax")
    email: str | None = Field(None, max_length=200, description="Email")
    website: str | None = Field(None, max_length=200, description="Website")
    established_date: date | None = Field(None, description="Tanggal pendirian")
    fiscal_year_start: int = Field(
        DEFAULT_FISCAL_YEAR_START_MONTH, ge=1, le=12, description="Bulan awal tahun fiskal"
    )
    fiscal_year_end: int = Field(
        DEFAULT_FISCAL_YEAR_END_MONTH, ge=1, le=12, description="Bulan akhir tahun fiskal"
    )
    base_currency: str = Field(
        DEFAULT_BASE_CURRENCY, min_length=3, max_length=3, description="Mata uang dasar"
    )
    functional_currency: str = Field(
        DEFAULT_FUNCTIONAL_CURRENCY, min_length=3, max_length=3, description="Mata uang fungsional"
    )
    is_taxable: bool = Field(True, description="Apakah PKP")
    is_withholding_agent: bool = Field(True, description="Apakah pemotong pajak")
    parent_company_id: UUID | None = Field(None, description="ID perusahaan induk")
    consolidation_group_id: UUID | None = Field(None, description="ID grup konsolidasi")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("npwp")
    @classmethod
    def validate_npwp(cls, v: str | None) -> str | None:
        if v and not v.isdigit():
            raise ValueError("NPWP must contain only digits")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v and "@" not in v:
            raise ValueError("Invalid email format")
        return v


class LegalEntityUpdateSchema(BaseModel):
    """Schema untuk update entitas hukum."""

    model_config = ConfigDict(from_attributes=True)

    legal_name: str | None = Field(None, min_length=3, max_length=200)
    trade_name: str | None = Field(None, max_length=200)
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    province: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=20)
    fax: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    website: str | None = Field(None, max_length=200)
    status: LegalEntityStatus | None = None
    notes: str | None = Field(None, max_length=500)


class LegalEntityResponseSchema(BaseModel):
    """Response entitas hukum."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legal_name: str
    trade_name: str | None
    entity_type: LegalEntityType
    registration_number: str | None
    npwp: str | None
    nppp: str | None
    address: str | None
    city: str | None
    postal_code: str | None
    province: str | None
    country: str
    phone: str | None
    fax: str | None
    email: str | None
    website: str | None
    established_date: date | None
    fiscal_year_start: int
    fiscal_year_end: int
    base_currency: str
    functional_currency: str
    is_taxable: bool
    is_withholding_agent: bool
    status: LegalEntityStatus
    is_active: bool
    is_locked: bool = False
    parent_company_id: UUID | None
    parent_company_name: str | None = None
    consolidation_group_id: UUID | None
    consolidation_group_name: str | None = None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class TaxProfileSchema(BaseModel):
    """Schema untuk profil pajak."""

    model_config = ConfigDict(from_attributes=True)

    tax_office: str | None = Field(None, max_length=200, description="Kantor pajak")
    tax_office_code: str | None = Field(None, max_length=20, description="Kode KPP")
    tax_classification: str | None = Field(None, max_length=50, description="Klasifikasi pajak")
    taxable_date: date | None = Field(None, description="Tanggal pengukuhan PKP")
    vat_collector_number: str | None = Field(
        None, max_length=30, description="Nomor pengukuhan PKP"
    )
    annual_tax_return_due_date: int | None = Field(
        None, ge=1, le=31, description="Tanggal jatuh tempo SPT Tahunan"
    )
    monthly_tax_due_date: int | None = Field(
        None, ge=1, le=31, description="Tanggal jatuh tempo SPT Masa"
    )
    corporate_tax_rate: Decimal = Field(DEFAULT_TAX_RATE_PPH_BADAN, ge=0, le=100, decimal_places=2)
    vat_rate: Decimal = Field(DEFAULT_TAX_RATE_PPN, ge=0, le=100, decimal_places=2)
    is_using_final_tax: bool = Field(False, description="Menggunakan PPh Final")
    final_tax_rate: Decimal | None = Field(None, ge=0, le=100, decimal_places=2)
    notes: str | None = Field(None, max_length=500)


class TaxProfileResponseSchema(BaseModel):
    """Response profil pajak."""

    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID
    tax_office: str | None
    tax_office_code: str | None
    tax_classification: str | None
    taxable_date: date | None
    vat_collector_number: str | None
    annual_tax_return_due_date: int | None
    monthly_tax_due_date: int | None
    corporate_tax_rate: Decimal
    vat_rate: Decimal
    is_using_final_tax: bool
    final_tax_rate: Decimal | None
    notes: str | None
    status: TaxStatus
    updated_at: datetime
    updated_by: UUID
    version: int = 1


class BranchCreateSchema(BaseModel):
    """Schema untuk membuat cabang."""

    model_config = ConfigDict(from_attributes=True)

    branch_code: str = Field(..., min_length=2, max_length=20, description="Kode cabang")
    branch_name: str = Field(..., min_length=3, max_length=200, description="Nama cabang")
    address: str | None = Field(None, max_length=500, description="Alamat")
    city: str | None = Field(None, max_length=100, description="Kota")
    postal_code: str | None = Field(None, max_length=20, description="Kode pos")
    phone: str | None = Field(None, max_length=20, description="Telepon")
    email: str | None = Field(None, max_length=200, description="Email")
    manager_name: str | None = Field(None, max_length=200, description="Nama manager")
    is_active: bool = Field(True, description="Aktif")
    notes: str | None = Field(None, max_length=500)

    @field_validator("branch_code")
    @classmethod
    def validate_branch_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Branch code is required")
        return v.upper()


class BranchUpdateSchema(BaseModel):
    """Schema untuk update cabang."""

    model_config = ConfigDict(from_attributes=True)

    branch_name: str | None = Field(None, min_length=3, max_length=200)
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    manager_name: str | None = Field(None, max_length=200)
    is_active: bool | None = None
    status: BranchStatus | None = None
    notes: str | None = Field(None, max_length=500)


class BranchResponseSchema(BaseModel):
    """Response cabang."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legal_entity_id: UUID
    branch_code: str
    branch_name: str
    address: str | None
    city: str | None
    postal_code: str | None
    phone: str | None
    email: str | None
    manager_name: str | None
    status: BranchStatus
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class ConsolidationGroupCreateSchema(BaseModel):
    """Schema untuk membuat grup konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    group_code: str = Field(..., min_length=3, max_length=30, description="Kode grup")
    group_name: str = Field(..., min_length=3, max_length=200, description="Nama grup")
    description: str | None = Field(None, max_length=500, description="Deskripsi")
    base_currency: str = Field(
        DEFAULT_BASE_CURRENCY, min_length=3, max_length=3, description="Mata uang dasar"
    )
    fiscal_year_start: int = Field(DEFAULT_FISCAL_YEAR_START_MONTH, ge=1, le=12)
    fiscal_year_end: int = Field(DEFAULT_FISCAL_YEAR_END_MONTH, ge=1, le=12)
    notes: str | None = Field(None, max_length=500)

    @field_validator("group_code")
    @classmethod
    def validate_group_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Group code is required")
        return v.upper()


class ConsolidationGroupResponseSchema(BaseModel):
    """Response grup konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_code: str
    group_name: str
    description: str | None
    base_currency: str
    fiscal_year_start: int
    fiscal_year_end: int
    member_count: int
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_legal_entity_service() -> Any:
    """Get Legal Entity Service instance."""
    from application.service_layer.service_legal_entity import LegalEntityService
    from infrastructure.dependency_container.ioc_container import get_container

    container = get_container()
    return container.resolve(LegalEntityService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/legal-entities", tags=["Legal Entity"])


# ----------------------------------------------------------------------------
# LEGAL ENTITY CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/",
    response_model=LegalEntityResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create legal entity",
    operation_id="create_legal_entity",
)
async def create_legal_entity(
    request: LegalEntityCreateSchema,
    _permission: None = Depends(require_permission("legal_entity:create")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Create a new legal entity."""
    try:
        result = await service.create_legal_entity(
            legal_name=request.legal_name,
            trade_name=request.trade_name,
            entity_type=request.entity_type.value,
            registration_number=request.registration_number,
            npwp=request.npwp,
            nppp=request.nppp,
            address=request.address,
            city=request.city,
            postal_code=request.postal_code,
            province=request.province,
            country=request.country,
            phone=request.phone,
            fax=request.fax,
            email=request.email,
            website=request.website,
            established_date=request.established_date,
            fiscal_year_start=request.fiscal_year_start,
            fiscal_year_end=request.fiscal_year_end,
            base_currency=request.base_currency,
            functional_currency=request.functional_currency,
            is_taxable=request.is_taxable,
            is_withholding_agent=request.is_withholding_agent,
            parent_company_id=request.parent_company_id,
            consolidation_group_id=request.consolidation_group_id,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        return LegalEntityResponseSchema(
            id=result.id,
            legal_name=result.legal_name,
            trade_name=result.trade_name,
            entity_type=LegalEntityType(result.entity_type),
            registration_number=result.registration_number,
            npwp=result.npwp,
            nppp=result.nppp,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            province=result.province,
            country=result.country,
            phone=result.phone,
            fax=result.fax,
            email=result.email,
            website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency,
            functional_currency=result.functional_currency,
            is_taxable=result.is_taxable,
            is_withholding_agent=result.is_withholding_agent,
            status=LegalEntityStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create legal entity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/",
    response_model=list[LegalEntityResponseSchema],
    summary="List legal entities",
    operation_id="list_legal_entities",
)
async def list_legal_entities(
    entity_type: LegalEntityType | None = Query(None, description="Filter by entity type"),
    status: LegalEntityStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    parent_company_id: UUID | None = Query(None, description="Filter by parent company"),
    search: str | None = Query(None, description="Search in name or registration"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[LegalEntityResponseSchema]:
    """List legal entities with pagination and filters."""
    try:
        result = await service.list_legal_entities(
            entity_type=entity_type.value if entity_type else None,
            status=status.value if status else None,
            is_active=is_active,
            parent_company_id=parent_company_id,
            search=search,
            page=page,
            page_size=page_size,
        )

        return [
            LegalEntityResponseSchema(
                id=le.id,
                legal_name=le.legal_name,
                trade_name=le.trade_name,
                entity_type=LegalEntityType(le.entity_type),
                registration_number=le.registration_number,
                npwp=le.npwp,
                nppp=le.nppp,
                address=le.address,
                city=le.city,
                postal_code=le.postal_code,
                province=le.province,
                country=le.country,
                phone=le.phone,
                fax=le.fax,
                email=le.email,
                website=le.website,
                established_date=le.established_date,
                fiscal_year_start=le.fiscal_year_start,
                fiscal_year_end=le.fiscal_year_end,
                base_currency=le.base_currency,
                functional_currency=le.functional_currency,
                is_taxable=le.is_taxable,
                is_withholding_agent=le.is_withholding_agent,
                status=LegalEntityStatus(le.status),
                is_active=le.is_active,
                is_locked=le.is_locked,
                parent_company_id=le.parent_company_id,
                parent_company_name=le.parent_company_name,
                consolidation_group_id=le.consolidation_group_id,
                consolidation_group_name=le.consolidation_group_name,
                notes=le.notes,
                created_at=le.created_at,
                updated_at=le.updated_at,
                created_by=le.created_by,
                created_by_name=le.created_by_name,
                version=le.version,
            )
            for le in result.items
        ]
    except Exception as e:
        logger.exception(f"Failed to list legal entities: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{legal_entity_id}",
    response_model=LegalEntityResponseSchema,
    summary="Get legal entity by ID",
    operation_id="get_legal_entity",
)
async def get_legal_entity(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Get legal entity by ID."""
    try:
        le = await service.get_legal_entity_by_id(legal_entity_id)

        if not le:
            raise HTTPException(status_code=404, detail="Legal entity not found")

        return LegalEntityResponseSchema(
            id=le.id,
            legal_name=le.legal_name,
            trade_name=le.trade_name,
            entity_type=LegalEntityType(le.entity_type),
            registration_number=le.registration_number,
            npwp=le.npwp,
            nppp=le.nppp,
            address=le.address,
            city=le.city,
            postal_code=le.postal_code,
            province=le.province,
            country=le.country,
            phone=le.phone,
            fax=le.fax,
            email=le.email,
            website=le.website,
            established_date=le.established_date,
            fiscal_year_start=le.fiscal_year_start,
            fiscal_year_end=le.fiscal_year_end,
            base_currency=le.base_currency,
            functional_currency=le.functional_currency,
            is_taxable=le.is_taxable,
            is_withholding_agent=le.is_withholding_agent,
            status=LegalEntityStatus(le.status),
            is_active=le.is_active,
            is_locked=le.is_locked,
            parent_company_id=le.parent_company_id,
            parent_company_name=le.parent_company_name,
            consolidation_group_id=le.consolidation_group_id,
            consolidation_group_name=le.consolidation_group_name,
            notes=le.notes,
            created_at=le.created_at,
            updated_at=le.updated_at,
            created_by=le.created_by,
            created_by_name=le.created_by_name,
            version=le.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get legal entity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-npwp/{npwp}",
    response_model=LegalEntityResponseSchema,
    summary="Get legal entity by NPWP",
    operation_id="get_legal_entity_by_npwp",
)
async def get_legal_entity_by_npwp(
    npwp: str,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Get legal entity by NPWP."""
    try:
        le = await service.get_legal_entity_by_npwp(npwp)

        if not le:
            raise HTTPException(status_code=404, detail=f"Legal entity with NPWP {npwp} not found")

        return LegalEntityResponseSchema(
            id=le.id,
            legal_name=le.legal_name,
            trade_name=le.trade_name,
            entity_type=LegalEntityType(le.entity_type),
            registration_number=le.registration_number,
            npwp=le.npwp,
            nppp=le.nppp,
            address=le.address,
            city=le.city,
            postal_code=le.postal_code,
            province=le.province,
            country=le.country,
            phone=le.phone,
            fax=le.fax,
            email=le.email,
            website=le.website,
            established_date=le.established_date,
            fiscal_year_start=le.fiscal_year_start,
            fiscal_year_end=le.fiscal_year_end,
            base_currency=le.base_currency,
            functional_currency=le.functional_currency,
            is_taxable=le.is_taxable,
            is_withholding_agent=le.is_withholding_agent,
            status=LegalEntityStatus(le.status),
            is_active=le.is_active,
            is_locked=le.is_locked,
            parent_company_id=le.parent_company_id,
            parent_company_name=le.parent_company_name,
            consolidation_group_id=le.consolidation_group_id,
            consolidation_group_name=le.consolidation_group_name,
            notes=le.notes,
            created_at=le.created_at,
            updated_at=le.updated_at,
            created_by=le.created_by,
            created_by_name=le.created_by_name,
            version=le.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get legal entity by NPWP: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-registration/{registration_number}",
    response_model=LegalEntityResponseSchema,
    summary="Get legal entity by registration number",
    operation_id="get_legal_entity_by_registration",
)
async def get_legal_entity_by_registration(
    registration_number: str,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Get legal entity by registration number (NIB)."""
    try:
        le = await service.get_legal_entity_by_registration(registration_number)

        if not le:
            raise HTTPException(
                status_code=404,
                detail=f"Legal entity with registration {registration_number} not found",
            )

        return LegalEntityResponseSchema(
            id=le.id,
            legal_name=le.legal_name,
            trade_name=le.trade_name,
            entity_type=LegalEntityType(le.entity_type),
            registration_number=le.registration_number,
            npwp=le.npwp,
            nppp=le.nppp,
            address=le.address,
            city=le.city,
            postal_code=le.postal_code,
            province=le.province,
            country=le.country,
            phone=le.phone,
            fax=le.fax,
            email=le.email,
            website=le.website,
            established_date=le.established_date,
            fiscal_year_start=le.fiscal_year_start,
            fiscal_year_end=le.fiscal_year_end,
            base_currency=le.base_currency,
            functional_currency=le.functional_currency,
            is_taxable=le.is_taxable,
            is_withholding_agent=le.is_withholding_agent,
            status=LegalEntityStatus(le.status),
            is_active=le.is_active,
            is_locked=le.is_locked,
            parent_company_id=le.parent_company_id,
            parent_company_name=le.parent_company_name,
            consolidation_group_id=le.consolidation_group_id,
            consolidation_group_name=le.consolidation_group_name,
            notes=le.notes,
            created_at=le.created_at,
            updated_at=le.updated_at,
            created_by=le.created_by,
            created_by_name=le.created_by_name,
            version=le.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get legal entity by registration: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{legal_entity_id}",
    response_model=LegalEntityResponseSchema,
    summary="Update legal entity",
    operation_id="update_legal_entity",
)
async def update_legal_entity(
    legal_entity_id: UUID,
    request: LegalEntityUpdateSchema,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Update legal entity information."""
    try:
        result = await service.update_legal_entity(
            legal_entity_id=legal_entity_id,
            legal_name=request.legal_name,
            trade_name=request.trade_name,
            address=request.address,
            city=request.city,
            postal_code=request.postal_code,
            province=request.province,
            phone=request.phone,
            fax=request.fax,
            email=request.email,
            website=request.website,
            status=request.status.value if request.status else None,
            notes=request.notes,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Legal entity not found or cannot be updated"
            )

        return LegalEntityResponseSchema(
            id=result.id,
            legal_name=result.legal_name,
            trade_name=result.trade_name,
            entity_type=LegalEntityType(result.entity_type),
            registration_number=result.registration_number,
            npwp=result.npwp,
            nppp=result.nppp,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            province=result.province,
            country=result.country,
            phone=result.phone,
            fax=result.fax,
            email=result.email,
            website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency,
            functional_currency=result.functional_currency,
            is_taxable=result.is_taxable,
            is_withholding_agent=result.is_withholding_agent,
            status=LegalEntityStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update legal entity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Deactivate legal entity",
    operation_id="deactivate_legal_entity",
)
async def deactivate_legal_entity(
    legal_entity_id: UUID,
    reason: str = Query("", description="Reason for deactivation"),
    _permission: None = Depends(require_permission("legal_entity:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    """Deactivate a legal entity (soft delete)."""
    try:
        result = await service.deactivate_legal_entity(
            legal_entity_id, current_user.user_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")

        return {
            "legal_entity_id": str(legal_entity_id),
            "legal_name": result.legal_name,
            "status": result.status,
            "message": "Legal entity deactivated",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to deactivate legal entity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{legal_entity_id}/activate",
    response_model=LegalEntityResponseSchema,
    summary="Activate legal entity",
    operation_id="activate_legal_entity",
)
async def activate_legal_entity(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Activate a deactivated legal entity."""
    try:
        result = await service.activate_legal_entity(legal_entity_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")

        return LegalEntityResponseSchema(
            id=result.id,
            legal_name=result.legal_name,
            trade_name=result.trade_name,
            entity_type=LegalEntityType(result.entity_type),
            registration_number=result.registration_number,
            npwp=result.npwp,
            nppp=result.nppp,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            province=result.province,
            country=result.country,
            phone=result.phone,
            fax=result.fax,
            email=result.email,
            website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency,
            functional_currency=result.functional_currency,
            is_taxable=result.is_taxable,
            is_withholding_agent=result.is_withholding_agent,
            status=LegalEntityStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to activate legal entity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{legal_entity_id}/lock",
    response_model=LegalEntityResponseSchema,
    summary="Lock legal entity",
    operation_id="lock_legal_entity",
)
async def lock_legal_entity(
    legal_entity_id: UUID,
    reason: str = Query("", description="Lock reason"),
    _permission: None = Depends(require_permission("legal_entity:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Lock a legal entity to prevent modifications."""
    try:
        result = await service.lock_legal_entity(legal_entity_id, current_user.user_id, reason)

        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")

        return LegalEntityResponseSchema(
            id=result.id,
            legal_name=result.legal_name,
            trade_name=result.trade_name,
            entity_type=LegalEntityType(result.entity_type),
            registration_number=result.registration_number,
            npwp=result.npwp,
            nppp=result.nppp,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            province=result.province,
            country=result.country,
            phone=result.phone,
            fax=result.fax,
            email=result.email,
            website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency,
            functional_currency=result.functional_currency,
            is_taxable=result.is_taxable,
            is_withholding_agent=result.is_withholding_agent,
            status=LegalEntityStatus(result.status),
            is_active=result.is_active,
            is_locked=True,
            parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to lock legal entity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{legal_entity_id}/unlock",
    response_model=LegalEntityResponseSchema,
    summary="Unlock legal entity",
    operation_id="unlock_legal_entity",
)
async def unlock_legal_entity(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    """Unlock a locked legal entity."""
    try:
        result = await service.unlock_legal_entity(legal_entity_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")

        return LegalEntityResponseSchema(
            id=result.id,
            legal_name=result.legal_name,
            trade_name=result.trade_name,
            entity_type=LegalEntityType(result.entity_type),
            registration_number=result.registration_number,
            npwp=result.npwp,
            nppp=result.nppp,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            province=result.province,
            country=result.country,
            phone=result.phone,
            fax=result.fax,
            email=result.email,
            website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency,
            functional_currency=result.functional_currency,
            is_taxable=result.is_taxable,
            is_withholding_agent=result.is_withholding_agent,
            status=LegalEntityStatus(result.status),
            is_active=result.is_active,
            is_locked=False,
            parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to unlock legal entity: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TAX PROFILE
# ----------------------------------------------------------------------------


@router.get(
    "/{legal_entity_id}/tax-profile",
    response_model=TaxProfileResponseSchema,
    summary="Get tax profile",
    operation_id="get_tax_profile",
)
async def get_tax_profile(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> TaxProfileResponseSchema:
    """Get tax profile for a legal entity."""
    try:
        profile = await service.get_tax_profile(legal_entity_id)

        if not profile:
            raise HTTPException(status_code=404, detail="Tax profile not found")

        return TaxProfileResponseSchema(
            legal_entity_id=profile.legal_entity_id,
            tax_office=profile.tax_office,
            tax_office_code=profile.tax_office_code,
            tax_classification=profile.tax_classification,
            taxable_date=profile.taxable_date,
            vat_collector_number=profile.vat_collector_number,
            annual_tax_return_due_date=profile.annual_tax_return_due_date,
            monthly_tax_due_date=profile.monthly_tax_due_date,
            corporate_tax_rate=profile.corporate_tax_rate,
            vat_rate=profile.vat_rate,
            is_using_final_tax=profile.is_using_final_tax,
            final_tax_rate=profile.final_tax_rate,
            notes=profile.notes,
            status=TaxStatus(profile.status),
            updated_at=profile.updated_at,
            updated_by=profile.updated_by,
            version=profile.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get tax profile: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{legal_entity_id}/tax-profile",
    response_model=TaxProfileResponseSchema,
    summary="Update tax profile",
    operation_id="update_tax_profile",
)
async def update_tax_profile(
    legal_entity_id: UUID,
    request: TaxProfileSchema,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> TaxProfileResponseSchema:
    """Update tax profile for a legal entity."""
    try:
        result = await service.update_tax_profile(
            legal_entity_id=legal_entity_id,
            tax_office=request.tax_office,
            tax_office_code=request.tax_office_code,
            tax_classification=request.tax_classification,
            taxable_date=request.taxable_date,
            vat_collector_number=request.vat_collector_number,
            annual_tax_return_due_date=request.annual_tax_return_due_date,
            monthly_tax_due_date=request.monthly_tax_due_date,
            corporate_tax_rate=request.corporate_tax_rate,
            vat_rate=request.vat_rate,
            is_using_final_tax=request.is_using_final_tax,
            final_tax_rate=request.final_tax_rate,
            notes=request.notes,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")

        return TaxProfileResponseSchema(
            legal_entity_id=result.legal_entity_id,
            tax_office=result.tax_office,
            tax_office_code=result.tax_office_code,
            tax_classification=result.tax_classification,
            taxable_date=result.taxable_date,
            vat_collector_number=result.vat_collector_number,
            annual_tax_return_due_date=result.annual_tax_return_due_date,
            monthly_tax_due_date=result.monthly_tax_due_date,
            corporate_tax_rate=result.corporate_tax_rate,
            vat_rate=result.vat_rate,
            is_using_final_tax=result.is_using_final_tax,
            final_tax_rate=result.final_tax_rate,
            notes=result.notes,
            status=TaxStatus(result.status),
            updated_at=result.updated_at,
            updated_by=result.updated_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update tax profile: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BRANCH MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/{legal_entity_id}/branches",
    response_model=BranchResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create branch",
    operation_id="create_branch",
)
async def create_branch(
    legal_entity_id: UUID,
    request: BranchCreateSchema,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> BranchResponseSchema:
    """Create a branch for a legal entity."""
    try:
        result = await service.create_branch(
            legal_entity_id=legal_entity_id,
            branch_code=request.branch_code,
            branch_name=request.branch_name,
            address=request.address,
            city=request.city,
            postal_code=request.postal_code,
            phone=request.phone,
            email=request.email,
            manager_name=request.manager_name,
            is_active=request.is_active,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        return BranchResponseSchema(
            id=result.id,
            legal_entity_id=result.legal_entity_id,
            branch_code=result.branch_code,
            branch_name=result.branch_name,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            phone=result.phone,
            email=result.email,
            manager_name=result.manager_name,
            status=BranchStatus(result.status),
            is_active=result.is_active,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{legal_entity_id}/branches",
    response_model=list[BranchResponseSchema],
    summary="List branches",
    operation_id="list_branches",
)
async def list_branches(
    legal_entity_id: UUID,
    status: BranchStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[BranchResponseSchema]:
    """List branches of a legal entity."""
    try:
        branches = await service.list_branches(
            legal_entity_id=legal_entity_id,
            status=status.value if status else None,
            is_active=is_active,
        )

        return [
            BranchResponseSchema(
                id=b.id,
                legal_entity_id=b.legal_entity_id,
                branch_code=b.branch_code,
                branch_name=b.branch_name,
                address=b.address,
                city=b.city,
                postal_code=b.postal_code,
                phone=b.phone,
                email=b.email,
                manager_name=b.manager_name,
                status=BranchStatus(b.status),
                is_active=b.is_active,
                notes=b.notes,
                created_at=b.created_at,
                updated_at=b.updated_at,
                created_by=b.created_by,
                created_by_name=b.created_by_name,
                version=b.version,
            )
            for b in branches
        ]
    except Exception as e:
        logger.exception(f"Failed to list branches: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{legal_entity_id}/branches/{branch_id}",
    response_model=BranchResponseSchema,
    summary="Get branch by ID",
    operation_id="get_branch",
)
async def get_branch(
    legal_entity_id: UUID,
    branch_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> BranchResponseSchema:
    """Get branch by ID."""
    try:
        branch = await service.get_branch_by_id(branch_id, legal_entity_id)

        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")

        return BranchResponseSchema(
            id=branch.id,
            legal_entity_id=branch.legal_entity_id,
            branch_code=branch.branch_code,
            branch_name=branch.branch_name,
            address=branch.address,
            city=branch.city,
            postal_code=branch.postal_code,
            phone=branch.phone,
            email=branch.email,
            manager_name=branch.manager_name,
            status=BranchStatus(branch.status),
            is_active=branch.is_active,
            notes=branch.notes,
            created_at=branch.created_at,
            updated_at=branch.updated_at,
            created_by=branch.created_by,
            created_by_name=branch.created_by_name,
            version=branch.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{legal_entity_id}/branches/{branch_id}",
    response_model=BranchResponseSchema,
    summary="Update branch",
    operation_id="update_branch",
)
async def update_branch(
    legal_entity_id: UUID,
    branch_id: UUID,
    request: BranchUpdateSchema,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> BranchResponseSchema:
    """Update branch information."""
    try:
        result = await service.update_branch(
            branch_id=branch_id,
            legal_entity_id=legal_entity_id,
            branch_name=request.branch_name,
            address=request.address,
            city=request.city,
            phone=request.phone,
            email=request.email,
            manager_name=request.manager_name,
            is_active=request.is_active,
            status=request.status.value if request.status else None,
            notes=request.notes,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Branch not found")

        return BranchResponseSchema(
            id=result.id,
            legal_entity_id=result.legal_entity_id,
            branch_code=result.branch_code,
            branch_name=result.branch_name,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            phone=result.phone,
            email=result.email,
            manager_name=result.manager_name,
            status=BranchStatus(result.status),
            is_active=result.is_active,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{legal_entity_id}/branches/{branch_id}",
    response_model=dict[str, Any],
    summary="Close branch",
    operation_id="close_branch",
)
async def close_branch(
    legal_entity_id: UUID,
    branch_id: UUID,
    reason: str = Query("", description="Reason for closure"),
    _permission: None = Depends(require_permission("legal_entity:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    """Close a branch (soft delete)."""
    try:
        result = await service.close_branch(
            branch_id, legal_entity_id, current_user.user_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Branch not found")

        return {
            "branch_id": str(branch_id),
            "branch_code": result.branch_code,
            "branch_name": result.branch_name,
            "status": result.status,
            "message": "Branch closed",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to close branch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CONSOLIDATION GROUP
# ----------------------------------------------------------------------------


@router.post(
    "/consolidation-groups",
    response_model=ConsolidationGroupResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create consolidation group",
    operation_id="create_consolidation_group",
)
async def create_consolidation_group(
    request: ConsolidationGroupCreateSchema,
    _permission: None = Depends(require_permission("legal_entity:create")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> ConsolidationGroupResponseSchema:
    """Create a consolidation group."""
    try:
        result = await service.create_consolidation_group(
            group_code=request.group_code,
            group_name=request.group_name,
            description=request.description,
            base_currency=request.base_currency,
            fiscal_year_start=request.fiscal_year_start,
            fiscal_year_end=request.fiscal_year_end,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        return ConsolidationGroupResponseSchema(
            id=result.id,
            group_code=result.group_code,
            group_name=result.group_name,
            description=result.description,
            base_currency=result.base_currency,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            member_count=result.member_count,
            is_active=result.is_active,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create consolidation group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/consolidation-groups",
    response_model=list[ConsolidationGroupResponseSchema],
    summary="List consolidation groups",
    operation_id="list_consolidation_groups",
)
async def list_consolidation_groups(
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[ConsolidationGroupResponseSchema]:
    """List all consolidation groups."""
    try:
        groups = await service.list_consolidation_groups(is_active=is_active)

        return [
            ConsolidationGroupResponseSchema(
                id=g.id,
                group_code=g.group_code,
                group_name=g.group_name,
                description=g.description,
                base_currency=g.base_currency,
                fiscal_year_start=g.fiscal_year_start,
                fiscal_year_end=g.fiscal_year_end,
                member_count=g.member_count,
                is_active=g.is_active,
                notes=g.notes,
                created_at=g.created_at,
                updated_at=g.updated_at,
                created_by=g.created_by,
                created_by_name=g.created_by_name,
                version=g.version,
            )
            for g in groups
        ]
    except Exception as e:
        logger.exception(f"Failed to list consolidation groups: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/consolidation-groups/{group_id}",
    response_model=ConsolidationGroupResponseSchema,
    summary="Get consolidation group by ID",
    operation_id="get_consolidation_group",
)
async def get_consolidation_group(
    group_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> ConsolidationGroupResponseSchema:
    """Get consolidation group by ID."""
    try:
        group = await service.get_consolidation_group_by_id(group_id)

        if not group:
            raise HTTPException(status_code=404, detail="Consolidation group not found")

        return ConsolidationGroupResponseSchema(
            id=group.id,
            group_code=group.group_code,
            group_name=group.group_name,
            description=group.description,
            base_currency=group.base_currency,
            fiscal_year_start=group.fiscal_year_start,
            fiscal_year_end=group.fiscal_year_end,
            member_count=group.member_count,
            is_active=group.is_active,
            notes=group.notes,
            created_at=group.created_at,
            updated_at=group.updated_at,
            created_by=group.created_by,
            created_by_name=group.created_by_name,
            version=group.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get consolidation group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/consolidation-groups/{group_id}",
    response_model=ConsolidationGroupResponseSchema,
    summary="Update consolidation group",
    operation_id="update_consolidation_group",
)
async def update_consolidation_group(
    group_id: UUID,
    request: ConsolidationGroupCreateSchema,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> ConsolidationGroupResponseSchema:
    """Update consolidation group information."""
    try:
        result = await service.update_consolidation_group(
            group_id=group_id,
            group_name=request.group_name,
            description=request.description,
            base_currency=request.base_currency,
            fiscal_year_start=request.fiscal_year_start,
            fiscal_year_end=request.fiscal_year_end,
            notes=request.notes,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Consolidation group not found")

        return ConsolidationGroupResponseSchema(
            id=result.id,
            group_code=result.group_code,
            group_name=result.group_name,
            description=result.description,
            base_currency=result.base_currency,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            member_count=result.member_count,
            is_active=result.is_active,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update consolidation group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/consolidation-groups/{group_id}",
    response_model=dict[str, Any],
    summary="Deactivate consolidation group",
    operation_id="deactivate_consolidation_group",
)
async def deactivate_consolidation_group(
    group_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    """Deactivate a consolidation group."""
    try:
        result = await service.deactivate_consolidation_group(group_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Consolidation group not found")

        return {
            "group_id": str(group_id),
            "group_code": result.group_code,
            "is_active": result.is_active,
            "message": "Consolidation group deactivated",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to deactivate consolidation group: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/consolidation-groups/{group_id}/members/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Add member to consolidation group",
    operation_id="add_group_member",
)
async def add_group_member(
    group_id: UUID,
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    """Add a legal entity to a consolidation group."""
    try:
        result = await service.add_member_to_group(group_id, legal_entity_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Group or legal entity not found")

        return {
            "group_id": str(group_id),
            "legal_entity_id": str(legal_entity_id),
            "legal_entity_name": result.legal_entity_name,
            "added": True,
            "message": "Member added to consolidation group",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to add group member: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/consolidation-groups/{group_id}/members/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Remove member from consolidation group",
    operation_id="remove_group_member",
)
async def remove_group_member(
    group_id: UUID,
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    """Remove a legal entity from a consolidation group."""
    try:
        result = await service.remove_member_from_group(
            group_id, legal_entity_id, current_user.user_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Group or legal entity not found")

        return {
            "group_id": str(group_id),
            "legal_entity_id": str(legal_entity_id),
            "legal_entity_name": result.legal_entity_name,
            "removed": True,
            "message": "Member removed from consolidation group",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to remove group member: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HISTORY & STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/{legal_entity_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get legal entity history",
    operation_id="get_legal_entity_history",
)
async def get_legal_entity_history(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[dict[str, Any]]:
    """Get legal entity change history (audit trail)."""
    try:
        history = await service.get_legal_entity_history(legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "field": h.field,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception(f"Failed to get legal entity history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{legal_entity_id}/status",
    response_model=dict[str, Any],
    summary="Get legal entity status",
    operation_id="get_legal_entity_status",
)
async def get_legal_entity_status(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    """Get detailed legal entity status."""
    try:
        status_info = await service.get_legal_entity_status(legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Legal entity not found")

        return {
            "legal_entity_id": str(legal_entity_id),
            "legal_name": status_info.legal_name,
            "status": status_info.status,
            "is_active": status_info.is_active,
            "is_locked": status_info.is_locked,
            "can_edit": status_info.can_edit,
            "can_delete": status_info.can_delete,
            "can_add_branch": status_info.can_add_branch,
            "can_modify_tax": status_info.can_modify_tax,
            "tax_status": status_info.tax_status,
            "registration_valid": status_info.registration_valid,
            "npwp_valid": status_info.npwp_valid,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get legal entity status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
