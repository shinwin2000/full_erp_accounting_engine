
#!/usr/bin/env python3
"""
Module: fastapi_journal_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Jurnal (Journal Entry)
               sesuai dengan prinsip double-entry. Mendukung create draft, submit,
               approve (4-eyes principle), post, reverse, dan query.

Method Standards (ERP):
- create_journal() / update_journal() / delete_journal() / get_journal()
- submit_journal() / approve_journal() / reject_journal()
- post_journal() / reverse_journal() / unpost_journal()
- cancel_journal() / void_journal() / restore_journal()
- lock_journal() / unlock_journal() / archive_journal()
- validate_journal() / validate_balance()
- add_line() / remove_line() / update_line()
- calculate_total_debit() / calculate_total_credit()
- get_journal_status() / get_journal_history() / get_journal_snapshot()
- audit_trail_journal() / can_transition_journal()
- register_journal_event() / get_journal_events() / clear_journal_events()
- version_journal()
"""


from __future__ import annotations
from fastapi import Request

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from adapters.dependency_provider import get_service
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
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


class JournalStatus(str, Enum):
    """Status jurnal sesuai standar ERP."""

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
    """Jenis jurnal."""

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
    """Sumber jurnal."""

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
# PYDANTIC SCHEMAS
# ============================================================================


class JournalLineSchema(BaseModel):
    """Line item dalam jurnal (double entry)."""

    model_config = ConfigDict(from_attributes=True)

    account_code: str = Field(..., min_length=3, max_length=20, description="Kode akun")
    debit_amount: Decimal = Field(0, decimal_places=2, description="Jumlah debit")
    credit_amount: Decimal = Field(0, decimal_places=2, description="Jumlah credit")
    cost_center: str | None = Field(None, max_length=20, description="Cost center")
    department: str | None = Field(None, max_length=20, description="Department")
    project_id: UUID | None = Field(None, description="Project ID")
    description: str | None = Field(None, max_length=500, description="Line description")
    tax_id: UUID | None = Field(None, description="Tax transaction ID")

    @field_validator("debit_amount", "credit_amount")
    @classmethod
    def validate_amount_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("Amount cannot be negative")
        return v

    @model_validator(mode="after")
    def validate_one_amount(self) -> JournalLineSchema:
        """Debit atau credit harus salah satu yang > 0, tidak boleh keduanya > 0 atau keduanya 0."""
        if self.debit_amount > 0 and self.credit_amount > 0:
            raise ValueError("Line cannot have both debit and credit amounts")
        if self.debit_amount == 0 and self.credit_amount == 0:
            raise ValueError("Line must have either debit or credit amount")
        return self


class JournalCreateSchema(BaseModel):
    """Schema untuk membuat jurnal baru."""

    model_config = ConfigDict(from_attributes=True)

    journal_date: date = Field(default_factory=date.today, description="Tanggal jurnal")
    description: str = Field(..., min_length=3, max_length=500, description="Deskripsi jurnal")
    journal_type: JournalType = Field(JournalType.GENERAL, description="Jenis jurnal")
    lines: list[JournalLineSchema] = Field(..., min_length=2, description="Line items")
    reference_number: str | None = Field(None, max_length=50, description="Nomor referensi")
    source_type: JournalSource = Field(JournalSource.MANUAL, description="Sumber jurnal")
    source_id: str | None = Field(None, max_length=50, description="ID sumber")
    notes: str | None = Field(None, max_length=500, description="Catatan internal")
    attachment_ids: list[UUID] | None = Field(None, description="Dokumen pendukung")

    @model_validator(mode="after")
    def validate_double_entry(self) -> JournalCreateSchema:
        total_debit = sum(line.debit_amount for line in self.lines)
        total_credit = sum(line.credit_amount for line in self.lines)

        if abs(total_debit - total_credit) > Decimal("0.01"):
            raise ValueError(
                "Total debit ({:.2f}) must equal total credit ({:.2f})".format(
                    total_debit, total_credit
                )
            )
        return self


class JournalUpdateSchema(BaseModel):
    """Schema untuk update jurnal."""

    model_config = ConfigDict(from_attributes=True)

    journal_date: date | None = None
    description: str | None = Field(None, min_length=3, max_length=500)
    journal_type: JournalType | None = None
    lines: list[JournalLineSchema] | None = None
    reference_number: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    attachment_ids: list[UUID] | None = None


class JournalResponseSchema(BaseModel):
    """Response jurnal."""

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
    """Response untuk action pada jurnal."""

    model_config = ConfigDict(from_attributes=True)

    journal_id: UUID
    journal_number: str
    action: str
    status: JournalStatus
    message: str
    timestamp: datetime


class JournalListResponseSchema(BaseModel):
    """Response list jurnal dengan pagination."""

    model_config = ConfigDict(from_attributes=True)

    items: list[JournalResponseSchema]
    total: int
    page: int
    page_size: int
    total_debit: Decimal
    total_credit: Decimal


class JournalApproveSchema(BaseModel):
    """Schema untuk approve jurnal."""

    model_config = ConfigDict(from_attributes=True)

    notes: str | None = Field(None, max_length=200, description="Approval notes")


class JournalRejectSchema(BaseModel):
    """Schema untuk reject jurnal."""

    model_config = ConfigDict(from_attributes=True)

    reason: str = Field(..., min_length=5, max_length=500, description="Rejection reason")


class JournalReverseSchema(BaseModel):
    """Schema untuk reverse jurnal."""

    model_config = ConfigDict(from_attributes=True)

    reversal_date: date = Field(default_factory=date.today, description="Reversal date")
    reason: str = Field(..., min_length=5, max_length=500, description="Reversal reason")
    post_immediately: bool = Field(True, description="Post reversal immediately")


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_journal_service(request: Request, ) -> Any:
    """Get Journal Service instance."""
    from application.service_layer.service_journal import JournalService
    from fastapi import Request

    container = request.app.state.container
    return container.resolve(JournalService)


async def get_post_journal_use_case() -> Any:
    """Get Post Journal Use Case instance."""
    from application.use_cases.post_journal_entry import PostJournalEntryUseCase
    from fastapi import Request

    container = request.app.state.container
    return container.resolve(PostJournalEntryUseCase)


async def get_approve_journal_use_case() -> Any:
    """Get Approve Journal Four Eyes Use Case instance."""
    from application.use_cases.approve_journal_four_eyes import ApproveJournalFourEyesUseCase
    from fastapi import Request

    container = request.app.state.container
    return container.resolve(ApproveJournalFourEyesUseCase)


async def get_reverse_journal_use_case() -> Any:
    """Get Reverse Journal Use Case instance."""
    from application.use_cases.reverse_journal import ReverseJournalUseCase
    from fastapi import Request

    container = request.app.state.container
    return container.resolve(ReverseJournalUseCase)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/journals", tags=["Journal"])


# ----------------------------------------------------------------------------
# JOURNAL CRUD OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/",
    response_model=JournalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create new journal draft",
    operation_id="create_journal",
)
async def create_journal(
    request: JournalCreateSchema,
    _permission: None = Depends(require_permission("journal:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    """
    Create a new journal entry (draft status).

    - Must have at least 2 lines (double entry)
    - Total debit must equal total credit
    - Accounts must exist and be active
    - Cannot be posted until approved
    """
    from application.dto_objects.journal_request import JournalCreateRequest, JournalLineRequest

    try:
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

        return JournalResponseSchema(
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
    """Get journal entry by ID."""
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
    """Get journal entry by journal number."""
    try:
        journal = await journal_service.get_journal_by_number(journal_number, legal_entity_id)

        if not journal:
            raise HTTPException(
                status_code=404,
                detail="Journal {} not found".format(journal_number)
            )

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
    _permission: None = Depends(require_permission("journal:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    """
    Update a draft journal entry.

    - Only DRAFT and REJECTED journals can be updated
    - Cannot update after submission or approval
    """
    from application.dto_objects.journal_request import JournalLineRequest, JournalUpdateRequest

    try:
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

        return JournalResponseSchema(
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
    _permission: None = Depends(require_permission("journal:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    """Cancel a draft journal entry."""
    try:
        result = await journal_service.cancel_journal(
            journal_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be cancelled")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="cancel",
            status=JournalStatus(result.status),
            message="Journal cancelled",
            timestamp=datetime.now(),
        )
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
    _permission: None = Depends(require_permission("journal:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalResponseSchema:
    """Restore a cancelled journal back to draft status."""
    try:
        result = await journal_service.restore_journal(
            journal_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be restored")

        return JournalResponseSchema(
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
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to restore journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# JOURNAL WORKFLOW (submit, approve, reject, post, reverse)
# ----------------------------------------------------------------------------


@router.post(
    "/{journal_id}/submit",
    response_model=JournalActionResponseSchema,
    summary="Submit journal for approval",
    operation_id="submit_journal",
)
async def submit_journal(
    journal_id: UUID,
    _permission: None = Depends(require_permission("journal:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    """Submit journal for approval workflow (four-eyes principle)."""
    try:
        result = await journal_service.submit_journal(
            journal_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be submitted")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="submit",
            status=JournalStatus(result.status),
            message="Journal submitted for approval",
            timestamp=datetime.now(),
        )
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
    _permission: None = Depends(require_permission("journal:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    use_case: Any = Depends(get_approve_journal_use_case),
) -> JournalActionResponseSchema:
    """
    Approve a submitted journal (four-eyes principle).

    - Cannot approve own journal
    - Different user must approve
    - Journal must be in SUBMITTED status
    """
    try:
        result = await use_case.approve(
            journal_id=journal_id,
            approver_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            notes=request.notes,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be approved")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="approve",
            status=JournalStatus(result.status),
            message="Journal approved",
            timestamp=datetime.now(),
        )
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
    _permission: None = Depends(require_permission("journal:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    """Reject a submitted journal."""
    try:
        result = await journal_service.reject_journal(
            journal_id=journal_id,
            rejector_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=request.reason,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be rejected")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="reject",
            status=JournalStatus(result.status),
            message="Journal rejected: {}".format(request.reason),
            timestamp=datetime.now(),
        )
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
    _permission: None = Depends(require_permission("journal:post")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    post_use_case: Any = Depends(get_post_journal_use_case),
) -> JournalActionResponseSchema:
    """
    Post journal to General Ledger.

    - Journal must be in APPROVED status
    - Creates ledger entries
    - Updates account balances
    - Cannot be reversed after posting (use reverse endpoint)
    """
    try:
        result = await post_use_case.post(
            journal_id=journal_id,
            posted_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be posted")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="post",
            status=JournalStatus(result.status),
            message="Journal posted to General Ledger",
            timestamp=datetime.now(),
        )
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
    _permission: None = Depends(require_permission("journal:reverse")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    reverse_use_case: Any = Depends(get_reverse_journal_use_case),
) -> JournalActionResponseSchema:
    """
    Reverse a posted journal.

    - Creates a reversing journal entry
    - Original journal status becomes REVERSED
    - Can only reverse POSTED journals
    - Reversal date can be specified
    """
    try:
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

        return JournalActionResponseSchema(
            journal_id=result.original_id,
            journal_number=result.original_number,
            action="reverse",
            status=JournalStatus(result.original_status),
            message="Reversal journal created: {}".format(result.reversal_number),
            timestamp=datetime.now(),
        )
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
    _permission: None = Depends(require_permission("journal:admin")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    """
    Unpost a posted journal (admin only, use with caution).

    - Reverses ledger entries
    - Restores journal to APPROVED status
    - Use reverse instead for normal operations
    """
    try:
        result = await journal_service.unpost_journal(
            journal_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found or cannot be unposted")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="unpost",
            status=JournalStatus(result.status),
            message="Journal unposted (reversed)",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unpost journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# JOURNAL LOCK/UNLOCK
# ----------------------------------------------------------------------------


@router.post(
    "/{journal_id}/lock",
    response_model=JournalActionResponseSchema,
    summary="Lock journal for audit",
    operation_id="lock_journal",
)
async def lock_journal(
    journal_id: UUID,
    reason: str = Query("", description="Lock reason"),
    _permission: None = Depends(require_permission("journal:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    """Lock journal to prevent any modifications."""
    try:
        result = await journal_service.lock_journal(
            journal_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="lock",
            status=JournalStatus(result.status),
            message="Journal locked",
            timestamp=datetime.now(),
        )
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
    _permission: None = Depends(require_permission("journal:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    journal_service: Any = Depends(get_journal_service),
) -> JournalActionResponseSchema:
    """Unlock a locked journal."""
    try:
        result = await journal_service.unlock_journal(
            journal_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Journal not found")

        return JournalActionResponseSchema(
            journal_id=result.id,
            journal_number=result.journal_number,
            action="unlock",
            status=JournalStatus(result.status),
            message="Journal unlocked",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unlock journal: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LIST JOURNALS
# ----------------------------------------------------------------------------


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
    """List journal entries with pagination and filters."""
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


# ----------------------------------------------------------------------------
# JOURNAL VALIDATION & STATUS
# ----------------------------------------------------------------------------


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
    """Validate journal (check balance, account existence, etc.)."""
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
    """Get detailed journal status including workflow state."""
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
    """Get journal status change history (audit trail)."""
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


# ----------------------------------------------------------------------------
# JOURNAL LEDGER ENTRIES
# ----------------------------------------------------------------------------


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
    """Get ledger entries created from this journal (if posted)."""
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


# ----------------------------------------------------------------------------
# EXPORT JOURNAL
# ----------------------------------------------------------------------------


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
    """Export journals to CSV or Excel."""
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
        filename = "journals_{}_{}_{}.{}".format(
            legal_entity_id, start_date, end_date, format
        )

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": "attachment; filename={}".format(filename)},
        )
    except Exception as e:
        logger.exception("Failed to export journals: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]