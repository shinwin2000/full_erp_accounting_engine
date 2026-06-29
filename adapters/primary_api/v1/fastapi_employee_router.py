#!/usr/bin/env python3
"""
Module: fastapi_employee_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Employee (karyawan):
               CRUD employee, status management, salary structure,
               BPJS management, PTKP management, dan employee resignation.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

# Import service
from application.service_layer.service_employee import (
    EmployeeService,
    Employee,
    EmployeeStatus,
    MaritalStatus,
    EmployeeServiceError,
    EmployeeNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class EmployeeStatusEnum(str, Enum):
    ACTIVE = "active"
    RESIGNED = "resigned"
    TERMINATED = "terminated"
    LEAVE = "leave"


class MaritalStatusEnum(str, Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


# ---------- Request/Response Models ----------

class CreateEmployeeRequest(BaseModel):
    legal_entity_id: UUID
    employee_code: str = Field(..., min_length=1, max_length=50, description="Unique employee code")
    full_name: str = Field(..., min_length=1, max_length=255, description="Full name")
    npwp: str | None = Field(None, max_length=20, description="Tax ID (NPWP)")
    nik: str | None = Field(None, max_length=20, description="Identity number (KTP)")
    birth_date: date | None = None
    marital_status: MaritalStatusEnum = MaritalStatusEnum.SINGLE
    dependents: int = Field(0, ge=0, le=10, description="Number of dependents for PTKP")
    basic_salary: Decimal = Field(Decimal("0"), ge=0)
    position_allowance: Decimal = Decimal("0")
    transport_allowance: Decimal = Decimal("0")
    meal_allowance: Decimal = Decimal("0")
    overtime_rate: Decimal = Decimal("0")
    join_date: date | None = None

    model_config = ConfigDict(use_enum_values=True)


class UpdateEmployeeRequest(BaseModel):
    full_name: str | None = Field(None, max_length=255)
    nik: str | None = Field(None, max_length=20)
    npwp: str | None = Field(None, max_length=20)
    birth_date: date | None = None
    marital_status: MaritalStatusEnum | None = None
    dependents: int | None = Field(None, ge=0, le=10)


class UpdateSalaryStructureRequest(BaseModel):
    basic_salary: Decimal | None = Field(None, ge=0)
    position_allowance: Decimal | None = Field(None, ge=0)
    transport_allowance: Decimal | None = Field(None, ge=0)
    meal_allowance: Decimal | None = Field(None, ge=0)
    overtime_rate: Decimal | None = Field(None, ge=0)


class UpdateBPJSRequest(BaseModel):
    bpjs_kesehatan_employee: Decimal | None = Field(None, ge=0)
    bpjs_kesehatan_employer: Decimal | None = Field(None, ge=0)
    bpjs_ketenagakerjaan_employee: Decimal | None = Field(None, ge=0)
    bpjs_ketenagakerjaan_employer: Decimal | None = Field(None, ge=0)


class UpdatePTKPRequest(BaseModel):
    marital_status: MaritalStatusEnum
    dependents: int = Field(..., ge=0, le=10)


class ResignEmployeeRequest(BaseModel):
    resignation_date: date
    reason: str | None = Field(None, max_length=500)


class EmployeeResponseModel(BaseModel):
    id: UUID
    legal_entity_id: UUID
    employee_code: str
    full_name: str
    npwp: str | None
    nik: str | None
    birth_date: date | None
    marital_status: str
    dependents: int
    basic_salary: Decimal
    position_allowance: Decimal
    transport_allowance: Decimal
    meal_allowance: Decimal
    overtime_rate: Decimal
    bpjs_kesehatan_employee: Decimal | None
    bpjs_kesehatan_employer: Decimal | None
    bpjs_ketenagakerjaan_employee: Decimal | None
    bpjs_ketenagakerjaan_employer: Decimal | None
    status: str
    join_date: date | None
    resignation_date: date | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    version: int


# ============================================================================
# HELPER: Get Correlation ID
# ============================================================================

def get_correlation_id(request: Request) -> str:
    corr_id = request.headers.get("X-Correlation-ID")
    if not corr_id:
        from uuid import uuid4
        corr_id = str(uuid4())
    return corr_id


# ============================================================================
# HELPER: Convert Domain to Response
# ============================================================================

def to_employee_response(employee: Employee) -> EmployeeResponseModel:
    return EmployeeResponseModel(
        id=employee.id,
        legal_entity_id=employee.legal_entity_id,
        employee_code=employee.employee_code,
        full_name=employee.full_name,
        npwp=employee.npwp,
        nik=employee.nik,
        birth_date=employee.birth_date,
        marital_status=employee.marital_status.value if employee.marital_status else "single",
        dependents=employee.dependents,
        basic_salary=employee.basic_salary,
        position_allowance=employee.position_allowance,
        transport_allowance=employee.transport_allowance,
        meal_allowance=employee.meal_allowance,
        overtime_rate=employee.overtime_rate,
        bpjs_kesehatan_employee=employee.bpjs_kesehatan_employee,
        bpjs_kesehatan_employer=employee.bpjs_kesehatan_employer,
        bpjs_ketenagakerjaan_employee=employee.bpjs_ketenagakerjaan_employee,
        bpjs_ketenagakerjaan_employer=employee.bpjs_ketenagakerjaan_employer,
        status=employee.status.value if employee.status else "active",
        join_date=employee.join_date,
        resignation_date=employee.resignation_date,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
        created_by=employee.created_by,
        version=employee.version,
    )


# ============================================================================
# EMPLOYEE CRUD ENDPOINTS
# ============================================================================

@router.post(
    "/employees",
    response_model=EmployeeResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new employee",
)
async def create_employee(
    request: Request,
    payload: CreateEmployeeRequest,
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Create a new employee.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.create_employee(
            legal_entity_id=payload.legal_entity_id,
            employee_code=payload.employee_code,
            full_name=payload.full_name,
            npwp=payload.npwp,
            nik=payload.nik,
            birth_date=payload.birth_date,
            marital_status=payload.marital_status.value,
            dependents=payload.dependents,
            basic_salary=payload.basic_salary,
            position_allowance=payload.position_allowance,
            transport_allowance=payload.transport_allowance,
            meal_allowance=payload.meal_allowance,
            overtime_rate=payload.overtime_rate,
            join_date=payload.join_date,
            created_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_employee_response(result)
    except EmployeeServiceError as e:
        logger.warning(f"Employee service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating employee: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/employees/{employee_id}",
    response_model=EmployeeResponseModel,
    summary="Get employee by ID",
)
async def get_employee(
    employee_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Get a single employee by ID.
    """
    try:
        result = await service.get_employee(employee_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )
        return to_employee_response(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/employees",
    response_model=list[EmployeeResponseModel],
    summary="List employees",
)
async def list_employees(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    status: EmployeeStatusEnum | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> list[EmployeeResponseModel]:
    """
    List employees with filters.
    """
    try:
        results = await service.list_employees(
            legal_entity_id=legal_entity_id,
            status=status.value if status else None,
        )
        # Apply pagination manually (since service doesn't support pagination yet)
        paginated = results[offset:offset + limit]
        return [to_employee_response(e) for e in paginated]
    except Exception as e:
        logger.error(f"Error listing employees: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.patch(
    "/employees/{employee_id}",
    response_model=EmployeeResponseModel,
    summary="Update employee",
)
async def update_employee(
    request: Request,
    employee_id: UUID,
    payload: UpdateEmployeeRequest,
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update employee details (name, NIK, NPWP, marital status, dependents, etc.).
    """
    try:
        correlation_id = get_correlation_id(request)
        # Convert marital_status to string if provided
        marital_status_str = payload.marital_status.value if payload.marital_status else None
        result = await service.update_employee(
            employee_id=employee_id,
            full_name=payload.full_name,
            nik=payload.nik,
            npwp=payload.npwp,
            birth_date=payload.birth_date,
            marital_status=marital_status_str,
            dependents=payload.dependents,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )
        return to_employee_response(result)
    except EmployeeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    except EmployeeServiceError as e:
        logger.warning(f"Employee service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# SALARY STRUCTURE ENDPOINTS
# ============================================================================

@router.post(
    "/employees/{employee_id}/salary-structure",
    response_model=EmployeeResponseModel,
    summary="Update salary structure",
)
async def update_salary_structure(
    request: Request,
    employee_id: UUID,
    payload: UpdateSalaryStructureRequest,
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update employee salary structure (basic salary, allowances, overtime rate).
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_salary_structure(
            employee_id=employee_id,
            basic_salary=payload.basic_salary,
            position_allowance=payload.position_allowance,
            transport_allowance=payload.transport_allowance,
            meal_allowance=payload.meal_allowance,
            overtime_rate=payload.overtime_rate,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )
        return to_employee_response(result)
    except EmployeeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    except Exception as e:
        logger.error(f"Error updating salary structure for employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# BPJS MANAGEMENT ENDPOINTS
# ============================================================================

@router.post(
    "/employees/{employee_id}/bpjs",
    response_model=EmployeeResponseModel,
    summary="Update BPJS data",
)
async def update_bpjs(
    request: Request,
    employee_id: UUID,
    payload: UpdateBPJSRequest,
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update BPJS (health and employment insurance) data for employee.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_bpjs(
            employee_id=employee_id,
            bpjs_kesehatan_employee=payload.bpjs_kesehatan_employee,
            bpjs_kesehatan_employer=payload.bpjs_kesehatan_employer,
            bpjs_ketenagakerjaan_employee=payload.bpjs_ketenagakerjaan_employee,
            bpjs_ketenagakerjaan_employer=payload.bpjs_ketenagakerjaan_employer,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )
        return to_employee_response(result)
    except EmployeeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    except Exception as e:
        logger.error(f"Error updating BPJS for employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# PTKP MANAGEMENT ENDPOINTS
# ============================================================================

@router.post(
    "/employees/{employee_id}/ptkp",
    response_model=EmployeeResponseModel,
    summary="Update PTKP (marital status & dependents)",
)
async def update_ptkp(
    request: Request,
    employee_id: UUID,
    payload: UpdatePTKPRequest,
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update PTKP (marital status and number of dependents) for tax calculation.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_ptkp(
            employee_id=employee_id,
            marital_status=payload.marital_status.value,
            dependents=payload.dependents,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )
        return to_employee_response(result)
    except EmployeeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    except Exception as e:
        logger.error(f"Error updating PTKP for employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# EMPLOYEE STATUS MANAGEMENT ENDPOINTS
# ============================================================================

@router.post(
    "/employees/{employee_id}/resign",
    response_model=EmployeeResponseModel,
    summary="Resign an employee",
)
async def resign_employee(
    request: Request,
    employee_id: UUID,
    payload: ResignEmployeeRequest,
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Process employee resignation.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.resign_employee(
            employee_id=employee_id,
            resignation_date=payload.resignation_date,
            reason=payload.reason,
            resigned_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )
        return to_employee_response(result)
    except EmployeeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    except Exception as e:
        logger.error(f"Error resigning employee {employee_id}: {e}", exc_info=True)
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
    summary="Get employee service statistics",
)
async def get_employee_stats(
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> dict[str, int]:
    """
    Get employee service statistics (internal monitoring).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting employee stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )