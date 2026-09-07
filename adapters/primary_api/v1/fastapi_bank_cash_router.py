#!/usr/bin/env python3
"""
Module: fastapi_bank_cash_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Bank & Cash:
               rekening bank, transaksi bank, rekonsiliasi bank, buku kas
               (cash book), petty cash fund, transfer antar bank, dan laporan kas.

Method Standards (ERP):
- create_bank_account() / update_bank_account() / delete_bank_account() / get_bank_account()
- activate_bank_account() / deactivate_bank_account() / lock_bank_account() / unlock_bank_account()
- create_transaction() / update_transaction() / delete_transaction() / get_transaction()
- reverse_transaction() / void_transaction()
- create_cash_book() / update_cash_book() / close_cash_book() / reopen_cash_book()
- create_petty_cash() / replenish_petty_cash() / close_petty_cash()
- create_transfer() / approve_transfer() / cancel_transfer()
- reconcile_bank() / close_reconciliation() / reverse_reconciliation()
- import_statement() / export_transactions()
- get_balance() / get_cash_flow() / get_daily_position()
- lock_account() / unlock_account() / archive_account() / restore_account()
- get_account_status() / get_account_history() / get_account_snapshot()
- audit_trail_account() / can_transition_account()
- register_account_event() / get_account_events() / clear_account_events()
- version_account()
"""


from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)
from application.service_layer.service_bank_cash import (
    BankAccountNotFoundError,
    CashBookNotFoundError,
    CreateBankAccountRequest,
    UpdateBankAccountRequest,
)
from domain.shared_value_objects.enums import TransactionType
from infrastructure.database.session_factory_sqlalchemy import get_async_session

# Import port yang dibutuhkan untuk adapter
from ports.primary.bank_cash_repository_port import CashBookRepositoryPort
from ports.primary.report_repository_port import CashFlowRepositoryPort

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


# Global instance
_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class BankAccountType(str, Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    DEPOSIT = "deposit"
    LOAN = "loan"
    CREDIT_CARD = "credit_card"
    PETTY_CASH = "petty_cash"
    CASH_ON_HAND = "cash_on_hand"


class BankAccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    LOCKED = "locked"
    ARCHIVED = "archived"


class TransactionStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    POSTED = "posted"
    # PENTING (fix): sebelumnya enum ini tidak punya COMPLETED / REJECTED,
    # padahal domain/bank_cash/bank_transaction_entity.py:TransactionStatus
    # (yang benar-benar dipakai service_bank_cash.py.record_transaction())
    # menyetel status jadi 'completed' begitu transaksi selesai dibuat.
    # Karena enum ini dipakai sebagai tipe field `status` di
    # BankTransactionResponseSchema, respons apapun dengan status
    # 'completed' selalu gagal validasi Pydantic -> 422/500 padahal data
    # sudah tersimpan benar di database.
    COMPLETED = "completed"
    REJECTED = "rejected"
    CLEARED = "cleared"
    REVERSED = "reversed"
    CANCELLED = "cancelled"
    VOID = "void"
    RECONCILED = "reconciled"


class ReconciliationStatus(str, Enum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CashBookStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    LOCKED = "locked"
    ARCHIVED = "archived"


class PettyCashStatus(str, Enum):
    ACTIVE = "active"
    REIMBURSED = "reimbursed"
    CLOSED = "closed"
    LOCKED = "locked"


class TransferStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PROCESSED = "processed"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REVERSED = "reversed"


# ============================================================================
# PYDANTIC SCHEMAS (tidak diubah)
# ============================================================================

class BankAccountCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_number: str = Field(..., min_length=5, max_length=30)
    account_name: str = Field(..., min_length=3, max_length=200)
    bank_name: str = Field(..., max_length=100)
    bank_code: str = Field(..., max_length=10)
    branch: str | None = Field(None, max_length=100)
    currency_code: str = Field("IDR", min_length=3, max_length=3)
    account_type: BankAccountType = Field(BankAccountType.CHECKING)
    opening_balance: Decimal = Field(0, decimal_places=2)
    opening_balance_date: date = Field(default_factory=date.today)
    gl_account_id: UUID | None = None
    is_active: bool = True
    is_default: bool = False

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Account number is required")
        return v.strip()

    @field_validator("bank_code")
    @classmethod
    def validate_bank_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Bank code is required")
        return v.upper().strip()


class BankAccountUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_name: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None
    currency_code: str | None = None
    account_type: BankAccountType | None = None
    opening_balance_date: date | None = None
    branch: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    gl_account_id: UUID | None = None
    status: BankAccountStatus | None = None


class BankAccountResponseSchema(BaseModel):
    """
    CATATAN: field `bank_address`, `swift_code`, `iban`, `daily_limit`,
    `transaction_limit`, `notes`, `created_by_name`, `updated_by` yang
    sebelumnya ada di schema ini SENGAJA DIHAPUS karena tidak pernah benar-
    benar tersimpan di database (tidak ada kolomnya) — API sebelumnya
    menerima/menampilkan field-field ini tapi datanya selalu hilang diam-
    diam. Kalau field-field ini memang dibutuhkan, perlu migration baru
    untuk menambah kolomnya di tabel `bank_account` dulu.
    """
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    legal_entity_id: UUID | None = None
    account_number: str
    account_name: str
    bank_name: str
    bank_code: str
    branch: str | None = None
    currency_code: str
    account_type: BankAccountType
    current_balance: Decimal
    available_balance: Decimal
    opening_balance: Decimal
    opening_balance_date: date | None
    gl_account_id: UUID | None
    status: BankAccountStatus
    is_active: bool
    is_default: bool
    is_locked: bool = False
    created_at: datetime
    created_by: UUID | None = None
    updated_at: datetime | None = None
    version: int = 1


class BankTransactionCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bank_account_id: UUID
    transaction_date: date = Field(default_factory=date.today)
    transaction_type: TransactionType
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    description: str = Field(..., max_length=500)
    reference_number: str | None = None
    counterparty_account: str | None = None
    counterparty_name: str | None = None
    transfer_to_account_id: UUID | None = None
    post_to_ledger: bool = True
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class BankTransactionUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    description: str | None = None
    reference_number: str | None = None
    notes: str | None = None
    status: TransactionStatus | None = None


class BankTransactionResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transaction_number: str
    bank_account_id: UUID
    bank_account_name: str | None
    transaction_date: date
    transaction_type: TransactionType
    amount: Decimal
    description: str
    reference_number: str | None
    counterparty_account: str | None
    counterparty_name: str | None
    journal_id: UUID | None
    status: TransactionStatus
    reconciled_at: datetime | None = None
    reconciliation_id: UUID | None = None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1
    is_reversed: bool = False
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None


class BankTransactionReverseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason: str = Field(..., min_length=5, max_length=500)
    reversal_date: date = Field(default_factory=date.today)


class BankReconciliationCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bank_account_id: UUID
    statement_date: date
    statement_balance: Decimal = Field(..., decimal_places=2)
    statement_transactions: list[dict[str, Any]]
    auto_match_threshold: Decimal = Field(Decimal(0.01), decimal_places=2)
    notes: str | None = None


class BankReconciliationResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    reconciliation_number: str
    bank_account_id: UUID
    bank_account_name: str | None
    statement_date: date
    statement_balance: Decimal
    book_balance: Decimal
    difference: Decimal
    matched_count: int
    unmatched_book_count: int
    unmatched_statement_count: int
    adjustment_amount: Decimal
    adjustment_journal_id: UUID | None
    status: ReconciliationStatus
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    version: int = 1


class CashBookCreateSchema(BaseModel):
    """CATATAN: `name`, `location`, `custodian_id`, `min_balance`, `max_balance`
    dihapus dari schema ini karena tidak ada kolomnya di tabel `cash_book` --
    menerima field yang datanya selalu hilang diam-diam lebih berbahaya
    daripada tidak menyediakannya sama sekali."""
    model_config = ConfigDict(from_attributes=True)
    currency_code: str = Field("IDR", min_length=3, max_length=3)
    opening_balance: Decimal = Field(0, decimal_places=2)
    opening_balance_date: date = Field(default_factory=date.today)
    gl_cash_account_id: UUID | None = None
    gl_bank_account_id: UUID | None = None


class CashBookResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    legal_entity_id: UUID
    currency_code: str
    current_balance: Decimal
    opening_balance: Decimal
    opening_balance_date: date
    gl_cash_account_id: UUID | None
    gl_bank_account_id: UUID | None
    is_closed: bool = False
    created_at: datetime
    created_by: UUID | None = None
    updated_at: datetime
    version: int = 1


class CashBookUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    gl_cash_account_id: UUID | None = None
    gl_bank_account_id: UUID | None = None


class CashTransactionCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    cash_book_id: UUID
    transaction_date: date = Field(default_factory=date.today)
    transaction_type: TransactionType
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    description: str = Field(..., max_length=500)
    reference_number: str | None = None
    counterparty_name: str | None = None
    post_to_ledger: bool = True
    notes: str | None = None


class CashTransactionResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transaction_number: str
    cash_book_id: UUID
    cash_book_name: str | None
    transaction_date: date
    transaction_type: TransactionType
    amount: Decimal
    description: str
    reference_number: str | None
    counterparty_name: str | None
    journal_id: UUID | None
    status: TransactionStatus
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1
    is_reversed: bool = False


class PettyCashCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    fund_name: str = Field(..., min_length=3, max_length=100)
    currency_code: str = Field("IDR", min_length=3, max_length=3)
    initial_amount: Decimal = Field(..., gt=0, decimal_places=2)
    custodian_id: UUID
    gl_petty_cash_account_id: UUID
    reimbursement_threshold: Decimal = Field(Decimal(1000000), gt=0, decimal_places=2)
    fund_location: str | None = None
    notes: str | None = None


class PettyCashResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    fund_name: str
    currency_code: str
    current_balance: Decimal
    initial_amount: Decimal
    custodian_id: UUID
    custodian_name: str | None
    gl_account_id: UUID
    reimbursement_threshold: Decimal
    status: PettyCashStatus
    fund_location: str | None
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class PettyCashReimbursementSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reimbursement_date: date = Field(default_factory=date.today)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    bank_account_id: UUID
    description: str = Field(..., max_length=500)
    notes: str | None = None


class BankTransferCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_bank_account_id: UUID
    to_bank_account_id: UUID
    transfer_date: date = Field(default_factory=date.today)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    description: str = Field(..., max_length=500)
    reference_number: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_accounts(self) -> BankTransferCreateSchema:
        if self.from_bank_account_id == self.to_bank_account_id:
            raise ValueError("Source and destination accounts must be different")
        return self


class BankTransferResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transfer_number: str
    from_account_id: UUID
    from_account_name: str | None
    to_account_id: UUID
    to_account_name: str | None
    transfer_date: date
    amount: Decimal
    description: str
    reference_number: str | None
    notes: str | None
    status: TransferStatus
    from_journal_id: UUID | None
    to_journal_id: UUID | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    processed_at: datetime | None = None
    version: int = 1


class BankTransferApproveSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    approved: bool
    notes: str | None = None


class CashFlowReportSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    legal_entity_id: UUID
    start_date: date
    end_date: date
    beginning_cash: Decimal
    cash_receipts: Decimal
    cash_disbursements: Decimal
    net_cash_flow: Decimal
    ending_cash: Decimal
    by_category: dict[str, Decimal]
    generated_at: datetime


class DailyCashPositionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    as_of_date: date
    account_type: str
    account_id: UUID
    account_name: str
    currency: str
    balance: Decimal


class AccountBalanceHistorySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    as_of_date: date
    balance: Decimal
    available_balance: Decimal
    change_from_previous: Decimal


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_bank_cash_service(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    from application.service_layer.service_bank_cash import BankCashService

    container = request.app.state.container
    svc = await container.resolve_async(BankCashService)
    svc._bank_repo.session = session
    return svc


async def get_bank_reconciliation_use_case(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    from application.use_cases.bank_reconciliation import BankReconciliationUseCase

    container = request.app.state.container
    svc = await container.resolve_async(BankReconciliationUseCase)
    if hasattr(svc, '_bank_repo'):
        svc._bank_repo.session = session
    return svc


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/bank-cash", tags=["Bank & Cash"])


# ----------------------------------------------------------------------------
# SYNCHRONOUS HEALTH CHECKS
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "service": "bank-cash-router"}

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    return {"version": "1.0", "name": "Bank & Cash Router"}


# ----------------------------------------------------------------------------
# BANK ACCOUNT CRUD OPERATIONS
# ----------------------------------------------------------------------------

@router.post(
    "/bank-accounts",
    response_model=BankAccountResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create bank account",
    operation_id="create_bank_account",
)
async def create_bank_account(
    request: BankAccountCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("bank:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankAccountResponseSchema:
    method_name = "create_bank_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BankAccountResponseSchema(**cached)

    try:
        result = await service.create_bank_account(
            request=CreateBankAccountRequest(
                legal_entity_id=legal_entity_id,
                account_name=request.account_name,
                account_number=request.account_number,
                bank_name=request.bank_name,
                bank_code=request.bank_code,
                branch=request.branch,
                currency_code=request.currency_code,
                account_type=request.account_type.value,
                opening_balance=request.opening_balance,
                opening_balance_date=request.opening_balance_date,
                gl_account_id=request.gl_account_id,
                is_active=request.is_active,
                is_default=request.is_default,
            ),
            user_id=current_user.user_id,
        )

        response = BankAccountResponseSchema.model_validate(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create bank account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/bank-accounts",
    response_model=list[BankAccountResponseSchema],
    summary="List bank accounts",
    operation_id="list_bank_accounts",
)
async def list_bank_accounts(
    account_type: BankAccountType | None = Query(None),
    currency: str | None = Query(None, min_length=3, max_length=3),
    is_active: bool | None = Query(True),
    _permission: None = Depends(require_permission("bank:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[BankAccountResponseSchema]:
    try:
        accounts = await service.list_bank_accounts(
            legal_entity_id=legal_entity_id,
            account_type=account_type.value if account_type else None,
            currency=currency,
            is_active=is_active,
        )
        return [BankAccountResponseSchema.model_validate(a) for a in accounts]
    except Exception as e:
        logger.exception(f"Failed to list bank accounts: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/bank-accounts/{account_id}",
    response_model=BankAccountResponseSchema,
    summary="Get bank account by ID",
    operation_id="get_bank_account",
)
async def get_bank_account(
    account_id: UUID,
    _permission: None = Depends(require_permission("bank:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankAccountResponseSchema:
    try:
        account = await service.get_bank_account(account_id)
        return BankAccountResponseSchema.model_validate(account)
    except BankAccountNotFoundError:
        raise HTTPException(status_code=404, detail="Bank account not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get bank account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/bank-accounts/{account_id}",
    response_model=BankAccountResponseSchema,
    summary="Update bank account",
    operation_id="update_bank_account",
)
async def update_bank_account(
    account_id: UUID,
    request: BankAccountUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("bank:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankAccountResponseSchema:
    method_name = "update_bank_account"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BankAccountResponseSchema(**cached)

    try:
        result = await service.update_bank_account(
            account_id=account_id,
            request=UpdateBankAccountRequest(
                account_name=request.account_name,
                bank_name=request.bank_name,
                bank_code=request.bank_code,
                currency_code=request.currency_code,
                account_type=request.account_type.value if request.account_type else None,
                opening_balance_date=request.opening_balance_date,
                branch=request.branch,
                is_active=request.is_active,
                is_default=request.is_default,
                gl_account_id=request.gl_account_id,
                status=request.status.value if request.status else None,
            ),
            user_id=current_user.user_id,
        )

        response = BankAccountResponseSchema.model_validate(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except BankAccountNotFoundError:
        raise HTTPException(status_code=404, detail="Bank account not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to update bank account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/bank-accounts/{account_id}",
    response_model=dict[str, Any],
    summary="Deactivate/close bank account",
    operation_id="deactivate_bank_account",
)
async def deactivate_bank_account(
    account_id: UUID,
    permanent: bool = Query(False),
    reason: str = Query(""),
    _permission: None = Depends(require_permission("bank:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> dict[str, Any]:
    try:
        if permanent:
            result = await service.close_bank_account(
                account_id, reason, current_user.user_id
            )
            action = "closed"
        else:
            result = await service.deactivate_bank_account(
                account_id, current_user.user_id, reason
            )
            action = "deactivated"
        return {
            "account_id": str(account_id),
            "account_number": result.account_number,
            "action": action,
            "status": result.status,
            "message": f"Bank account {action} successfully",
        }
    except BankAccountNotFoundError:
        raise HTTPException(status_code=404, detail="Bank account not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to deactivate bank account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/bank-accounts/{account_id}/activate",
    response_model=BankAccountResponseSchema,
    summary="Activate bank account",
    operation_id="activate_bank_account",
)
async def activate_bank_account(
    account_id: UUID,
    _permission: None = Depends(require_permission("bank:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankAccountResponseSchema:
    try:
        result = await service.activate_bank_account(
            account_id, current_user.user_id
        )
        return BankAccountResponseSchema.model_validate(result)
    except BankAccountNotFoundError:
        raise HTTPException(status_code=404, detail="Bank account not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to activate bank account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/bank-accounts/{account_id}/lock",
    response_model=BankAccountResponseSchema,
    summary="Lock bank account",
    operation_id="lock_bank_account",
)
async def lock_bank_account(
    account_id: UUID,
    reason: str = Query(""),
    _permission: None = Depends(require_permission("bank:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankAccountResponseSchema:
    try:
        result = await service.block_bank_account(
            account_id, reason, current_user.user_id
        )
        return BankAccountResponseSchema.model_validate(result)
    except BankAccountNotFoundError:
        raise HTTPException(status_code=404, detail="Bank account not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to lock bank account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/bank-accounts/{account_id}/unlock",
    response_model=BankAccountResponseSchema,
    summary="Unlock bank account",
    operation_id="unlock_bank_account",
)
async def unlock_bank_account(
    account_id: UUID,
    _permission: None = Depends(require_permission("bank:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankAccountResponseSchema:
    try:
        result = await service.unlock_bank_account(
            account_id, current_user.user_id
        )
        return BankAccountResponseSchema.model_validate(result)
    except BankAccountNotFoundError:
        raise HTTPException(status_code=404, detail="Bank account not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to unlock bank account: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BANK TRANSACTIONS
# ----------------------------------------------------------------------------

@router.post(
    "/transactions",
    response_model=BankTransactionResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create manual bank transaction",
    operation_id="create_bank_transaction",
)
async def create_bank_transaction(
    request: BankTransactionCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("bank:transaction")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankTransactionResponseSchema:
    method_name = "create_bank_transaction"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BankTransactionResponseSchema(**cached)

    try:
        result = await service.create_transaction(
            legal_entity_id=legal_entity_id,
            bank_account_id=request.bank_account_id,
            transaction_date=request.transaction_date,
            transaction_type=request.transaction_type.value,
            amount=request.amount,
            description=request.description,
            reference_number=request.reference_number,
            counterparty_account=request.counterparty_account,
            counterparty_name=request.counterparty_name,
            transfer_to_account_id=request.transfer_to_account_id,
            post_to_ledger=request.post_to_ledger,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = BankTransactionResponseSchema(
            id=result.id,
            transaction_number=result.transaction_number,
            bank_account_id=result.bank_account_id,
            bank_account_name=result.bank_account_name,
            transaction_date=result.transaction_date,
            transaction_type=TransactionType(result.transaction_type),
            amount=result.amount,
            description=result.description,
            reference_number=result.reference_number,
            counterparty_account=result.counterparty_account,
            counterparty_name=result.counterparty_name,
            journal_id=result.journal_id,
            status=TransactionStatus(result.status),
            reconciled_at=result.reconciled_at,
            reconciliation_id=result.reconciliation_id,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_reversed=result.is_reversed,
            reversed_at=result.reversed_at,
            reversed_by=result.reversed_by,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create bank transaction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/transactions/{transaction_id}",
    response_model=BankTransactionResponseSchema,
    summary="Get bank transaction by ID",
    operation_id="get_bank_transaction",
)
async def get_bank_transaction(
    transaction_id: UUID,
    _permission: None = Depends(require_permission("bank:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankTransactionResponseSchema:
    try:
        transaction = await service.get_transaction(transaction_id, legal_entity_id)
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return BankTransactionResponseSchema(
            id=transaction.id,
            transaction_number=transaction.transaction_number,
            bank_account_id=transaction.bank_account_id,
            bank_account_name=transaction.bank_account_name,
            transaction_date=transaction.transaction_date,
            transaction_type=TransactionType(transaction.transaction_type),
            amount=transaction.amount,
            description=transaction.description,
            reference_number=transaction.reference_number,
            counterparty_account=transaction.counterparty_account,
            counterparty_name=transaction.counterparty_name,
            journal_id=transaction.journal_id,
            status=TransactionStatus(transaction.status),
            reconciled_at=transaction.reconciled_at,
            reconciliation_id=transaction.reconciliation_id,
            created_at=transaction.created_at,
            created_by=transaction.created_by,
            created_by_name=transaction.created_by_name,
            version=transaction.version,
            is_reversed=transaction.is_reversed,
            reversed_at=transaction.reversed_at,
            reversed_by=transaction.reversed_by,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get bank transaction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/transactions/{transaction_id}",
    response_model=BankTransactionResponseSchema,
    summary="Update bank transaction",
    operation_id="update_bank_transaction",
)
async def update_bank_transaction(
    transaction_id: UUID,
    request: BankTransactionUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("bank:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankTransactionResponseSchema:
    method_name = "update_bank_transaction"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BankTransactionResponseSchema(**cached)

    try:
        result = await service.update_transaction(
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            description=request.description,
            reference_number=request.reference_number,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Transaction not found or cannot be updated")
        response = BankTransactionResponseSchema(
            id=result.id,
            transaction_number=result.transaction_number,
            bank_account_id=result.bank_account_id,
            bank_account_name=result.bank_account_name,
            transaction_date=result.transaction_date,
            transaction_type=TransactionType(result.transaction_type),
            amount=result.amount,
            description=result.description,
            reference_number=result.reference_number,
            counterparty_account=result.counterparty_account,
            counterparty_name=result.counterparty_name,
            journal_id=result.journal_id,
            status=TransactionStatus(result.status),
            reconciled_at=result.reconciled_at,
            reconciliation_id=result.reconciliation_id,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_reversed=result.is_reversed,
            reversed_at=result.reversed_at,
            reversed_by=result.reversed_by,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update bank transaction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/transactions/{transaction_id}/reverse",
    response_model=BankTransactionResponseSchema,
    summary="Reverse a transaction",
    operation_id="reverse_bank_transaction",
)
async def reverse_bank_transaction(
    transaction_id: UUID,
    request: BankTransactionReverseSchema,
    _permission: None = Depends(require_permission("bank:reverse")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankTransactionResponseSchema:
    try:
        result = await service.reverse_transaction(
            transaction_id=transaction_id,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=request.reason,
            reversal_date=request.reversal_date,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Transaction not found or cannot be reversed")
        return BankTransactionResponseSchema(
            id=result.id,
            transaction_number=result.transaction_number,
            bank_account_id=result.bank_account_id,
            bank_account_name=result.bank_account_name,
            transaction_date=result.transaction_date,
            transaction_type=TransactionType(result.transaction_type),
            amount=result.amount,
            description=result.description,
            reference_number=result.reference_number,
            counterparty_account=result.counterparty_account,
            counterparty_name=result.counterparty_name,
            journal_id=result.journal_id,
            status=TransactionStatus(result.status),
            reconciled_at=result.reconciled_at,
            reconciliation_id=result.reconciliation_id,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_reversed=True,
            reversed_at=result.reversed_at,
            reversed_by=result.reversed_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reverse bank transaction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/transactions",
    response_model=list[BankTransactionResponseSchema],
    summary="List bank transactions",
    operation_id="list_bank_transactions",
)
async def list_bank_transactions(
    bank_account_id: UUID | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    transaction_type: TransactionType | None = Query(None),
    status: TransactionStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("bank:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[BankTransactionResponseSchema]:
    try:
        transactions = await service.list_transactions(
            legal_entity_id=legal_entity_id,
            bank_account_id=bank_account_id,
            start_date=start_date,
            end_date=end_date,
            transaction_type=transaction_type.value if transaction_type else None,
            status=status.value if status else None,
            page=page,
            page_size=page_size,
        )
        return [
            BankTransactionResponseSchema(
                id=t.id,
                transaction_number=t.transaction_number,
                bank_account_id=t.bank_account_id,
                bank_account_name=t.bank_account_name,
                transaction_date=t.transaction_date,
                transaction_type=TransactionType(t.transaction_type),
                amount=t.amount,
                description=t.description,
                reference_number=t.reference_number,
                counterparty_account=t.counterparty_account,
                counterparty_name=t.counterparty_name,
                journal_id=t.journal_id,
                status=TransactionStatus(t.status),
                reconciled_at=t.reconciled_at,
                reconciliation_id=t.reconciliation_id,
                created_at=t.created_at,
                created_by=t.created_by,
                created_by_name=t.created_by_name,
                version=t.version,
                is_reversed=t.is_reversed,
                reversed_at=t.reversed_at,
                reversed_by=t.reversed_by,
            )
            for t in transactions
        ]
    except Exception as e:
        logger.exception(f"Failed to list bank transactions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BANK STATEMENT IMPORT
# ----------------------------------------------------------------------------

@router.post(
    "/import-statement",
    response_model=dict[str, Any],
    summary="Import bank statement file",
    operation_id="import_bank_statement",
)
async def import_bank_statement(
    file: UploadFile = File(...),
    bank_account_id: UUID = Form(...),
    statement_date: date = Form(...),
    file_format: str = Form("mt940"),
    _permission: None = Depends(require_permission("bank:import")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> dict[str, Any]:
    try:
        content = await file.read()
        text_content = content.decode("utf-8", errors="replace")
        result = await service.import_bank_statement(
            legal_entity_id=legal_entity_id,
            bank_account_id=bank_account_id,
            statement_date=statement_date,
            file_content=text_content,
            file_format=file_format,
            imported_by=current_user.user_id,
        )
        return {
            "message": f"Imported {result.imported_count} transactions",
            "imported_count": result.imported_count,
            "skipped_count": result.skipped_count,
            "errors": result.errors,
            "bank_account_id": str(bank_account_id),
            "statement_date": statement_date.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to import bank statement: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BANK RECONCILIATION
# ----------------------------------------------------------------------------

@router.post(
    "/reconciliations",
    response_model=BankReconciliationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Perform bank reconciliation",
    operation_id="reconcile_bank",
)
async def reconcile_bank(
    request: BankReconciliationCreateSchema,
    _permission: None = Depends(require_permission("bank:reconcile")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    use_case: Any = Depends(get_bank_reconciliation_use_case),
) -> BankReconciliationResponseSchema:
    try:
        result = await use_case.reconcile(
            legal_entity_id=legal_entity_id,
            bank_account_id=request.bank_account_id,
            statement_date=request.statement_date,
            statement_balance=request.statement_balance,
            statement_transactions=request.statement_transactions,
            auto_match_threshold=request.auto_match_threshold,
            notes=request.notes,
            reconciled_by=current_user.user_id,
        )
        return BankReconciliationResponseSchema(
            id=result.id,
            reconciliation_number=result.reconciliation_number,
            bank_account_id=result.bank_account_id,
            bank_account_name=result.bank_account_name,
            statement_date=result.statement_date,
            statement_balance=result.statement_balance,
            book_balance=result.book_balance,
            difference=result.difference,
            matched_count=result.matched_count,
            unmatched_book_count=result.unmatched_book_count,
            unmatched_statement_count=result.unmatched_statement_count,
            adjustment_amount=result.adjustment_amount,
            adjustment_journal_id=result.adjustment_journal_id,
            status=ReconciliationStatus(result.status),
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reconcile bank: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/reconciliations/{bank_account_id}",
    response_model=list[BankReconciliationResponseSchema],
    summary="Get reconciliation history",
    operation_id="get_reconciliation_history",
)
async def get_reconciliation_history(
    bank_account_id: UUID,
    limit: int = Query(12, ge=1, le=100),
    _permission: None = Depends(require_permission("bank:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[BankReconciliationResponseSchema]:
    try:
        reconciliations = await service.get_reconciliation_history(
            bank_account_id=bank_account_id,
            legal_entity_id=legal_entity_id,
            limit=limit,
        )
        return [
            BankReconciliationResponseSchema(
                id=r.id,
                reconciliation_number=r.reconciliation_number,
                bank_account_id=r.bank_account_id,
                bank_account_name=r.bank_account_name,
                statement_date=r.statement_date,
                statement_balance=r.statement_balance,
                book_balance=r.book_balance,
                difference=r.difference,
                matched_count=r.matched_count,
                unmatched_book_count=r.unmatched_book_count,
                unmatched_statement_count=r.unmatched_statement_count,
                adjustment_amount=r.adjustment_amount,
                adjustment_journal_id=r.adjustment_journal_id,
                status=ReconciliationStatus(r.status),
                notes=r.notes,
                created_at=r.created_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                completed_at=r.completed_at,
                completed_by=r.completed_by,
                version=r.version,
            )
            for r in reconciliations
        ]
    except Exception as e:
        logger.exception(f"Failed to get reconciliation history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/reconciliations/{reconciliation_id}/close",
    response_model=BankReconciliationResponseSchema,
    summary="Close reconciliation",
    operation_id="close_reconciliation",
)
async def close_reconciliation(
    reconciliation_id: UUID,
    _permission: None = Depends(require_permission("bank:reconcile")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankReconciliationResponseSchema:
    try:
        result = await service.close_reconciliation(
            reconciliation_id=reconciliation_id,
            legal_entity_id=legal_entity_id,
            closed_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Reconciliation not found")
        return BankReconciliationResponseSchema(
            id=result.id,
            reconciliation_number=result.reconciliation_number,
            bank_account_id=result.bank_account_id,
            bank_account_name=result.bank_account_name,
            statement_date=result.statement_date,
            statement_balance=result.statement_balance,
            book_balance=result.book_balance,
            difference=result.difference,
            matched_count=result.matched_count,
            unmatched_book_count=result.unmatched_book_count,
            unmatched_statement_count=result.unmatched_statement_count,
            adjustment_amount=result.adjustment_amount,
            adjustment_journal_id=result.adjustment_journal_id,
            status=ReconciliationStatus(result.status),
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to close reconciliation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CASH BOOK (BUKU KAS)
# ----------------------------------------------------------------------------

@router.post(
    "/cash-books",
    response_model=CashBookResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create cash book",
    operation_id="create_cash_book",
)
async def create_cash_book(
    request: CashBookCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("cash:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> CashBookResponseSchema:
    method_name = "create_cash_book"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return CashBookResponseSchema(**cached)

    try:
        result = await service.create_cash_book(
            legal_entity_id=legal_entity_id,
            currency_code=request.currency_code,
            opening_balance=request.opening_balance,
            opening_balance_date=request.opening_balance_date,
            gl_cash_account_id=request.gl_cash_account_id,
            gl_bank_account_id=request.gl_bank_account_id,
            user_id=current_user.user_id,
        )
        response = CashBookResponseSchema.model_validate(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create cash book: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/cash-books",
    response_model=list[CashBookResponseSchema],
    summary="List cash books",
    operation_id="list_cash_books",
)
async def list_cash_books(
    status: CashBookStatus | None = Query(None),
    custodian_id: UUID | None = Query(None),
    _permission: None = Depends(require_permission("cash:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[CashBookResponseSchema]:
    try:
        cash_books = await service.list_cash_books(
            legal_entity_id=legal_entity_id,
            status=status.value if status else None,
            custodian_id=custodian_id,
        )
        return [CashBookResponseSchema.model_validate(cb) for cb in cash_books]
    except Exception as e:
        logger.exception(f"Failed to list cash books: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/cash-books/{cash_book_id}",
    response_model=CashBookResponseSchema,
    summary="Get cash book by ID",
    operation_id="get_cash_book_by_id",
)
async def get_cash_book_by_id(
    cash_book_id: UUID,
    _permission: None = Depends(require_permission("cash:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> CashBookResponseSchema:
    try:
        cash_book = await service.get_cash_book_by_id(cash_book_id)
        if not cash_book:
            raise HTTPException(status_code=404, detail="Cash book not found")
        return CashBookResponseSchema.model_validate(cash_book)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get cash book: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/cash-books/by-currency",
    response_model=list[CashBookResponseSchema],
    summary="Get cash books by currency",
    operation_id="get_cash_books_by_currency",
)
async def get_cash_books_by_currency(
    currency_code: str = Query(..., min_length=3, max_length=3),
    _permission: None = Depends(require_permission("cash:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[CashBookResponseSchema]:
    try:
        cash_books = await service.get_cash_books_by_currency(legal_entity_id, currency_code)
        return [CashBookResponseSchema.model_validate(cb) for cb in cash_books]
    except Exception as e:
        logger.exception(f"Failed to get cash books by currency: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/cash-books/{cash_book_id}/transactions",
    response_model=list[CashTransactionResponseSchema],
    summary="Get transactions of a cash book",
    operation_id="get_cash_book_transactions",
)
async def get_cash_book_transactions(
    cash_book_id: UUID,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _permission: None = Depends(require_permission("cash:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[CashTransactionResponseSchema]:
    try:
        transactions = await service.get_cash_book_transactions(
            cash_book_id=cash_book_id,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        return [
            CashTransactionResponseSchema(
                id=t.id,
                transaction_number=t.transaction_number,
                cash_book_id=t.cash_book_id,
                cash_book_name=t.cash_book_name,
                transaction_date=t.transaction_date,
                transaction_type=TransactionType(t.transaction_type),
                amount=t.amount,
                description=t.description,
                reference_number=t.reference_number,
                counterparty_name=t.counterparty_name,
                journal_id=t.journal_id,
                status=TransactionStatus(t.status),
                created_at=t.created_at,
                created_by=t.created_by,
                created_by_name=t.created_by_name,
                version=t.version,
                is_reversed=t.is_reversed,
            )
            for t in transactions
        ]
    except Exception as e:
        logger.exception(f"Failed to get cash book transactions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/cash-books/{cash_book_id}",
    response_model=CashBookResponseSchema,
    summary="Update cash book",
    operation_id="update_cash_book",
)
async def update_cash_book(
    cash_book_id: UUID,
    request: CashBookUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("cash:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> CashBookResponseSchema:
    method_name = "update_cash_book"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return CashBookResponseSchema(**cached)

    try:
        result = await service.update_cash_book(
            cash_book_id=cash_book_id,
            gl_cash_account_id=request.gl_cash_account_id,
            gl_bank_account_id=request.gl_bank_account_id,
            user_id=current_user.user_id,
        )
        response = CashBookResponseSchema.model_validate(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except CashBookNotFoundError:
        raise HTTPException(status_code=404, detail="Cash book not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update cash book: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/cash-books/{cash_book_id}/balance",
    response_model=Decimal,
    summary="Get current balance of cash book",
    operation_id="get_cash_book_balance",
)
async def get_cash_book_balance(
    cash_book_id: UUID,
    as_of_date: date = Query(default_factory=date.today),
    _permission: None = Depends(require_permission("cash:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> Decimal:
    try:
        balance = await service.get_cash_book_balance(cash_book_id, legal_entity_id, as_of_date)
        if balance is None:
            raise HTTPException(status_code=404, detail="Cash book not found")
        return balance
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get cash book balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/cash-transactions",
    response_model=CashTransactionResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record cash transaction",
    operation_id="record_cash_transaction",
)
async def record_cash_transaction(
    request: CashTransactionCreateSchema,
    _permission: None = Depends(require_permission("cash:transaction")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> CashTransactionResponseSchema:
    try:
        result = await service.record_cash_transaction(
            legal_entity_id=legal_entity_id,
            cash_book_id=request.cash_book_id,
            transaction_date=request.transaction_date,
            transaction_type=request.transaction_type.value,
            amount=request.amount,
            description=request.description,
            reference_number=request.reference_number,
            counterparty_name=request.counterparty_name,
            post_to_ledger=request.post_to_ledger,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        return CashTransactionResponseSchema(
            id=result.id,
            transaction_number=result.transaction_number,
            cash_book_id=result.cash_book_id,
            cash_book_name=result.cash_book_name,
            transaction_date=result.transaction_date,
            transaction_type=TransactionType(result.transaction_type),
            amount=result.amount,
            description=result.description,
            reference_number=result.reference_number,
            counterparty_name=result.counterparty_name,
            journal_id=result.journal_id,
            status=TransactionStatus(result.status),
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_reversed=result.is_reversed,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to record cash transaction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PETTY CASH FUND (KAS KECIL)
# ----------------------------------------------------------------------------

@router.post(
    "/petty-cash",
    response_model=PettyCashResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create petty cash fund",
    operation_id="create_petty_cash_fund",
)
async def create_petty_cash_fund(
    request: PettyCashCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("cash:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> PettyCashResponseSchema:
    method_name = "create_petty_cash_fund"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return PettyCashResponseSchema(**cached)

    try:
        result = await service.create_petty_cash_fund(
            legal_entity_id=legal_entity_id,
            fund_name=request.fund_name,
            currency_code=request.currency_code,
            initial_amount=request.initial_amount,
            custodian_id=request.custodian_id,
            gl_petty_cash_account_id=request.gl_petty_cash_account_id,
            reimbursement_threshold=request.reimbursement_threshold,
            fund_location=request.fund_location,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = PettyCashResponseSchema(
            id=result.id,
            fund_name=result.fund_name,
            currency_code=result.currency_code,
            current_balance=result.current_balance,
            initial_amount=result.initial_amount,
            custodian_id=result.custodian_id,
            custodian_name=result.custodian_name,
            gl_account_id=result.gl_account_id,
            reimbursement_threshold=result.reimbursement_threshold,
            status=PettyCashStatus(result.status),
            fund_location=result.fund_location,
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
        logger.exception(f"Failed to create petty cash fund: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/petty-cash/{fund_id}/reimburse",
    response_model=PettyCashResponseSchema,
    summary="Reimburse petty cash",
    operation_id="reimburse_petty_cash",
)
async def reimburse_petty_cash(
    fund_id: UUID,
    request: PettyCashReimbursementSchema,
    _permission: None = Depends(require_permission("cash:transaction")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> PettyCashResponseSchema:
    try:
        result = await service.reimburse_petty_cash(
            fund_id=fund_id,
            legal_entity_id=legal_entity_id,
            reimbursement_date=request.reimbursement_date,
            amount=request.amount,
            bank_account_id=request.bank_account_id,
            description=request.description,
            notes=request.notes,
            reimbursed_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Petty cash fund not found")
        return PettyCashResponseSchema(
            id=result.id,
            fund_name=result.fund_name,
            currency_code=result.currency_code,
            current_balance=result.current_balance,
            initial_amount=result.initial_amount,
            custodian_id=result.custodian_id,
            custodian_name=result.custodian_name,
            gl_account_id=result.gl_account_id,
            reimbursement_threshold=result.reimbursement_threshold,
            status=PettyCashStatus(result.status),
            fund_location=result.fund_location,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reimburse petty cash: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BANK TRANSFER (INTERNAL)
# ----------------------------------------------------------------------------

@router.post(
    "/transfers",
    response_model=BankTransferResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create internal bank transfer",
    operation_id="create_bank_transfer",
)
async def create_bank_transfer(
    request: BankTransferCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("bank:transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankTransferResponseSchema:
    method_name = "create_bank_transfer"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BankTransferResponseSchema(**cached)

    try:
        result = await service.create_internal_transfer(
            legal_entity_id=legal_entity_id,
            from_bank_account_id=request.from_bank_account_id,
            to_bank_account_id=request.to_bank_account_id,
            transfer_date=request.transfer_date,
            amount=request.amount,
            description=request.description,
            reference_number=request.reference_number,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = BankTransferResponseSchema(
            id=result.id,
            transfer_number=result.transfer_number,
            from_account_id=result.from_account_id,
            from_account_name=result.from_account_name,
            to_account_id=result.to_account_id,
            to_account_name=result.to_account_name,
            transfer_date=result.transfer_date,
            amount=result.amount,
            description=result.description,
            reference_number=result.reference_number,
            notes=result.notes,
            status=TransferStatus(result.status),
            from_journal_id=result.from_journal_id,
            to_journal_id=result.to_journal_id,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            processed_at=result.processed_at,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create bank transfer: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/transfers/{transfer_id}/approve",
    response_model=BankTransferResponseSchema,
    summary="Approve bank transfer",
    operation_id="approve_bank_transfer",
)
async def approve_bank_transfer(
    transfer_id: UUID,
    request: BankTransferApproveSchema,
    _permission: None = Depends(require_permission("bank:approve_transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankTransferResponseSchema:
    try:
        if request.approved:
            result = await service.approve_transfer(
                transfer_id, legal_entity_id, current_user.user_id, request.notes
            )
        else:
            result = await service.reject_transfer(
                transfer_id, legal_entity_id, current_user.user_id, request.notes
            )
        if not result:
            raise HTTPException(status_code=404, detail="Transfer not found")
        return BankTransferResponseSchema(
            id=result.id,
            transfer_number=result.transfer_number,
            from_account_id=result.from_account_id,
            from_account_name=result.from_account_name,
            to_account_id=result.to_account_id,
            to_account_name=result.to_account_name,
            transfer_date=result.transfer_date,
            amount=result.amount,
            description=result.description,
            reference_number=result.reference_number,
            notes=result.notes,
            status=TransferStatus(result.status),
            from_journal_id=result.from_journal_id,
            to_journal_id=result.to_journal_id,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            processed_at=result.processed_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to approve bank transfer: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/transfers/{transfer_id}/process",
    response_model=BankTransferResponseSchema,
    summary="Process bank transfer",
    operation_id="process_bank_transfer",
)
async def process_bank_transfer(
    transfer_id: UUID,
    _permission: None = Depends(require_permission("bank:process_transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> BankTransferResponseSchema:
    try:
        result = await service.process_transfer(transfer_id, legal_entity_id, current_user.user_id)
        if not result:
            raise HTTPException(status_code=404, detail="Transfer not found")
        return BankTransferResponseSchema(
            id=result.id,
            transfer_number=result.transfer_number,
            from_account_id=result.from_account_id,
            from_account_name=result.from_account_name,
            to_account_id=result.to_account_id,
            to_account_name=result.to_account_name,
            transfer_date=result.transfer_date,
            amount=result.amount,
            description=result.description,
            reference_number=result.reference_number,
            notes=result.notes,
            status=TransferStatus(result.status),
            from_journal_id=result.from_journal_id,
            to_journal_id=result.to_journal_id,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            processed_at=result.processed_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to process bank transfer: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/transfers/{transfer_id}",
    response_model=dict[str, Any],
    summary="Cancel bank transfer",
    operation_id="cancel_bank_transfer",
)
async def cancel_bank_transfer(
    transfer_id: UUID,
    reason: str = Query(""),
    _permission: None = Depends(require_permission("bank:cancel_transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> dict[str, Any]:
    try:
        result = await service.cancel_transfer(
            transfer_id, legal_entity_id, current_user.user_id, reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Transfer not found")
        return {
            "transfer_id": str(transfer_id),
            "transfer_number": result.transfer_number,
            "status": result.status,
            "message": f"Transfer cancelled: {reason}" if reason else "Transfer cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to cancel bank transfer: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REPORTS & DASHBOARD
# ----------------------------------------------------------------------------

@router.get(
    "/balance/{account_id}",
    response_model=Decimal,
    summary="Get current balance of bank account",
    operation_id="get_bank_balance",
)
async def get_bank_balance(
    account_id: UUID,
    as_of_date: date = Query(default_factory=date.today),
    _permission: None = Depends(require_permission("bank:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> Decimal:
    try:
        balance = await service.get_account_balance(account_id, legal_entity_id, as_of_date)
        if balance is None:
            raise HTTPException(status_code=404, detail="Bank account not found")
        return balance
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get bank balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/balance-history/{account_id}",
    response_model=list[AccountBalanceHistorySchema],
    summary="Get balance history of bank account",
    operation_id="get_bank_balance_history",
)
async def get_bank_balance_history(
    account_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    _permission: None = Depends(require_permission("bank:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[AccountBalanceHistorySchema]:
    try:
        history = await service.get_balance_history(
            account_id=account_id,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )
        return [
            AccountBalanceHistorySchema(
                as_of_date=h.as_of_date,
                balance=h.balance,
                available_balance=h.available_balance,
                change_from_previous=h.change_from_previous,
            )
            for h in history
        ]
    except Exception as e:
        logger.exception(f"Failed to get balance history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/cash-flow",
    response_model=CashFlowReportSchema,
    summary="Get cash flow report",
    operation_id="get_cash_flow_report",
)
async def get_cash_flow_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    account_type: BankAccountType | None = Query(None),
    _permission: None = Depends(require_permission("cash:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> CashFlowReportSchema:
    try:
        report = await service.get_cash_flow_report(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            account_type=account_type.value if account_type else None,
        )
        return CashFlowReportSchema(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            beginning_cash=report.beginning_cash,
            cash_receipts=report.cash_receipts,
            cash_disbursements=report.cash_disbursements,
            net_cash_flow=report.net_cash_flow,
            ending_cash=report.ending_cash,
            by_category=report.by_category,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get cash flow report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/daily-position",
    response_model=list[DailyCashPositionSchema],
    summary="Get daily cash position",
    operation_id="get_daily_cash_position",
)
async def get_daily_cash_position(
    as_of_date: date = Query(default_factory=date.today),
    _permission: None = Depends(require_permission("cash:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> list[DailyCashPositionSchema]:
    try:
        positions = await service.get_daily_cash_position(legal_entity_id, as_of_date)
        return [
            DailyCashPositionSchema(
                as_of_date=as_of_date,
                account_type=p.account_type,
                account_id=p.account_id,
                account_name=p.account_name,
                currency=p.currency,
                balance=p.balance,
            )
            for p in positions
        ]
    except Exception as e:
        logger.exception(f"Failed to get daily cash position: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/export",
    summary="Export bank transactions",
    operation_id="export_bank_transactions",
)
async def export_bank_transactions(
    bank_account_id: UUID = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    format: str = Query("csv"),
    _permission: None = Depends(require_permission("bank:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_bank_cash_service),
) -> Response:
    try:
        data = await service.export_transactions(
            bank_account_id=bank_account_id,
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
        filename = f"bank_transactions_{bank_account_id}_{start_date}_{end_date}.{format}"
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export transactions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================================================
# ADAPTER UNTUK CASHBOOKREPOSITORYPORT (tanpa dekorator)
# ============================================================================

class CashBookRepositoryAdapter(CashBookRepositoryPort):
    def __init__(self):
        self._service = None

    async def _get_service(self):
        if self._service is None:
            from application.service_layer.service_bank_cash import BankCashService
            self._service = BankCashService()
        return self._service

    async def add(self, cash_book) -> dict:
        service = await self._get_service()
        result = await service.create_cash_book(
            legal_entity_id=cash_book.get("legal_entity_id"),
            currency_code=cash_book.get("currency_code", "IDR"),
            opening_balance=cash_book.get("opening_balance", 0),
            opening_balance_date=cash_book.get("opening_balance_date", date.today()),
            gl_cash_account_id=cash_book.get("gl_cash_account_id"),
            gl_bank_account_id=cash_book.get("gl_bank_account_id"),
            user_id=cash_book.get("created_by"),
        )
        return {
            "id": result.id,
            "legal_entity_id": result.legal_entity_id,
            "currency_code": result.currency_code,
            "current_balance": result.current_balance,
            "opening_balance": result.opening_balance,
            "opening_balance_date": result.opening_balance_date,
            "gl_cash_account_id": result.gl_cash_account_id,
            "gl_bank_account_id": result.gl_bank_account_id,
            "is_closed": result.is_closed,
            "created_at": result.created_at,
            "created_by": result.created_by,
            "updated_at": result.updated_at,
            "version": result.version,
        }

    async def get_balance(self, cash_book_id: UUID, as_of_date: date | None = None) -> Decimal:
        # Stub, return 0
        return Decimal(0)

    async def get_by_id(self, cash_book_id: UUID) -> dict:
        raise NotImplementedError("get_by_id requires legal_entity_id which is not in the port signature. This adapter is a stub.")

    async def get_by_legal_entity_and_currency(self, legal_entity_id: UUID, currency_code: str) -> list[dict]:
        service = await self._get_service()
        cash_books = await service.get_cash_books_by_currency(legal_entity_id, currency_code)
        return [
            {
                "id": cb.id,
                "legal_entity_id": cb.legal_entity_id,
                "currency_code": cb.currency_code,
                "current_balance": cb.current_balance,
                "opening_balance": cb.opening_balance,
                "opening_balance_date": cb.opening_balance_date,
                "gl_cash_account_id": cb.gl_cash_account_id,
                "gl_bank_account_id": cb.gl_bank_account_id,
                "is_closed": cb.is_closed,
                "created_at": cb.created_at,
                "created_by": cb.created_by,
                "updated_at": cb.updated_at,
                "version": cb.version,
            }
            for cb in cash_books
        ]

    async def get_transactions(self, cash_book_id: UUID, start_date: date | None = None, end_date: date | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        # Stub, return empty
        return []

    async def record_transaction(self, transaction: dict) -> dict:
        service = await self._get_service()
        result = await service.record_cash_transaction(
            legal_entity_id=transaction.get("legal_entity_id"),
            cash_book_id=transaction.get("cash_book_id"),
            transaction_date=transaction.get("transaction_date", date.today()),
            transaction_type=transaction.get("transaction_type"),
            amount=transaction.get("amount"),
            description=transaction.get("description"),
            reference_number=transaction.get("reference_number"),
            counterparty_name=transaction.get("counterparty_name"),
            post_to_ledger=transaction.get("post_to_ledger", True),
            notes=transaction.get("notes"),
            created_by=transaction.get("created_by"),
        )
        return {
            "id": result.id,
            "transaction_number": result.transaction_number,
            "cash_book_id": result.cash_book_id,
            "cash_book_name": result.cash_book_name,
            "transaction_date": result.transaction_date,
            "transaction_type": result.transaction_type,
            "amount": result.amount,
            "description": result.description,
            "reference_number": result.reference_number,
            "counterparty_name": result.counterparty_name,
            "journal_id": result.journal_id,
            "status": result.status,
            "created_at": result.created_at,
            "created_by": result.created_by,
            "created_by_name": result.created_by_name,
            "version": result.version,
            "is_reversed": result.is_reversed,
        }

    async def update(self, cash_book_id: UUID, data: dict, idempotency_key: str | None = None) -> dict:
        """
        Update cash book. Supports idempotency via optional idempotency_key.
        """
        method_name = "cash_book_repository_update"
        if idempotency_key:
            cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
            if cached is not None:
                return cached

        service = await self._get_service()
        result = await service.update_cash_book(
            cash_book_id=cash_book_id,
            gl_cash_account_id=data.get("gl_cash_account_id"),
            gl_bank_account_id=data.get("gl_bank_account_id"),
            user_id=data.get("updated_by"),
        )
        response = {
            "id": result.id,
            "legal_entity_id": result.legal_entity_id,
            "currency_code": result.currency_code,
            "current_balance": result.current_balance,
            "opening_balance": result.opening_balance,
            "opening_balance_date": result.opening_balance_date,
            "gl_cash_account_id": result.gl_cash_account_id,
            "gl_bank_account_id": result.gl_bank_account_id,
            "is_closed": result.is_closed,
            "created_at": result.created_at,
            "created_by": result.created_by,
            "updated_at": result.updated_at,
            "version": result.version,
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response


# ============================================================================
# ADAPTER UNTUK CASHFLOWREPOSITORYPORT (tanpa dekorator)
# ============================================================================

class CashFlowRepositoryAdapter(CashFlowRepositoryPort):
    def __init__(self):
        self._service = None

    async def _get_service(self):
        if self._service is None:
            from application.service_layer.service_bank_cash import BankCashService
            self._service = BankCashService()
        return self._service

    async def get_cash_flow(
        self,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
        account_type: str | None = None,
    ) -> dict:
        service = await self._get_service()
        report = await service.get_cash_flow_report(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            account_type=account_type,
        )
        return {
            "legal_entity_id": legal_entity_id,
            "start_date": start_date,
            "end_date": end_date,
            "beginning_cash": report.beginning_cash,
            "cash_receipts": report.cash_receipts,
            "cash_disbursements": report.cash_disbursements,
            "net_cash_flow": report.net_cash_flow,
            "ending_cash": report.ending_cash,
            "by_category": report.by_category,
            "generated_at": datetime.now(),
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CashBookRepositoryAdapter",
    "CashFlowRepositoryAdapter",
    "router",
]
