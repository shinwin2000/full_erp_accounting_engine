#!/usr/bin/env python3
"""
Module: fastapi_coa_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API endpoint untuk Chart of Accounts (COA) management.

CATATAN SINKRONISASI: setiap endpoint di bawah ini memanggil method
`COAService` (lihat application/service_layer/service_coa.py) dengan nama
yang PERSIS SAMA. Kalau menambah endpoint baru, tambahkan juga method-nya di
COAService — jangan biarkan router memanggil method yang tidak ada (itulah
akar masalah versi sebelumnya: banyak endpoint memanggil method yang tidak
pernah didefinisikan di service, sehingga selalu gagal dengan 500).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================


class IdempotencyManager:
    """Simple in-memory idempotency manager untuk FastAPI endpoints.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam."""

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
        if (datetime.now(UTC) - timestamp).total_seconds() > self._ttl_seconds:
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
        self._storage[storage_key] = (result_json, datetime.now(UTC))


_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class AccountType(str, Enum):
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    REVENUE = "Revenue"
    EXPENSE = "Expense"
    CONTRA_ASSET = "ContraAsset"
    CONTRA_LIABILITY = "ContraLiability"
    CONTRA_EQUITY = "ContraEquity"


class NormalBalance(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"
    ARCHIVED = "archived"


class CashflowType(str, Enum):
    OPERATING = "operating"
    INVESTING = "investing"
    FINANCING = "financing"


ACCOUNT_TYPE_PREFIXES = {
    AccountType.ASSET: ["1"],
    AccountType.LIABILITY: ["2"],
    AccountType.EQUITY: ["3"],
    AccountType.REVENUE: ["4"],
    AccountType.EXPENSE: ["5", "6"],
}

DEFAULT_CATEGORIES = {
    "1-1000": "Kas dan Bank",
    "1-2000": "Piutang",
    "1-3000": "Persediaan",
    "1-4000": "Aset Tetap",
    "1-5000": "Aset Tidak Berwujud",
    "1-9000": "Akumulasi Penyusutan",
    "2-1000": "Utang Usaha",
    "2-2000": "Utang Pajak",
    "2-3000": "Utang Bank",
    "2-4000": "Utang Jangka Panjang",
    "3-1000": "Modal",
    "3-2000": "Laba Ditahan",
    "4-1000": "Pendapatan Usaha",
    "4-2000": "Pendapatan Lain-lain",
    "5-1000": "Beban Pokok Penjualan",
    "5-2000": "Beban Operasional",
    "6-1000": "Beban Lain-lain",
}


# ============================================================================
# SCHEMAS
# ============================================================================


class AccountCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_code: str = Field(..., min_length=1, max_length=20, description="Kode akun")
    account_name: str = Field(..., min_length=2, max_length=200, description="Nama akun")
    account_name_en: str | None = Field(None, max_length=200, description="Nama akun (Inggris)")
    account_type: AccountType = Field(..., description="Jenis akun")
    normal_balance: NormalBalance = Field(..., description="Saldo normal (debit atau credit)")
    parent_account_code: str | None = Field(None, max_length=20, description="Kode akun induk")
    account_group: str | None = Field(None, max_length=100, description="Kategori/grup akun")
    description: str | None = Field(None, max_length=500, description="Deskripsi akun")
    currency_code: str = Field("IDR", min_length=3, max_length=3, description="Mata uang")
    is_bank_account: bool = False
    is_cash_account: bool = False
    is_intercompany: bool = False
    is_header: bool = Field(False, description="Header/parent account (tidak bisa dipakai posting)")
    allow_posting: bool = Field(True, description="Boleh dipakai sebagai baris jurnal")
    level: int = Field(0, ge=0, le=10, description="Level dalam hierarki (dihitung ulang jika ada parent)")
    sort_order: int = Field(0, description="Urutan tampil dalam grup/level yang sama")
    opening_balance: Decimal = Field(0, decimal_places=2, description="Saldo awal")
    tax_code: str | None = Field(None, max_length=30, description="Kode pajak default")
    cashflow_type: CashflowType | None = Field(None, description="Klasifikasi arus kas")
    budget_control: bool = Field(False, description="Apakah dikontrol anggaran?")
    reconciliation_required: bool = Field(False, description="Wajib direkonsiliasi (mis. akun bank)")
    category: str | None = Field(None, max_length=50, description="[Deprecated] alias dari account_group")

    @field_validator("account_type", mode="before")
    @classmethod
    def normalize_account_type(cls, v: object) -> object:
        # Frontend desktop (coa_page.py) kadang mengirim account_type huruf kecil
        # (mis. "asset"), sedangkan enum backend memakai Title/Camel Case
        # ("Asset", "ContraAsset"). Dinormalisasi di sini supaya backend
        # toleran terhadap variasi casing/underscore.
        if isinstance(v, str):
            cleaned = v.strip().replace("_", " ").replace("-", " ")
            return "".join(word.capitalize() for word in cleaned.split())
        return v

    @field_validator("account_code")
    @classmethod
    def validate_account_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Account code is required")
        if not v.replace("-", "").replace(".", "").isdigit():
            raise ValueError("Account code must contain digits and optional hyphens/periods")
        return v.upper()

    @field_validator("parent_account_code")
    @classmethod
    def validate_parent(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @model_validator(mode="after")
    def validate_account_type_prefix(self) -> AccountCreateSchema:
        first_digit = self.account_code[0] if self.account_code else ""
        expected_prefixes = ACCOUNT_TYPE_PREFIXES.get(self.account_type, [])
        if expected_prefixes and first_digit not in expected_prefixes:
            raise ValueError(
                f"Account code for {self.account_type.value} should start with "
                f"{', '.join(expected_prefixes)}"
            )
        return self


class AccountUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_name: str | None = Field(None, min_length=2, max_length=200)
    account_name_en: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=500)
    status: AccountStatus | None = None
    parent_account_code: str | None = Field(None, max_length=20)
    account_group: str | None = Field(None, max_length=100)
    currency_code: str | None = Field(None, min_length=3, max_length=3)
    is_bank_account: bool | None = None
    is_cash_account: bool | None = None
    is_intercompany: bool | None = None
    allow_posting: bool | None = None
    sort_order: int | None = None
    tax_code: str | None = Field(None, max_length=30)
    cashflow_type: CashflowType | None = None
    budget_control: bool | None = None
    reconciliation_required: bool | None = None
    category: str | None = Field(None, max_length=50, description="[Deprecated] alias dari account_group")

    @field_validator("parent_account_code")
    @classmethod
    def validate_parent(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class AccountResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_code: str
    account_name: str
    account_name_en: str | None = None
    account_type: AccountType
    account_group: str | None = None
    normal_balance: NormalBalance
    parent_account_id: UUID | None
    parent_account_code: str | None
    level: int
    sort_order: int = 0
    description: str | None
    status: AccountStatus
    currency_code: str
    is_bank_account: bool
    is_cash_account: bool
    is_intercompany: bool
    is_header: bool
    allow_posting: bool = True
    is_used_in_transaction: bool = False
    is_locked: bool = False
    lock_reason: str | None = None
    current_balance: Decimal = Decimal(0)
    opening_balance: Decimal = Decimal(0)
    tax_code: str | None = None
    cashflow_type: CashflowType | None = None
    budget_control: bool = False
    reconciliation_required: bool = False
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    updated_by: UUID | None = None
    version: int = 1
    children: list[AccountResponseSchema] | None = None

    @computed_field  # type: ignore[misc]
    @property
    def category(self) -> str | None:
        """[Deprecated] alias baca-saja dari account_group, dipertahankan di
        output JSON supaya klien lama yang masih membaca `category` tidak
        langsung patah."""
        return self.account_group


class AccountBalanceResponseSchema(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    as_of_date: datetime
    balance: Decimal
    normal_balance: NormalBalance
    is_debit_balance: bool
    opening_balance: Decimal
    debit_movement: Decimal
    credit_movement: Decimal


class AccountUsageResponseSchema(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    journal_count: int
    last_used_at: datetime | None
    total_debit: Decimal
    total_credit: Decimal
    is_used_in_journal: bool
    is_used_in_budget: bool
    is_used_in_tax: bool


class AccountListResponseSchema(BaseModel):
    items: list[AccountResponseSchema]
    total: int
    page: int
    page_size: int


class AccountTreeResponseSchema(BaseModel):
    root_accounts: list[AccountResponseSchema]
    flattened: list[AccountResponseSchema]
    total_accounts: int
    total_levels: int


class AccountValidationResultSchema(BaseModel):
    is_valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []


class BulkStatusUpdateSchema(BaseModel):
    account_ids: list[UUID] = Field(..., min_length=1)
    status: AccountStatus = Field(..., description="New status")
    reason: str | None = Field(None, max_length=500)


class BulkParentUpdateSchema(BaseModel):
    account_ids: list[UUID] = Field(..., min_length=1)
    parent_account_code: str | None = Field(None, max_length=20)


class ImportExportResultSchema(BaseModel):
    success: bool
    message: str
    imported_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    errors: list[str] = []


class DuplicateAccountSchema(BaseModel):
    new_account_code: str = Field(..., min_length=1, max_length=20)
    new_account_name: str | None = Field(None, max_length=200)


class MoveAccountSchema(BaseModel):
    new_parent_account_code: str | None = Field(
        None, max_length=20, description="Kosongkan (null) untuk jadikan akun root"
    )


class AccountStatisticsResponseSchema(BaseModel):
    total_accounts: int
    active_accounts: int
    inactive_accounts: int
    header_accounts: int
    posting_accounts: int
    by_type: dict[str, int]
    by_level: dict[str, int]


async def get_coa_service(request: Request) -> Any:
    from application.service_layer.service_coa import COAService
    container = request.app.state.container
    return await container.resolve_async(COAService)


router = APIRouter(prefix="/chart-of-accounts", tags=["Chart of Accounts"])


# ----------------------------------------------------------------------------
# HEALTH CHECK
# ----------------------------------------------------------------------------

@router.get("/ping-coa")
def ping_coa() -> dict[str, str]:
    return {"status": "ok", "service": "coa"}


# ----------------------------------------------------------------------------
# RESPONSE MAPPING HELPER (satu tempat -> tidak ada lagi drift antar endpoint)
# ----------------------------------------------------------------------------


def _to_response(a: Any) -> AccountResponseSchema:
    return AccountResponseSchema(
        id=a.id,
        account_code=a.account_code,
        account_name=a.account_name,
        account_name_en=a.account_name_en,
        account_type=AccountType(a.account_type),
        account_group=a.account_group,
        normal_balance=NormalBalance(a.normal_balance),
        parent_account_id=a.parent_account_id,
        parent_account_code=a.parent_account_code,
        level=a.level,
        sort_order=a.sort_order,
        description=a.description,
        status=AccountStatus(a.status),
        currency_code=a.currency_code,
        is_bank_account=a.is_bank_account,
        is_cash_account=a.is_cash_account,
        is_intercompany=a.is_intercompany,
        is_header=a.is_header,
        allow_posting=a.allow_posting,
        is_used_in_transaction=a.is_used_in_transaction,
        is_locked=a.is_locked,
        lock_reason=a.lock_reason,
        current_balance=a.current_balance,
        opening_balance=a.opening_balance,
        tax_code=a.tax_code,
        cashflow_type=CashflowType(a.cashflow_type) if a.cashflow_type else None,
        budget_control=a.budget_control,
        reconciliation_required=a.reconciliation_required,
        created_at=a.created_at,
        updated_at=a.updated_at,
        created_by=a.created_by,
        created_by_name=a.created_by_name,
        updated_by=a.updated_by,
        version=a.version,
        children=[_to_response(c) for c in a.children] if a.children else None,
    )


def _err(e: Exception) -> HTTPException:
    from application.service_layer.service_coa import (
        AccountCodeAlreadyExistsError,
        AccountCycleDetectedError,
        AccountHasChildrenError,
        AccountHasTransactionsError,
        AccountLockedError,
        AccountNotFoundError,
        InvalidParentAccountError,
        PostingAccountCannotHaveChildrenError,
    )

    if isinstance(e, AccountNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, (
        AccountCodeAlreadyExistsError, InvalidParentAccountError, AccountCycleDetectedError,
        AccountHasChildrenError, AccountHasTransactionsError, AccountLockedError,
        PostingAccountCannotHaveChildrenError, ValueError,
    )):
        return HTTPException(status_code=422, detail=str(e))
    logger.exception("Unhandled COA error: %s", e)
    return HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ACCOUNT CRUD OPERATIONS
# ----------------------------------------------------------------------------

@router.post(
    "/accounts",
    response_model=AccountResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create new account",
    operation_id="coa_create_account",
)
async def create_account(
    request: AccountCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    method_name = "create_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return AccountResponseSchema(**cached)

    try:
        result = await coa_service.create_account_write(
            legal_entity_id=legal_entity_id,
            account_code=request.account_code,
            account_name=request.account_name,
            account_name_en=request.account_name_en,
            account_type=request.account_type.value,
            normal_balance=request.normal_balance.value,
            parent_account_code=request.parent_account_code,
            description=request.description,
            currency_code=request.currency_code,
            is_bank_account=request.is_bank_account,
            is_cash_account=request.is_cash_account,
            is_intercompany=request.is_intercompany,
            is_header=request.is_header,
            allow_posting=request.allow_posting,
            level=request.level,
            sort_order=request.sort_order,
            opening_balance=request.opening_balance,
            account_group=request.account_group,
            tax_code=request.tax_code,
            cashflow_type=request.cashflow_type.value if request.cashflow_type else None,
            category=request.category,
            budget_control=request.budget_control,
            reconciliation_required=request.reconciliation_required,
            created_by=current_user.user_id,
        )
        response = _to_response(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/{account_id}",
    response_model=AccountResponseSchema,
    summary="Get account by ID",
    operation_id="coa_get_account_by_id",
)
async def get_account_by_id(
    account_id: UUID = Path(...),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    try:
        account = await coa_service.get_account_by_id(account_id, legal_entity_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return _to_response(account)
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/by-code/{account_code}",
    response_model=AccountResponseSchema,
    summary="Get account by account code",
    operation_id="coa_get_account_by_code",
)
async def get_account_by_code(
    account_code: str = Path(..., min_length=1, max_length=20),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    try:
        account = await coa_service.get_account_by_code(account_code, legal_entity_id)
        if not account:
            raise HTTPException(status_code=404, detail=f"Account with code {account_code} not found")
        return _to_response(account)
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.put(
    "/accounts/{account_id}",
    response_model=AccountResponseSchema,
    summary="Update account",
    operation_id="coa_update_account",
)
async def update_account(
    account_id: UUID,
    request: AccountUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    method_name = "update_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return AccountResponseSchema(**cached)

    try:
        result = await coa_service.update_account_write(
            account_id=account_id,
            legal_entity_id=legal_entity_id,
            account_name=request.account_name,
            account_name_en=request.account_name_en,
            description=request.description,
            status=request.status.value if request.status else None,
            parent_account_code=request.parent_account_code,
            currency_code=request.currency_code,
            is_bank_account=request.is_bank_account,
            is_cash_account=request.is_cash_account,
            is_intercompany=request.is_intercompany,
            allow_posting=request.allow_posting,
            sort_order=request.sort_order,
            account_group=request.account_group,
            tax_code=request.tax_code,
            cashflow_type=request.cashflow_type.value if request.cashflow_type else None,
            category=request.category,
            budget_control=request.budget_control,
            reconciliation_required=request.reconciliation_required,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Account not found or cannot be updated")
        response = _to_response(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.delete(
    "/accounts/{account_id}",
    response_model=dict[str, str],
    summary="Deactivate/archive/delete account",
    operation_id="coa_deactivate_account",
)
async def deactivate_account(
    account_id: UUID,
    permanent: bool = Query(False, description="Coba hapus permanen kalau akun belum pernah dipakai transaksi"),
    reason: str = Query("", description="Reason for deactivation"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> dict[str, str]:
    method_name = "deactivate_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached

    try:
        if permanent:
            from application.service_layer.service_coa import (
                AccountHasChildrenError,
                AccountHasTransactionsError,
            )
            try:
                await coa_service.delete_account(
                    account_id, current_user.user_id, legal_entity_id, reason
                )
                response = {"message": "Account permanently deleted"}
            except (AccountHasChildrenError, AccountHasTransactionsError):
                # Sudah pernah dipakai transaksi / masih punya sub-akun -> tidak
                # boleh dihapus permanen demi integritas laporan historis;
                # fallback otomatis ke arsip (soft delete), sesuai prinsip COA
                # produksi: "akun ini hampir tidak pernah benar-benar dihapus".
                result = await coa_service.void_account(
                    account_id, current_user.user_id, legal_entity_id, reason
                )
                if not result:
                    raise HTTPException(status_code=404, detail="Account not found")
                response = {
                    "message": (
                        f"Account {result.account_code} already used in transactions or has "
                        "sub-accounts; archived (soft delete) instead of permanently deleted"
                    )
                }
        else:
            result = await coa_service.deactivate_account(
                account_id, current_user.user_id, legal_entity_id, reason
            )
            if not result:
                raise HTTPException(status_code=404, detail="Account not found or cannot be deactivated")
            response = {"message": f"Account {result.account_code} deactivated successfully"}

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.post(
    "/accounts/{account_id}/activate",
    response_model=AccountResponseSchema,
    summary="Activate account",
    operation_id="coa_activate_account",
)
async def activate_account(
    account_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    method_name = "activate_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return AccountResponseSchema(**cached)
    try:
        result = await coa_service.activate_account(account_id, current_user.user_id, legal_entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Account not found or cannot be activated")
        response = _to_response(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.post(
    "/accounts/{account_id}/lock",
    response_model=AccountResponseSchema,
    summary="Lock account",
    operation_id="coa_lock_account",
)
async def lock_account(
    account_id: UUID,
    reason: str = Query("", description="Lock reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    method_name = "lock_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return AccountResponseSchema(**cached)
    try:
        result = await coa_service.lock_account(account_id, current_user.user_id, legal_entity_id, reason)
        if not result:
            raise HTTPException(status_code=404, detail="Account not found")
        response = _to_response(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.post(
    "/accounts/{account_id}/unlock",
    response_model=AccountResponseSchema,
    summary="Unlock account",
    operation_id="coa_unlock_account",
)
async def unlock_account(
    account_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    method_name = "unlock_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return AccountResponseSchema(**cached)
    try:
        result = await coa_service.unlock_account(account_id, current_user.user_id, legal_entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Account not found")
        response = _to_response(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.post(
    "/accounts/{account_id}/duplicate",
    response_model=AccountResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate an existing account under a new code",
    operation_id="coa_duplicate_account",
)
async def duplicate_account(
    account_id: UUID,
    request: DuplicateAccountSchema,
    _permission: None = Depends(require_permission("coa:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    try:
        source = await coa_service.get_account_by_id(account_id, legal_entity_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source account not found")
        result = await coa_service.create_account_write(
            legal_entity_id=legal_entity_id,
            account_code=request.new_account_code,
            account_name=request.new_account_name or f"{source.account_name} (Copy)",
            account_name_en=source.account_name_en,
            account_type=source.account_type,
            normal_balance=source.normal_balance,
            parent_account_code=source.parent_account_code,
            description=source.description,
            currency_code=source.currency_code,
            is_bank_account=source.is_bank_account,
            is_cash_account=source.is_cash_account,
            is_intercompany=source.is_intercompany,
            is_header=source.is_header,
            allow_posting=source.allow_posting,
            level=source.level,
            sort_order=source.sort_order,
            opening_balance=Decimal("0"),
            account_group=source.account_group,
            tax_code=source.tax_code,
            cashflow_type=source.cashflow_type,
            budget_control=source.budget_control,
            reconciliation_required=source.reconciliation_required,
            created_by=current_user.user_id,
        )
        return _to_response(result)
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.post(
    "/accounts/{account_id}/move",
    response_model=AccountResponseSchema,
    summary="Move account to a different parent (or make it a root account)",
    operation_id="coa_move_account",
)
async def move_account(
    account_id: UUID,
    request: MoveAccountSchema,
    _permission: None = Depends(require_permission("coa:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    try:
        result = await coa_service.update_account_write(
            account_id=account_id,
            legal_entity_id=legal_entity_id,
            account_name=None,
            account_name_en=None,
            description=None,
            status=None,
            parent_account_code=request.new_parent_account_code or "",
            currency_code=None,
            is_bank_account=None,
            is_cash_account=None,
            is_intercompany=None,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Account not found")
        return _to_response(result)
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# LIST ACCOUNTS + FILTER SHORTCUTS
# ----------------------------------------------------------------------------

@router.get(
    "/accounts",
    response_model=AccountListResponseSchema,
    summary="List accounts with filters",
    operation_id="coa_list_accounts",
)
async def list_accounts(
    account_type: AccountType | None = Query(None, description="Filter by account type"),
    status: AccountStatus | None = Query(None, description="Filter by status"),
    parent_account_code: str | None = Query(None, description="Filter by parent"),
    is_header: bool | None = Query(None, description="Filter header accounts"),
    allow_posting: bool | None = Query(None, description="Filter posting-allowed accounts"),
    account_group: str | None = Query(None, description="Filter by account group/category"),
    level: int | None = Query(None, ge=0, le=10, description="Filter by level"),
    search: str | None = Query(None, description="Search in code or name"),
    include_inactive: bool = Query(False, description="Include inactive accounts"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=5000, description="Items per page"),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        result = await coa_service.list_accounts(
            legal_entity_id=legal_entity_id,
            account_type=account_type.value if account_type else None,
            status=status.value if status else None,
            parent_account_code=parent_account_code,
            is_header=is_header,
            allow_posting=allow_posting,
            account_group=account_group,
            level=level,
            search=search,
            include_inactive=include_inactive,
            page=page,
            page_size=page_size,
        )
        return AccountListResponseSchema(
            items=[_to_response(acc) for acc in result.items],
            total=result.total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/active",
    response_model=AccountListResponseSchema,
    summary="List active accounts only",
    operation_id="coa_list_active_accounts",
)
async def list_active_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=5000),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        result = await coa_service.list_accounts(
            legal_entity_id=legal_entity_id, status="active",
            include_inactive=False, page=page, page_size=page_size,
        )
        return AccountListResponseSchema(
            items=[_to_response(acc) for acc in result.items], total=result.total, page=page, page_size=page_size,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/header",
    response_model=AccountListResponseSchema,
    summary="List header (parent-only) accounts",
    operation_id="coa_list_header_accounts",
)
async def list_header_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=5000),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        result = await coa_service.list_accounts(
            legal_entity_id=legal_entity_id, is_header=True,
            include_inactive=True, page=page, page_size=page_size,
        )
        return AccountListResponseSchema(
            items=[_to_response(acc) for acc in result.items], total=result.total, page=page, page_size=page_size,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/posting",
    response_model=AccountListResponseSchema,
    summary="List posting-allowed (non-header) accounts",
    operation_id="coa_list_posting_accounts",
)
async def list_posting_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=5000),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        result = await coa_service.list_accounts(
            legal_entity_id=legal_entity_id, allow_posting=True, is_header=False,
            status="active", include_inactive=False, page=page, page_size=page_size,
        )
        return AccountListResponseSchema(
            items=[_to_response(acc) for acc in result.items], total=result.total, page=page, page_size=page_size,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/by-type/{account_type}",
    response_model=AccountListResponseSchema,
    summary="List accounts filtered by type",
    operation_id="coa_list_accounts_by_type",
)
async def list_accounts_by_type(
    account_type: AccountType,
    include_inactive: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=5000),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        result = await coa_service.list_accounts(
            legal_entity_id=legal_entity_id, account_type=account_type.value,
            include_inactive=include_inactive, page=page, page_size=page_size,
        )
        return AccountListResponseSchema(
            items=[_to_response(acc) for acc in result.items], total=result.total, page=page, page_size=page_size,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/by-parent/{parent_account_code}",
    response_model=AccountListResponseSchema,
    summary="List direct children of a parent account",
    operation_id="coa_list_accounts_by_parent",
)
async def list_accounts_by_parent(
    parent_account_code: str,
    include_inactive: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=5000),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        result = await coa_service.list_accounts(
            legal_entity_id=legal_entity_id, parent_account_code=parent_account_code.upper(),
            include_inactive=include_inactive, page=page, page_size=page_size,
        )
        return AccountListResponseSchema(
            items=[_to_response(acc) for acc in result.items], total=result.total, page=page, page_size=page_size,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/search",
    response_model=AccountListResponseSchema,
    summary="Search accounts by code or name",
    operation_id="coa_search_accounts",
)
async def search_accounts(
    q: str = Query(..., min_length=1, description="Search term (code or name)"),
    include_inactive: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        result = await coa_service.list_accounts(
            legal_entity_id=legal_entity_id, search=q,
            include_inactive=include_inactive, page=page, page_size=page_size,
        )
        return AccountListResponseSchema(
            items=[_to_response(acc) for acc in result.items], total=result.total, page=page, page_size=page_size,
        )
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# ACCOUNT HIERARCHY TREE
# ----------------------------------------------------------------------------

@router.get(
    "/tree",
    response_model=AccountTreeResponseSchema,
    summary="Get account hierarchy tree",
    operation_id="coa_get_account_tree",
)
async def get_account_tree(
    include_inactive: bool = Query(False, description="Include inactive accounts"),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountTreeResponseSchema:
    try:
        tree = await coa_service.get_account_hierarchy(legal_entity_id, include_inactive)
        root_accounts = [_to_response(root) for root in tree.root_accounts]
        flattened = [_to_response(acc) for acc in tree.flattened]
        return AccountTreeResponseSchema(
            root_accounts=root_accounts,
            flattened=flattened,
            total_accounts=len(flattened),
            total_levels=tree.total_levels,
        )
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# ACCOUNT BALANCE & USAGE
# ----------------------------------------------------------------------------

@router.get(
    "/accounts/{account_id}/balance",
    response_model=AccountBalanceResponseSchema,
    summary="Get account balance",
    operation_id="coa_get_account_balance",
)
async def get_account_balance(
    account_id: UUID,
    as_of_date: datetime = Query(default_factory=datetime.now, description="As of date"),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountBalanceResponseSchema:
    try:
        balance = await coa_service.get_account_balance(account_id, legal_entity_id, as_of_date)
        if not balance:
            raise HTTPException(status_code=404, detail="Account not found")
        return AccountBalanceResponseSchema(
            account_id=account_id,
            account_code=balance.account_code,
            account_name=balance.account_name,
            as_of_date=as_of_date,
            balance=balance.balance,
            normal_balance=NormalBalance(balance.normal_balance),
            is_debit_balance=balance.is_debit_balance,
            opening_balance=balance.opening_balance,
            debit_movement=balance.debit_movement,
            credit_movement=balance.credit_movement,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/{account_id}/usage",
    response_model=AccountUsageResponseSchema,
    summary="Get account usage information",
    operation_id="coa_get_account_usage",
)
async def get_account_usage(
    account_id: UUID,
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountUsageResponseSchema:
    try:
        usage = await coa_service.get_account_usage(account_id, legal_entity_id)
        if not usage:
            raise HTTPException(status_code=404, detail="Account not found")
        return AccountUsageResponseSchema(
            account_id=account_id,
            account_code=usage.account_code,
            account_name=usage.account_name,
            journal_count=usage.journal_count,
            last_used_at=usage.last_used_at,
            total_debit=usage.total_debit,
            total_credit=usage.total_credit,
            is_used_in_journal=usage.is_used_in_journal,
            is_used_in_budget=usage.is_used_in_budget,
            is_used_in_tax=usage.is_used_in_tax,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# STATISTICS
# ----------------------------------------------------------------------------

@router.get(
    "/statistics",
    response_model=AccountStatisticsResponseSchema,
    summary="Get Chart of Accounts statistics",
    operation_id="coa_get_statistics",
)
async def get_statistics(
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountStatisticsResponseSchema:
    try:
        all_accounts = await coa_service.list_accounts_raw(legal_entity_id, include_inactive=True)
        by_type: dict[str, int] = {}
        by_level: dict[str, int] = {}
        active = inactive = header = posting = 0
        for a in all_accounts:
            by_type[a.account_type] = by_type.get(a.account_type, 0) + 1
            by_level[str(a.level)] = by_level.get(str(a.level), 0) + 1
            if a.status == "active":
                active += 1
            else:
                inactive += 1
            if a.is_header:
                header += 1
            elif a.allow_posting:
                posting += 1
        return AccountStatisticsResponseSchema(
            total_accounts=len(all_accounts),
            active_accounts=active,
            inactive_accounts=inactive,
            header_accounts=header,
            posting_accounts=posting,
            by_type=by_type,
            by_level=by_level,
        )
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# ACCOUNT VALIDATION
# ----------------------------------------------------------------------------

@router.get(
    "/accounts/{account_id}/validate",
    response_model=AccountValidationResultSchema,
    summary="Validate account before modification",
    operation_id="coa_validate_account",
)
async def validate_account(
    account_id: UUID,
    action: str = Query("delete", description="Action to validate: delete, update, deactivate"),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountValidationResultSchema:
    try:
        result = await coa_service.validate_account_modification(account_id, legal_entity_id, action)
        return AccountValidationResultSchema(
            is_valid=result.is_valid, errors=result.errors, warnings=result.warnings, suggestions=result.suggestions,
        )
    except Exception as e:
        raise _err(e)


@router.get(
    "/validate-code/{account_code}",
    response_model=AccountValidationResultSchema,
    summary="Validate account code",
    operation_id="coa_validate_account_code",
)
async def validate_account_code(
    account_code: str = Path(..., min_length=1, max_length=20),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountValidationResultSchema:
    try:
        result = await coa_service.validate_account_code(account_code, legal_entity_id)
        return AccountValidationResultSchema(
            is_valid=result.is_valid, errors=result.errors, warnings=result.warnings, suggestions=result.suggestions,
        )
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# BULK OPERATIONS
# ----------------------------------------------------------------------------

@router.patch(
    "/accounts/bulk-status",
    response_model=dict[str, Any],
    summary="Bulk update account status",
    operation_id="coa_bulk_update_status",
)
async def bulk_update_status(
    request: BulkStatusUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> dict[str, Any]:
    method_name = "bulk_update_status"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached
    try:
        result = await coa_service.bulk_update_status(
            account_ids=request.account_ids, status=request.status.value, reason=request.reason,
            updated_by=current_user.user_id, legal_entity_id=legal_entity_id,
        )
        response = {
            "total": result.total, "success_count": result.success_count, "failed_count": result.failed_count,
            "failed_ids": [str(fid) for fid in result.failed_ids], "errors": result.errors,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except Exception as e:
        raise _err(e)


@router.patch(
    "/accounts/bulk-parent",
    response_model=dict[str, Any],
    summary="Bulk update parent account",
    operation_id="coa_bulk_update_parent",
)
async def bulk_update_parent(
    request: BulkParentUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> dict[str, Any]:
    method_name = "bulk_update_parent"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached
    try:
        result = await coa_service.bulk_update_parent(
            account_ids=request.account_ids, parent_account_code=request.parent_account_code,
            updated_by=current_user.user_id, legal_entity_id=legal_entity_id,
        )
        response = {
            "total": result.total, "success_count": result.success_count, "failed_count": result.failed_count,
            "failed_ids": [str(fid) for fid in result.failed_ids], "errors": result.errors,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# IMPORT & EXPORT
# ----------------------------------------------------------------------------

@router.get(
    "/export",
    summary="Export Chart of Accounts",
    operation_id="coa_export",
)
async def export_coa(
    format: str = Query("json", pattern="^(json|csv|excel)$", description="Export format"),
    include_inactive: bool = Query(False, description="Include inactive accounts"),
    _permission: None = Depends(require_permission("coa:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> Response:
    try:
        data = await coa_service.export_coa(legal_entity_id, format, include_inactive)
        media_types = {
            "json": "application/json", "csv": "text/csv",
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        extensions = {"json": "json", "csv": "csv", "excel": "csv"}
        filename = f"coa_export_{legal_entity_id}.{extensions[format]}"
        return Response(
            content=data, media_type=media_types[format],
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        raise _err(e)


@router.post(
    "/import",
    response_model=ImportExportResultSchema,
    summary="Import Chart of Accounts",
    operation_id="coa_import",
)
async def import_coa(
    file: UploadFile = File(..., description="COA file (JSON, CSV, or Excel-as-CSV)"),
    mode: str = Query("merge", pattern="^(merge|replace)$", description="Import mode"),
    validate_only: bool = Query(False, description="Only validate, don't save"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("coa:import")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> ImportExportResultSchema:
    method_name = "import_coa"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return ImportExportResultSchema(**cached)

    try:
        content = await file.read()
        filename = file.filename or "import.csv"
        file_content = content.decode("utf-8-sig") if filename.lower().endswith((".json", ".csv")) else content
        result = await coa_service.import_coa(
            legal_entity_id=legal_entity_id,
            file_content=file_content,
            file_format=filename.split(".")[-1].lower(),
            mode=mode,
            validate_only=validate_only,
            imported_by=current_user.user_id,
        )
        response = ImportExportResultSchema(
            success=result.success, message=result.message, imported_count=result.imported_count,
            updated_count=result.updated_count, skipped_count=result.skipped_count, errors=result.errors,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)


# ----------------------------------------------------------------------------
# ACCOUNT HISTORY & AUDIT
# ----------------------------------------------------------------------------

@router.get(
    "/accounts/{account_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get account change history",
    operation_id="coa_get_account_history",
)
async def get_account_history(
    account_id: UUID,
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> list[dict[str, Any]]:
    try:
        history = await coa_service.get_account_history(account_id, legal_entity_id, start_date, end_date)
        return [
            {
                "timestamp": h.timestamp.isoformat(), "action": h.action, "field": h.field,
                "old_value": h.old_value, "new_value": h.new_value, "actor_id": str(h.actor_id),
                "actor_name": h.actor_name, "reason": h.reason,
            }
            for h in history
        ]
    except Exception as e:
        raise _err(e)


@router.get(
    "/accounts/{account_id}/audit-trail",
    response_model=list[dict[str, Any]],
    summary="Get account audit trail",
    operation_id="coa_get_account_audit_trail",
)
async def get_account_audit_trail(
    account_id: UUID,
    limit: int = Query(100, ge=1, le=1000, description="Number of records"),
    _permission: None = Depends(require_permission("coa:audit")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> list[dict[str, Any]]:
    try:
        audit_trail = await coa_service.get_account_audit_trail(account_id, legal_entity_id, limit)
        return [
            {
                "timestamp": a.timestamp.isoformat(), "event_type": a.event_type, "event_data": a.event_data,
                "actor_id": str(a.actor_id), "actor_name": a.actor_name, "version": a.version,
            }
            for a in audit_trail
        ]
    except Exception as e:
        raise _err(e)


__all__ = ["router"]
