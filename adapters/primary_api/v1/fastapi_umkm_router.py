
#!/usr/bin/env python3
"""
Module: fastapi_umkm_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk UMKM (Usaha Mikro Kecil Menengah)
               dengan sistem akuntansi sederhana: jurnal sederhana (double entry),
               laporan keuangan sederhana, dan bantuan kepatuhan pajak.

Method Standards (ERP):
- create_journal_entry() / update_journal_entry() / delete_journal_entry()
- post_journal_entry() / reverse_journal_entry()
- get_income_statement() / get_balance_sheet() / get_cash_flow()
- get_tax_compliance() / calculate_estimated_tax()
- get_business_profile() / update_business_profile()
- get_transaction_summary() / get_category_summary()
- get_journal_status() / get_journal_history()
- audit_trail_journal() / can_transition_journal()
- register_journal_event() / get_journal_events()
- version_journal()
"""


from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class UMKMJournalStatus(str, Enum):
    """Status jurnal UMKM."""

    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"
    REVERSED = "reversed"


class TransactionCategory(str, Enum):
    """Kategori transaksi untuk UMKM."""

    REVENUE = "revenue"  # Pendapatan
    COST_OF_GOODS_SOLD = "cogs"  # HPP
    OPERATING_EXPENSE = "operating_expense"  # Beban operasional
    OTHER_INCOME = "other_income"  # Pendapatan lain
    OTHER_EXPENSE = "other_expense"  # Beban lain
    ASSET = "asset"  # Aset
    LIABILITY = "liability"  # Kewajiban
    EQUITY = "equity"  # Ekuitas


# Akun sederhana untuk UMKM (menggunakan kode akun yang lebih sederhana)
SIMPLIFIED_ACCOUNTS = {
    # Aset (1-1000 - 1-1999)
    "1-1100": {"name": "Kas", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1200": {"name": "Bank", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1300": {"name": "Piutang Usaha", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1400": {"name": "Persediaan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1500": {"name": "Perlengkapan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1600": {"name": "Peralatan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1700": {"name": "Kendaraan", "type": "ASSET", "normal_balance": "DEBIT"},
    "1-1800": {"name": "Akumulasi Penyusutan", "type": "ASSET", "normal_balance": "CREDIT"},
    # Kewajiban (2-1000 - 2-1999)
    "2-2100": {"name": "Utang Usaha", "type": "LIABILITY", "normal_balance": "CREDIT"},
    "2-2200": {"name": "Utang Pajak", "type": "LIABILITY", "normal_balance": "CREDIT"},
    "2-2300": {"name": "Utang Bank", "type": "LIABILITY", "normal_balance": "CREDIT"},
    # Ekuitas (3-1000 - 3-1999)
    "3-3100": {"name": "Modal", "type": "EQUITY", "normal_balance": "CREDIT"},
    "3-3200": {"name": "Prive", "type": "EQUITY", "normal_balance": "DEBIT"},
    "3-3300": {"name": "Laba Ditahan", "type": "EQUITY", "normal_balance": "CREDIT"},
    # Pendapatan (4-1000 - 4-1999)
    "4-4100": {"name": "Pendapatan Usaha", "type": "REVENUE", "normal_balance": "CREDIT"},
    "4-4200": {"name": "Pendapatan Jasa", "type": "REVENUE", "normal_balance": "CREDIT"},
    "4-4300": {"name": "Pendapatan Lain-lain", "type": "REVENUE", "normal_balance": "CREDIT"},
    # Beban (5-1000 - 5-1999)
    "5-5100": {"name": "Beban Pokok Penjualan", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5200": {"name": "Beban Gaji", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5300": {"name": "Beban Sewa", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5400": {"name": "Beban Listrik & Air", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5500": {"name": "Beban Telepon & Internet", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5600": {"name": "Beban Transportasi", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5700": {"name": "Beban Pemasaran", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5800": {"name": "Beban Administrasi", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-5900": {"name": "Beban Penyusutan", "type": "EXPENSE", "normal_balance": "DEBIT"},
    "5-6000": {"name": "Beban Lain-lain", "type": "EXPENSE", "normal_balance": "DEBIT"},
}

# Tarif PPh Final UMKM (0.5% dari omzet)
UMKM_FINAL_TAX_RATE = Decimal("0.5")  # 0.5%
UMKM_MAX_REVENUE_YEARLY = Decimal("4_800_000_000")  # 4.8 Miliar


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class SimplifiedJournalEntrySchema(BaseModel):
    """Schema untuk jurnal sederhana UMKM."""

    model_config = ConfigDict(from_attributes=True)

    journal_date: date = Field(default_factory=date.today, description="Tanggal jurnal")
    description: str = Field(..., min_length=3, max_length=500, description="Deskripsi")
    debit_account_code: str = Field(..., min_length=3, max_length=20, description="Kode akun debit")
    credit_account_code: str = Field(
        ..., min_length=3, max_length=20, description="Kode akun kredit"
    )
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Jumlah")
    category: TransactionCategory | None = Field(None, description="Kategori transaksi")
    tax_id: UUID | None = None
    attachment_url: str | None = Field(None, max_length=500, description="URL lampiran")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("debit_account_code", "credit_account_code")
    @classmethod
    def validate_account_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Account code is required")
        if v not in SIMPLIFIED_ACCOUNTS:
            valid_codes = list(SIMPLIFIED_ACCOUNTS.keys())
            raise ValueError(f"Invalid account code: {v}. Valid codes: {valid_codes}")
        return v.upper()

    @model_validator(mode="after")
    def validate_different_accounts(self) -> SimplifiedJournalEntrySchema:
        if self.debit_account_code == self.credit_account_code:
            raise ValueError("Debit and credit accounts must be different")
        return self


class SimplifiedJournalResponseSchema(BaseModel):
    """Response jurnal UMKM."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    journal_number: str
    journal_date: date
    description: str
    debit_account_code: str
    debit_account_name: str
    credit_account_code: str
    credit_account_name: str
    amount: Decimal
    category: TransactionCategory | None
    status: UMKMJournalStatus
    tax_id: UUID | None
    attachment_url: str | None
    notes: str | None
    posted_at: datetime | None = None
    posted_by: UUID | None = None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class IncomeStatementSimpleSchema(BaseModel):
    """Response laba rugi sederhana."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    period_name: str
    total_revenue: Decimal
    total_cogs: Decimal
    gross_profit: Decimal
    total_expenses: Decimal
    operating_profit: Decimal
    other_income: Decimal
    other_expenses: Decimal
    net_income: Decimal
    revenue_details: list[dict[str, Any]]
    expense_details: list[dict[str, Any]]
    generated_at: datetime


class BalanceSheetSimpleSchema(BaseModel):
    """Response neraca sederhana."""

    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    assets_details: list[dict[str, Any]]
    liabilities_details: list[dict[str, Any]]
    equity_details: list[dict[str, Any]]
    is_balanced: bool
    generated_at: datetime


class CashFlowSimpleSchema(BaseModel):
    """Response arus kas sederhana."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    beginning_cash: Decimal
    cash_in_from_operations: Decimal
    cash_out_from_operations: Decimal
    net_cash_operations: Decimal
    cash_in_from_investing: Decimal
    cash_out_from_investing: Decimal
    net_cash_investing: Decimal
    cash_in_from_financing: Decimal
    cash_out_from_financing: Decimal
    net_cash_financing: Decimal
    net_cash_flow: Decimal
    ending_cash: Decimal
    generated_at: datetime


class TaxComplianceHelperResponseSchema(BaseModel):
    """Response bantuan kepatuhan pajak UMKM."""

    model_config = ConfigDict(from_attributes=True)

    period_year: int
    period_month: int
    total_revenue_period: Decimal
    total_revenue_ytd: Decimal
    estimated_pph_final: Decimal
    tax_due_reminder: str
    submission_deadline: date
    is_required_to_file: bool
    notes: str | None
    calculated_at: datetime


class BusinessProfileSchema(BaseModel):
    """Schema profil bisnis UMKM."""

    model_config = ConfigDict(from_attributes=True)

    business_name: str = Field(..., max_length=200)
    business_type: str = Field(..., max_length=100, description="Jenis usaha")
    npwp: str | None = Field(None, min_length=15, max_length=15)
    business_address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    established_date: date | None = None
    industry: str | None = Field(None, max_length=100)
    uses_final_tax: bool = Field(True, description="Menggunakan PPh Final 0.5%")
    accounting_method: str = Field("cash", description="cash atau accrual")
    fiscal_year_start: int = Field(1, ge=1, le=12)
    tax_submission_reminder_days: int = Field(7, ge=1, le=30)


class BusinessProfileResponseSchema(BaseModel):
    """Response profil bisnis UMKM."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legal_entity_id: UUID
    business_name: str
    business_type: str
    npwp: str | None
    business_address: str | None
    phone: str | None
    email: str | None
    website: str | None
    established_date: date | None
    industry: str | None
    uses_final_tax: bool
    accounting_method: str
    fiscal_year_start: int
    tax_submission_reminder_days: int
    created_at: datetime
    updated_at: datetime
    version: int = 1


class TransactionSummarySchema(BaseModel):
    """Response ringkasan transaksi per kategori."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    by_category: dict[str, Decimal]
    by_account: dict[str, Decimal]
    by_month: dict[str, Decimal]
    total_transactions: int
    total_amount: Decimal
    generated_at: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_umkm_service(request: Request, ) -> Any:
    """Get UMKM Simplified Service instance."""

    from application.service_layer.service_umkm import UMKMSimplifiedService

    container = request.app.state.container
    return container.resolve(UMKMSimplifiedService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/umkm", tags=["UMKM Simplified"])


# ----------------------------------------------------------------------------
# SIMPLIFIED JOURNAL (UMKM)
# ----------------------------------------------------------------------------


@router.post(
    "/journals",
    response_model=SimplifiedJournalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create simplified journal entry",
    operation_id="create_umkm_journal",
)
async def create_journal_entry(
    request: SimplifiedJournalEntrySchema,
    _permission: None = Depends(require_permission("umkm:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> SimplifiedJournalResponseSchema:
    """Create a simplified journal entry for UMKM (one debit, one credit)."""
    try:
        result = await service.create_journal_entry(
            legal_entity_id=legal_entity_id,
            journal_date=request.journal_date,
            description=request.description,
            debit_account_code=request.debit_account_code,
            credit_account_code=request.credit_account_code,
            amount=request.amount,
            category=request.category.value if request.category else None,
            tax_id=request.tax_id,
            attachment_url=request.attachment_url,
            notes=request.notes,
            created_by=current_user.user_id,
        )

        debit_account = SIMPLIFIED_ACCOUNTS.get(request.debit_account_code, {})
        credit_account = SIMPLIFIED_ACCOUNTS.get(request.credit_account_code, {})

        return SimplifiedJournalResponseSchema(
            id=result.id,
            journal_number=result.journal_number,
            journal_date=result.journal_date,
            description=result.description,
            debit_account_code=result.debit_account_code,
            debit_account_name=debit_account.get("name", result.debit_account_code),
            credit_account_code=result.credit_account_code,
            credit_account_name=credit_account.get("name", result.credit_account_code),
            amount=result.amount,
            category=TransactionCategory(result.category) if result.category else None,
            status=UMKMJournalStatus(result.status),
            tax_id=result.tax_id,
            attachment_url=result.attachment_url,
            notes=result.notes,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create journal entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/journals",
    response_model=list[SimplifiedJournalResponseSchema],
    summary="List simplified journal entries",
    operation_id="list_umkm_journals",
)
async def list_journal_entries(
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    status: UMKMJournalStatus | None = Query(None, description="Filter by status"),
    category: TransactionCategory | None = Query(None, description="Filter by category"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> list[SimplifiedJournalResponseSchema]:
    """List simplified journal entries with pagination and filters."""
    try:
        result = await service.list_journal_entries(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            status=status.value if status else None,
            category=category.value if category else None,
            page=page,
            page_size=page_size,
        )

        return [
            SimplifiedJournalResponseSchema(
                id=j.id,
                journal_number=j.journal_number,
                journal_date=j.journal_date,
                description=j.description,
                debit_account_code=j.debit_account_code,
                debit_account_name=SIMPLIFIED_ACCOUNTS.get(j.debit_account_code, {}).get(
                    "name", j.debit_account_code
                ),
                credit_account_code=j.credit_account_code,
                credit_account_name=SIMPLIFIED_ACCOUNTS.get(j.credit_account_code, {}).get(
                    "name", j.credit_account_code
                ),
                amount=j.amount,
                category=TransactionCategory(j.category) if j.category else None,
                status=UMKMJournalStatus(j.status),
                tax_id=j.tax_id,
                attachment_url=j.attachment_url,
                notes=j.notes,
                posted_at=j.posted_at,
                posted_by=j.posted_by,
                created_at=j.created_at,
                created_by=j.created_by,
                created_by_name=j.created_by_name,
                version=j.version,
            )
            for j in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list journal entries: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/journals/{journal_id}",
    response_model=SimplifiedJournalResponseSchema,
    summary="Get journal entry by ID",
    operation_id="get_umkm_journal",
)
async def get_journal_entry(
    journal_id: UUID,
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> SimplifiedJournalResponseSchema:
    """Get journal entry by ID."""
    try:
        journal = await service.get_journal_entry(journal_id, legal_entity_id)

        if not journal:
            raise HTTPException(status_code=404, detail="Journal entry not found")

        return SimplifiedJournalResponseSchema(
            id=journal.id,
            journal_number=journal.journal_number,
            journal_date=journal.journal_date,
            description=journal.description,
            debit_account_code=journal.debit_account_code,
            debit_account_name=SIMPLIFIED_ACCOUNTS.get(journal.debit_account_code, {}).get(
                "name", journal.debit_account_code
            ),
            credit_account_code=journal.credit_account_code,
            credit_account_name=SIMPLIFIED_ACCOUNTS.get(journal.credit_account_code, {}).get(
                "name", journal.credit_account_code
            ),
            amount=journal.amount,
            category=TransactionCategory(journal.category) if journal.category else None,
            status=UMKMJournalStatus(journal.status),
            tax_id=journal.tax_id,
            attachment_url=journal.attachment_url,
            notes=journal.notes,
            posted_at=journal.posted_at,
            posted_by=journal.posted_by,
            created_at=journal.created_at,
            created_by=journal.created_by,
            created_by_name=journal.created_by_name,
            version=journal.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get journal entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/journals/{journal_id}",
    response_model=SimplifiedJournalResponseSchema,
    summary="Update journal entry",
    operation_id="update_umkm_journal",
)
async def update_journal_entry(
    journal_id: UUID,
    request: SimplifiedJournalEntrySchema,
    _permission: None = Depends(require_permission("umkm:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> SimplifiedJournalResponseSchema:
    """Update a draft journal entry."""
    try:
        result = await service.update_journal_entry(
            journal_id=journal_id,
            journal_date=request.journal_date,
            description=request.description,
            debit_account_code=request.debit_account_code,
            credit_account_code=request.credit_account_code,
            amount=request.amount,
            category=request.category.value if request.category else None,
            tax_id=request.tax_id,
            attachment_url=request.attachment_url,
            notes=request.notes,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Journal entry not found or cannot be updated"
            )

        debit_account = SIMPLIFIED_ACCOUNTS.get(request.debit_account_code, {})
        credit_account = SIMPLIFIED_ACCOUNTS.get(request.credit_account_code, {})

        return SimplifiedJournalResponseSchema(
            id=result.id,
            journal_number=result.journal_number,
            journal_date=result.journal_date,
            description=result.description,
            debit_account_code=result.debit_account_code,
            debit_account_name=debit_account.get("name", result.debit_account_code),
            credit_account_code=result.credit_account_code,
            credit_account_name=credit_account.get("name", result.credit_account_code),
            amount=result.amount,
            category=TransactionCategory(result.category) if result.category else None,
            status=UMKMJournalStatus(result.status),
            tax_id=result.tax_id,
            attachment_url=result.attachment_url,
            notes=result.notes,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update journal entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/journals/{journal_id}",
    response_model=dict[str, Any],
    summary="Cancel journal entry",
    operation_id="cancel_umkm_journal",
)
async def cancel_journal_entry(
    journal_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("umkm:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> dict[str, Any]:
    """Cancel a draft journal entry."""
    try:
        result = await service.cancel_journal_entry(
            journal_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Journal entry not found or cannot be cancelled"
            )

        return {
            "journal_id": str(journal_id),
            "journal_number": result.journal_number,
            "status": result.status,
            "message": "Journal entry cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel journal entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/journals/{journal_id}/post",
    response_model=SimplifiedJournalResponseSchema,
    summary="Post journal entry to ledger",
    operation_id="post_umkm_journal",
)
async def post_journal_entry(
    journal_id: UUID,
    _permission: None = Depends(require_permission("umkm:post")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> SimplifiedJournalResponseSchema:
    """Post a journal entry to the general ledger."""
    try:
        result = await service.post_journal_entry(journal_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(
                status_code=404, detail="Journal entry not found or cannot be posted"
            )

        return SimplifiedJournalResponseSchema(
            id=result.id,
            journal_number=result.journal_number,
            journal_date=result.journal_date,
            description=result.description,
            debit_account_code=result.debit_account_code,
            debit_account_name=SIMPLIFIED_ACCOUNTS.get(result.debit_account_code, {}).get(
                "name", result.debit_account_code
            ),
            credit_account_code=result.credit_account_code,
            credit_account_name=SIMPLIFIED_ACCOUNTS.get(result.credit_account_code, {}).get(
                "name", result.credit_account_code
            ),
            amount=result.amount,
            category=TransactionCategory(result.category) if result.category else None,
            status=UMKMJournalStatus(result.status),
            tax_id=result.tax_id,
            attachment_url=result.attachment_url,
            notes=result.notes,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to post journal entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/journals/{journal_id}/reverse",
    response_model=SimplifiedJournalResponseSchema,
    summary="Reverse a posted journal entry",
    operation_id="reverse_umkm_journal",
)
async def reverse_journal_entry(
    journal_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    _permission: None = Depends(require_permission("umkm:post")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> SimplifiedJournalResponseSchema:
    """Reverse a posted journal entry (creates reversing entry)."""
    try:
        result = await service.reverse_journal_entry(
            journal_id=journal_id,
            reason=reason,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Journal entry not found or cannot be reversed"
            )

        return SimplifiedJournalResponseSchema(
            id=result.id,
            journal_number=result.journal_number,
            journal_date=result.journal_date,
            description=result.description,
            debit_account_code=result.debit_account_code,
            debit_account_name=SIMPLIFIED_ACCOUNTS.get(result.debit_account_code, {}).get(
                "name", result.debit_account_code
            ),
            credit_account_code=result.credit_account_code,
            credit_account_name=SIMPLIFIED_ACCOUNTS.get(result.credit_account_code, {}).get(
                "name", result.credit_account_code
            ),
            amount=result.amount,
            category=TransactionCategory(result.category) if result.category else None,
            status=UMKMJournalStatus(result.status),
            tax_id=result.tax_id,
            attachment_url=result.attachment_url,
            notes=result.notes,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reverse journal entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SIMPLE FINANCIAL REPORTS
# ----------------------------------------------------------------------------


@router.get(
    "/reports/income-statement",
    response_model=IncomeStatementSimpleSchema,
    summary="Get simple income statement (P&L)",
    operation_id="get_umkm_income_statement",
)
async def get_income_statement(
    period_start: date = Query(..., description="Start date"),
    period_end: date = Query(..., description="End date"),
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> IncomeStatementSimpleSchema:
    """Get simple income statement (laporan laba rugi) for a period."""
    try:
        report = await service.get_income_statement(
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
        )

        return IncomeStatementSimpleSchema(
            period_start=period_start,
            period_end=period_end,
            period_name=report.period_name,
            total_revenue=report.total_revenue,
            total_cogs=report.total_cogs,
            gross_profit=report.gross_profit,
            total_expenses=report.total_expenses,
            operating_profit=report.operating_profit,
            other_income=report.other_income,
            other_expenses=report.other_expenses,
            net_income=report.net_income,
            revenue_details=report.revenue_details,
            expense_details=report.expense_details,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get income statement: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/reports/balance-sheet",
    response_model=BalanceSheetSimpleSchema,
    summary="Get simple balance sheet",
    operation_id="get_umkm_balance_sheet",
)
async def get_balance_sheet(
    as_of_date: date = Query(..., description="Balance sheet date"),
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> BalanceSheetSimpleSchema:
    """Get simple balance sheet (neraca) as of a date."""
    try:
        report = await service.get_balance_sheet(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
        )

        return BalanceSheetSimpleSchema(
            as_of_date=as_of_date,
            total_assets=report.total_assets,
            total_liabilities=report.total_liabilities,
            total_equity=report.total_equity,
            assets_details=report.assets_details,
            liabilities_details=report.liabilities_details,
            equity_details=report.equity_details,
            is_balanced=report.is_balanced,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get balance sheet: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/reports/cash-flow",
    response_model=CashFlowSimpleSchema,
    summary="Get simple cash flow statement",
    operation_id="get_umkm_cash_flow",
)
async def get_cash_flow(
    period_start: date = Query(..., description="Start date"),
    period_end: date = Query(..., description="End date"),
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> CashFlowSimpleSchema:
    """Get simple cash flow statement (laporan arus kas) for a period."""
    try:
        report = await service.get_cash_flow(
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
        )

        return CashFlowSimpleSchema(
            period_start=period_start,
            period_end=period_end,
            beginning_cash=report.beginning_cash,
            cash_in_from_operations=report.cash_in_from_operations,
            cash_out_from_operations=report.cash_out_from_operations,
            net_cash_operations=report.net_cash_operations,
            cash_in_from_investing=report.cash_in_from_investing,
            cash_out_from_investing=report.cash_out_from_investing,
            net_cash_investing=report.net_cash_investing,
            cash_in_from_financing=report.cash_in_from_financing,
            cash_out_from_financing=report.cash_out_from_financing,
            net_cash_financing=report.net_cash_financing,
            net_cash_flow=report.net_cash_flow,
            ending_cash=report.ending_cash,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get cash flow: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TAX COMPLIANCE HELPER (PPh Final UMKM 0.5%)
# ----------------------------------------------------------------------------


@router.get(
    "/tax-compliance",
    response_model=TaxComplianceHelperResponseSchema,
    summary="Get tax compliance assistance",
    operation_id="get_umkm_tax_compliance",
)
async def get_tax_compliance(
    period_year: int = Query(..., ge=2024, le=2100, description="Tax year"),
    period_month: int = Query(..., ge=1, le=12, description="Tax month"),
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> TaxComplianceHelperResponseSchema:
    """Get tax compliance assistance for UMKM (PPh Final 0.5%)."""
    try:
        helper = await service.get_tax_compliance(
            legal_entity_id=legal_entity_id,
            period_year=period_year,
            period_month=period_month,
        )

        return TaxComplianceHelperResponseSchema(
            period_year=period_year,
            period_month=period_month,
            total_revenue_period=helper.total_revenue_period,
            total_revenue_ytd=helper.total_revenue_ytd,
            estimated_pph_final=helper.estimated_pph_final,
            tax_due_reminder=helper.tax_due_reminder,
            submission_deadline=helper.submission_deadline,
            is_required_to_file=helper.is_required_to_file,
            notes=helper.notes,
            calculated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get tax compliance: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUSINESS PROFILE
# ----------------------------------------------------------------------------


@router.get(
    "/profile",
    response_model=BusinessProfileResponseSchema,
    summary="Get business profile",
    operation_id="get_umkm_profile",
)
async def get_business_profile(
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> BusinessProfileResponseSchema:
    """Get UMKM business profile."""
    try:
        profile = await service.get_business_profile(legal_entity_id)

        if not profile:
            raise HTTPException(status_code=404, detail="Business profile not found")

        return BusinessProfileResponseSchema(
            id=profile.id,
            legal_entity_id=profile.legal_entity_id,
            business_name=profile.business_name,
            business_type=profile.business_type,
            npwp=profile.npwp,
            business_address=profile.business_address,
            phone=profile.phone,
            email=profile.email,
            website=profile.website,
            established_date=profile.established_date,
            industry=profile.industry,
            uses_final_tax=profile.uses_final_tax,
            accounting_method=profile.accounting_method,
            fiscal_year_start=profile.fiscal_year_start,
            tax_submission_reminder_days=profile.tax_submission_reminder_days,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            version=profile.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get business profile: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/profile",
    response_model=BusinessProfileResponseSchema,
    summary="Update business profile",
    operation_id="update_umkm_profile",
)
async def update_business_profile(
    request: BusinessProfileSchema,
    _permission: None = Depends(require_permission("umkm:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> BusinessProfileResponseSchema:
    """Update UMKM business profile."""
    try:
        result = await service.update_business_profile(
            legal_entity_id=legal_entity_id,
            business_name=request.business_name,
            business_type=request.business_type,
            npwp=request.npwp,
            business_address=request.business_address,
            phone=request.phone,
            email=request.email,
            website=request.website,
            established_date=request.established_date,
            industry=request.industry,
            uses_final_tax=request.uses_final_tax,
            accounting_method=request.accounting_method,
            fiscal_year_start=request.fiscal_year_start,
            tax_submission_reminder_days=request.tax_submission_reminder_days,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Business profile not found")

        return BusinessProfileResponseSchema(
            id=result.id,
            legal_entity_id=result.legal_entity_id,
            business_name=result.business_name,
            business_type=result.business_type,
            npwp=result.npwp,
            business_address=result.business_address,
            phone=result.phone,
            email=result.email,
            website=result.website,
            established_date=result.established_date,
            industry=result.industry,
            uses_final_tax=result.uses_final_tax,
            accounting_method=result.accounting_method,
            fiscal_year_start=result.fiscal_year_start,
            tax_submission_reminder_days=result.tax_submission_reminder_days,
            created_at=result.created_at,
            updated_at=result.updated_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update business profile: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TRANSACTION SUMMARY
# ----------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=TransactionSummarySchema,
    summary="Get transaction summary",
    operation_id="get_umkm_summary",
)
async def get_transaction_summary(
    period_start: date = Query(..., description="Start date"),
    period_end: date = Query(..., description="End date"),
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> TransactionSummarySchema:
    """Get transaction summary by category and account."""
    try:
        summary = await service.get_transaction_summary(
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
        )

        return TransactionSummarySchema(
            period_start=period_start,
            period_end=period_end,
            by_category={k: float(v) for k, v in summary.by_category.items()},
            by_account={k: float(v) for k, v in summary.by_account.items()},
            by_month={k: float(v) for k, v in summary.by_month.items()},
            total_transactions=summary.total_transactions,
            total_amount=summary.total_amount,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get transaction summary: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CHART OF ACCOUNTS (Simplified)
# ----------------------------------------------------------------------------


@router.get(
    "/accounts",
    response_model=list[dict[str, Any]],
    summary="Get simplified chart of accounts",
    operation_id="get_umkm_accounts",
)
async def get_simplified_accounts(
    account_type: str | None = Query(
        None, description="Filter by account type (ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE)"
    ),
    _permission: None = Depends(require_permission("umkm:read")),
) -> list[dict[str, Any]]:
    """Get the simplified chart of accounts for UMKM."""
    accounts = []
    for code, data in SIMPLIFIED_ACCOUNTS.items():
        if account_type and data["type"] != account_type:
            continue
        accounts.append(
            {
                "account_code": code,
                "account_name": data["name"],
                "account_type": data["type"],
                "normal_balance": data["normal_balance"],
            }
        )
    return accounts


# ----------------------------------------------------------------------------
# JURNAL HISTORY & STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/journals/{journal_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get journal history",
    operation_id="get_umkm_journal_history",
)
async def get_journal_history(
    journal_id: UUID,
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> list[dict[str, Any]]:
    """Get journal entry change history (audit trail)."""
    try:
        history = await service.get_journal_history(journal_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "from_status": h.from_status,
                "to_status": h.to_status,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
                "notes": h.notes,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get journal history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/journals/{journal_id}/status",
    response_model=dict[str, Any],
    summary="Get journal status",
    operation_id="get_umkm_journal_status",
)
async def get_journal_status(
    journal_id: UUID,
    _permission: None = Depends(require_permission("umkm:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> dict[str, Any]:
    """Get detailed journal status including workflow state."""
    try:
        status_info = await service.get_journal_status(journal_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Journal entry not found")

        return {
            "journal_id": str(journal_id),
            "journal_number": status_info.journal_number,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_post": status_info.can_post,
            "can_reverse": status_info.can_reverse,
            "can_cancel": status_info.can_cancel,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "posted_at": status_info.posted_at.isoformat() if status_info.posted_at else None,
            "posted_by": str(status_info.posted_by) if status_info.posted_by else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get journal status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export/transactions",
    summary="Export transactions",
    operation_id="export_umkm_transactions",
)
async def export_transactions(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    _permission: None = Depends(require_permission("umkm:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_umkm_service),
) -> Response:
    """Export transactions to CSV or Excel."""
    try:
        data = await service.export_transactions(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            format=format,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"umkm_transactions_{legal_entity_id}_{start_date}_{end_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export transactions: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
