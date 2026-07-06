#!/usr/bin/env python3
"""
Module: fastapi_coa_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API endpoint untuk Chart of Accounts (COA) management.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
    Header,
)
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)
from application.dto_objects.coa_request import (
    AccountCreateRequest,
    AccountQueryParams,
    AccountUpdateRequest,
)

logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk FastAPI endpoints.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: Dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> Optional[Dict[str, Any]]:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now(timezone.utc) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: Dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(timezone.utc))


# Global instance
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


class NormalBalance(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"
    ARCHIVED = "archived"


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


class AccountCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_code: str = Field(..., min_length=3, max_length=20, description="Kode akun")
    account_name: str = Field(..., min_length=3, max_length=200, description="Nama akun")
    account_type: AccountType = Field(..., description="Jenis akun")
    normal_balance: NormalBalance = Field(..., description="Saldo normal (debit atau credit)")
    parent_account_code: str | None = Field(None, max_length=20, description="Kode akun induk")
    description: str | None = Field(None, max_length=500, description="Deskripsi akun")
    currency_code: str = Field("IDR", min_length=3, max_length=3, description="Mata uang")
    is_bank_account: bool = False
    is_cash_account: bool = False
    is_intercompany: bool = False
    is_header: bool = False
    level: int = Field(1, ge=1, le=10, description="Level dalam hierarki")
    opening_balance: Decimal = Field(0, decimal_places=2, description="Saldo awal")
    category: str | None = Field(None, max_length=50, description="Kategori akun")
    budget_control: bool = Field(False, description="Apakah dikontrol anggaran?")

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
        if v:
            return v.upper()
        return v

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

    account_name: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, max_length=500)
    status: AccountStatus | None = None
    parent_account_code: str | None = Field(None, max_length=20)
    currency_code: str | None = Field(None, min_length=3, max_length=3)
    is_bank_account: bool | None = None
    is_cash_account: bool | None = None
    is_intercompany: bool | None = None
    category: str | None = Field(None, max_length=50)
    budget_control: bool | None = None

    @field_validator("parent_account_code")
    @classmethod
    def validate_parent(cls, v: str | None) -> str | None:
        if v:
            return v.upper()
        return v


class AccountResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_code: str
    account_name: str
    account_type: AccountType
    normal_balance: NormalBalance
    parent_account_id: UUID | None
    parent_account_code: str | None
    level: int
    description: str | None
    status: AccountStatus
    currency_code: str
    is_bank_account: bool
    is_cash_account: bool
    is_intercompany: bool
    is_header: bool
    is_used_in_transaction: bool = False
    is_locked: bool = False
    current_balance: Decimal = Decimal(0)
    category: str | None
    budget_control: bool = False
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1
    children: list[AccountResponseSchema] | None = None


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


async def get_coa_service(request: Request) -> Any:
    from application.service_layer.service_coa import COAService
    container = request.app.state.container
    return container.resolve(COAService)


router = APIRouter(prefix="/chart-of-accounts", tags=["Chart of Accounts"])


# ----------------------------------------------------------------------------
# HEALTH CHECK (UNIQUE PATH)
# ----------------------------------------------------------------------------

@router.get("/ping-coa")
def ping_coa() -> dict[str, str]:
    return {"status": "ok", "service": "coa"}


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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return AccountResponseSchema(**cached)

    try:
        create_dto = AccountCreateRequest(
            account_code=request.account_code,
            account_name=request.account_name,
            account_type=request.account_type.value,
            normal_balance=request.normal_balance.value,
            parent_account_code=request.parent_account_code,
            description=request.description,
            currency_code=request.currency_code,
            is_bank_account=request.is_bank_account,
            is_cash_account=request.is_cash_account,
            is_intercompany=request.is_intercompany,
            is_header=request.is_header,
            level=request.level,
            opening_balance=request.opening_balance,
            category=request.category,
            budget_control=request.budget_control,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await coa_service.create_account(create_dto)
        response = AccountResponseSchema(
            id=result.id,
            account_code=result.account_code,
            account_name=result.account_name,
            account_type=AccountType(result.account_type),
            normal_balance=NormalBalance(result.normal_balance),
            parent_account_id=result.parent_account_id,
            parent_account_code=result.parent_account_code,
            level=result.level,
            description=result.description,
            status=AccountStatus(result.status),
            currency_code=result.currency_code,
            is_bank_account=result.is_bank_account,
            is_cash_account=result.is_cash_account,
            is_intercompany=result.is_intercompany,
            is_header=result.is_header,
            is_used_in_transaction=result.is_used_in_transaction,
            is_locked=result.is_locked,
            current_balance=result.current_balance,
            category=result.category,
            budget_control=result.budget_control,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            children=None,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
        return AccountResponseSchema(
            id=account.id,
            account_code=account.account_code,
            account_name=account.account_name,
            account_type=AccountType(account.account_type),
            normal_balance=NormalBalance(account.normal_balance),
            parent_account_id=account.parent_account_id,
            parent_account_code=account.parent_account_code,
            level=account.level,
            description=account.description,
            status=AccountStatus(account.status),
            currency_code=account.currency_code,
            is_bank_account=account.is_bank_account,
            is_cash_account=account.is_cash_account,
            is_intercompany=account.is_intercompany,
            is_header=account.is_header,
            is_used_in_transaction=account.is_used_in_transaction,
            is_locked=account.is_locked,
            current_balance=account.current_balance,
            category=account.category,
            budget_control=account.budget_control,
            created_at=account.created_at,
            updated_at=account.updated_at,
            created_by=account.created_by,
            created_by_name=account.created_by_name,
            version=account.version,
            children=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/accounts/by-code/{account_code}",
    response_model=AccountResponseSchema,
    summary="Get account by account code",
    operation_id="coa_get_account_by_code",
)
async def get_account_by_code(
    account_code: str = Path(..., min_length=3, max_length=20),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountResponseSchema:
    try:
        account = await coa_service.get_account_by_code(account_code, legal_entity_id)
        if not account:
            raise HTTPException(status_code=404, detail=f"Account with code {account_code} not found")
        return AccountResponseSchema(
            id=account.id,
            account_code=account.account_code,
            account_name=account.account_name,
            account_type=AccountType(account.account_type),
            normal_balance=NormalBalance(account.normal_balance),
            parent_account_id=account.parent_account_id,
            parent_account_code=account.parent_account_code,
            level=account.level,
            description=account.description,
            status=AccountStatus(account.status),
            currency_code=account.currency_code,
            is_bank_account=account.is_bank_account,
            is_cash_account=account.is_cash_account,
            is_intercompany=account.is_intercompany,
            is_header=account.is_header,
            is_used_in_transaction=account.is_used_in_transaction,
            is_locked=account.is_locked,
            current_balance=account.current_balance,
            category=account.category,
            budget_control=account.budget_control,
            created_at=account.created_at,
            updated_at=account.updated_at,
            created_by=account.created_by,
            created_by_name=account.created_by_name,
            version=account.version,
            children=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get account by code: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return AccountResponseSchema(**cached)

    try:
        update_dto = AccountUpdateRequest(
            id=account_id,
            account_name=request.account_name,
            description=request.description,
            status=request.status.value if request.status else None,
            parent_account_code=request.parent_account_code,
            currency_code=request.currency_code,
            is_bank_account=request.is_bank_account,
            is_cash_account=request.is_cash_account,
            is_intercompany=request.is_intercompany,
            category=request.category,
            budget_control=request.budget_control,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await coa_service.update_account(update_dto)
        if not result:
            raise HTTPException(status_code=404, detail="Account not found or cannot be updated")
        response = AccountResponseSchema(
            id=result.id,
            account_code=result.account_code,
            account_name=result.account_name,
            account_type=AccountType(result.account_type),
            normal_balance=NormalBalance(result.normal_balance),
            parent_account_id=result.parent_account_id,
            parent_account_code=result.parent_account_code,
            level=result.level,
            description=result.description,
            status=AccountStatus(result.status),
            currency_code=result.currency_code,
            is_bank_account=result.is_bank_account,
            is_cash_account=result.is_cash_account,
            is_intercompany=result.is_intercompany,
            is_header=result.is_header,
            is_used_in_transaction=result.is_used_in_transaction,
            is_locked=result.is_locked,
            current_balance=result.current_balance,
            category=result.category,
            budget_control=result.budget_control,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            children=None,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/accounts/{account_id}",
    response_model=dict[str, str],
    summary="Deactivate/delete account",
    operation_id="coa_deactivate_account",
)
async def deactivate_account(
    account_id: UUID,
    permanent: bool = Query(False, description="Permanent deletion (void)"),
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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        if permanent:
            result = await coa_service.void_account(
                account_id, current_user.user_id, legal_entity_id, reason
            )
            action = "voided"
        else:
            result = await coa_service.deactivate_account(
                account_id, current_user.user_id, legal_entity_id, reason
            )
            action = "deactivated"
        if not result:
            raise HTTPException(status_code=404, detail="Account not found or cannot be deactivated")
        response = {"message": f"Account {result.account_code} {action} successfully"}
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return AccountResponseSchema(**cached)

    try:
        result = await coa_service.activate_account(
            account_id, current_user.user_id, legal_entity_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="Account not found or cannot be activated")
        response = AccountResponseSchema(
            id=result.id,
            account_code=result.account_code,
            account_name=result.account_name,
            account_type=AccountType(result.account_type),
            normal_balance=NormalBalance(result.normal_balance),
            parent_account_id=result.parent_account_id,
            parent_account_code=result.parent_account_code,
            level=result.level,
            description=result.description,
            status=AccountStatus(result.status),
            currency_code=result.currency_code,
            is_bank_account=result.is_bank_account,
            is_cash_account=result.is_cash_account,
            is_intercompany=result.is_intercompany,
            is_header=result.is_header,
            is_used_in_transaction=result.is_used_in_transaction,
            is_locked=result.is_locked,
            current_balance=result.current_balance,
            category=result.category,
            budget_control=result.budget_control,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            children=None,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to activate account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return AccountResponseSchema(**cached)

    try:
        result = await coa_service.lock_account(
            account_id, current_user.user_id, legal_entity_id, reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Account not found")
        response = AccountResponseSchema(
            id=result.id,
            account_code=result.account_code,
            account_name=result.account_name,
            account_type=AccountType(result.account_type),
            normal_balance=NormalBalance(result.normal_balance),
            parent_account_id=result.parent_account_id,
            parent_account_code=result.parent_account_code,
            level=result.level,
            description=result.description,
            status=AccountStatus(result.status),
            currency_code=result.currency_code,
            is_bank_account=result.is_bank_account,
            is_cash_account=result.is_cash_account,
            is_intercompany=result.is_intercompany,
            is_header=result.is_header,
            is_used_in_transaction=result.is_used_in_transaction,
            is_locked=True,
            current_balance=result.current_balance,
            category=result.category,
            budget_control=result.budget_control,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            children=None,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to lock account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return AccountResponseSchema(**cached)

    try:
        result = await coa_service.unlock_account(account_id, current_user.user_id, legal_entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Account not found")
        response = AccountResponseSchema(
            id=result.id,
            account_code=result.account_code,
            account_name=result.account_name,
            account_type=AccountType(result.account_type),
            normal_balance=NormalBalance(result.normal_balance),
            parent_account_id=result.parent_account_id,
            parent_account_code=result.parent_account_code,
            level=result.level,
            description=result.description,
            status=AccountStatus(result.status),
            currency_code=result.currency_code,
            is_bank_account=result.is_bank_account,
            is_cash_account=result.is_cash_account,
            is_intercompany=result.is_intercompany,
            is_header=result.is_header,
            is_used_in_transaction=result.is_used_in_transaction,
            is_locked=False,
            current_balance=result.current_balance,
            category=result.category,
            budget_control=result.budget_control,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            children=None,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unlock account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LIST ACCOUNTS
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
    level: int | None = Query(None, ge=1, le=10, description="Filter by level"),
    search: str | None = Query(None, description="Search in code or name"),
    include_inactive: bool = Query(False, description="Include inactive accounts"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=200, description="Items per page"),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountListResponseSchema:
    try:
        params = AccountQueryParams(
            account_type=account_type.value if account_type else None,
            status=status.value if status else None,
            parent_account_code=parent_account_code,
            is_header=is_header,
            level=level,
            search=search,
            include_inactive=include_inactive,
            legal_entity_id=legal_entity_id,
            page=page,
            page_size=page_size,
        )
        result = await coa_service.list_accounts(params)
        items = [
            AccountResponseSchema(
                id=acc.id,
                account_code=acc.account_code,
                account_name=acc.account_name,
                account_type=AccountType(acc.account_type),
                normal_balance=NormalBalance(acc.normal_balance),
                parent_account_id=acc.parent_account_id,
                parent_account_code=acc.parent_account_code,
                level=acc.level,
                description=acc.description,
                status=AccountStatus(acc.status),
                currency_code=acc.currency_code,
                is_bank_account=acc.is_bank_account,
                is_cash_account=acc.is_cash_account,
                is_intercompany=acc.is_intercompany,
                is_header=acc.is_header,
                is_used_in_transaction=acc.is_used_in_transaction,
                is_locked=acc.is_locked,
                current_balance=acc.current_balance,
                category=acc.category,
                budget_control=acc.budget_control,
                created_at=acc.created_at,
                updated_at=acc.updated_at,
                created_by=acc.created_by,
                created_by_name=acc.created_by_name,
                version=acc.version,
                children=None,
            )
            for acc in result.items
        ]
        return AccountListResponseSchema(
            items=items,
            total=result.total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.exception("Failed to list accounts: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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

        def build_tree(acc) -> AccountResponseSchema:
            return AccountResponseSchema(
                id=acc.id,
                account_code=acc.account_code,
                account_name=acc.account_name,
                account_type=AccountType(acc.account_type),
                normal_balance=NormalBalance(acc.normal_balance),
                parent_account_id=acc.parent_account_id,
                parent_account_code=acc.parent_account_code,
                level=acc.level,
                description=acc.description,
                status=AccountStatus(acc.status),
                currency_code=acc.currency_code,
                is_bank_account=acc.is_bank_account,
                is_cash_account=acc.is_cash_account,
                is_intercompany=acc.is_intercompany,
                is_header=acc.is_header,
                is_used_in_transaction=acc.is_used_in_transaction,
                is_locked=acc.is_locked,
                current_balance=acc.current_balance,
                category=acc.category,
                budget_control=acc.budget_control,
                created_at=acc.created_at,
                updated_at=acc.updated_at,
                created_by=acc.created_by,
                created_by_name=acc.created_by_name,
                version=acc.version,
                children=[build_tree(child) for child in acc.children] if hasattr(acc, "children") else None,
            )

        root_accounts = [build_tree(root) for root in tree.root_accounts]
        flattened = [build_tree(acc) for acc in tree.flattened]

        return AccountTreeResponseSchema(
            root_accounts=root_accounts,
            flattened=flattened,
            total_accounts=len(flattened),
            total_levels=tree.total_levels,
        )
    except Exception as e:
        logger.exception("Failed to get account tree: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ACCOUNT BALANCE & USAGE (FIXED OPERATION ID)
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
        logger.exception("Failed to get account balance: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
        logger.exception("Failed to get account usage: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
        result = await coa_service.validate_account_modification(
            account_id, legal_entity_id, action
        )
        return AccountValidationResultSchema(
            is_valid=result.is_valid,
            errors=result.errors,
            warnings=result.warnings,
            suggestions=result.suggestions,
        )
    except Exception as e:
        logger.exception("Failed to validate account: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/validate-code/{account_code}",
    response_model=AccountValidationResultSchema,
    summary="Validate account code",
    operation_id="coa_validate_account_code",
)
async def validate_account_code(
    account_code: str = Path(..., min_length=3, max_length=20),
    _permission: None = Depends(require_permission("coa:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    coa_service: Any = Depends(get_coa_service),
) -> AccountValidationResultSchema:
    try:
        result = await coa_service.validate_account_code(account_code, legal_entity_id)
        return AccountValidationResultSchema(
            is_valid=result.is_valid,
            errors=result.errors,
            warnings=result.warnings,
            suggestions=result.suggestions,
        )
    except Exception as e:
        logger.exception("Failed to validate account code: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await coa_service.bulk_update_status(
            account_ids=request.account_ids,
            status=request.status.value,
            reason=request.reason,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        response = {
            "total": result.total,
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "failed_ids": [str(fid) for fid in result.failed_ids],
            "errors": result.errors,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except Exception as e:
        logger.exception("Failed to bulk update status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await coa_service.bulk_update_parent(
            account_ids=request.account_ids,
            parent_account_code=request.parent_account_code,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        response = {
            "total": result.total,
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "failed_ids": [str(fid) for fid in result.failed_ids],
            "errors": result.errors,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except Exception as e:
        logger.exception("Failed to bulk update parent: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
            "json": "application/json",
            "csv": "text/csv",
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        extensions = {
            "json": "json",
            "csv": "csv",
            "excel": "xlsx",
        }
        filename = f"coa_export_{legal_entity_id}.{extensions[format]}"
        return Response(
            content=data,
            media_type=media_types[format],
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export COA: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/import",
    response_model=ImportExportResultSchema,
    summary="Import Chart of Accounts",
    operation_id="coa_import",
)
async def import_coa(
    file: UploadFile = File(..., description="COA file (JSON, CSV, or Excel)"),
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
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ImportExportResultSchema(**cached)

    try:
        content = await file.read()
        file_content = content.decode("utf-8") if file.filename.endswith((".json", ".csv")) else content
        result = await coa_service.import_coa(
            legal_entity_id=legal_entity_id,
            file_content=file_content,
            file_format=file.filename.split(".")[-1].lower(),
            mode=mode,
            validate_only=validate_only,
            imported_by=current_user.user_id,
        )
        response = ImportExportResultSchema(
            success=result.success,
            message=result.message,
            imported_count=result.imported_count,
            updated_count=result.updated_count,
            skipped_count=result.skipped_count,
            errors=result.errors,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to import COA: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
        logger.exception("Failed to get account history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


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
                "timestamp": a.timestamp.isoformat(),
                "event_type": a.event_type,
                "event_data": a.event_data,
                "actor_id": str(a.actor_id),
                "actor_name": a.actor_name,
                "version": a.version,
            }
            for a in audit_trail
        ]
    except Exception as e:
        logger.exception("Failed to get account audit trail: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


__all__ = ["router"]