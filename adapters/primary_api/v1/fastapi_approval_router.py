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

Catatan:
- Service dibangun per-request dengan session dari ``get_async_session`` (commit saat
  sukses, rollback saat ada exception) -- lihat ``get_approval_svc``.
- Error mapping: PermissionError -> 403, ValueError -> 422, IntegrityError -> 409,
  HTTPException diteruskan apa adanya (404 tidak berubah jadi 500).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)
from adapters.secondary_impl.approval_entity_gateway_impl import ApprovalEntityGateway
from application.service_layer.service_approval import MAX_AMOUNT as _MAX_AMOUNT
from application.service_layer.service_approval import ApprovalService, level_name
from infrastructure.database.session_factory_sqlalchemy import get_async_session

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
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
    """Aksi pada approval workflow."""

    SUBMIT = "submit"  # Submit approval
    APPROVE = "approve"  # Setujui
    REJECT = "reject"  # Tolak
    ESCALATE = "escalate"  # Naikkan level
    RECALL = "recall"  # Tarik kembali
    CANCEL = "cancel"  # Batalkan
    DELEGATE = "delegate"  # Delegasikan
    REASSIGN = "reassign"  # Assign ulang


class ApprovalEntityType(str, Enum):
    """Jenis entity yang dapat diapprove.

    HARUS identik dengan CHECK constraint ``ck_approval_entity_type`` di database
    (tabel approval_request dan approval_matrix). Untuk menambah jenis baru, ubah
    constraint lewat migrasi DAN daftar ENTITY_TYPES di service_approval.py.
    """

    JOURNAL = "journal"
    AP_INVOICE = "ap_invoice"
    AR_INVOICE = "ar_invoice"
    PAYMENT = "payment"
    PURCHASE_ORDER = "purchase_order"
    SALES_ORDER = "sales_order"
    BUDGET = "budget"
    MASTER_DATA = "master_data"


class ApprovalLevel(str, Enum):
    """Level approval (urutan menentukan angka 1..9)."""

    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    LEVEL_3 = "level_3"
    LEVEL_4 = "level_4"
    LEVEL_5 = "level_5"
    EXECUTIVE = "executive"
    CFO = "cfo"
    CEO = "ceo"
    BOARD = "board"


# ============================================================================
# SCHEMAS
# ============================================================================


class ApprovalRequestCreateSchema(BaseModel):
    """Schema untuk membuat approval request baru."""

    model_config = ConfigDict(from_attributes=True)

    entity_type: ApprovalEntityType = Field(..., description="Jenis entity yang diapprove")
    entity_id: UUID = Field(..., description="ID entity")
    approval_matrix_id: UUID | None = Field(
        None, description="ID approval matrix (kosong = dipilih otomatis dari entity_type & amount)"
    )
    notes: str | None = Field(None, max_length=500, description="Catatan dari requester")
    amount: Decimal | None = Field(
        None, gt=0, le=_MAX_AMOUNT, decimal_places=2, description="Nilai transaksi (untuk routing)"
    )


class ApprovalActionSchema(BaseModel):
    """Schema untuk action pada approval."""

    model_config = ConfigDict(from_attributes=True)

    action: ApprovalAction = Field(..., description="Action yang dilakukan")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    delegate_to_user_id: UUID | None = Field(None, description="Untuk action DELEGATE: user tujuan")
    escalation_level: ApprovalLevel | None = Field(
        None, description="Untuk action ESCALATE: level tujuan (kosong = level berikutnya)"
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
    escalated_to: UUID | None = None  # user (approver) tujuan eskalasi
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    completed_by_name: str | None = None
    final_decision: str | None = None
    is_locked: bool = False
    version: int = 1
    history: list[dict[str, Any]] = Field(default_factory=list)


class ApprovalHistorySchema(BaseModel):
    """Response history approval."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    approval_request_id: UUID
    action: ApprovalAction
    from_level: ApprovalLevel | None = None
    to_level: ApprovalLevel | None = None
    actor_id: UUID | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    action_at: datetime
    notes: str | None = None
    previous_approver_id: UUID | None = None
    new_approver_id: UUID | None = None


class ApprovalMatrixRuleSchema(BaseModel):
    """Rule dalam approval matrix.

    Setiap rule WAJIB punya minimal satu ``approver_user_ids`` (approver berbasis role
    belum didukung karena request hanya memiliki satu approver_id).
    """

    model_config = ConfigDict(from_attributes=True)

    level: ApprovalLevel = Field(..., description="Level approval")
    min_amount: Decimal | None = Field(None, ge=0, le=_MAX_AMOUNT, decimal_places=2, description="Minimal amount")
    max_amount: Decimal | None = Field(None, ge=0, le=_MAX_AMOUNT, decimal_places=2, description="Maksimal amount")
    approver_role_ids: list[UUID] = Field(
        default_factory=list, description="(Belum dipakai untuk routing) Role IDs"
    )
    approver_user_ids: list[UUID] = Field(
        default_factory=list, description="User IDs approver (minimal satu)"
    )
    approver_name: str | None = Field(None, max_length=200, description="Nama tampilan approver")
    approver_role: str | None = Field(None, max_length=100, description="Jabatan approver")
    min_approvers: int = Field(1, ge=1, le=10, description="Minimal approver (hanya 1 didukung)")
    max_approvers: int = Field(1, ge=1, le=10, description="Maksimal approver")
    auto_approve_if_requester_in_role: bool = Field(
        False, description="(Belum didukung) Auto approve jika requester dalam role"
    )
    is_final: bool = Field(False, description="Level terakhir")
    escalation_days: int | None = Field(None, ge=1, description="Hari sebelum jatuh tempo/eskalasi")
    escalation_to_level: ApprovalLevel | None = Field(None, description="Level tujuan eskalasi")

    @model_validator(mode="after")
    def validate_amounts(self) -> ApprovalMatrixRuleSchema:
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("Min amount cannot be greater than max amount")
        return self


class ApprovalMatrixCreateSchema(BaseModel):
    """Schema untuk membuat approval matrix."""

    model_config = ConfigDict(from_attributes=True)

    matrix_code: str = Field(..., min_length=3, max_length=50, description="Kode matrix")
    matrix_name: str = Field(..., min_length=3, max_length=200, description="Nama matrix")
    entity_type: ApprovalEntityType = Field(..., description="Jenis entity")
    min_amount: Decimal | None = Field(
        None, ge=0, le=_MAX_AMOUNT, decimal_places=2, description="Minimal amount matrix"
    )
    max_amount: Decimal | None = Field(
        None, ge=0, le=_MAX_AMOUNT, decimal_places=2, description="Maksimal amount matrix"
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
        return v.strip().upper()

    @model_validator(mode="after")
    def validate_amounts(self) -> ApprovalMatrixCreateSchema:
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("Min amount cannot be greater than max amount")
        return self


class ApprovalMatrixUpdateSchema(BaseModel):
    """Schema untuk update approval matrix."""

    model_config = ConfigDict(from_attributes=True)

    matrix_name: str | None = Field(None, min_length=3, max_length=200)
    min_amount: Decimal | None = Field(None, ge=0, le=_MAX_AMOUNT, decimal_places=2)
    max_amount: Decimal | None = Field(None, ge=0, le=_MAX_AMOUNT, decimal_places=2)
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
    created_by: UUID | None = None
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
    status: ApprovalStatus = ApprovalStatus.PENDING
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
            raise ValueError("End date must be on or after start date")
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
    reason: str | None = None
    is_active: bool
    created_at: datetime
    created_by: UUID | None = None


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
    by_entity_type: dict[str, int]
    by_level: dict[str, int]
    as_of_date: datetime


# ============================================================================
# DEPENDENCIES & HELPERS
# ============================================================================


async def get_approval_svc(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> ApprovalService:
    """Service approval dengan session request-scoped.

    Session dari ``get_async_session`` di-commit saat endpoint sukses dan di-rollback
    saat ada exception, sehingga data approval benar-benar tersimpan (atau tidak sama
    sekali). Service di-resolve dari container (transient) lalu session-nya diganti
    dengan session request ini -- pola yang sama dengan modul Budget.
    """
    from adapters.secondary_impl.sqlalchemy_approval_repository_impl import (
        SQLAlchemyApprovalRepository,
    )

    service: ApprovalService | None = None
    container = getattr(request.app.state, "container", None)
    if container is not None:
        try:
            service = await container.resolve_async(ApprovalService)
        except Exception:
            logger.warning("Container failed to resolve ApprovalService; building directly", exc_info=True)
            service = None

    repo = getattr(service, "_repo", None)
    if service is None or not isinstance(repo, SQLAlchemyApprovalRepository):
        service = ApprovalService(SQLAlchemyApprovalRepository(session))
    else:
        repo._session = session  # ganti session transient dengan session request-scoped

    # Sinkronisasi dengan modul entity (jurnal, PO, SO, budget) memakai session & container request ini.
    # Saklar: set env APPROVAL_ENTITY_SYNC=false untuk menjalankan approval tanpa sinkronisasi.
    if entity_sync_enabled():
        service.attach_entity_gateway(ApprovalEntityGateway(session, container))
    return service


router = APIRouter(prefix="/approvals", tags=["Approval Workflow"])


def entity_sync_enabled() -> bool:
    """Sinkronisasi dengan modul entity aktif kecuali APPROVAL_ENTITY_SYNC di-set false/0/no/off."""
    return os.getenv("APPROVAL_ENTITY_SYNC", "true").strip().lower() not in ("0", "false", "no", "off")


def _to_http(exc: Exception, operation: str) -> HTTPException:
    """Petakan exception service ke HTTPException."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, IntegrityError):
        logger.warning("Integrity error during %s: %s", operation, exc.orig)
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Data conflicts with an existing record or violates a database constraint",
        )
    logger.exception("Unexpected error during %s: %s", operation, exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Failed to {operation}",
    )


def _level(value: int | None) -> ApprovalLevel | None:
    return ApprovalLevel(level_name(value)) if value is not None else None


def _approval_response(r: Any) -> ApprovalResponseSchema:
    return ApprovalResponseSchema(
        id=r.id,
        request_number=r.request_number,
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        entity_reference=r.entity_reference,
        amount=r.amount,
        status=r.status,
        current_level=_level(r.current_level),
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
        escalated_to=r.escalated_to,
        completed_at=r.completed_at,
        completed_by=r.completed_by,
        completed_by_name=r.completed_by_name,
        final_decision=r.final_decision,
        is_locked=r.is_locked,
        version=r.version,
        history=r.history,
    )


def _task_response(r: Any) -> ApprovalTaskResponseSchema:
    return ApprovalTaskResponseSchema(
        id=r.id,
        request_number=r.request_number,
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        entity_reference=r.entity_reference,
        amount=r.amount,
        status=r.status,
        requester_id=r.requester_id,
        requester_name=r.requester_name,
        submitted_at=r.submitted_at,
        current_level=_level(r.current_level),
        due_date=r.due_date,
        days_remaining=r.days_remaining,
        is_overdue=r.is_overdue,
        notes=r.notes,
    )


def _matrix_response(m: Any) -> ApprovalMatrixResponseSchema:
    return ApprovalMatrixResponseSchema.model_validate(m, from_attributes=True)


def _delegation_response(d: Any) -> ApprovalDelegationResponseSchema:
    return ApprovalDelegationResponseSchema.model_validate(d, from_attributes=True)


def _rules_payload(rules: list[ApprovalMatrixRuleSchema]) -> list[dict[str, Any]]:
    # mode="json": UUID/Decimal/Enum -> tipe JSON-safe (JSONB tidak bisa menyimpan objek Python).
    return [rule.model_dump(mode="json") for rule in rules]


# ============================================================================
# APPROVAL REQUESTS
# ============================================================================


@router.post(
    "/requests",
    response_model=ApprovalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit entity for approval",
    description="Submit sebuah entity untuk approval. Approver level pertama ditentukan dari approval matrix.",
    operation_id="submit_approval",
)
async def submit_for_approval(
    request: ApprovalRequestCreateSchema,
    _permission: None = Depends(require_permission("approval:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema:
    try:
        result = await approval_svc.submit_approval(
            entity_type=request.entity_type.value,
            entity_id=request.entity_id,
            approval_matrix_id=request.approval_matrix_id,
            requester_id=current_user.user_id,
            requester_name=current_user.username,
            legal_entity_id=legal_entity_id,
            amount=request.amount,
            notes=request.notes,
        )
        return _approval_response(result)
    except Exception as exc:
        raise _to_http(exc, "submit approval request") from exc


@router.get(
    "/requests/by-number/{request_number}",
    response_model=ApprovalResponseSchema,
    summary="Get approval request by request number",
    operation_id="get_approval_request_by_number",
)
async def get_approval_request_by_number(
    request_number: str,
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema:
    try:
        result = await approval_svc.get_approval_request_by_number(request_number, legal_entity_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request {request_number} not found",
            )
        return _approval_response(result)
    except Exception as exc:
        raise _to_http(exc, "get approval request") from exc


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
    try:
        result = await approval_svc.get_approval_request(request_id, legal_entity_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request {request_id} not found",
            )
        return _approval_response(result)
    except Exception as exc:
        raise _to_http(exc, "get approval request") from exc


@router.post(
    "/requests/{request_id}/recall",
    response_model=ApprovalResponseSchema,
    summary="Recall approval request",
    description="Tarik kembali request yang masih pending. Hanya requester yang boleh.",
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
    try:
        result = await approval_svc.recall_approval(
            request_id, current_user.user_id, legal_entity_id, reason or None
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request {request_id} not found",
            )
        return _approval_response(result)
    except Exception as exc:
        raise _to_http(exc, "recall approval request") from exc


@router.delete(
    "/requests/{request_id}",
    response_model=dict[str, Any],
    summary="Cancel approval request",
    description="Batalkan request (pending/escalated). Membutuhkan permission approval:cancel.",
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
    try:
        result = await approval_svc.cancel_approval(
            request_id, current_user.user_id, legal_entity_id, reason or None
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request {request_id} not found",
            )
        return {
            "message": "Approval request cancelled successfully",
            "request_id": str(request_id),
            "request_number": result.request_number,
            "status": result.status,
        }
    except Exception as exc:
        raise _to_http(exc, "cancel approval request") from exc


@router.post(
    "/requests/{request_id}/action",
    response_model=ApprovalResponseSchema,
    summary="Perform approval action",
    description=(
        "Approve / reject / escalate / delegate. Hanya approver yang ditugaskan (atau delegasi "
        "aktifnya) yang boleh; requester tidak boleh memproses request miliknya sendiri. "
        "Approve pada level yang bukan terakhir memindahkan request ke approver level berikutnya."
    ),
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
    try:
        result = await approval_svc.process_approval_action(
            request_id=request_id,
            action=action_data.action.value,
            actor_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            notes=action_data.notes,
            actor_name=current_user.username,
            delegate_to_user_id=action_data.delegate_to_user_id,
            escalation_level=action_data.escalation_level.value
            if action_data.escalation_level
            else None,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval request {request_id} not found",
            )
        return _approval_response(result)
    except Exception as exc:
        raise _to_http(exc, "process approval action") from exc


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
    approver_id: UUID | None = Query(None, description="Filter by current approver"),
    start_date: date | None = Query(None, description="Created on/after (inclusive)"),
    end_date: date | None = Query(None, description="Created on/before (inclusive)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> list[ApprovalResponseSchema]:
    try:
        result = await approval_svc.list_approval_requests(
            legal_entity_id=legal_entity_id,
            entity_type=entity_type.value if entity_type else None,
            status=status.value if status else None,
            requester_id=requester_id,
            approver_id=approver_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
        return [_approval_response(item) for item in result.items]
    except Exception as exc:
        raise _to_http(exc, "list approval requests") from exc


@router.get(
    "/my-tasks",
    response_model=list[ApprovalTaskResponseSchema],
    summary="Get my approval tasks",
    description="Request pending yang ditugaskan ke saya (termasuk yang didelegasikan kepada saya).",
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
    try:
        tasks = await approval_svc.get_pending_tasks_for_user(
            user_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            entity_type=entity_type.value if entity_type else None,
            overdue_only=overdue_only,
        )
        return [_task_response(t) for t in tasks]
    except Exception as exc:
        raise _to_http(exc, "get approval tasks") from exc


@router.get(
    "/my-tasks/count",
    response_model=dict[str, Any],
    summary="Get my approval tasks count",
    operation_id="get_my_approval_tasks_count",
)
async def get_my_approval_tasks_count(
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    current_user: TokenPayload = Depends(get_current_user),
    approval_svc: Any = Depends(get_approval_svc),
) -> dict[str, Any]:
    try:
        counts = await approval_svc.get_pending_tasks_count(
            user_id=current_user.user_id, legal_entity_id=legal_entity_id
        )
        return {
            "total": counts.total,
            "overdue": counts.overdue,
            "by_entity_type": counts.by_entity_type,
        }
    except Exception as exc:
        raise _to_http(exc, "get approval tasks count") from exc


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
    try:
        history = await approval_svc.get_approval_history(request_id, legal_entity_id)
        return [
            ApprovalHistorySchema(
                id=h.id,
                approval_request_id=h.approval_request_id,
                action=h.action,
                from_level=_level(h.from_level),
                to_level=_level(h.to_level),
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
    except Exception as exc:
        raise _to_http(exc, "get approval history") from exc


# ============================================================================
# APPROVAL MATRIX
# ============================================================================


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
    try:
        result = await approval_svc.create_approval_matrix(
            matrix_code=request.matrix_code,
            matrix_name=request.matrix_name,
            entity_type=request.entity_type.value,
            min_amount=request.min_amount,
            max_amount=request.max_amount,
            currency=request.currency.upper(),
            rules=_rules_payload(request.rules),
            is_active=request.is_active,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            created_by_name=current_user.username,
        )
        return _matrix_response(result)
    except Exception as exc:
        raise _to_http(exc, "create approval matrix") from exc


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
    try:
        matrices = await approval_svc.list_approval_matrices(
            legal_entity_id=legal_entity_id,
            entity_type=entity_type.value if entity_type else None,
            is_active=is_active,
        )
        return [_matrix_response(m) for m in matrices]
    except Exception as exc:
        raise _to_http(exc, "list approval matrices") from exc


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
    try:
        result = await approval_svc.get_approval_matrix(matrix_id, legal_entity_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval matrix {matrix_id} not found",
            )
        return _matrix_response(result)
    except Exception as exc:
        raise _to_http(exc, "get approval matrix") from exc


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
    try:
        result = await approval_svc.update_approval_matrix(
            matrix_id=matrix_id,
            matrix_name=request.matrix_name,
            min_amount=request.min_amount,
            max_amount=request.max_amount,
            currency=request.currency.upper() if request.currency else None,
            rules=_rules_payload(request.rules) if request.rules is not None else None,
            is_active=request.is_active,
            notes=request.notes,
            legal_entity_id=legal_entity_id,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval matrix {matrix_id} not found",
            )
        return _matrix_response(result)
    except Exception as exc:
        raise _to_http(exc, "update approval matrix") from exc


@router.delete(
    "/matrices/{matrix_id}",
    response_model=dict[str, Any],
    summary="Delete or deactivate approval matrix",
    description=(
        "Default: nonaktifkan matrix. ``permanent=true``: hapus permanen "
        "(ditolak bila masih dipakai request pending)."
    ),
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
    try:
        matrix = await approval_svc.get_approval_matrix(matrix_id, legal_entity_id)
        if not matrix:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval matrix {matrix_id} not found",
            )
        if permanent:
            done = await approval_svc.delete_approval_matrix(
                matrix_id, legal_entity_id, current_user.user_id
            )
        else:
            done = await approval_svc.deactivate_approval_matrix(
                matrix_id, legal_entity_id, current_user.user_id
            )
        if not done:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Approval matrix {matrix_id} not found",
            )
        return {
            "message": "Approval matrix deleted permanently" if permanent else "Approval matrix deactivated",
            "matrix_id": str(matrix_id),
            "matrix_code": matrix.matrix_code,
            "permanent": permanent,
        }
    except Exception as exc:
        raise _to_http(exc, "delete approval matrix") from exc


# ============================================================================
# DELEGATIONS
# ============================================================================


@router.post(
    "/delegations",
    response_model=ApprovalDelegationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Delegate my approval authority",
    operation_id="delegate_approval",
)
async def delegate_approval(
    request: ApprovalDelegationSchema,
    _permission: None = Depends(require_permission("approval:delegate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalDelegationResponseSchema:
    try:
        result = await approval_svc.create_delegation(
            delegator_id=current_user.user_id,
            delegate_to_id=request.delegate_to_user_id,
            start_date=request.start_date,
            end_date=request.end_date,
            reason=request.reason,
            legal_entity_id=legal_entity_id,
            delegator_name=current_user.username,
        )
        return _delegation_response(result)
    except Exception as exc:
        raise _to_http(exc, "create delegation") from exc


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
    try:
        delegations = await approval_svc.list_delegations(
            delegator_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            is_active=is_active,
        )
        return [_delegation_response(d) for d in delegations]
    except Exception as exc:
        raise _to_http(exc, "list delegations") from exc


@router.delete(
    "/delegations/{delegation_id}",
    response_model=dict[str, Any],
    summary="Revoke delegation",
    description="Cabut delegasi. Hanya pemberi delegasi (delegator) yang boleh.",
    operation_id="revoke_delegation",
)
async def revoke_delegation(
    delegation_id: UUID,
    _permission: None = Depends(require_permission("approval:delegate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> dict[str, Any]:
    try:
        done = await approval_svc.revoke_delegation(delegation_id, current_user.user_id, legal_entity_id)
        if not done:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Delegation {delegation_id} not found",
            )
        return {"message": "Delegation revoked successfully", "delegation_id": str(delegation_id)}
    except Exception as exc:
        raise _to_http(exc, "revoke delegation") from exc


# ============================================================================
# STATISTICS / ENTITY STATUS / EXPORT
# ============================================================================


@router.get(
    "/statistics",
    response_model=ApprovalStatsResponseSchema,
    summary="Get approval statistics",
    operation_id="get_approval_statistics",
)
async def get_approval_statistics(
    start_date: date | None = Query(None, description="Start date (inclusive)"),
    end_date: date | None = Query(None, description="End date (inclusive)"),
    entity_type: ApprovalEntityType | None = Query(None, description="Filter by entity type"),
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalStatsResponseSchema:
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
            average_approval_time_hours=stats.average_approval_time_hours or 0.0,
            by_entity_type=stats.by_entity_type,
            by_level=stats.by_level,
            as_of_date=datetime.now(UTC),
        )
    except Exception as exc:
        raise _to_http(exc, "get approval statistics") from exc


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=ApprovalResponseSchema | None,
    summary="Get latest approval status of an entity",
    operation_id="get_entity_approval_status",
)
async def get_entity_approval_status(
    entity_type: ApprovalEntityType,
    entity_id: UUID,
    _permission: None = Depends(require_permission("approval:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> ApprovalResponseSchema | None:
    try:
        result = await approval_svc.get_entity_approval_status(
            entity_type.value, entity_id, legal_entity_id
        )
        return _approval_response(result) if result else None
    except Exception as exc:
        raise _to_http(exc, "get entity approval status") from exc


@router.get(
    "/export",
    summary="Export approval requests",
    description="Export ke CSV. Format 'excel' belum didukung (mengembalikan 422).",
    operation_id="export_approval_requests",
)
async def export_approval_requests(
    start_date: date = Query(..., description="Start date (inclusive)"),
    end_date: date = Query(..., description="End date (inclusive)"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: ApprovalStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("approval:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    approval_svc: Any = Depends(get_approval_svc),
) -> Response:
    try:
        if end_date < start_date:
            raise HTTPException(
                status_code=422, detail="end_date must be on or after start_date"
            )
        content = await approval_svc.export_approval_requests(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            format=format,
            status=status.value if status else None,
        )
        filename = f"approval_requests_{start_date}_{end_date}.csv"
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        raise _to_http(exc, "export approval requests") from exc
