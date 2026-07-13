#!/usr/bin/env python3
"""
Module: fastapi_consolidation_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk konsolidasi keuangan antar entitas hukum:
               manajemen grup konsolidasi, transaksi intercompany, jurnal eliminasi,
               laporan konsolidasi (neraca, laba rugi, perubahan ekuitas, arus kas),
               dan non-controlling interest (NCI).

Method Standards (ERP):
- create_consolidation_group() / update_group() / delete_group()
- add_member() / remove_member() / update_member_ownership()
- create_intercompany_transaction() / eliminate_intercompany()
- generate_consolidation_report() / generate_balance_sheet() / generate_income_statement()
- calculate_nci() / allocate_nci()
- get_consolidation_status() / get_consolidation_history()
- run_consolidation() / reverse_consolidation()
- lock_consolidation() / unlock_consolidation()
- get_elimination_entries() / post_elimination_entries()
- get_currency_translation() / set_translation_rates()
- audit_trail_consolidation() / can_transition_consolidation()
- register_consolidation_event() / get_consolidation_events()
- version_consolidation()
"""


from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER (for write operations)
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk FastAPI endpoints.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now())


# Global instance
_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class ConsolidationMethod(str, Enum):
    """Metode konsolidasi."""

    FULL = "full"  # Konsolidasi penuh
    EQUITY = "equity"  # Metode ekuitas
    PROPORTIONAL = "proportional"  # Konsolidasi proporsional
    COST = "cost"  # Metode biaya


class IntercompanyType(str, Enum):
    """Jenis transaksi intercompany."""

    SALES = "sales"  # Penjualan barang
    SERVICE = "service"  # Jasa
    LOAN = "loan"  # Pinjaman
    INTEREST = "interest"  # Bunga
    DIVIDEND = "dividend"  # Dividen
    FUND_TRANSFER = "fund_transfer"  # Transfer dana
    ASSET_TRANSFER = "asset_transfer"  # Transfer aset
    EXPENSE_ALLOCATION = "expense_allocation"  # Alokasi biaya
    MANAGEMENT_FEE = "management_fee"  # Fee manajemen
    ROYALTY = "royalty"  # Royalti


class EliminationStatus(str, Enum):
    """Status eliminasi."""

    PENDING = "pending"
    ELIMINATED = "eliminated"
    PARTIALLY_ELIMINATED = "partially_eliminated"
    ADJUSTED = "adjusted"
    CANCELLED = "cancelled"


class ConsolidationStatus(str, Enum):
    """Status konsolidasi."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    APPROVED = "approved"
    REVERSED = "reversed"
    LOCKED = "locked"
    CANCELLED = "cancelled"


class CurrencyTranslationMethod(str, Enum):
    """Metode translasi mata uang."""

    CURRENT_RATE = "current_rate"  # Kurs saat ini (Asset & Liability)
    HISTORICAL_RATE = "historical_rate"  # Kurs historis (Equity)
    AVERAGE_RATE = "average_rate"  # Kurs rata-rata (Income Statement)


# Default consolidation settings
DEFAULT_FUNCTIONAL_CURRENCY = "IDR"
DEFAULT_TRANSLATION_METHOD = CurrencyTranslationMethod.CURRENT_RATE
NCI_ACCOUNT_CODE = "3-3300"  # Non-controlling interest account


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class ConsolidationGroupCreateSchema(BaseModel):
    """Schema untuk membuat grup konsolidasi baru."""

    model_config = ConfigDict(from_attributes=True)

    group_code: str = Field(..., min_length=3, max_length=30, description="Kode grup")
    group_name: str = Field(..., min_length=3, max_length=200, description="Nama grup")
    parent_entity_id: UUID | None = Field(None, description="Entitas induk")
    functional_currency: str = Field(
        DEFAULT_FUNCTIONAL_CURRENCY, min_length=3, max_length=3, description="Mata uang fungsional"
    )
    description: str | None = Field(None, max_length=500, description="Deskripsi")
    fiscal_year_start: int = Field(1, ge=1, le=12, description="Bulan awal tahun fiskal")

    @field_validator("group_code")
    @classmethod
    def validate_group_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Group code is required")
        return v.upper()


class ConsolidationGroupUpdateSchema(BaseModel):
    """Schema untuk update grup konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    group_name: str | None = Field(None, min_length=3, max_length=200)
    parent_entity_id: UUID | None = None
    functional_currency: str | None = Field(None, min_length=3, max_length=3)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class ConsolidationGroupResponseSchema(BaseModel):
    """Response grup konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_code: str
    group_name: str
    parent_entity_id: UUID | None
    parent_entity_name: str | None = None
    functional_currency: str
    description: str | None
    is_active: bool
    member_count: int
    fiscal_year_start: int
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class ConsolidationMemberSchema(BaseModel):
    """Schema untuk anggota grup konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID = Field(..., description="ID entitas hukum")
    ownership_percentage: Decimal = Field(
        ..., ge=0, le=100, decimal_places=2, description="Persentase kepemilikan"
    )
    consolidation_method: ConsolidationMethod = Field(
        ConsolidationMethod.FULL, description="Metode konsolidasi"
    )
    effective_date: date = Field(default_factory=date.today, description="Tanggal efektif")
    notes: str | None = Field(None, max_length=500)


class ConsolidationMemberResponseSchema(BaseModel):
    """Response anggota grup konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_id: UUID
    legal_entity_id: UUID
    legal_entity_name: str | None = None
    legal_entity_code: str | None = None
    ownership_percentage: Decimal
    consolidation_method: ConsolidationMethod
    effective_date: date
    notes: str | None
    is_active: bool
    joined_at: datetime
    created_by: UUID
    version: int = 1


class IntercompanyTransactionCreateSchema(BaseModel):
    """Schema untuk membuat transaksi intercompany."""

    model_config = ConfigDict(from_attributes=True)

    from_legal_entity_id: UUID = Field(..., description="Entitas asal")
    to_legal_entity_id: UUID = Field(..., description="Entitas tujuan")
    transaction_date: date = Field(default_factory=date.today, description="Tanggal transaksi")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Jumlah transaksi")
    currency: str = Field(
        DEFAULT_FUNCTIONAL_CURRENCY, min_length=3, max_length=3, description="Mata uang"
    )
    exchange_rate: Decimal = Field(1, gt=0, decimal_places=6, description="Kurs")
    transaction_type: IntercompanyType = Field(..., description="Jenis transaksi")
    description: str = Field(..., max_length=500, description="Deskripsi")
    reference_number: str | None = Field(None, max_length=50, description="Nomor referensi")
    invoice_number: str | None = Field(None, max_length=50, description="Nomor invoice")
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_entities(self) -> IntercompanyTransactionCreateSchema:
        if self.from_legal_entity_id == self.to_legal_entity_id:
            raise ValueError("From and to legal entities must be different")
        return self


class IntercompanyTransactionResponseSchema(BaseModel):
    """Response transaksi intercompany."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_number: str
    from_legal_entity_id: UUID
    from_legal_entity_name: str | None = None
    to_legal_entity_id: UUID
    to_legal_entity_name: str | None = None
    transaction_date: date
    amount: Decimal
    amount_in_group_currency: Decimal
    currency: str
    exchange_rate: Decimal
    transaction_type: IntercompanyType
    description: str
    reference_number: str | None
    invoice_number: str | None
    elimination_status: EliminationStatus
    elimination_entry_id: UUID | None = None
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class EliminationEntryCreateSchema(BaseModel):
    """Schema untuk membuat jurnal eliminasi."""

    model_config = ConfigDict(from_attributes=True)

    consolidation_group_id: UUID = Field(..., description="ID grup konsolidasi")
    fiscal_year: int = Field(..., ge=2024, le=2100, description="Tahun fiskal")
    period: int = Field(..., ge=1, le=12, description="Periode")
    intercompany_transaction_ids: list[UUID] = Field(
        ..., description="Transaksi IC yang dieliminasi"
    )
    notes: str | None = Field(None, max_length=500)


class EliminationEntryResponseSchema(BaseModel):
    """Response jurnal eliminasi."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    elimination_number: str
    consolidation_group_id: UUID
    group_name: str | None = None
    fiscal_year: int
    period: int
    description: str
    journal_id: UUID | None = None
    status: EliminationStatus
    intercompany_transaction_ids: list[UUID]
    eliminated_amount: Decimal
    nci_adjustment: Decimal
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    posted_at: datetime | None = None
    posted_by: UUID | None = None
    version: int = 1


class ConsolidationRunRequestSchema(BaseModel):
    """Schema untuk menjalankan konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    consolidation_group_id: UUID = Field(..., description="ID grup konsolidasi")
    fiscal_year: int = Field(..., ge=2024, le=2100, description="Tahun fiskal")
    period: int = Field(..., ge=1, le=12, description="Periode")
    include_nci: bool = Field(True, description="Sertakan non-controlling interest")
    translation_method: CurrencyTranslationMethod = Field(
        DEFAULT_TRANSLATION_METHOD, description="Metode translasi"
    )
    reporting_currency: str = Field(
        DEFAULT_FUNCTIONAL_CURRENCY, min_length=3, max_length=3, description="Mata uang pelaporan"
    )
    as_of_date: date = Field(default_factory=date.today, description="Tanggal laporan")
    post_eliminations: bool = Field(True, description="Posting jurnal eliminasi")


class ConsolidationRunResponseSchema(BaseModel):
    """Response konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    consolidation_id: UUID
    consolidation_number: str
    consolidation_group_id: UUID
    group_name: str
    fiscal_year: int
    period: int
    as_of_date: date
    reporting_currency: str
    status: ConsolidationStatus
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    total_revenue: Decimal
    total_expense: Decimal
    net_income: Decimal
    nci_amount: Decimal
    equity_attributable_to_parent: Decimal
    elimination_entries_count: int
    intercompany_transactions_count: int
    journal_ids: list[UUID]
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    completed_at: datetime | None = None


class BalanceSheetConsolidatedSchema(BaseModel):
    """Response neraca konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    consolidation_id: UUID
    group_name: str
    as_of_date: date
    reporting_currency: str
    assets: dict[str, Any]
    liabilities: dict[str, Any]
    equity: dict[str, Any]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    nci: Decimal
    total_liabilities_equity: Decimal
    is_balanced: bool
    generated_at: datetime


class IncomeStatementConsolidatedSchema(BaseModel):
    """Response laba rugi konsolidasi."""

    model_config = ConfigDict(from_attributes=True)

    consolidation_id: UUID
    group_name: str
    period_start: date
    period_end: date
    reporting_currency: str
    revenues: dict[str, Any]
    cost_of_goods_sold: dict[str, Any]
    gross_profit: Decimal
    operating_expenses: dict[str, Any]
    operating_income: Decimal
    other_income: dict[str, Any]
    other_expenses: dict[str, Any]
    income_before_tax: Decimal
    tax_expense: Decimal
    net_income: Decimal
    nci_share: Decimal
    parent_share: Decimal
    generated_at: datetime


class NCICalculationSchema(BaseModel):
    """Schema untuk perhitungan NCI."""

    model_config = ConfigDict(from_attributes=True)

    consolidation_group_id: UUID
    fiscal_year: int
    period: int
    net_income: Decimal
    dividends_declared: Decimal = Decimal(0)
    other_comprehensive_income: Decimal = Decimal(0)


class NCIResponseSchema(BaseModel):
    """Response NCI."""

    model_config = ConfigDict(from_attributes=True)

    legal_entity_id: UUID
    legal_entity_name: str
    ownership_percentage: Decimal
    nci_share_net_income: Decimal
    nci_share_oci: Decimal
    nci_share_dividends: Decimal
    beginning_nci_balance: Decimal
    ending_nci_balance: Decimal
    journal_id: UUID | None = None


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_consolidation_service(request: Request) -> Any:
    """Get Consolidation Service instance."""

    from application.service_layer.service_consolidation import ConsolidationService

    container = request.app.state.container
    return container.resolve(ConsolidationService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/consolidation", tags=["Consolidation"])


# ----------------------------------------------------------------------------
# CONSOLIDATION GROUP CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/groups",
    response_model=ConsolidationGroupResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create consolidation group",
    operation_id="create_consolidation_group",
)
async def create_consolidation_group(
    request: ConsolidationGroupCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("consolidation:create")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> ConsolidationGroupResponseSchema:
    """Create a new consolidation group."""
    method_name = "create_consolidation_group"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ConsolidationGroupResponseSchema(**cached)

    try:
        result = await service.create_group(
            group_code=request.group_code,
            group_name=request.group_name,
            parent_entity_id=request.parent_entity_id,
            functional_currency=request.functional_currency,
            description=request.description,
            fiscal_year_start=request.fiscal_year_start,
            created_by=current_user.user_id,
        )

        response = ConsolidationGroupResponseSchema(
            id=result.id,
            group_code=result.group_code,
            group_name=result.group_name,
            parent_entity_id=result.parent_entity_id,
            parent_entity_name=result.parent_entity_name,
            functional_currency=result.functional_currency,
            description=result.description,
            is_active=result.is_active,
            member_count=result.member_count,
            fiscal_year_start=result.fiscal_year_start,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create consolidation group: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/groups",
    response_model=list[ConsolidationGroupResponseSchema],
    summary="List consolidation groups",
    operation_id="list_consolidation_groups",
)
async def list_consolidation_groups(
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> list[ConsolidationGroupResponseSchema]:
    """List all consolidation groups."""
    try:
        groups = await service.list_groups(is_active=is_active)

        return [
            ConsolidationGroupResponseSchema(
                id=g.id,
                group_code=g.group_code,
                group_name=g.group_name,
                parent_entity_id=g.parent_entity_id,
                parent_entity_name=g.parent_entity_name,
                functional_currency=g.functional_currency,
                description=g.description,
                is_active=g.is_active,
                member_count=g.member_count,
                fiscal_year_start=g.fiscal_year_start,
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
    "/groups/{group_id}",
    response_model=ConsolidationGroupResponseSchema,
    summary="Get consolidation group by ID",
    operation_id="get_consolidation_group",
)
async def get_consolidation_group(
    group_id: UUID,
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> ConsolidationGroupResponseSchema:
    """Get consolidation group by ID."""
    try:
        group = await service.get_group_by_id(group_id)

        if not group:
            raise HTTPException(status_code=404, detail="Consolidation group not found")

        return ConsolidationGroupResponseSchema(
            id=group.id,
            group_code=group.group_code,
            group_name=group.group_name,
            parent_entity_id=group.parent_entity_id,
            parent_entity_name=group.parent_entity_name,
            functional_currency=group.functional_currency,
            description=group.description,
            is_active=group.is_active,
            member_count=group.member_count,
            fiscal_year_start=group.fiscal_year_start,
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
    "/groups/{group_id}",
    response_model=ConsolidationGroupResponseSchema,
    summary="Update consolidation group",
    operation_id="update_consolidation_group",
)
async def update_consolidation_group(
    group_id: UUID,
    request: ConsolidationGroupUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("consolidation:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> ConsolidationGroupResponseSchema:
    """Update consolidation group information."""
    method_name = "update_consolidation_group"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ConsolidationGroupResponseSchema(**cached)

    try:
        result = await service.update_group(
            group_id=group_id,
            group_name=request.group_name,
            parent_entity_id=request.parent_entity_id,
            functional_currency=request.functional_currency,
            description=request.description,
            is_active=request.is_active,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Consolidation group not found")

        response = ConsolidationGroupResponseSchema(
            id=result.id,
            group_code=result.group_code,
            group_name=result.group_name,
            parent_entity_id=result.parent_entity_id,
            parent_entity_name=result.parent_entity_name,
            functional_currency=result.functional_currency,
            description=result.description,
            is_active=result.is_active,
            member_count=result.member_count,
            fiscal_year_start=result.fiscal_year_start,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update consolidation group: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/groups/{group_id}",
    response_model=dict[str, Any],
    summary="Deactivate consolidation group",
    operation_id="deactivate_consolidation_group",
)
async def deactivate_consolidation_group(
    group_id: UUID,
    _permission: None = Depends(require_permission("consolidation:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> dict[str, Any]:
    """Deactivate a consolidation group (soft delete)."""
    try:
        result = await service.deactivate_group(group_id, current_user.user_id)

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


# ----------------------------------------------------------------------------
# GROUP MEMBERS MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/groups/{group_id}/members",
    response_model=ConsolidationMemberResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Add member to consolidation group",
    operation_id="add_group_member",
)
async def add_group_member(
    group_id: UUID,
    request: ConsolidationMemberSchema,
    _permission: None = Depends(require_permission("consolidation:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> ConsolidationMemberResponseSchema:
    """Add a member entity to consolidation group."""
    try:
        result = await service.add_member(
            group_id=group_id,
            legal_entity_id=request.legal_entity_id,
            ownership_percentage=request.ownership_percentage,
            consolidation_method=request.consolidation_method.value,
            effective_date=request.effective_date,
            notes=request.notes,
            added_by=current_user.user_id,
        )

        return ConsolidationMemberResponseSchema(
            id=result.id,
            group_id=group_id,
            legal_entity_id=result.legal_entity_id,
            legal_entity_name=result.legal_entity_name,
            legal_entity_code=result.legal_entity_code,
            ownership_percentage=result.ownership_percentage,
            consolidation_method=ConsolidationMethod(result.consolidation_method),
            effective_date=result.effective_date,
            notes=result.notes,
            is_active=result.is_active,
            joined_at=result.joined_at,
            created_by=result.created_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to add group member: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/groups/{group_id}/members",
    response_model=list[ConsolidationMemberResponseSchema],
    summary="List group members",
    operation_id="list_group_members",
)
async def list_group_members(
    group_id: UUID,
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> list[ConsolidationMemberResponseSchema]:
    """List all members of a consolidation group."""
    try:
        members = await service.get_group_members(group_id)

        return [
            ConsolidationMemberResponseSchema(
                id=m.id,
                group_id=group_id,
                legal_entity_id=m.legal_entity_id,
                legal_entity_name=m.legal_entity_name,
                legal_entity_code=m.legal_entity_code,
                ownership_percentage=m.ownership_percentage,
                consolidation_method=ConsolidationMethod(m.consolidation_method),
                effective_date=m.effective_date,
                notes=m.notes,
                is_active=m.is_active,
                joined_at=m.joined_at,
                created_by=m.created_by,
                version=m.version,
            )
            for m in members
        ]
    except Exception as e:
        logger.exception(f"Failed to list group members: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/groups/{group_id}/members/{member_id}",
    response_model=ConsolidationMemberResponseSchema,
    summary="Update group member",
    operation_id="update_group_member",
)
async def update_group_member(
    group_id: UUID,
    member_id: UUID,
    ownership_percentage: Decimal = Body(..., ge=0, le=100, decimal_places=2),
    consolidation_method: ConsolidationMethod = Body(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("consolidation:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> ConsolidationMemberResponseSchema:
    """Update member ownership percentage or consolidation method."""
    method_name = "update_group_member"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ConsolidationMemberResponseSchema(**cached)

    try:
        result = await service.update_member(
            member_id=member_id,
            group_id=group_id,
            ownership_percentage=ownership_percentage,
            consolidation_method=consolidation_method.value,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Group member not found")

        response = ConsolidationMemberResponseSchema(
            id=result.id,
            group_id=group_id,
            legal_entity_id=result.legal_entity_id,
            legal_entity_name=result.legal_entity_name,
            legal_entity_code=result.legal_entity_code,
            ownership_percentage=result.ownership_percentage,
            consolidation_method=ConsolidationMethod(result.consolidation_method),
            effective_date=result.effective_date,
            notes=result.notes,
            is_active=result.is_active,
            joined_at=result.joined_at,
            created_by=result.created_by,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update group member: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/groups/{group_id}/members/{member_id}",
    response_model=dict[str, Any],
    summary="Remove member from group",
    operation_id="remove_group_member",
)
async def remove_group_member(
    group_id: UUID,
    member_id: UUID,
    _permission: None = Depends(require_permission("consolidation:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> dict[str, Any]:
    """Remove a member from consolidation group."""
    try:
        result = await service.remove_member(member_id, group_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Group member not found")

        return {
            "member_id": str(member_id),
            "legal_entity_id": str(result.legal_entity_id),
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
# INTERCOMPANY TRANSACTIONS
# ----------------------------------------------------------------------------


@router.post(
    "/intercompany",
    response_model=IntercompanyTransactionResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create intercompany transaction",
    operation_id="create_intercompany_transaction",
)
async def create_intercompany_transaction(
    request: IntercompanyTransactionCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("consolidation:ic_transaction")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> IntercompanyTransactionResponseSchema:
    """Record an intercompany transaction."""
    method_name = "create_intercompany_transaction"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return IntercompanyTransactionResponseSchema(**cached)

    try:
        result = await service.create_intercompany_transaction(
            from_legal_entity_id=request.from_legal_entity_id,
            to_legal_entity_id=request.to_legal_entity_id,
            transaction_date=request.transaction_date,
            amount=request.amount,
            currency=request.currency,
            exchange_rate=request.exchange_rate,
            transaction_type=request.transaction_type.value,
            description=request.description,
            reference_number=request.reference_number,
            invoice_number=request.invoice_number,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        response = IntercompanyTransactionResponseSchema(
            id=result.id,
            transaction_number=result.transaction_number,
            from_legal_entity_id=result.from_legal_entity_id,
            from_legal_entity_name=result.from_legal_entity_name,
            to_legal_entity_id=result.to_legal_entity_id,
            to_legal_entity_name=result.to_legal_entity_name,
            transaction_date=result.transaction_date,
            amount=result.amount,
            amount_in_group_currency=result.amount_in_group_currency,
            currency=result.currency,
            exchange_rate=result.exchange_rate,
            transaction_type=IntercompanyType(result.transaction_type),
            description=result.description,
            reference_number=result.reference_number,
            invoice_number=result.invoice_number,
            elimination_status=EliminationStatus(result.elimination_status),
            elimination_entry_id=result.elimination_entry_id,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create intercompany transaction: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/intercompany",
    response_model=list[IntercompanyTransactionResponseSchema],
    summary="List intercompany transactions",
    operation_id="list_intercompany_transactions",
)
async def list_intercompany_transactions(
    from_legal_entity_id: UUID | None = Query(None, description="Filter by from entity"),
    to_legal_entity_id: UUID | None = Query(None, description="Filter by to entity"),
    transaction_type: IntercompanyType | None = Query(None, description="Filter by type"),
    elimination_status: EliminationStatus | None = Query(
        None, description="Filter by elimination status"
    ),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> list[IntercompanyTransactionResponseSchema]:
    """List intercompany transactions with filters."""
    try:
        transactions = await service.list_intercompany_transactions(
            from_legal_entity_id=from_legal_entity_id,
            to_legal_entity_id=to_legal_entity_id,
            transaction_type=transaction_type.value if transaction_type else None,
            elimination_status=elimination_status.value if elimination_status else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            IntercompanyTransactionResponseSchema(
                id=t.id,
                transaction_number=t.transaction_number,
                from_legal_entity_id=t.from_legal_entity_id,
                from_legal_entity_name=t.from_legal_entity_name,
                to_legal_entity_id=t.to_legal_entity_id,
                to_legal_entity_name=t.to_legal_entity_name,
                transaction_date=t.transaction_date,
                amount=t.amount,
                amount_in_group_currency=t.amount_in_group_currency,
                currency=t.currency,
                exchange_rate=t.exchange_rate,
                transaction_type=IntercompanyType(t.transaction_type),
                description=t.description,
                reference_number=t.reference_number,
                invoice_number=t.invoice_number,
                elimination_status=EliminationStatus(t.elimination_status),
                elimination_entry_id=t.elimination_entry_id,
                notes=t.notes,
                created_at=t.created_at,
                created_by=t.created_by,
                created_by_name=t.created_by_name,
                version=t.version,
            )
            for t in transactions
        ]
    except Exception as e:
        logger.exception(f"Failed to list intercompany transactions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/intercompany/{transaction_id}",
    response_model=IntercompanyTransactionResponseSchema,
    summary="Get intercompany transaction by ID",
    operation_id="get_intercompany_transaction",
)
async def get_intercompany_transaction(
    transaction_id: UUID,
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> IntercompanyTransactionResponseSchema:
    """Get intercompany transaction by ID."""
    try:
        transaction = await service.get_intercompany_transaction_by_id(transaction_id)

        if not transaction:
            raise HTTPException(status_code=404, detail="Intercompany transaction not found")

        return IntercompanyTransactionResponseSchema(
            id=transaction.id,
            transaction_number=transaction.transaction_number,
            from_legal_entity_id=transaction.from_legal_entity_id,
            from_legal_entity_name=transaction.from_legal_entity_name,
            to_legal_entity_id=transaction.to_legal_entity_id,
            to_legal_entity_name=transaction.to_legal_entity_name,
            transaction_date=transaction.transaction_date,
            amount=transaction.amount,
            amount_in_group_currency=transaction.amount_in_group_currency,
            currency=transaction.currency,
            exchange_rate=transaction.exchange_rate,
            transaction_type=IntercompanyType(transaction.transaction_type),
            description=transaction.description,
            reference_number=transaction.reference_number,
            invoice_number=transaction.invoice_number,
            elimination_status=EliminationStatus(transaction.elimination_status),
            elimination_entry_id=transaction.elimination_entry_id,
            notes=transaction.notes,
            created_at=transaction.created_at,
            created_by=transaction.created_by,
            created_by_name=transaction.created_by_name,
            version=transaction.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get intercompany transaction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ELIMINATION ENTRIES
# ----------------------------------------------------------------------------


@router.post(
    "/eliminate",
    response_model=EliminationEntryResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Generate elimination entries",
    operation_id="generate_elimination_entries",
)
async def generate_elimination_entries(
    request: EliminationEntryCreateSchema,
    _permission: None = Depends(require_permission("consolidation:eliminate")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> EliminationEntryResponseSchema:
    """Generate elimination entries for intercompany transactions."""
    try:
        result = await service.generate_elimination_entries(
            consolidation_group_id=request.consolidation_group_id,
            fiscal_year=request.fiscal_year,
            period=request.period,
            intercompany_transaction_ids=request.intercompany_transaction_ids,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        return EliminationEntryResponseSchema(
            id=result.id,
            elimination_number=result.elimination_number,
            consolidation_group_id=result.consolidation_group_id,
            group_name=result.group_name,
            fiscal_year=result.fiscal_year,
            period=result.period,
            description=result.description,
            journal_id=result.journal_id,
            status=EliminationStatus(result.status),
            intercompany_transaction_ids=result.intercompany_transaction_ids,
            eliminated_amount=result.eliminated_amount,
            nci_adjustment=result.nci_adjustment,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to generate elimination entries: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/elimination/{elimination_id}/post",
    response_model=EliminationEntryResponseSchema,
    summary="Post elimination entry to GL",
    operation_id="post_elimination_entry",
)
async def post_elimination_entry(
    elimination_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("consolidation:post")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> EliminationEntryResponseSchema:
    """Post elimination entry to general ledger."""
    method_name = "post_elimination_entry"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EliminationEntryResponseSchema(**cached)

    try:
        result = await service.post_elimination_entry(elimination_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Elimination entry not found")

        response = EliminationEntryResponseSchema(
            id=result.id,
            elimination_number=result.elimination_number,
            consolidation_group_id=result.consolidation_group_id,
            group_name=result.group_name,
            fiscal_year=result.fiscal_year,
            period=result.period,
            description=result.description,
            journal_id=result.journal_id,
            status=EliminationStatus(result.status),
            intercompany_transaction_ids=result.intercompany_transaction_ids,
            eliminated_amount=result.eliminated_amount,
            nci_adjustment=result.nci_adjustment,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to post elimination entry: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/elimination",
    response_model=list[EliminationEntryResponseSchema],
    summary="List elimination entries",
    operation_id="list_elimination_entries",
)
async def list_elimination_entries(
    consolidation_group_id: UUID | None = Query(None, description="Filter by group"),
    fiscal_year: int | None = Query(None, description="Filter by fiscal year"),
    period: int | None = Query(None, ge=1, le=12, description="Filter by period"),
    status: EliminationStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> list[EliminationEntryResponseSchema]:
    """List elimination entries with filters."""
    try:
        entries = await service.list_elimination_entries(
            consolidation_group_id=consolidation_group_id,
            fiscal_year=fiscal_year,
            period=period,
            status=status.value if status else None,
        )

        return [
            EliminationEntryResponseSchema(
                id=e.id,
                elimination_number=e.elimination_number,
                consolidation_group_id=e.consolidation_group_id,
                group_name=e.group_name,
                fiscal_year=e.fiscal_year,
                period=e.period,
                description=e.description,
                journal_id=e.journal_id,
                status=EliminationStatus(e.status),
                intercompany_transaction_ids=e.intercompany_transaction_ids,
                eliminated_amount=e.eliminated_amount,
                nci_adjustment=e.nci_adjustment,
                notes=e.notes,
                created_at=e.created_at,
                updated_at=e.updated_at,
                created_by=e.created_by,
                created_by_name=e.created_by_name,
                posted_at=e.posted_at,
                posted_by=e.posted_by,
                version=e.version,
            )
            for e in entries
        ]
    except Exception as e:
        logger.exception(f"Failed to list elimination entries: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# NON-CONTROLLING INTEREST (NCI)
# ----------------------------------------------------------------------------


@router.post(
    "/nci/calculate",
    response_model=list[NCIResponseSchema],
    summary="Calculate non-controlling interest",
    operation_id="calculate_nci",
)
async def calculate_nci(
    request: NCICalculationSchema,
    _permission: None = Depends(require_permission("consolidation:calculate")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> list[NCIResponseSchema]:
    """Calculate non-controlling interest share for the period."""
    try:
        results = await service.calculate_nci(
            consolidation_group_id=request.consolidation_group_id,
            fiscal_year=request.fiscal_year,
            period=request.period,
            net_income=request.net_income,
            dividends_declared=request.dividends_declared,
            other_comprehensive_income=request.other_comprehensive_income,
            calculated_by=current_user.user_id,
        )

        return [
            NCIResponseSchema(
                legal_entity_id=r.legal_entity_id,
                legal_entity_name=r.legal_entity_name,
                ownership_percentage=r.ownership_percentage,
                nci_share_net_income=r.nci_share_net_income,
                nci_share_oci=r.nci_share_oci,
                nci_share_dividends=r.nci_share_dividends,
                beginning_nci_balance=r.beginning_nci_balance,
                ending_nci_balance=r.ending_nci_balance,
                journal_id=r.journal_id,
            )
            for r in results
        ]
    except Exception as e:
        logger.exception(f"Failed to calculate NCI: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CONSOLIDATION REPORTS
# ----------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=ConsolidationRunResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Run consolidation",
    operation_id="run_consolidation",
)
async def run_consolidation(
    request: ConsolidationRunRequestSchema,
    _permission: None = Depends(require_permission("consolidation:run")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> ConsolidationRunResponseSchema:
    """Run full consolidation for the period."""
    try:
        result = await service.run_consolidation(
            consolidation_group_id=request.consolidation_group_id,
            fiscal_year=request.fiscal_year,
            period=request.period,
            include_nci=request.include_nci,
            translation_method=request.translation_method.value,
            reporting_currency=request.reporting_currency,
            as_of_date=request.as_of_date,
            post_eliminations=request.post_eliminations,
            performed_by=current_user.user_id,
        )

        return ConsolidationRunResponseSchema(
            consolidation_id=result.id,
            consolidation_number=result.consolidation_number,
            consolidation_group_id=result.consolidation_group_id,
            group_name=result.group_name,
            fiscal_year=result.fiscal_year,
            period=result.period,
            as_of_date=result.as_of_date,
            reporting_currency=result.reporting_currency,
            status=ConsolidationStatus(result.status),
            total_assets=result.total_assets,
            total_liabilities=result.total_liabilities,
            total_equity=result.total_equity,
            total_revenue=result.total_revenue,
            total_expense=result.total_expense,
            net_income=result.net_income,
            nci_amount=result.nci_amount,
            equity_attributable_to_parent=result.equity_attributable_to_parent,
            elimination_entries_count=result.elimination_entries_count,
            intercompany_transactions_count=result.intercompany_transactions_count,
            journal_ids=result.journal_ids,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            completed_at=result.completed_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to run consolidation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/report/balance-sheet/{consolidation_id}",
    response_model=BalanceSheetConsolidatedSchema,
    summary="Get consolidated balance sheet",
    operation_id="get_consolidated_balance_sheet",
)
async def get_consolidated_balance_sheet(
    consolidation_id: UUID,
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> BalanceSheetConsolidatedSchema:
    """Get consolidated balance sheet from a consolidation run."""
    try:
        report = await service.get_consolidated_balance_sheet(consolidation_id)

        if not report:
            raise HTTPException(status_code=404, detail="Consolidation not found")

        return BalanceSheetConsolidatedSchema(
            consolidation_id=consolidation_id,
            group_name=report.group_name,
            as_of_date=report.as_of_date,
            reporting_currency=report.reporting_currency,
            assets=report.assets,
            liabilities=report.liabilities,
            equity=report.equity,
            total_assets=report.total_assets,
            total_liabilities=report.total_liabilities,
            total_equity=report.total_equity,
            nci=report.nci,
            total_liabilities_equity=report.total_liabilities + report.total_equity,
            is_balanced=report.is_balanced,
            generated_at=datetime.now(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get consolidated balance sheet: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/report/income-statement/{consolidation_id}",
    response_model=IncomeStatementConsolidatedSchema,
    summary="Get consolidated income statement",
    operation_id="get_consolidated_income_statement",
)
async def get_consolidated_income_statement(
    consolidation_id: UUID,
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> IncomeStatementConsolidatedSchema:
    """Get consolidated income statement from a consolidation run."""
    try:
        report = await service.get_consolidated_income_statement(consolidation_id)

        if not report:
            raise HTTPException(status_code=404, detail="Consolidation not found")

        return IncomeStatementConsolidatedSchema(
            consolidation_id=consolidation_id,
            group_name=report.group_name,
            period_start=report.period_start,
            period_end=report.period_end,
            reporting_currency=report.reporting_currency,
            revenues=report.revenues,
            cost_of_goods_sold=report.cost_of_goods_sold,
            gross_profit=report.gross_profit,
            operating_expenses=report.operating_expenses,
            operating_income=report.operating_income,
            other_income=report.other_income,
            other_expenses=report.other_expenses,
            income_before_tax=report.income_before_tax,
            tax_expense=report.tax_expense,
            net_income=report.net_income,
            nci_share=report.nci_share,
            parent_share=report.parent_share,
            generated_at=datetime.now(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get consolidated income statement: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/report/{consolidation_id}",
    response_model=dict[str, Any],
    summary="Get complete consolidation report",
    operation_id="get_consolidation_report",
)
async def get_consolidation_report(
    consolidation_id: UUID,
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> dict[str, Any]:
    """Get complete consolidation report with all financial statements."""
    try:
        report = await service.get_complete_consolidation_report(consolidation_id)

        if not report:
            raise HTTPException(status_code=404, detail="Consolidation not found")

        return {
            "consolidation_id": str(consolidation_id),
            "group_name": report.group_name,
            "fiscal_year": report.fiscal_year,
            "period": report.period,
            "as_of_date": report.as_of_date.isoformat(),
            "reporting_currency": report.reporting_currency,
            "balance_sheet": {
                "total_assets": float(report.balance_sheet.total_assets),
                "total_liabilities": float(report.balance_sheet.total_liabilities),
                "total_equity": float(report.balance_sheet.total_equity),
                "nci": float(report.balance_sheet.nci),
                "details": report.balance_sheet.details,
            },
            "income_statement": {
                "total_revenue": float(report.income_statement.total_revenue),
                "total_expense": float(report.income_statement.total_expense),
                "net_income": float(report.income_statement.net_income),
                "nci_share": float(report.income_statement.nci_share),
                "parent_share": float(report.income_statement.parent_share),
                "details": report.income_statement.details,
            },
            "elimination_entries": report.elimination_entries,
            "intercompany_transactions": report.intercompany_transactions,
            "nci_calculation": report.nci_calculation,
            "generated_at": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get consolidation report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CONSOLIDATION HISTORY & STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/history",
    response_model=list[ConsolidationRunResponseSchema],
    summary="Get consolidation history",
    operation_id="get_consolidation_history",
)
async def get_consolidation_history(
    consolidation_group_id: UUID | None = Query(None, description="Filter by group"),
    fiscal_year: int | None = Query(None, description="Filter by fiscal year"),
    status: ConsolidationStatus | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> list[ConsolidationRunResponseSchema]:
    """Get consolidation run history."""
    try:
        runs = await service.list_consolidation_runs(
            consolidation_group_id=consolidation_group_id,
            fiscal_year=fiscal_year,
            status=status.value if status else None,
            page=page,
            page_size=page_size,
        )

        return [
            ConsolidationRunResponseSchema(
                consolidation_id=r.id,
                consolidation_number=r.consolidation_number,
                consolidation_group_id=r.consolidation_group_id,
                group_name=r.group_name,
                fiscal_year=r.fiscal_year,
                period=r.period,
                as_of_date=r.as_of_date,
                reporting_currency=r.reporting_currency,
                status=ConsolidationStatus(r.status),
                total_assets=r.total_assets,
                total_liabilities=r.total_liabilities,
                total_equity=r.total_equity,
                total_revenue=r.total_revenue,
                total_expense=r.total_expense,
                net_income=r.net_income,
                nci_amount=r.nci_amount,
                equity_attributable_to_parent=r.equity_attributable_to_parent,
                elimination_entries_count=r.elimination_entries_count,
                intercompany_transactions_count=r.intercompany_transactions_count,
                journal_ids=r.journal_ids,
                created_at=r.created_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                completed_at=r.completed_at,
            )
            for r in runs
        ]
    except Exception as e:
        logger.exception(f"Failed to get consolidation history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/consolidation/{consolidation_id}/status",
    response_model=dict[str, Any],
    summary="Get consolidation status",
    operation_id="get_consolidation_status",
)
async def get_consolidation_status(
    consolidation_id: UUID,
    _permission: None = Depends(require_permission("consolidation:read")),
    service: Any = Depends(get_consolidation_service),
) -> dict[str, Any]:
    """Get detailed consolidation run status."""
    try:
        status_info = await service.get_consolidation_status(consolidation_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Consolidation not found")

        return {
            "consolidation_id": str(consolidation_id),
            "consolidation_number": status_info.consolidation_number,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_reverse": status_info.can_reverse,
            "can_post": status_info.can_post,
            "is_locked": status_info.is_locked,
            "progress_percent": status_info.progress_percent,
            "current_step": status_info.current_step,
            "total_steps": status_info.total_steps,
            "errors": status_info.errors,
            "warnings": status_info.warnings,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get consolidation status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/consolidation/{consolidation_id}/reverse",
    response_model=dict[str, Any],
    summary="Reverse consolidation",
    operation_id="reverse_consolidation",
)
async def reverse_consolidation(
    consolidation_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    _permission: None = Depends(require_permission("consolidation:run")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_consolidation_service),
) -> dict[str, Any]:
    """Reverse a consolidation run."""
    try:
        result = await service.reverse_consolidation(
            consolidation_id=consolidation_id,
            reason=reason,
            reversed_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Consolidation not found or cannot be reversed"
            )

        return {
            "consolidation_id": str(consolidation_id),
            "consolidation_number": result.consolidation_number,
            "status": result.status,
            "reversed": True,
            "message": f"Consolidation reversed: {reason}",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reverse consolidation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export/consolidation/{consolidation_id}",
    summary="Export consolidation report",
    operation_id="export_consolidation_report",
)
async def export_consolidation_report(
    consolidation_id: UUID,
    format: str = Query("excel", pattern="^(excel|pdf|csv)$", description="Export format"),
    _permission: None = Depends(require_permission("consolidation:export")),
    service: Any = Depends(get_consolidation_service),
) -> Response:
    """Export consolidation report to Excel, PDF, or CSV."""
    try:
        data, filename = await service.export_consolidation_report(
            consolidation_id=consolidation_id,
            format=format,
        )

        media_type = {
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
            "csv": "text/csv",
        }.get(format, "application/octet-stream")

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export consolidation report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
