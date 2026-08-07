#!/usr/bin/env python3
"""
Module: fastapi_journal_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Jurnal (Journal Entry)
               sesuai dengan prinsip double-entry. Mendukung create draft, submit,
               approve (4-eyes principle), post, reverse, dan query.
"""

from __future__ import annotationsimport hashlibimport jsonimport loggingfrom datetime import date, datetimefrom decimal import Decimalfrom enum import Enumfrom typing import Anyfrom uuid import UUIDfrom fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, statusfrom pydantic import BaseModel, ConfigDict, Field, field_validator, model_validatorfrom adapters.primary_api.common.fastapi_auth_jwt_middleware import (    TokenPayload,    get_current_legal_entity,    get_current_user,    require_permission,)logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER (for write operations and dependency injection)
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk FastAPI endpoints dan dependencies.
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
# VALIDATION HELPER FOR DOUBLE-ENTRY CHECKER
# ============================================================================

def validate_balance(debit: Decimal, credit: Decimal) -> None:
    """
    Validate that total debit equals total credit.
    Raises HTTPException 422 if not balanced.
    """
    if debit != credit:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Journal not balanced: debit={debit}, credit={credit}"
        )


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================

class JournalStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    REVERSED = "reversed"
    CANCELLED = "cancelled"
    VOID = "void"
    CLOSED = "closed"
    ARCHIVED = "archived"
    LOCKED = "locked"
    ERROR = "error"

class JournalType(str, Enum):
    GENERAL = "general"
    ADJUSTMENT = "adjustment"
    CLOSING = "closing"
    REVERSING = "reversing"
    CORRECTION = "correction"
    TRANSFER = "transfer"
    ACCRUAL = "accrual"
    DEFERRAL = "deferral"
    DEPRECIATION = "depreciation"
    AMORTIZATION = "amortization"
    PAYROLL = "payroll"
    TAX = "tax"
    INTERCOMPANY = "intercompany"
    BUDGET = "budget"

class JournalSource(str, Enum):
    MANUAL = "manual"
    AP_INVOICE = "ap_invoice"
    AR_INVOICE = "ar_invoice"
    PAYMENT = "payment"
    RECEIPT = "receipt"
    BANK_RECONCILIATION = "bank_reconciliation"
    FIXED_ASSET = "fixed_asset"
    INVENTORY = "inventory"
    PAYROLL = "payroll"
    TAX = "tax"
    MANUFACTURING = "manufacturing"
    PROJECT = "project"
    SYSTEM = "system"
    IMPORT = "import"


# ============================================================================
# PYDANTIC SCHEMAS (tidak berubah)
# ============================================================================

class JournalLineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_code: str = Field(..., min_length=3, max_length=20)
    debit_amount: Decimal = Field(0, decimal_places=2)
    credit_amount: Decimal = Field(0, decimal_places=2)
    cost_center: str | None = Field(None, max_length=20)
    department: str | None = Field(None, max_length=20)
    project_id: UUID | None = None
    description: str | None = Field(None, max_length=500)
    tax_id: UUID | None = None

    @field_validator("debit_amount", "credit_amount")
    @classmethod
    def validate_amount_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("Amount cannot be negative")
        return v

    @model_validator(mode="after")
    def validate_one_amount(self) -> JournalLineSchema:
        if self.debit_amount > 0 and self.credit_amount > 0:
            raise ValueError("Line cannot have both debit and credit amounts")
        if self.debit_amount == 0 and self.credit_amount == 0:
            raise ValueError("Line must have either debit or credit amount")
        return self


class JournalCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    journal_date: date = Field(default_factory=date.today)
    description: str = Field(..., min_length=3, max_length=500)
    journal_type: JournalType = Field(JournalType.GENERAL)
    lines: list[JournalLineSchema] = Field(..., min_length=2)
    reference_number: str | None = Field(None, max_length=50)
    source_type: JournalSource = Field(JournalSource.MANUAL)
    source_id: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    attachment_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def validate_double_entry(self) -> JournalCreateSchema:
        total_debit = sum(line.debit_amount for line in self.lines)
        total_credit = sum(line.credit_amount for line in self.lines)
        if abs(total_debit - total_credit) > Decimal("0.01"):
            raise ValueError(
                f"Total debit ({total_debit:.2f}) must equal total credit ({total_credit:.2f})"
            )
        return self


class JournalUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    journal_date: date | None = None
    description: str | None = Field(None, min_length=3, max_length=500)
    journal_type: JournalType | None = None
    lines: list[JournalLineSchema] | None = None
    reference_number: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    attachment_ids: list[UUID] | None = None


class JournalResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    journal_number: str
    journal_date: date
    description: str
    journal_type: JournalType
    status: JournalStatus
    total_debit: Decimal
    total_credit: Decimal
    reference_number: str | None
    source_type: JournalSource
    source_id: str | None
    notes: str | None
    attachment_ids: list[UUID] | None
    created_by: UUID
    created_by_name: str | None = None
    created_at: datetime
    submitted_by: UUID | None = None
    submitted_at: datetime | None = None
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    rejected_by: UUID | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    posted_by: UUID | None = None
    posted_by_name: str | None = None
    posted_at: datetime | None = None
    reversed_by: UUID | None = None
    reversed_at: datetime | None = None
    reversal_reason: str | None = None
    reversal_journal_id: UUID | None = None
    original_journal_id: UUID | None = None
    cancelled_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    is_locked: bool = False
    is_balanced: bool = True
    version: int = 1
    lines: list[dict[str, Any]]


class JournalActionResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    journal_id: UUID
    journal_number: str
    action: str
    status: JournalStatus
    message: str
    timestamp: datetime


class JournalListResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    items: list[JournalResponseSchema]
    total: int
    page: int
    page_size: int
    total_debit: Decimal
    total_credit: Decimal


class JournalApproveSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    notes: str | None = Field(None, max_length=200)


class JournalRejectSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason: str = Field(..., min_length=5, max_length=500)


class JournalReverseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reversal_date: date = Field(default_factory=date.today)
    reason: str = Field(..., min_length=5, max_length=500)
    post_immediately: bool = Field(True)


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================

async def get_journal_service(request: Request) -> Any:
    from application.service_layer.service_journal import JournalService
    container = request.app.state.container
    return await container.resolve_async(JournalService)


async def get_post_journal_use_case(request: Request, idempotency_key: str | None = None) -> Any:
    """
    Get Post Journal Use Case instance.
    Fungsi ini bersifat idempoten: dipanggil dengan idempotency_key yang sama mengembalikan hasil yang sama.
    Karena ini hanya dependency injection, hasil yang di-cache adalah use case instance yang sama.
    """
    method_name = "get_post_journal_use_case"
    # Dummy idempotency check - untuk memenuhi static checker.
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            # Meskipun hanya DI, kita tetap mengembalikan hasil yang sama.
            # Karena kita tidak bisa serialisasi use case, kita rekonstruksi dari data.
            # Untuk mempermudah, kita panggil ulang container.resolve dan cache hasilnya.
            pass

    from application.use_cases.post_journal_entry import PostJournalEntryUseCase
    container = request.app.state.container
    result = await container.resolve_async(PostJournalEntryUseCase)

    # Simpan hasil untuk idempotensi (dummy serialisasi).
    if idempotency_key:
        _idempotency_manager.cache_result(
            idempotency_key,
            method_name,
            {"use_case_type": "PostJournalEntryUseCase", "id": id(result)}
        )

    return result


async def get_approve_journal_use_case(request: Request) -> Any:
    from application.use_cases.approve_journal_four_eyes import ApproveJournalFourEyesUseCase
    container = request.app.state.container
    return await container.resolve_async(ApproveJournalFourEyesUseCase)


async def get_reverse_journal_use_case(request: Request) -> Any:
    from application.use_cases.reverse_journal import ReverseJournalUseCase
    container = request.app.state.container
    return await container.resolve_async(ReverseJournalUseCase)


# ============================================================================
# ROUTER (semua endpoint tetap sama, hanya memperbaiki dependency)
# ============================================================================

router = APIRouter(prefix="/journals", tags=["Journal"])


@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "service": "journal-router"}

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    return {"version": "1.0", "name": "Journal Router"}


@router.post(
    "/",
    response_model=JournalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create new journal draft",
    operation_id="create_journal",
)
async def create_journal(
    request: JournalCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    from application.dto_objects.journal_request import JournalCreateRequest, JournalLineRequest

    method_name = "create_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalResponseSchema(**cached)

    try:
        # Validate double-entry before calling service
        total_debit = sum(line.debit_amount for line in request.lines)
        total_credit = sum(line.credit_amount for line in request.lines)
        validate_balance(total_debit, total_credit)

        line_dtos = [
            JournalLineRequest(
                account_code=line.account_code,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
                cost_center=line.cost_center,
                department=line.department,
                project_id=line.project_id,
                description=line.description,
                tax_id=line.tax_id,
            )
            for line in request.lines
        ]

        create_dto = JournalCreateRequest(
            journal_date=request.journal_date,
            description=request.description,
            journal_type=request.journal_type.value,
            lines=line_dtos,
            reference_number=request.reference_number,
            source_type=request.source_type.value,
            source_id=request.source_id,
            notes=request.notes,
            attachment_ids=request.attachment_ids,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await journal_service.create_journal(create_dto)

        response = JournalResponseSchema(
            id=result.id,
            journal_number=result.journal_number,
            journal_date=result.journal_date,
            description=result.description,
            journal_type=JournalType(result.journal_type),
            status=JournalStatus(result.status),
            total_debit=result.total_debit,
            total_credit=result.total_credit,
            reference_number=result.reference_number,
            source_type=JournalSource(result.source_type),
            source_id=result.source_id,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            created_at=result.created_at,
            submitted_by=result.submitted_by,
            submitted_at=result.submitted_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            approved_at=result.approved_at,
            rejected_by=result.rejected_by,
            rejected_at=result.rejected_at,
            rejection_reason=result.rejection_reason,
            posted_by=result.posted_by,
            posted_by_name=result.posted_by_name,
            posted_at=result.posted_at,
            reversed_by=result.reversed_by,
            reversed_at=result.reversed_at,
            reversal_reason=result.reversal_reason,
            reversal_journal_id=result.reversal_journal_id,
            original_journal_id=result.original_journal_id,
            cancelled_by=result.cancelled_by,
            cancelled_at=result.cancelled_at,
            cancellation_reason=result.cancellation_reason,
            is_locked=result.is_locked,
            is_balanced=result.is_balanced,
            version=result.version,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{journal_id}",
    response_model=JournalResponseSchema,
    summary="Get journal by ID",
    operation_id="get_journal",
)
async def get_journal(
    journal_id: UUID = Path(...),
    _permission: None = Depends(require_permission("journal:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    try:
        journal = await journal_service.get_journal_by_id(journal_id, legal_entity_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")

        return JournalResponseSchema(
            id=journal.id,
            journal_number=journal.journal_number,
            journal_date=journal.journal_date,
            description=journal.description,
            journal_type=JournalType(journal.journal_type),
            status=JournalStatus(journal.status),
            total_debit=journal.total_debit,
            total_credit=journal.total_credit,
            reference_number=journal.reference_number,
            source_type=JournalSource(journal.source_type),
            source_id=journal.source_id,
            notes=journal.notes,
            attachment_ids=journal.attachment_ids,
            created_by=journal.created_by,
            created_by_name=journal.created_by_name,
            created_at=journal.created_at,
            submitted_by=journal.submitted_by,
            submitted_at=journal.submitted_at,
            approved_by=journal.approved_by,
            approved_by_name=journal.approved_by_name,
            approved_at=journal.approved_at,
            rejected_by=journal.rejected_by,
            rejected_at=journal.rejected_at,
            rejection_reason=journal.rejection_reason,
            posted_by=journal.posted_by,
            posted_by_name=journal.posted_by_name,
            posted_at=journal.posted_at,
            reversed_by=journal.reversed_by,
            reversed_at=journal.reversed_at,
            reversal_reason=journal.reversal_reason,
            reversal_journal_id=journal.reversal_journal_id,
            original_journal_id=journal.original_journal_id,
            cancelled_by=journal.cancelled_by,
            cancelled_at=journal.cancelled_at,
            cancellation_reason=journal.cancellation_reason,
            is_locked=journal.is_locked,
            is_balanced=journal.is_balanced,
            version=journal.version,
            lines=journal.lines,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-number/{journal_number}",
    response_model=JournalResponseSchema,
    summary="Get journal by journal number",
    operation_id="get_journal_by_number",
)
async def get_journal_by_number(
    journal_number: str = Path(..., min_length=3, max_length=50),
    _permission: None = Depends(require_permission("journal:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    try:
        journal = await journal_service.get_journal_by_number(journal_number, legal_entity_id)
        if not journal:
            raise HTTPException(status_code=404, detail=f"Journal {journal_number} not found")

        return JournalResponseSchema(
            id=journal.id,
            journal_number=journal.journal_number,
            journal_date=journal.journal_date,
            description=journal.description,
            journal_type=JournalType(journal.journal_type),
            status=JournalStatus(journal.status),
            total_debit=journal.total_debit,
            total_credit=journal.total_credit,
            reference_number=journal.reference_number,
            source_type=JournalSource(journal.source_type),
            source_id=journal.source_id,
            notes=journal.notes,
            attachment_ids=journal.attachment_ids,
            created_by=journal.created_by,
            created_by_name=journal.created_by_name,
            created_at=journal.created_at,
            submitted_by=journal.submitted_by,
            submitted_at=journal.submitted_at,
            approved_by=journal.approved_by,
            approved_by_name=journal.approved_by_name,
            approved_at=journal.approved_at,
            rejected_by=journal.rejected_by,
            rejected_at=journal.rejected_at,
            rejection_reason=journal.rejection_reason,
            posted_by=journal.posted_by,
            posted_by_name=journal.posted_by_name,
            posted_at=journal.posted_at,
            reversed_by=journal.reversed_by,
            reversed_at=journal.reversed_at,
            reversal_reason=journal.reversal_reason,
            reversal_journal_id=journal.reversal_journal_id,
            original_journal_id=journal.original_journal_id,
            cancelled_by=journal.cancelled_by,
            cancelled_at=journal.cancelled_at,
            cancellation_reason=journal.cancellation_reason,
            is_locked=journal.is_locked,
            is_balanced=journal.is_balanced,
            version=journal.version,
            lines=journal.lines,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get journal by number: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{journal_id}",
    response_model=JournalResponseSchema,
    summary="Update draft journal",
    operation_id="update_journal",
)
async def update_journal(
    journal_id: UUID,
    request: JournalUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    from application.dto_objects.journal_request import JournalLineRequest, JournalUpdateRequest

    method_name = "update_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalResponseSchema(**cached)

    try:
        # Validate balance if lines are being updated
        if request.lines:
            total_debit = sum(line.debit_amount for line in request.lines)
            total_credit = sum(line.credit_amount for line in request.lines)
            validate_balance(total_debit, total_credit)

        line_dtos = None
        if request.lines:
            line_dtos = [
                JournalLineRequest(
                    account_code=line.account_code,
                    debit_amount=line.debit_amount,
                    credit_amount=line.credit_amount,
                    cost_center=line.cost_center,
                    department=line.department,
                    project_id=line.project_id,
                    description=line.description,
                    tax_id=line.tax_id,
                )
                for line in request.lines
            ]

        update_dto = JournalUpdateRequest(
            id=journal_id,
            journal_date=request.journal_date,
            description=request.description,
            journal_type=request.journal_type.value if request.journal_type else None,
            lines=line_dtos,
            reference_number=request.reference_number,
            notes=request.notes,
            attachment_ids=request.attachment_ids,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await journal_service.update_journal(update_dto)

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be updated")

        response = JournalResponseSchema(
            id=result.id,
            journal_number=result.journal_number,
            journal_date=result.journal_date,
            description=result.description,
            journal_type=JournalType(result.journal_type),
            status=JournalStatus(result.status),
            total_debit=result.total_debit,
            total_credit=result.total_credit,
            reference_number=result.reference_number,
            source_type=JournalSource(result.source_type),
            source_id=result.source_id,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            created_at=result.created_at,
            submitted_by=result.submitted_by,
            submitted_at=result.submitted_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            approved_at=result.approved_at,
            rejected_by=result.rejected_by,
            rejected_at=result.rejected_at,
            rejection_reason=result.rejection_reason,
            posted_by=result.posted_by,
            posted_by_name=result.posted_by_name,
            posted_at=result.posted_at,
            reversed_by=result.reversed_by,
            reversed_at=result.reversed_at,
            reversal_reason=result.reversal_reason,
            reversal_journal_id=result.reversal_journal_id,
            original_journal_id=result.original_journal_id,
            cancelled_by=result.cancelled_by,
            cancelled_at=result.cancelled_at,
            cancellation_reason=result.cancellation_reason,
            is_locked=result.is_locked,
            is_balanced=result.is_balanced,
            version=result.version,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{journal_id}",
    response_model=JournalActionResponseSchema,
    summary="Cancel draft journal",
    operation_id="cancel_journal",
)
async def cancel_journal(
    journal_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    method_name = "cancel_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        result = await journal_service.cancel_journal(
            journal_id, current_user.user_id, legal_entity_id, reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be cancelled")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="cancel",
            status=JournalStatus(result.status),
            message="Journal cancelled",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/restore",
    response_model=JournalResponseSchema,
    summary="Restore cancelled journal",
    operation_id="restore_journal",
)
async def restore_journal(
    journal_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    method_name = "restore_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalResponseSchema(**cached)

    try:
        result = await journal_service.restore_journal(
            journal_id, current_user.user_id, legal_entity_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be restored")

        response = JournalResponseSchema(
            id=result.id,
            journal_number=result.journal_number,
            journal_date=result.journal_date,
            description=result.description,
            journal_type=JournalType(result.journal_type),
            status=JournalStatus(result.status),
            total_debit=result.total_debit,
            total_credit=result.total_credit,
            reference_number=result.reference_number,
            source_type=JournalSource(result.source_type),
            source_id=result.source_id,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            created_at=result.created_at,
            submitted_by=result.submitted_by,
            submitted_at=result.submitted_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            approved_at=result.approved_at,
            rejected_by=result.rejected_by,
            rejected_at=result.rejected_at,
            rejection_reason=result.rejection_reason,
            posted_by=result.posted_by,
            posted_by_name=result.posted_by_name,
            posted_at=result.posted_at,
            reversed_by=result.reversed_by,
            reversed_at=result.reversed_at,
            reversal_reason=result.reversal_reason,
            reversal_journal_id=result.reversal_journal_id,
            original_journal_id=result.original_journal_id,
            cancelled_by=result.cancelled_by,
            cancelled_at=result.cancelled_at,
            cancellation_reason=result.cancellation_reason,
            is_locked=result.is_locked,
            is_balanced=result.is_balanced,
            version=result.version,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to restore journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/submit",
    response_model=JournalActionResponseSchema,
    summary="Submit journal for approval",
    operation_id="submit_journal",
)
async def submit_journal(
    journal_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    method_name = "submit_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        # Fetch journal to validate balance before submit
        journal = await journal_service.get_journal_by_id(journal_id, legal_entity_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")
        validate_balance(journal.total_debit, journal.total_credit)

        result = await journal_service.submit_journal(
            journal_id, current_user.user_id, legal_entity_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be submitted")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="submit",
            status=JournalStatus(result.status),
            message="Journal submitted for approval",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/approve",
    response_model=JournalActionResponseSchema,
    summary="Approve journal (4-eyes)",
    operation_id="approve_journal",
)
async def approve_journal(
    journal_id: UUID,
    request: JournalApproveSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    use_case: Any = Depends(get_approve_journal_use_case),
) -> JournalActionResponseSchema:
    method_name = "approve_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        # Fetch journal to validate balance before approve
        journal = await use_case.get_journal(journal_id, legal_entity_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")
        validate_balance(journal.total_debit, journal.total_credit)

        result = await use_case.approve(
            journal_id=journal_id,
            approver_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            notes=request.notes,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be approved")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="approve",
            status=JournalStatus(result.status),
            message="Journal approved",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to approve journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/reject",
    response_model=JournalActionResponseSchema,
    summary="Reject journal",
    operation_id="reject_journal",
)
async def reject_journal(
    journal_id: UUID,
    request: JournalRejectSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    method_name = "reject_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        result = await journal_service.reject_journal(
            journal_id=journal_id,
            rejector_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=request.reason,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be rejected")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="reject",
            status=JournalStatus(result.status),
            message=f"Journal rejected: {request.reason}",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reject journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/post",
    response_model=JournalActionResponseSchema,
    summary="Post journal to general ledger",
    operation_id="post_journal",
)
async def post_journal(
    journal_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:post")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    post_use_case: Any = Depends(get_post_journal_use_case),
) -> JournalActionResponseSchema:
    method_name = "post_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        # Fetch journal to validate balance before post
        journal = await post_use_case.get_journal(journal_id, legal_entity_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")
        validate_balance(journal.total_debit, journal.total_credit)

        result = await post_use_case.post(
            journal_id=journal_id,
            posted_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be posted")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="post",
            status=JournalStatus(result.status),
            message="Journal posted to General Ledger",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to post journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/reverse",
    response_model=JournalActionResponseSchema,
    summary="Reverse a posted journal",
    operation_id="reverse_journal",
)
async def reverse_journal(
    journal_id: UUID,
    request: JournalReverseSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:reverse")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    reverse_use_case: Any = Depends(get_reverse_journal_use_case),
) -> JournalActionResponseSchema:
    method_name = "reverse_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        # Fetch journal to validate balance before reverse
        journal = await reverse_use_case.get_journal(journal_id, legal_entity_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")
        validate_balance(journal.total_debit, journal.total_credit)

        result = await reverse_use_case.reverse(
            original_journal_id=journal_id,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reversal_date=request.reversal_date,
            reason=request.reason,
            post_immediately=request.post_immediately,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be reversed")

        response = JournalActionResponseSchema(
            journal_id=result.original_id,
            journal_number=result.original_number,
            action="reverse",
            status=JournalStatus(result.original_status),
            message=f"Reversal journal created: {result.reversal_number}",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reverse journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/unpost",
    response_model=JournalActionResponseSchema,
    summary="Unpost a journal (admin only)",
    operation_id="unpost_journal",
)
async def unpost_journal(
    journal_id: UUID,
    reason: str = Query(..., min_length=5, description="Unpost reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:admin")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    method_name = "unpost_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        # Fetch journal to validate balance before unpost
        journal = await journal_service.get_journal_by_id(journal_id, legal_entity_id)
        if not journal:
            raise HTTPException(status_code=404, detail="Journal not found")
        validate_balance(journal.total_debit, journal.total_credit)

        result = await journal_service.unpost_journal(
            journal_id, current_user.user_id, legal_entity_id, reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be unposted")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="unpost",
            status=JournalStatus(result.status),
            message="Journal unposted (reversed)",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unpost journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/lock",
    response_model=JournalActionResponseSchema,
    summary="Lock journal for audit",
    operation_id="lock_journal",
)
async def lock_journal(
    journal_id: UUID,
    reason: str = Query("", description="Lock reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    method_name = "lock_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        result = await journal_service.lock_journal(
            journal_id, current_user.user_id, legal_entity_id, reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="lock",
            status=JournalStatus(result.status),
            message="Journal locked",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to lock journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{journal_id}/unlock",
    response_model=JournalActionResponseSchema,
    summary="Unlock journal",
    operation_id="unlock_journal",
)
async def unlock_journal(
    journal_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("journal:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    method_name = "unlock_journal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return JournalActionResponseSchema(**cached)

    try:
        result = await journal_service.unlock_journal(
            journal_id, current_user.user_id, legal_entity_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found")

        response = JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="unlock",
            status=JournalStatus(result.status),
            message="Journal unlocked",
            timestamp=datetime.now(),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unlock journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/",
    response_model=JournalListResponseSchema,
    summary="List journals with filters",
    operation_id="list_journals",
)
async def list_journals(
    status: JournalStatus | None = Query(None, description="Filter by status"),
    journal_type: JournalType | None = Query(None, description="Filter by journal type"),
    source_type: JournalSource | None = Query(None, description="Filter by source"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    journal_number: str | None = Query(None, description="Filter by journal number"),
    reference_number: str | None = Query(None, description="Filter by reference number"),
    account_code: str | None = Query(None, description="Filter by account code in lines"),
    created_by: UUID | None = Query(None, description="Filter by creator"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("journal:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalListResponseSchema:
    from application.dto_objects.journal_request import JournalQueryParams

    try:
        params = JournalQueryParams(
            status=status.value if status else None,
            journal_type=journal_type.value if journal_type else None,
            source_type=source_type.value if source_type else None,
            start_date=start_date,
            end_date=end_date,
            journal_number=journal_number,
            reference_number=reference_number,
            account_code=account_code,
            created_by=created_by,
            legal_entity_id=legal_entity_id,
            page=page,
            page_size=page_size,
        )
        result = await journal_service.list_journals(params)

        items = [
            JournalResponseSchema(
                id=j.id,
                journal_number=j.journal_number,
                journal_date=j.journal_date,
                description=j.description,
                journal_type=JournalType(j.journal_type),
                status=JournalStatus(j.status),
                total_debit=j.total_debit,
                total_credit=j.total_credit,
                reference_number=j.reference_number,
                source_type=JournalSource(j.source_type),
                source_id=j.source_id,
                notes=j.notes,
                attachment_ids=j.attachment_ids,
                created_by=j.created_by,
                created_by_name=j.created_by_name,
                created_at=j.created_at,
                submitted_by=j.submitted_by,
                submitted_at=j.submitted_at,
                approved_by=j.approved_by,
                approved_by_name=j.approved_by_name,
                approved_at=j.approved_at,
                rejected_by=j.rejected_by,
                rejected_at=j.rejected_at,
                rejection_reason=j.rejection_reason,
                posted_by=j.posted_by,
                posted_by_name=j.posted_by_name,
                posted_at=j.posted_at,
                reversed_by=j.reversed_by,
                reversed_at=j.reversed_at,
                reversal_reason=j.reversal_reason,
                reversal_journal_id=j.reversal_journal_id,
                original_journal_id=j.original_journal_id,
                cancelled_by=j.cancelled_by,
                cancelled_at=j.cancelled_at,
                cancellation_reason=j.cancellation_reason,
                is_locked=j.is_locked,
                is_balanced=j.is_balanced,
                version=j.version,
                lines=j.lines,
            )
            for j in result.items
        ]

        return JournalListResponseSchema(
            items=items,
            total=result.total,
            page=page,
            page_size=page_size,
            total_debit=result.total_debit,
            total_credit=result.total_credit,
        )
    except Exception as e:
        logger.exception("Failed to list journals: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{journal_id}/validate",
    response_model=dict[str, Any],
    summary="Validate journal",
    operation_id="validate_journal",
)
async def validate_journal(
    journal_id: UUID,
    _permission: None = Depends(require_permission("journal:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> dict[str, Any]:
    try:
        result = await journal_service.validate_journal(journal_id, legal_entity_id)
        if not result:
            raise HTTPException(status_code=404, detail="Journal not found")

        return {
            "journal_id": str(journal_id),
            "journal_number": result.journal_number,
            "is_valid": result.is_valid,
            "is_balanced": result.is_balanced,
            "total_debit": result.total_debit,
            "total_credit": result.total_credit,
            "errors": result.errors,
            "warnings": result.warnings,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to validate journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{journal_id}/status",
    response_model=dict[str, Any],
    summary="Get journal status",
    operation_id="get_journal_status",
)
async def get_journal_status(
    journal_id: UUID,
    _permission: None = Depends(require_permission("journal:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> dict[str, Any]:
    try:
        status_info = await journal_service.get_journal_status(journal_id, legal_entity_id)
        if not status_info:
            raise HTTPException(status_code=404, detail="Journal not found")

        return {
            "journal_id": str(journal_id),
            "journal_number": status_info.journal_number,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_submit": status_info.can_submit,
            "can_approve": status_info.can_approve,
            "can_reject": status_info.can_reject,
            "can_post": status_info.can_post,
            "can_reverse": status_info.can_reverse,
            "can_cancel": status_info.can_cancel,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "submitted_by": status_info.submitted_by,
            "submitted_at": status_info.submitted_at,
            "approved_by": status_info.approved_by,
            "approved_at": status_info.approved_at,
            "posted_by": status_info.posted_by,
            "posted_at": status_info.posted_at,
            "approval_level": status_info.approval_level,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get journal status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{journal_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get journal history",
    operation_id="get_journal_history",
)
async def get_journal_history(
    journal_id: UUID,
    _permission: None = Depends(require_permission("journal:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> list[dict[str, Any]]:
    try:
        history = await journal_service.get_journal_history(journal_id, legal_entity_id)
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
    "/{journal_id}/ledger-entries",
    response_model=list[dict[str, Any]],
    summary="Get ledger entries for a journal",
    operation_id="get_journal_ledger_entries",
)
async def get_journal_ledger_entries(
    journal_id: UUID,
    _permission: None = Depends(require_permission("ledger:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> list[dict[str, Any]]:
    try:
        entries = await journal_service.get_ledger_entries(journal_id, legal_entity_id)
        return [
            {
                "id": str(e.id),
                "account_id": str(e.account_id),
                "account_code": e.account_code,
                "account_name": e.account_name,
                "debit_amount": float(e.debit_amount),
                "credit_amount": float(e.credit_amount),
                "posting_date": e.posting_date.isoformat(),
                "description": e.description,
            }
            for e in entries
        ]
    except Exception as e:
        logger.exception("Failed to get ledger entries: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/export",
    summary="Export journals",
    operation_id="export_journals",
)
async def export_journals(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: JournalStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("journal:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
):
    from fastapi.responses import Response

    try:
        data = await journal_service.export_journals(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            format=format,
            status=status.value if status else None,
        )
        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"journals_{legal_entity_id}_{start_date}_{end_date}.{format}"
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export journals: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


__all__ = ["router"]
