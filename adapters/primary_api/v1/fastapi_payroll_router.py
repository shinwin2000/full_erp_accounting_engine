#!/usr/bin/env python3
"""
Module: fastapi_payroll_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Payroll:
               payroll run, payslip, salary structure, komponen gaji.
Revisi: Menambahkan idempotensi pada fungsi write (POST, PUT, DELETE).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
)

# Import service
from application.service_layer.service_payroll import (
    EmployeeSalaryStructureDTO,
    PayrollRunRequest,
    PayrollService,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class PayrollFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    SEMI_MONTHLY = "SEMI_MONTHLY"
    WEEKLY = "WEEKLY"
    DAILY = "DAILY"


class PayrollStatus(str, Enum):
    DRAFT = "draft"
    PROCESSED = "processed"
    APPROVED = "approved"
    PAID = "paid"
    POSTED = "posted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SalaryComponentType(str, Enum):
    BASIC_SALARY = "BASIC_SALARY"
    ALLOWANCE = "ALLOWANCE"
    OVERTIME = "OVERTIME"
    BONUS = "BONUS"
    DEDUCTION_BPJS_KESEHATAN = "DEDUCTION_BPJS_KESEHATAN"
    DEDUCTION_BPJS_KETENAGAKERJAAN = "DEDUCTION_BPJS_KETENAGAKERJAAN"
    TAX_PPH21 = "TAX_PPH21"
    OTHER_DEDUCTION = "OTHER_DEDUCTION"
    OTHER_ALLOWANCE = "OTHER_ALLOWANCE"


# ---------- Request/Response Models ----------

class CreatePayrollRunRequest(BaseModel):
    legal_entity_id: UUID
    period_month: int = Field(..., ge=1, le=12)
    period_year: int = Field(..., ge=2000, le=2100)
    frequency: PayrollFrequency = PayrollFrequency.MONTHLY
    employee_ids: list[UUID] | None = None
    auto_post_to_gl: bool = True
    idempotency_key: str | None = Field(None, description="Idempotency key untuk mencegah duplikasi")

    model_config = ConfigDict(use_enum_values=True)


class PayrollRunResponseModel(BaseModel):
    payroll_run_id: UUID
    period: str
    frequency: str
    employee_count: int
    total_gross_pay: Decimal
    total_deductions: Decimal
    total_net_pay: Decimal
    total_tax_withheld: Decimal
    status: str
    generated_at: datetime
    idempotency_key: str | None = None


class SetSalaryStructureRequest(BaseModel):
    employee_id: UUID
    basic_salary: Decimal = Field(..., gt=0)
    position_allowance: Decimal = Decimal("0")
    transport_allowance: Decimal = Decimal("0")
    meal_allowance: Decimal = Decimal("0")
    overtime_rate: Decimal = Decimal("0")
    bpjs_kesehatan_employee: Decimal | None = None
    bpjs_kesehatan_employer: Decimal | None = None
    bpjs_ketenagakerjaan_employee: Decimal | None = None
    bpjs_ketenagakerjaan_employer: Decimal | None = None
    other_deductions: dict[str, Decimal] = Field(default_factory=dict)
    effective_date: date | None = None
    idempotency_key: str | None = Field(None, description="Idempotency key untuk mencegah duplikasi")


class SalaryStructureResponse(BaseModel):
    employee_id: UUID
    basic_salary: Decimal
    position_allowance: Decimal
    transport_allowance: Decimal
    meal_allowance: Decimal
    overtime_rate: Decimal
    bpjs_kesehatan_employee: Decimal | None
    bpjs_kesehatan_employer: Decimal | None
    bpjs_ketenagakerjaan_employee: Decimal | None
    bpjs_ketenagakerjaan_employer: Decimal | None
    other_deductions: dict[str, Decimal]


class AddSalaryComponentRequest(BaseModel):
    employee_id: UUID
    component_type: SalaryComponentType
    amount: Decimal = Field(..., ge=0)
    description: str
    effective_date: date | None = None
    idempotency_key: str | None = Field(None, description="Idempotency key untuk mencegah duplikasi")


class PayslipResponseModel(BaseModel):
    payslip_id: UUID
    employee_id: UUID
    employee_name: str
    payroll_run_id: UUID
    gross_pay: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    tax_withheld: Decimal
    components: list[dict[str, Any]]
    generated_at: datetime
    sent_at: datetime | None = None


class PostPayrollToGLRequest(BaseModel):
    payroll_run_id: UUID
    idempotency_key: str | None = Field(None, description="Idempotency key untuk mencegah duplikasi")


class PostPayrollToGLResponse(BaseModel):
    payroll_run_id: UUID
    posted_to_gl: bool
    journal_id: UUID | None = None
    posting_errors: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


class CancelPayrollRunRequest(BaseModel):
    reason: str
    idempotency_key: str | None = Field(None, description="Idempotency key untuk mencegah duplikasi")


# ============================================================================
# HELPER: Get Correlation ID & Idempotency Key
# ============================================================================

def get_correlation_id(request: Request) -> str:
    """Extract correlation ID from header or generate new."""
    corr_id = request.headers.get("X-Correlation-ID")
    if not corr_id:
        corr_id = str(uuid4())
    return corr_id


def get_idempotency_key(request: Request) -> str:
    """Extract idempotency key from header or generate new."""
    idem_key = request.headers.get("Idempotency-Key")
    if not idem_key:
        # Jika tidak ada header, generate dari request body (partial)
        # Untuk keperluan sederhana, kita generate UUID
        idem_key = str(uuid4())
    return idem_key


# ============================================================================
# PAYROLL RUN ENDPOINTS
# ============================================================================

@router.post(
    "/runs",
    response_model=PayrollRunResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Create payroll run",
    description="Create a new payroll run for a given period.",
)
async def create_payroll_run(
    request: Request,
    payload: CreatePayrollRunRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PayrollRunResponseModel:
    """
    Create a new payroll run.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = payload.idempotency_key or get_idempotency_key(request)

        # Cek apakah request sudah diproses (idempotensi)
        existing = await service.get_payroll_run_by_idempotency_key(idempotency_key)
        if existing:
            return PayrollRunResponseModel(
                payroll_run_id=existing.payroll_run_id,
                period=existing.period,
                frequency=existing.frequency,
                employee_count=existing.employee_count,
                total_gross_pay=existing.total_gross_pay,
                total_deductions=existing.total_deductions,
                total_net_pay=existing.total_net_pay,
                total_tax_withheld=existing.total_tax_withheld,
                status=existing.status,
                generated_at=existing.generated_at,
                idempotency_key=idempotency_key,
            )

        run_request = PayrollRunRequest(
            legal_entity_id=payload.legal_entity_id,
            period_month=payload.period_month,
            period_year=payload.period_year,
            frequency=payload.frequency.value,
            employee_ids=payload.employee_ids,
            auto_post_to_gl=payload.auto_post_to_gl,
        )
        result = await service.create_payroll_run(
            request=run_request,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return PayrollRunResponseModel(
            payroll_run_id=result.payroll_run_id,
            period=result.period,
            frequency=result.frequency,
            employee_count=result.employee_count,
            total_gross_pay=result.total_gross_pay,
            total_deductions=result.total_deductions,
            total_net_pay=result.total_net_pay,
            total_tax_withheld=result.total_tax_withheld,
            status=result.status,
            generated_at=result.generated_at,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"Error creating payroll run: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/runs/{run_id}/process",
    response_model=PayrollRunResponseModel,
    summary="Process payroll run",
    description="Calculate payroll components and generate payslips.",
)
async def process_payroll_run(
    request: Request,
    run_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PayrollRunResponseModel:
    """
    Process payroll run: calculate all salaries, deductions, taxes.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = get_idempotency_key(request)

        # Cek apakah sudah diproses
        existing = await service.get_payroll_run_by_idempotency_key(idempotency_key)
        if existing and existing.payroll_run_id == run_id:
            return PayrollRunResponseModel(
                payroll_run_id=existing.payroll_run_id,
                period=existing.period,
                frequency=existing.frequency,
                employee_count=existing.employee_count,
                total_gross_pay=existing.total_gross_pay,
                total_deductions=existing.total_deductions,
                total_net_pay=existing.total_net_pay,
                total_tax_withheld=existing.total_tax_withheld,
                status=existing.status,
                generated_at=existing.generated_at,
                idempotency_key=idempotency_key,
            )

        result = await service.process_payroll_run(
            payroll_run_id=run_id,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return PayrollRunResponseModel(
            payroll_run_id=result.payroll_run_id,
            period=result.period,
            frequency=result.frequency,
            employee_count=result.employee_count,
            total_gross_pay=result.total_gross_pay,
            total_deductions=result.total_deductions,
            total_net_pay=result.total_net_pay,
            total_tax_withheld=result.total_tax_withheld,
            status=result.status,
            generated_at=result.generated_at,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"Error processing payroll run {run_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/runs/{run_id}/approve",
    response_model=PayrollRunResponseModel,
    summary="Approve payroll run",
)
async def approve_payroll_run(
    request: Request,
    run_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PayrollRunResponseModel:
    """
    Approve a processed payroll run (four-eyes principle).
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = get_idempotency_key(request)

        existing = await service.get_payroll_run_by_idempotency_key(idempotency_key)
        if existing and existing.payroll_run_id == run_id:
            return PayrollRunResponseModel(
                payroll_run_id=existing.payroll_run_id,
                period=existing.period,
                frequency=existing.frequency,
                employee_count=existing.employee_count,
                total_gross_pay=existing.total_gross_pay,
                total_deductions=existing.total_deductions,
                total_net_pay=existing.total_net_pay,
                total_tax_withheld=existing.total_tax_withheld,
                status=existing.status,
                generated_at=existing.generated_at,
                idempotency_key=idempotency_key,
            )

        result = await service.approve_payroll_run(
            payroll_run_id=run_id,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return PayrollRunResponseModel(
            payroll_run_id=result.payroll_run_id,
            period=result.period,
            frequency=result.frequency,
            employee_count=result.employee_count,
            total_gross_pay=result.total_gross_pay,
            total_deductions=result.total_deductions,
            total_net_pay=result.total_net_pay,
            total_tax_withheld=result.total_tax_withheld,
            status=result.status,
            generated_at=result.generated_at,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"Error approving payroll run {run_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/runs/{run_id}/pay",
    response_model=PayrollRunResponseModel,
    summary="Mark payroll run as paid",
)
async def pay_payroll_run(
    request: Request,
    run_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PayrollRunResponseModel:
    """
    Mark payroll run as paid.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = get_idempotency_key(request)

        existing = await service.get_payroll_run_by_idempotency_key(idempotency_key)
        if existing and existing.payroll_run_id == run_id:
            return PayrollRunResponseModel(
                payroll_run_id=existing.payroll_run_id,
                period=existing.period,
                frequency=existing.frequency,
                employee_count=existing.employee_count,
                total_gross_pay=existing.total_gross_pay,
                total_deductions=existing.total_deductions,
                total_net_pay=existing.total_net_pay,
                total_tax_withheld=existing.total_tax_withheld,
                status=existing.status,
                generated_at=existing.generated_at,
                idempotency_key=idempotency_key,
            )

        result = await service.pay_payroll_run(
            payroll_run_id=run_id,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return PayrollRunResponseModel(
            payroll_run_id=result.payroll_run_id,
            period=result.period,
            frequency=result.frequency,
            employee_count=result.employee_count,
            total_gross_pay=result.total_gross_pay,
            total_deductions=result.total_deductions,
            total_net_pay=result.total_net_pay,
            total_tax_withheld=result.total_tax_withheld,
            status=result.status,
            generated_at=result.generated_at,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"Error paying payroll run {run_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/runs/{run_id}/post-to-gl",
    response_model=PostPayrollToGLResponse,
    summary="Post payroll to General Ledger",
)
async def post_payroll_to_gl(
    request: Request,
    run_id: UUID,
    payload: PostPayrollToGLRequest = Body(...),
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PostPayrollToGLResponse:
    """
    Post payroll journal entries to General Ledger.
    Idempotent: Menggunakan idempotency key untuk mencegah duplikasi posting.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = payload.idempotency_key or get_idempotency_key(request)

        # Cek apakah sudah pernah diposting dengan idempotency key ini
        existing = await service.get_payroll_post_result_by_idempotency_key(idempotency_key)
        if existing:
            return PostPayrollToGLResponse(
                payroll_run_id=existing.payroll_run_id,
                posted_to_gl=existing.posted_to_gl,
                journal_id=existing.journal_id,
                posting_errors=existing.posting_errors,
                idempotency_key=idempotency_key,
            )

        # Proses posting
        result = await service.post_payroll_to_gl(
            payroll_run_id=run_id,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return PostPayrollToGLResponse(
            payroll_run_id=result.payroll_run_id,
            posted_to_gl=result.posted_to_gl,
            journal_id=result.journal_id,
            posting_errors=result.posting_errors,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"Error posting payroll run {run_id} to GL: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=PayrollRunResponseModel,
    summary="Cancel payroll run",
)
async def cancel_payroll_run(
    request: Request,
    run_id: UUID,
    payload: CancelPayrollRunRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PayrollRunResponseModel:
    """
    Cancel a payroll run.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = payload.idempotency_key or get_idempotency_key(request)

        # Cek apakah sudah dibatalkan
        existing = await service.get_payroll_run_by_idempotency_key(idempotency_key)
        if existing and existing.payroll_run_id == run_id:
            return PayrollRunResponseModel(
                payroll_run_id=existing.payroll_run_id,
                period=existing.period,
                frequency=existing.frequency,
                employee_count=existing.employee_count,
                total_gross_pay=existing.total_gross_pay,
                total_deductions=existing.total_deductions,
                total_net_pay=existing.total_net_pay,
                total_tax_withheld=existing.total_tax_withheld,
                status=existing.status,
                generated_at=existing.generated_at,
                idempotency_key=idempotency_key,
            )

        await service.cancel_payroll_run(
            payroll_run_id=run_id,
            reason=payload.reason,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        # Get updated run after cancellation
        # TODO: Implement get_payroll_run in PayrollService
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cancel endpoint returns no data yet. Please implement get_payroll_run in service.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling payroll run {run_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/runs/{run_id}",
    response_model=PayrollRunResponseModel,
    summary="Get payroll run by ID",
)
async def get_payroll_run(
    run_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PayrollRunResponseModel:
    """
    Get payroll run details.
    """
    try:
        # TODO: Implement get_payroll_run in PayrollService
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Get payroll run not implemented yet",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting payroll run {run_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/runs",
    response_model=list[PayrollRunResponseModel],
    summary="List payroll runs",
)
async def list_payroll_runs(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    status: str | None = Query(None, description="Filter by status"),
    period: str | None = Query(None, description="Filter by period (YYYY-MM)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> list[PayrollRunResponseModel]:
    """
    List payroll runs with filters.
    """
    try:
        # TODO: Implement list_payroll_runs in PayrollService
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="List payroll runs not implemented yet",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing payroll runs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# PAYSLIP ENDPOINTS
# ============================================================================

@router.get(
    "/payslips/{payslip_id}",
    response_model=PayslipResponseModel,
    summary="Get payslip by ID",
)
async def get_payslip(
    payslip_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> PayslipResponseModel:
    """
    Get a payslip by ID.
    """
    try:
        result = await service.get_payslip(payslip_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payslip not found",
            )
        return PayslipResponseModel(
            payslip_id=result.payslip_id,
            employee_id=result.employee_id,
            employee_name=result.employee_name,
            payroll_run_id=result.payroll_run_id,
            gross_pay=result.gross_pay,
            total_deductions=result.total_deductions,
            net_pay=result.net_pay,
            tax_withheld=result.tax_withheld,
            components=result.components,
            generated_at=result.generated_at,
            sent_at=result.sent_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting payslip {payslip_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payslips/{payslip_id}/send",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Send payslip to employee",
)
async def send_payslip_to_employee(
    request: Request,
    payslip_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> Response:
    """
    Send payslip to employee via email/notification.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = get_idempotency_key(request)

        # Cek apakah sudah pernah dikirim
        existing = await service.get_payslip_send_status_by_idempotency_key(idempotency_key)
        if existing and existing.payslip_id == payslip_id:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        await service.send_payslip_to_employee(
            payslip_id=payslip_id,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error sending payslip {payslip_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# SALARY STRUCTURE ENDPOINTS
# ============================================================================

@router.post(
    "/salary-structure",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set employee salary structure",
)
async def set_salary_structure(
    request: Request,
    payload: SetSalaryStructureRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> Response:
    """
    Set or update employee salary structure.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = payload.idempotency_key or get_idempotency_key(request)

        # Cek apakah sudah pernah diset
        existing = await service.get_salary_structure_by_idempotency_key(
            employee_id=payload.employee_id,
            idempotency_key=idempotency_key
        )
        if existing:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        dto = EmployeeSalaryStructureDTO(
            employee_id=payload.employee_id,
            basic_salary=payload.basic_salary,
            position_allowance=payload.position_allowance,
            transport_allowance=payload.transport_allowance,
            meal_allowance=payload.meal_allowance,
            overtime_rate=payload.overtime_rate,
            bpjs_kesehatan_employee=payload.bpjs_kesehatan_employee,
            bpjs_kesehatan_employer=payload.bpjs_kesehatan_employer,
            bpjs_ketenagakerjaan_employee=payload.bpjs_ketenagakerjaan_employee,
            bpjs_ketenagakerjaan_employer=payload.bpjs_ketenagakerjaan_employer,
            other_deductions=payload.other_deductions,
        )
        await service.set_employee_salary_structure(
            employee_id=payload.employee_id,
            structure=dto,
            user_id=user.user_id,
            effective_date=payload.effective_date,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error setting salary structure: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/salary-structure/{employee_id}",
    response_model=SalaryStructureResponse,
    summary="Get employee salary structure",
)
async def get_salary_structure(
    employee_id: UUID,
    as_of_date: date | None = Query(None, description="Effective date"),
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> SalaryStructureResponse:
    """
    Get employee salary structure as of a date.
    """
    try:
        result = await service.get_salary_structure(employee_id, as_of_date)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Salary structure not found for employee",
            )
        return SalaryStructureResponse(
            employee_id=result.employee_id,
            basic_salary=result.basic_salary,
            position_allowance=result.position_allowance,
            transport_allowance=result.transport_allowance,
            meal_allowance=result.meal_allowance,
            overtime_rate=result.overtime_rate,
            bpjs_kesehatan_employee=result.bpjs_kesehatan_employee,
            bpjs_kesehatan_employer=result.bpjs_kesehatan_employer,
            bpjs_ketenagakerjaan_employee=result.bpjs_ketenagakerjaan_employee,
            bpjs_ketenagakerjaan_employer=result.bpjs_ketenagakerjaan_employer,
            other_deductions=result.other_deductions,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting salary structure for employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# SALARY COMPONENT ENDPOINTS
# ============================================================================

@router.post(
    "/salary-components",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Add salary component to employee",
)
async def add_salary_component(
    request: Request,
    payload: AddSalaryComponentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> Response:
    """
    Add a salary component (allowance or deduction) to an employee.
    """
    try:
        correlation_id = get_correlation_id(request)
        idempotency_key = payload.idempotency_key or get_idempotency_key(request)

        # Cek apakah sudah pernah ditambahkan
        existing = await service.get_salary_component_by_idempotency_key(
            employee_id=payload.employee_id,
            idempotency_key=idempotency_key
        )
        if existing:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        from application.service_layer.service_payroll import SalaryComponentRequest
        comp_request = SalaryComponentRequest(
            employee_id=payload.employee_id,
            component_type=payload.component_type.value,
            amount=payload.amount,
            description=payload.description,
            effective_date=payload.effective_date,
        )
        await service.add_salary_component(
            request=comp_request,
            user_id=user.user_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error adding salary component: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# REPORT ENDPOINTS
# ============================================================================

@router.get(
    "/reports/payroll-summary",
    response_model=str,
    summary="Generate payroll report",
)
async def generate_payroll_report(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    period_year: int = Query(..., ge=2000, le=2100),
    period_month: int = Query(..., ge=1, le=12),
    output_format: str = Query("CSV", pattern="^(CSV|PDF)$"),
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> str:
    """
    Generate payroll summary report (CSV or PDF).
    """
    try:
        result = await service.generate_payroll_report(
            legal_entity_id=legal_entity_id,
            period_year=period_year,
            period_month=period_month,
            output_format=output_format,
        )
        return result
    except Exception as e:
        logger.error(f"Error generating payroll report: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# STATS ENDPOINT
# ============================================================================

@router.get(
    "/stats",
    response_model=dict[str, int],
    summary="Get payroll service statistics",
)
async def get_payroll_stats(
    user: TokenPayload = Depends(get_current_user),
    service: PayrollService = Depends(get_service(PayrollService)),
) -> dict[str, int]:
    """
    Get payroll service statistics (internal monitoring).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting payroll stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
