#!/usr/bin/env python3
"""
Module: fastapi_approval_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk workflow approval generik:
               submit approval request, approve/reject, get approval history,
               approval matrix management, multi-level approval, escalation.

Method Standards (ERP):
- submit_approval() / approve() / reject() / escalate()
- recall_approval() / cancel_approval()
- get_approval_status() / get_approval_history()
- create_approval_matrix() / update_approval_matrix() / delete_approval_matrix()
- get_approval_matrix() / list_approval_matrices()
- get_pending_approvals() / get_my_approval_tasks()
- delegate_approval() / reassign_approval()
- can_transition_approval() / transition_approval()
- audit_trail_approval() / get_approval_events()
- version_approval() / version_approval_matrix()
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


class ApprovalStatus(str, Enum):
    """Status approval request."""

    PENDING = "pending"  # Menunggu approval
    APPROVED = "approved"  # Disetujui
    REJECTED = "rejected"  # Ditolak
    ESCALATED = "escalated"  # Dinaikkan level
    CANCELLED = "cancelled"  # Dibatalkan oleh requester
    EXPIRED = "expired"  # Kadaluarsa
    DELEGATED = "delegated"  # Didelegasikan


class ApprovalAction(str, Enum):
    """Action pada approval."""

    SUBMIT = "submit"  # Submit approval
    APPROVE = "approve"  # Setujui
    REJECT = "reject"  # Tolak
    ESCALATE = "escalate"  # Naikkan level
    RECALL = "recall"  # Tarik kembali
    CANCEL = "cancel"  # Batalkan
    DELEGATE = "delegate"  # Delegasikan
    REASSIGN = "reassign"  # Assign ulang


class ApprovalEntityType(str, Enum):
    """Jenis entity yang memerlukan approval."""

    JOURNAL = "journal"
    AP_INVOICE = "ap_invoice"
    AR_INVOICE = "ar_invoice"
    PURCHASE_ORDER = "purchase_order"
    SALES_ORDER = "sales_order"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    PAYMENT = "payment"
    RECEIPT = "receipt"
    BUDGET = "budget"
    FIXED_ASSET = "fixed_asset"
    PRICE_CHANGE = "price_change"
    CUSTOMER_CREDIT_LIMIT = "customer_credit_limit"
    VENDOR_CHANGE = "vendor_change"
    USER_ROLE = "user_role"


class ApprovalLevel(str, Enum):
    """Level approval."""

    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    LEVEL_3 = "level_3"
    LEVEL_4 = "level_4"
    LEVEL_5 = "level_5"
    EXECUTIVE = "executive"
    CFO = "cfo"
    CEO = "ceo"
    BOARD = "board"


# Approval amount thresholds (IDR)
APPROVAL_THRESHOLDS = {
    ApprovalLevel.LEVEL_1: 10_000_000,  # 10 juta
    ApprovalLevel.LEVEL_2: 50_000_000,  # 50 juta
    ApprovalLevel.LEVEL_3: 250_000_000,  # 250 juta
    ApprovalLevel.LEVEL_4: 1_000_000_000,  # 1 Miliar
    ApprovalLevel.LEVEL_5: 5_000_000_000,  # 5 Miliar
    ApprovalLevel.EXECUTIVE: 10_000_000_000,  # 10 Miliar
    ApprovalLevel.CFO: 50_000_000_000,  # 50 Miliar
    ApprovalLevel.CEO: 100_000_000_000,  # 100 Miliar
    ApprovalLevel.BOARD: float("inf"),
}

# Escalation days
ESCALATION_DAYS = {
    ApprovalLevel.LEVEL_1: 2,
    ApprovalLevel.LEVEL_2: 2,
    ApprovalLevel.LEVEL_3: 3,
    ApprovalLevel.LEVEL_4: 3,
    ApprovalLevel.LEVEL_5: 5,
    ApprovalLevel.EXECUTIVE: 5,
    ApprovalLevel.CFO: 7,
    ApprovalLevel.CEO: 7,
    ApprovalLevel.BOARD: 14,
}


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class ApprovalRequestCreateSchema(BaseModel):
    """Schema untuk membuat approval request baru."""

    model_config = ConfigDict(from_attributes=True)

    entity_type: ApprovalEntityType = Field(..., description="Jenis entity yang diapprove")
    entity_id: UUID = Field(..., description="ID entity")
    approval_matrix_id: UUID | None = Field(None, description="ID approval matrix yang digunakan")
    notes: str | None = Field(None, max_length=500, description="Catatan dari requester")
    amount: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Nilai transaksi (untuk routing)"
    )


class ApprovalActionSchema(BaseModel):
    """Schema untuk action pada approval."""

    model_config = ConfigDict(from_attributes=True)

    action: ApprovalAction = Field(..., description="Action yang dilakukan")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    delegate_to_user_id: UUID | None = Field(None, description="Untuk action DELEGATE: user tujuan")
    escalation_level: ApprovalLevel | None = Field(
        None, description="Untuk action ESCALATE: level tujuan"
    )


class ApprovalResponseSchema(BaseModel):
    """Response approval request."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_number: str
    entity_type: ApprovalEntityType
    entity_id: UUID
    entity_reference: str | None = None
    amount: Decimal | None = None
    status: ApprovalStatus
    current_level: ApprovalLevel
    requester_id: UUID
    requester_name: str | None = None
    requester_notes: str | None = None
    submitted_at: datetime
    current_approver_id: UUID | None = None
    current_approver_name: str | None = None
    current_approver_role: str | None = None
    approval_matrix_id: UUID | None = None
    approval_matrix_name: str | None = None
    due_date: datetime | None = None
    escalated_at: datetime | None = None
    escalated_to: ApprovalLevel | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    completed_by_name: str | None = None
    final_decision: str | None = None
    is_locked: bool = False
    version: int = 1
    history: list[dict[str, Any]] = []


class ApprovalHistorySchema(BaseModel):
    """Response history approval."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    approval_request_id: UUID
    action: ApprovalAction
    from_level: ApprovalLevel | None = None
    to_level: ApprovalLevel | None = None
    actor_id: UUID
    actor_name: str | None = None
    actor_role: str | None = None
    action_at: datetime
    notes: str | None = None
    previous_approver_id: UUID | None = None
    new_approver_id: UUID | None = None


class ApprovalMatrixRuleSchema(BaseModel):
    """Rule dalam approval matrix."""

    model_config = ConfigDict(from_attributes=True)

    level: ApprovalLevel = Field(..., description="Level approval")
    min_amount: Decimal | None = Field(None, ge=0, decimal_places=2, description="Minimal amount")
    max_amount: Decimal | None = Field(None, ge=0, decimal_places=2, description="Maksimal amount")
    approver_role_ids: list[UUID] = Field(
        default_factory=list, description="Role IDs yang dapat approve"
    )
    approver_user_ids: list[UUID] = Field(default_factory=list, description="User IDs spesifik")
    min_approvers: int = Field(1, ge=1, le=10, description="Minimal approver")
    max_approvers: int = Field(1, ge=1, le=10, description="Maksimal approver")
    auto_approve_if_requester_in_role: bool = Field(
        False, description="Auto approve jika requester dalam role"
    )
    is_final: bool = Field(False, description="Level terakhir")
    escalation_days: int | None = Field(None, ge=1, description="Hari sebelum eskalasi")
    escalation_to_level: ApprovalLevel | None = Field(None, description="Level tujuan eskalasi")

    @model_validator(mode="after")
    def validate_amounts(self) -> ApprovalMatrixRuleSchema:
        if self.min_amount is not None and self.max_amount is not None:
            if self.min_amount > self.max_amount:
                raise ValueError("Min amount cannot be greater than max amount")
        return self


class ApprovalMatrixCreateSchema(BaseModel):
    """Schema untuk membuat approval matrix."""

    model_config = ConfigDict(from_attributes=True)

    matrix_code: str = Field(..., min_length=3, max_length=50, description="Kode matrix")
    matrix_name: str = Field(..., min_length=3, max_length=200, description="Nama matrix")
    entity_type: ApprovalEntityType = Field(..., description="Jenis entity")
    min_amount: Decimal | None = Field(
        None, ge=0, decimal_places=2, description="Minimal amount matrix"
    )
    max_amount: Decimal | None = Field(
        None, ge=0, decimal_places=2, description="Maksimal amount matrix"
    )
    currency: str = Field("IDR", min_length=3, max_length=3, description="Mata uang")
    rules: list[ApprovalMatrixRuleSchema] = Field(..., min_length=1, description="Rules approval")
    is_active: bool = Field(True, description="Aktif")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("matrix_code")
    @classmethod
    def validate_matrix_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Matrix code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_amounts(self) -> ApprovalMatrixCreateSchema:
        if self.min_amount is not None and self.max_amount is not None:
            if self.min_amount > self.max_amount:
                raise ValueError("Min amount cannot be greater than max amount")
        return self


class ApprovalMatrixUpdateSchema(BaseModel):
    """Schema untuk update approval matrix."""

    model_config = ConfigDict(from_attributes=True)

    matrix_name: str | None = Field(None, min_length=3, max_length=200)
    min_amount: Decimal | None = Field(None, ge=0, decimal_places=2)
    max_amount: Decimal | None = Field(None, ge=0, decimal_places=2)
    currency: str | None = Field(None, min_length=3, max_length=3)
    rules: list[ApprovalMatrixRuleSchema] | None = None
    is_active: bool | None = None
    notes: str | None = Field(None, max_length=500)


class ApprovalMatrixResponseSchema(BaseModel):
    """Response approval matrix."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    matrix_code: str
    matrix_name: str
    entity_type: ApprovalEntityType
    min_amount: Decimal | None
    max_amount: Decimal | None
    currency: str
    rules: list[dict[str, Any]]
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class ApprovalTaskResponseSchema(BaseModel):
    """Response approval task untuk approver."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_number: str
    entity_type: ApprovalEntityType
    entity_id: UUID
    entity_reference: str | None = None
    amount: Decimal | None = None
    requester_id: UUID
    requester_name: str | None = None
    submitted_at: datetime
    current_level: ApprovalLevel
    due_date: datetime | None = None
    days_remaining: int | None = None
    is_overdue: bool = False
    notes: str | None = None


class ApprovalDelegationSchema(BaseModel):
    """Schema untuk delegasi approval."""

    model_config = ConfigDict(from_attributes=True)

    delegate_to_user_id: UUID = Field(..., description="User tujuan delegasi")
    start_date: date = Field(default_factory=date.today, description="Tanggal mulai")
    end_date: date = Field(..., description="Tanggal akhir")
    reason: str = Field(..., min_length=5, max_length=500, description="Alasan delegasi")

    @model_validator(mode="after")
    def validate_dates(self) -> ApprovalDelegationSchema:
        if self.end_date < self.start_date:
            raise ValueError("End date must be after start date")
        return self


class ApprovalDelegationResponseSchema(BaseModel):
    """Response delegasi approval."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    delegator_id: UUID
    delegator_name: str | None = None
    delegate_to_id: UUID
    delegate_to_name: str | None = None
    start_date: date
    end_date: date
    reason: str
    is_active: bool
    created_at: datetime
    created_by: UUID


class ApprovalStatsResponseSchema(BaseModel):
    """Response statistik approval."""

    model_config = ConfigDict(from_attributes=True)

    total_requests: int
    pending_requests: int
    approved_requests: int
    rejected_requests: int
    escalated_requests: int
    expired_requests: int
    average_approval_time_hours: float
    by_entity_type: dict[str, dict[str, int]]
    by_level: dict[str, int]
    as_of_date: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_approval_svc(request: Request) -> Any:
    """
    Get Approval Service instance.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.service_layer.service_approval import ApprovalService

    container = request.app.state.container
    return container.resolve(ApprovalService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/approvals", tags=["Approval Workflow"])


# ----------------------------------------------------------------------------
# APPROVAL REQUEST CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/requests",
    response_model=ApprovalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit entity for approval",
    operation_id="submit_approval",
)
async def submit_for_approval(
    request: ApprovalRequestCreateSchema,
    _permission: None = Depends(require_permission("approval:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema:
    """
    Submit an entity for approval workflow.

    - Automatically determines approval matrix based on entity type and amount
    - Routes to appropriate approvers based on matrix rules
    - Creates approval history entry
    - LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.submit_approval(
            entity_type=request.entity_type.value,
            entity_id=request.entity_id,
            approval_matrix_id=request.approval_matrix_id,
            requester_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            amount=request.amount,
            notes=request.notes,
        )

        return ApprovalResponseSchema(
            id=result.id,
            request_number=result.request_number,
            entity_type=ApprovalEntityType(result.entity_type),
            entity_id=result.entity_id,
            entity_reference=result.entity_reference,
            amount=result.amount,
            status=ApprovalStatus(result.status),
            current_level=ApprovalLevel(result.current_level),
            requester_id=result.requester_id,
            requester_name=result.requester_name,
            requester_notes=result.requester_notes,
            submitted_at=result.submitted_at,
            current_approver_id=result.current_approver_id,
            current_approver_name=result.current_approver_name,
            current_approver_role=result.current_approver_role,
            approval_matrix_id=result.approval_matrix_id,
            approval_matrix_name=result.approval_matrix_name,
            due_date=result.due_date,
            escalated_at=result.escalated_at,
            escalated_to=ApprovalLevel(result.escalated_to) if result.escalated_to else None,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            completed_by_name=result.completed_by_name,
            final_decision=result.final_decision,
            is_locked=result.is_locked,
            version=result.version,
            history=result.history,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit approval: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/requests/{request_id}",
    response_model=ApprovalResponseSchema,
    summary="Get approval request by ID",
    operation_id="get_approval_request",
)
async def get_approval_request(
    request_id: UUID,
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema:
    """Get approval request by ID."""
    try:
        result = await approval_svc.get_approval_request(request_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Approval request not found")

        return ApprovalResponseSchema(
            id=result.id,
            request_number=result.request_number,
            entity_type=ApprovalEntityType(result.entity_type),
            entity_id=result.entity_id,
            entity_reference=result.entity_reference,
            amount=result.amount,
            status=ApprovalStatus(result.status),
            current_level=ApprovalLevel(result.current_level),
            requester_id=result.requester_id,
            requester_name=result.requester_name,
            requester_notes=result.requester_notes,
            submitted_at=result.submitted_at,
            current_approver_id=result.current_approver_id,
            current_approver_name=result.current_approver_name,
            current_approver_role=result.current_approver_role,
            approval_matrix_id=result.approval_matrix_id,
            approval_matrix_name=result.approval_matrix_name,
            due_date=result.due_date,
            escalated_at=result.escalated_at,
            escalated_to=ApprovalLevel(result.escalated_to) if result.escalated_to else None,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            completed_by_name=result.completed_by_name,
            final_decision=result.final_decision,
            is_locked=result.is_locked,
            version=result.version,
            history=result.history,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get approval request: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/requests/by-number/{request_number}",
    response_model=ApprovalResponseSchema,
    summary="Get approval request by number",
    operation_id="get_approval_request_by_number",
)
async def get_approval_request_by_number(
    request_number: str,
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema:
    """Get approval request by request number."""
    try:
        result = await approval_svc.get_approval_request_by_number(request_number, legal_entity_id)

        if not result:
            raise HTTPException(
                status_code=404, detail=f"Approval request {request_number} not found"
            )

        return ApprovalResponseSchema(
            id=result.id,
            request_number=result.request_number,
            entity_type=ApprovalEntityType(result.entity_type),
            entity_id=result.entity_id,
            entity_reference=result.entity_reference,
            amount=result.amount,
            status=ApprovalStatus(result.status),
            current_level=ApprovalLevel(result.current_level),
            requester_id=result.requester_id,
            requester_name=result.requester_name,
            requester_notes=result.requester_notes,
            submitted_at=result.submitted_at,
            current_approver_id=result.current_approver_id,
            current_approver_name=result.current_approver_name,
            current_approver_role=result.current_approver_role,
            approval_matrix_id=result.approval_matrix_id,
            approval_matrix_name=result.approval_matrix_name,
            due_date=result.due_date,
            escalated_at=result.escalated_at,
            escalated_to=ApprovalLevel(result.escalated_to) if result.escalated_to else None,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            completed_by_name=result.completed_by_name,
            final_decision=result.final_decision,
            is_locked=result.is_locked,
            version=result.version,
            history=result.history,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get approval request by number: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/requests/{request_id}/recall",
    response_model=ApprovalResponseSchema,
    summary="Recall approval request",
    operation_id="recall_approval",
)
async def recall_approval(
    request_id: UUID,
    reason: str = Query("", description="Recall reason"),
    _permission: None = Depends(require_permission("approval:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema:
    """
    Recall an approval request (only by requester, only pending status).
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.recall_approval(
            request_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Approval request not found or cannot be recalled"
            )

        return ApprovalResponseSchema(
            id=result.id,
            request_number=result.request_number,
            entity_type=ApprovalEntityType(result.entity_type),
            entity_id=result.entity_id,
            entity_reference=result.entity_reference,
            amount=result.amount,
            status=ApprovalStatus(result.status),
            current_level=ApprovalLevel(result.current_level),
            requester_id=result.requester_id,
            requester_name=result.requester_name,
            requester_notes=result.requester_notes,
            submitted_at=result.submitted_at,
            current_approver_id=result.current_approver_id,
            current_approver_name=result.current_approver_name,
            current_approver_role=result.current_approver_role,
            approval_matrix_id=result.approval_matrix_id,
            approval_matrix_name=result.approval_matrix_name,
            due_date=result.due_date,
            escalated_at=result.escalated_at,
            escalated_to=ApprovalLevel(result.escalated_to) if result.escalated_to else None,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            completed_by_name=result.completed_by_name,
            final_decision=result.final_decision,
            is_locked=result.is_locked,
            version=result.version,
            history=result.history,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to recall approval: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/requests/{request_id}",
    response_model=dict[str, Any],
    summary="Cancel approval request",
    operation_id="cancel_approval",
)
async def cancel_approval(
    request_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("approval:cancel")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> dict[str, Any]:
    """
    Cancel an approval request (admin only, any status except completed).
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.cancel_approval(
            request_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Approval request not found")

        return {
            "request_id": str(request_id),
            "request_number": result.request_number,
            "status": result.status,
            "message": "Approval request cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel approval: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# APPROVAL ACTIONS (APPROVE, REJECT, ESCALATE)
# ----------------------------------------------------------------------------


@router.post(
    "/requests/{request_id}/action",
    response_model=ApprovalResponseSchema,
    summary="Perform approval action",
    operation_id="perform_approval_action",
)
async def perform_approval_action(
    request_id: UUID,
    action_data: ApprovalActionSchema,
    _permission: None = Depends(require_permission("approval:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema:
    """
    Perform approval action (approve, reject, escalate, delegate).

    - Approve: Menyetujui request, lanjut ke level berikutnya atau selesai
    - Reject: Menolak request, status menjadi REJECTED
    - Escalate: Menaikkan ke level yang lebih tinggi
    - Delegate: Mendelegasikan approval ke user lain
    - LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.process_approval_action(
            request_id=request_id,
            action=action_data.action.value,
            actor_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            notes=action_data.notes,
            delegate_to_user_id=action_data.delegate_to_user_id,
            escalation_level=action_data.escalation_level.value
            if action_data.escalation_level
            else None,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Approval request not found")

        return ApprovalResponseSchema(
            id=result.id,
            request_number=result.request_number,
            entity_type=ApprovalEntityType(result.entity_type),
            entity_id=result.entity_id,
            entity_reference=result.entity_reference,
            amount=result.amount,
            status=ApprovalStatus(result.status),
            current_level=ApprovalLevel(result.current_level),
            requester_id=result.requester_id,
            requester_name=result.requester_name,
            requester_notes=result.requester_notes,
            submitted_at=result.submitted_at,
            current_approver_id=result.current_approver_id,
            current_approver_name=result.current_approver_name,
            current_approver_role=result.current_approver_role,
            approval_matrix_id=result.approval_matrix_id,
            approval_matrix_name=result.approval_matrix_name,
            due_date=result.due_date,
            escalated_at=result.escalated_at,
            escalated_to=ApprovalLevel(result.escalated_to) if result.escalated_to else None,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            completed_by_name=result.completed_by_name,
            final_decision=result.final_decision,
            is_locked=result.is_locked,
            version=result.version,
            history=result.history,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to process approval action: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LIST APPROVAL REQUESTS
# ----------------------------------------------------------------------------


@router.get(
    "/requests",
    response_model=list[ApprovalResponseSchema],
    summary="List approval requests",
    operation_id="list_approval_requests",
)
async def list_approval_requests(
    entity_type: ApprovalEntityType | None = Query(None, description="Filter by entity type"),
    status: ApprovalStatus | None = Query(None, description="Filter by status"),
    requester_id: UUID | None = Query(None, description="Filter by requester"),
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> list[ApprovalResponseSchema]:
    """List approval requests with pagination and filters."""
    try:
        result = await approval_svc.list_approval_requests(
            legal_entity_id=legal_entity_id,
            entity_type=entity_type.value if entity_type else None,
            status=status.value if status else None,
            requester_id=requester_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            ApprovalResponseSchema(
                id=r.id,
                request_number=r.request_number,
                entity_type=ApprovalEntityType(r.entity_type),
                entity_id=r.entity_id,
                entity_reference=r.entity_reference,
                amount=r.amount,
                status=ApprovalStatus(r.status),
                current_level=ApprovalLevel(r.current_level),
                requester_id=r.requester_id,
                requester_name=r.requester_name,
                requester_notes=r.requester_notes,
                submitted_at=r.submitted_at,
                current_approver_id=r.current_approver_id,
                current_approver_name=r.current_approver_name,
                current_approver_role=r.current_approver_role,
                approval_matrix_id=r.approval_matrix_id,
                approval_matrix_name=r.approval_matrix_name,
                due_date=r.due_date,
                escalated_at=r.escalated_at,
                escalated_to=ApprovalLevel(r.escalated_to) if r.escalated_to else None,
                completed_at=r.completed_at,
                completed_by=r.completed_by,
                completed_by_name=r.completed_by_name,
                final_decision=r.final_decision,
                is_locked=r.is_locked,
                version=r.version,
                history=r.history,
            )
            for r in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list approval requests: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# APPROVER TASKS
# ----------------------------------------------------------------------------


@router.get(
    "/my-tasks",
    response_model=list[ApprovalTaskResponseSchema],
    summary="Get my pending approval tasks",
    operation_id="get_my_approval_tasks",
)
async def get_my_approval_tasks(
    entity_type: ApprovalEntityType | None = Query(None, description="Filter by entity type"),
    overdue_only: bool = Query(False, description="Show only overdue tasks"),
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    current_user: TokenPayload = Depends(get_current_user),
    approval_svc: Any = Depends(get_approval_svc),
) -> list[ApprovalTaskResponseSchema]:
    """Get all pending approval tasks for the current user as approver."""
    try:
        tasks = await approval_svc.get_pending_tasks_for_user(
            user_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            entity_type=entity_type.value if entity_type else None,
            overdue_only=overdue_only,
        )

        return [
            ApprovalTaskResponseSchema(
                id=t.id,
                request_number=t.request_number,
                entity_type=ApprovalEntityType(t.entity_type),
                entity_id=t.entity_id,
                entity_reference=t.entity_reference,
                amount=t.amount,
                requester_id=t.requester_id,
                requester_name=t.requester_name,
                submitted_at=t.submitted_at,
                current_level=ApprovalLevel(t.current_level),
                due_date=t.due_date,
                days_remaining=t.days_remaining,
                is_overdue=t.is_overdue,
                notes=t.notes,
            )
            for t in tasks
        ]
    except Exception as e:
        logger.exception("Failed to get approval tasks: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/my-tasks/count",
    response_model=dict[str, int],
    summary="Get count of my pending approval tasks",
    operation_id="get_my_approval_tasks_count",
)
async def get_my_approval_tasks_count(
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    current_user: TokenPayload = Depends(get_current_user),
    approval_svc: Any = Depends(get_approval_svc),
) -> dict[str, int]:
    """Get count of pending approval tasks for the current user."""
    try:
        counts = await approval_svc.get_pending_tasks_count(
            user_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return {
            "total": counts.total,
            "by_entity_type": counts.by_entity_type,
            "overdue": counts.overdue,
        }
    except Exception as e:
        logger.exception("Failed to get approval tasks count: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# APPROVAL HISTORY
# ----------------------------------------------------------------------------


@router.get(
    "/requests/{request_id}/history",
    response_model=list[ApprovalHistorySchema],
    summary="Get approval history",
    operation_id="get_approval_history",
)
async def get_approval_history(
    request_id: UUID,
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> list[ApprovalHistorySchema]:
    """Get approval history (audit trail of all actions)."""
    try:
        history = await approval_svc.get_approval_history(request_id, legal_entity_id)

        return [
            ApprovalHistorySchema(
                id=h.id,
                approval_request_id=h.approval_request_id,
                action=ApprovalAction(h.action),
                from_level=ApprovalLevel(h.from_level) if h.from_level else None,
                to_level=ApprovalLevel(h.to_level) if h.to_level else None,
                actor_id=h.actor_id,
                actor_name=h.actor_name,
                actor_role=h.actor_role,
                action_at=h.action_at,
                notes=h.notes,
                previous_approver_id=h.previous_approver_id,
                new_approver_id=h.new_approver_id,
            )
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get approval history: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# APPROVAL MATRIX CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/matrices",
    response_model=ApprovalMatrixResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create approval matrix",
    operation_id="create_approval_matrix",
)
async def create_approval_matrix(
    request: ApprovalMatrixCreateSchema,
    _permission: None = Depends(require_permission("approval:matrix_create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalMatrixResponseSchema:
    """
    Create a new approval matrix.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.create_approval_matrix(
            matrix_code=request.matrix_code,
            matrix_name=request.matrix_name,
            entity_type=request.entity_type.value,
            min_amount=request.min_amount,
            max_amount=request.max_amount,
            currency=request.currency,
            rules=[rule.dict() for rule in request.rules],
            is_active=request.is_active,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return ApprovalMatrixResponseSchema(
            id=result.id,
            matrix_code=result.matrix_code,
            matrix_name=result.matrix_name,
            entity_type=ApprovalEntityType(result.entity_type),
            min_amount=result.min_amount,
            max_amount=result.max_amount,
            currency=result.currency,
            rules=result.rules,
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
        logger.exception("Failed to create approval matrix: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/matrices",
    response_model=list[ApprovalMatrixResponseSchema],
    summary="List approval matrices",
    operation_id="list_approval_matrices",
)
async def list_approval_matrices(
    entity_type: ApprovalEntityType | None = Query(None, description="Filter by entity type"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("approval:matrix_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> list[ApprovalMatrixResponseSchema]:
    """List approval matrices with filters."""
    try:
        matrices = await approval_svc.list_approval_matrices(
            legal_entity_id=legal_entity_id,
            entity_type=entity_type.value if entity_type else None,
            is_active=is_active,
        )

        return [
            ApprovalMatrixResponseSchema(
                id=m.id,
                matrix_code=m.matrix_code,
                matrix_name=m.matrix_name,
                entity_type=ApprovalEntityType(m.entity_type),
                min_amount=m.min_amount,
                max_amount=m.max_amount,
                currency=m.currency,
                rules=m.rules,
                is_active=m.is_active,
                notes=m.notes,
                created_at=m.created_at,
                updated_at=m.updated_at,
                created_by=m.created_by,
                created_by_name=m.created_by_name,
                version=m.version,
            )
            for m in matrices
        ]
    except Exception as e:
        logger.exception("Failed to list approval matrices: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/matrices/{matrix_id}",
    response_model=ApprovalMatrixResponseSchema,
    summary="Get approval matrix by ID",
    operation_id="get_approval_matrix",
)
async def get_approval_matrix(
    matrix_id: UUID,
    _permission: None = Depends(require_permission("approval:matrix_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalMatrixResponseSchema:
    """Get approval matrix by ID."""
    try:
        matrix = await approval_svc.get_approval_matrix(matrix_id, legal_entity_id)

        if not matrix:
            raise HTTPException(status_code=404, detail="Approval matrix not found")

        return ApprovalMatrixResponseSchema(
            id=matrix.id,
            matrix_code=matrix.matrix_code,
            matrix_name=matrix.matrix_name,
            entity_type=ApprovalEntityType(matrix.entity_type),
            min_amount=matrix.min_amount,
            max_amount=matrix.max_amount,
            currency=matrix.currency,
            rules=matrix.rules,
            is_active=matrix.is_active,
            notes=matrix.notes,
            created_at=matrix.created_at,
            updated_at=matrix.updated_at,
            created_by=matrix.created_by,
            created_by_name=matrix.created_by_name,
            version=matrix.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get approval matrix: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/matrices/{matrix_id}",
    response_model=ApprovalMatrixResponseSchema,
    summary="Update approval matrix",
    operation_id="update_approval_matrix",
)
async def update_approval_matrix(
    matrix_id: UUID,
    request: ApprovalMatrixUpdateSchema,
    _permission: None = Depends(require_permission("approval:matrix_update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalMatrixResponseSchema:
    """
    Update an approval matrix.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.update_approval_matrix(
            matrix_id=matrix_id,
            matrix_name=request.matrix_name,
            min_amount=request.min_amount,
            max_amount=request.max_amount,
            currency=request.currency,
            rules=[rule.dict() for rule in request.rules] if request.rules else None,
            is_active=request.is_active,
            notes=request.notes,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Approval matrix not found")

        return ApprovalMatrixResponseSchema(
            id=result.id,
            matrix_code=result.matrix_code,
            matrix_name=result.matrix_name,
            entity_type=ApprovalEntityType(result.entity_type),
            min_amount=result.min_amount,
            max_amount=result.max_amount,
            currency=result.currency,
            rules=result.rules,
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
        logger.exception("Failed to update approval matrix: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/matrices/{matrix_id}",
    response_model=dict[str, Any],
    summary="Delete approval matrix",
    operation_id="delete_approval_matrix",
)
async def delete_approval_matrix(
    matrix_id: UUID,
    permanent: bool = Query(False, description="Permanent deletion"),
    _permission: None = Depends(require_permission("approval:matrix_delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> dict[str, Any]:
    """
    Delete or deactivate an approval matrix.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        if permanent:
            result = await approval_svc.delete_approval_matrix(
                matrix_id, legal_entity_id, current_user.user_id
            )
            action = "deleted"
        else:
            result = await approval_svc.deactivate_approval_matrix(
                matrix_id, legal_entity_id, current_user.user_id
            )
            action = "deactivated"

        if not result:
            raise HTTPException(status_code=404, detail="Approval matrix not found")

        return {
            "matrix_id": str(matrix_id),
            "matrix_code": result.matrix_code,
            "action": action,
            "message": f"Approval matrix {action}",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete approval matrix: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# APPROVAL DELEGATION
# ----------------------------------------------------------------------------


@router.post(
    "/delegations",
    response_model=ApprovalDelegationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Delegate approval authority",
    operation_id="delegate_approval",
)
async def delegate_approval(
    request: ApprovalDelegationSchema,
    _permission: None = Depends(require_permission("approval:delegate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalDelegationResponseSchema:
    """
    Delegate approval authority to another user for a period.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.create_delegation(
            delegator_id=current_user.user_id,
            delegate_to_id=request.delegate_to_user_id,
            start_date=request.start_date,
            end_date=request.end_date,
            reason=request.reason,
            legal_entity_id=legal_entity_id,
        )

        return ApprovalDelegationResponseSchema(
            id=result.id,
            delegator_id=result.delegator_id,
            delegator_name=result.delegator_name,
            delegate_to_id=result.delegate_to_id,
            delegate_to_name=result.delegate_to_name,
            start_date=result.start_date,
            end_date=result.end_date,
            reason=result.reason,
            is_active=result.is_active,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create delegation: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/delegations",
    response_model=list[ApprovalDelegationResponseSchema],
    summary="List my delegations",
    operation_id="list_my_delegations",
)
async def list_my_delegations(
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    current_user: TokenPayload = Depends(get_current_user),
    approval_svc: Any = Depends(get_approval_svc),
) -> list[ApprovalDelegationResponseSchema]:
    """List delegations where current user is delegator."""
    try:
        delegations = await approval_svc.list_delegations(
            delegator_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            is_active=is_active,
        )

        return [
            ApprovalDelegationResponseSchema(
                id=d.id,
                delegator_id=d.delegator_id,
                delegator_name=d.delegator_name,
                delegate_to_id=d.delegate_to_id,
                delegate_to_name=d.delegate_to_name,
                start_date=d.start_date,
                end_date=d.end_date,
                reason=d.reason,
                is_active=d.is_active,
                created_at=d.created_at,
                created_by=d.created_by,
            )
            for d in delegations
        ]
    except Exception as e:
        logger.exception("Failed to list delegations: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/delegations/{delegation_id}",
    response_model=dict[str, Any],
    summary="Revoke delegation",
    operation_id="revoke_delegation",
)
async def revoke_delegation(
    delegation_id: UUID,
    _permission: None = Depends(require_permission("approval:delegate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> dict[str, Any]:
    """
    Revoke an active delegation.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await approval_svc.revoke_delegation(
            delegation_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Delegation not found")

        return {
            "delegation_id": str(delegation_id),
            "revoked": True,
            "message": "Delegation revoked",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to revoke delegation: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# APPROVAL STATISTICS
# ----------------------------------------------------------------------------


@router.get(
    "/statistics",
    response_model=ApprovalStatsResponseSchema,
    summary="Get approval statistics",
    operation_id="get_approval_statistics",
)
async def get_approval_statistics(
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    entity_type: ApprovalEntityType | None = Query(None, description="Filter by entity type"),
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalStatsResponseSchema:
    """Get approval statistics for monitoring."""
    try:
        stats = await approval_svc.get_approval_statistics(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            entity_type=entity_type.value if entity_type else None,
        )

        return ApprovalStatsResponseSchema(
            total_requests=stats.total_requests,
            pending_requests=stats.pending_requests,
            approved_requests=stats.approved_requests,
            rejected_requests=stats.rejected_requests,
            escalated_requests=stats.escalated_requests,
            expired_requests=stats.expired_requests,
            average_approval_time_hours=stats.average_approval_time_hours,
            by_entity_type=stats.by_entity_type,
            by_level=stats.by_level,
            as_of_date=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get approval statistics: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# APPROVAL STATUS (for entity)
# ----------------------------------------------------------------------------


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=ApprovalResponseSchema | None,
    summary="Get approval status for an entity",
    operation_id="get_entity_approval_status",
)
async def get_entity_approval_status(
    entity_type: ApprovalEntityType,
    entity_id: UUID,
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema | None:
    """Get the latest approval request status for an entity."""
    try:
        result = await approval_svc.get_entity_approval_status(
            entity_type=entity_type.value,
            entity_id=entity_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            return None

        return ApprovalResponseSchema(
            id=result.id,
            request_number=result.request_number,
            entity_type=ApprovalEntityType(result.entity_type),
            entity_id=result.entity_id,
            entity_reference=result.entity_reference,
            amount=result.amount,
            status=ApprovalStatus(result.status),
            current_level=ApprovalLevel(result.current_level),
            requester_id=result.requester_id,
            requester_name=result.requester_name,
            requester_notes=result.requester_notes,
            submitted_at=result.submitted_at,
            current_approver_id=result.current_approver_id,
            current_approver_name=result.current_approver_name,
            current_approver_role=result.current_approver_role,
            approval_matrix_id=result.approval_matrix_id,
            approval_matrix_name=result.approval_matrix_name,
            due_date=result.due_date,
            escalated_at=result.escalated_at,
            escalated_to=ApprovalLevel(result.escalated_to) if result.escalated_to else None,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            completed_by_name=result.completed_by_name,
            final_decision=result.final_decision,
            is_locked=result.is_locked,
            version=result.version,
            history=result.history,
        )
    except Exception as e:
        logger.exception("Failed to get entity approval status: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export approval requests",
    operation_id="export_approval_requests",
)
async def export_approval_requests(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: ApprovalStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("approval:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> Response:
    """Export approval requests to CSV or Excel."""
    try:
        data = await approval_svc.export_approval_requests(
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
        filename = f"approval_requests_{legal_entity_id}_{start_date}_{end_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export approval requests: {}", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]