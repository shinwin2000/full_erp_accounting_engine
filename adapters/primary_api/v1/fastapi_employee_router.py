#!/usr/bin/env python3
"""
Module: fastapi_employee_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Employee (karyawan):
               CRUD employee, status management, salary structure,
               BPJS management, PTKP management, dan employee resignation.

PENTING (fix 2026-08-07): field request/response sekarang disesuaikan
dengan kolom `EmployeeTable` yang sesungguhnya (tabel `employee`, dipakai
juga oleh Payroll/Attendance), bukan lagi dataclass in-memory. Beberapa
field API lama tidak lagi ada satu-satu di skema DB, jadi diselaraskan:
  - `position_allowance` / `transport_allowance` / `meal_allowance` /
    `overtime_rate` (4 field terpisah) -> digabung jadi `allowances`
    (total tunjangan) + `overtime_rate_multiplier` (pengali lembur),
    sesuai kolom yang sudah dipakai modul Payroll. Memecah lagi jadi
    kolom granular butuh migration baru terpisah (lihat catatan di PR).
  - `bpjs_kesehatan_employee` dkk (nominal Rupiah) -> BPJS di skema asli
    disimpan sebagai NOMOR KEPESERTAAN (`bpjs_kesehatan_number`,
    `bpjs_ketenagakerjaan_number`) + TARIF persentase regulasi
    (`bpjs_jht_rate_employee`, dst, sudah ada default resmi), bukan
    nominal Rupiah per employee.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
)

# Import service
from application.service_layer.service_employee import (
    EmployeeDuplicateError,
    EmployeeNotFoundError,
    EmployeeService,
    EmployeeServiceError,
)

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


router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class EmployeeStatusEnum(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RESIGNED = "resigned"
    TERMINATED = "terminated"
    ON_LEAVE = "on_leave"


class MaritalStatusEnum(str, Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


# ---------- Request/Response Models ----------

class CreateEmployeeRequest(BaseModel):
    legal_entity_id: UUID
    employee_code: str = Field(..., min_length=1, max_length=30, description="Unique employee code")
    full_name: str = Field(..., min_length=1, max_length=200, description="Full name")
    nik: str | None = Field(None, max_length=30, description="Identity number (KTP)")
    npwp: str | None = Field(None, max_length=20, description="Tax ID (NPWP)")
    gender: str | None = Field(None, max_length=1, description="M / F / O")
    birth_place: str | None = Field(None, max_length=100)
    birth_date: date | None = None
    marital_status: MaritalStatusEnum = MaritalStatusEnum.SINGLE
    dependents: int = Field(0, ge=0, le=10, description="Number of dependents, used to derive PTKP status")
    religion: str | None = Field(None, max_length=50)
    address: str | None = None
    city: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    department: str | None = Field(None, max_length=100)
    division: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=100)
    job_level: str | None = Field(None, max_length=50)
    cost_center: str | None = Field(None, max_length=20)
    manager_id: UUID | None = None
    join_date: date | None = None
    basic_salary: Decimal = Field(Decimal("0"), ge=0)
    allowances: Decimal = Field(Decimal("0"), ge=0, description="Total tunjangan bulanan (gabungan)")
    overtime_rate_multiplier: Decimal = Field(Decimal("1.5"), ge=1, description="Pengali tarif lembur")
    bpjs_kesehatan_number: str | None = Field(None, max_length=30)
    bpjs_ketenagakerjaan_number: str | None = Field(None, max_length=30)
    bank_name: str | None = Field(None, max_length=100)
    bank_account_number: str | None = Field(None, max_length=50)
    bank_account_name: str | None = Field(None, max_length=100)
    notes: str | None = None

    model_config = ConfigDict(use_enum_values=True)


class UpdateEmployeeRequest(BaseModel):
    full_name: str | None = Field(None, max_length=200)
    nik: str | None = Field(None, max_length=30)
    npwp: str | None = Field(None, max_length=20)
    gender: str | None = Field(None, max_length=1)
    birth_date: date | None = None
    address: str | None = None
    city: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    department: str | None = Field(None, max_length=100)
    division: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=100)
    job_level: str | None = Field(None, max_length=50)
    cost_center: str | None = Field(None, max_length=20)
    manager_id: UUID | None = None
    bank_name: str | None = Field(None, max_length=100)
    bank_account_number: str | None = Field(None, max_length=50)
    bank_account_name: str | None = Field(None, max_length=100)
    notes: str | None = None


class UpdateSalaryStructureRequest(BaseModel):
    basic_salary: Decimal | None = Field(None, ge=0)
    allowances: Decimal | None = Field(None, ge=0)
    overtime_rate_multiplier: Decimal | None = Field(None, ge=1)


class UpdateBPJSRequest(BaseModel):
    bpjs_kesehatan_number: str | None = Field(None, max_length=30)
    bpjs_ketenagakerjaan_number: str | None = Field(None, max_length=30)
    bpjs_jht_rate_employee: Decimal | None = Field(None, ge=0, le=100)
    bpjs_jht_rate_employer: Decimal | None = Field(None, ge=0, le=100)
    bpjs_jkk_rate: Decimal | None = Field(None, ge=0, le=100)
    bpjs_jkm_rate: Decimal | None = Field(None, ge=0, le=100)
    bpjs_kesehatan_rate_employee: Decimal | None = Field(None, ge=0, le=100)
    bpjs_kesehatan_rate_employer: Decimal | None = Field(None, ge=0, le=100)


class UpdatePTKPRequest(BaseModel):
    marital_status: MaritalStatusEnum
    dependents: int = Field(..., ge=0, le=10)

    model_config = ConfigDict(use_enum_values=True)


class ResignEmployeeRequest(BaseModel):
    resignation_date: date
    reason: str | None = Field(None, max_length=500)


class EmployeeResponseModel(BaseModel):
    id: UUID
    legal_entity_id: UUID
    employee_code: str
    full_name: str
    preferred_name: str | None = None
    npwp: str | None = None
    nik: str | None = None
    gender: str | None = None
    birth_place: str | None = None
    birth_date: date | None = None
    age: int | None = None
    marital_status: str
    religion: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    mobile: str | None = None
    email: str | None = None
    ptkp_status: str
    department: str | None = None
    division: str | None = None
    position: str | None = None
    job_level: str | None = None
    cost_center: str | None = None
    manager_id: UUID | None = None
    join_date: date | None = None
    resignation_date: date | None = None
    status: str
    basic_salary: Decimal
    allowances: Decimal
    overtime_rate_multiplier: Decimal
    total_annual_salary: Decimal
    monthly_taxable_income: Decimal
    bpjs_kesehatan_number: str | None = None
    bpjs_ketenagakerjaan_number: str | None = None
    bpjs_jht_rate_employee: Decimal
    bpjs_jht_rate_employer: Decimal
    bpjs_jkk_rate: Decimal
    bpjs_jkm_rate: Decimal
    bpjs_kesehatan_rate_employee: Decimal
    bpjs_kesehatan_rate_employer: Decimal
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    annual_leave_balance: Decimal
    sick_leave_balance: Decimal
    special_leave_balance: Decimal
    is_active: bool
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int


# ============================================================================
# HELPER: Get Correlation ID
# ============================================================================

def get_correlation_id(request: Request) -> str:
    corr_id = request.headers.get("X-Correlation-ID")
    if not corr_id:
        corr_id = str(uuid4())
    return corr_id


# ============================================================================
# HELPER: Convert repository dict -> Response model
# ============================================================================

def to_employee_response(employee: dict[str, Any]) -> EmployeeResponseModel:
    """`employee` is the dict returned by EmployeeTable.to_dict() (via the
    repository). Field names are mapped/renamed here where the external API
    contract differs from the internal column name (e.g. tax_id -> npwp)."""
    return EmployeeResponseModel(
        id=employee["id"],
        legal_entity_id=employee["legal_entity_id"],
        employee_code=employee["employee_code"],
        full_name=employee["full_name"],
        preferred_name=employee.get("preferred_name"),
        npwp=employee.get("tax_id"),
        nik=employee.get("nik"),
        gender=employee.get("gender"),
        birth_place=employee.get("birth_place"),
        birth_date=employee.get("birth_date"),
        age=employee.get("age"),
        marital_status=employee.get("marital_status", "single"),
        religion=employee.get("religion"),
        address=employee.get("address"),
        city=employee.get("city"),
        postal_code=employee.get("postal_code"),
        phone=employee.get("phone"),
        mobile=employee.get("mobile"),
        email=employee.get("email"),
        ptkp_status=employee.get("ptkp_status", "TK/0"),
        department=employee.get("department"),
        division=employee.get("division"),
        position=employee.get("position"),
        job_level=employee.get("job_level"),
        cost_center=employee.get("cost_center"),
        manager_id=employee.get("manager_id"),
        join_date=employee.get("join_date"),
        resignation_date=employee.get("resignation_date"),
        status=employee.get("employment_status", "active"),
        basic_salary=employee.get("basic_salary", 0),
        allowances=employee.get("allowances", 0),
        overtime_rate_multiplier=employee.get("overtime_rate_multiplier", 0),
        total_annual_salary=employee.get("total_annual_salary", 0),
        monthly_taxable_income=employee.get("monthly_taxable_income", 0),
        bpjs_kesehatan_number=employee.get("bpjs_kesehatan_number"),
        bpjs_ketenagakerjaan_number=employee.get("bpjs_ketenagakerjaan_number"),
        bpjs_jht_rate_employee=employee.get("bpjs_jht_rate_employee", 0),
        bpjs_jht_rate_employer=employee.get("bpjs_jht_rate_employer", 0),
        bpjs_jkk_rate=employee.get("bpjs_jkk_rate", 0),
        bpjs_jkm_rate=employee.get("bpjs_jkm_rate", 0),
        bpjs_kesehatan_rate_employee=employee.get("bpjs_kesehatan_rate_employee", 0),
        bpjs_kesehatan_rate_employer=employee.get("bpjs_kesehatan_rate_employer", 0),
        bank_name=employee.get("bank_name"),
        bank_account_number=employee.get("bank_account_number"),
        bank_account_name=employee.get("bank_account_name"),
        annual_leave_balance=employee.get("annual_leave_balance", 0),
        sick_leave_balance=employee.get("sick_leave_balance", 0),
        special_leave_balance=employee.get("special_leave_balance", 0),
        is_active=employee.get("is_active", True),
        notes=employee.get("notes"),
        created_by=employee.get("created_by"),
        created_at=employee.get("created_at"),
        updated_at=employee.get("updated_at"),
        version=employee.get("version", 1),
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
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Create a new employee. Persisted to the `employee` table.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "create_employee"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EmployeeResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.create_employee(
            legal_entity_id=payload.legal_entity_id,
            employee_code=payload.employee_code,
            full_name=payload.full_name,
            nik=payload.nik,
            npwp=payload.npwp,
            gender=payload.gender,
            birth_place=payload.birth_place,
            birth_date=payload.birth_date,
            marital_status=payload.marital_status,  # already a str: model_config uses use_enum_values=True
            dependents=payload.dependents,
            religion=payload.religion,
            address=payload.address,
            city=payload.city,
            postal_code=payload.postal_code,
            phone=payload.phone,
            mobile=payload.mobile,
            email=payload.email,
            department=payload.department,
            division=payload.division,
            position=payload.position,
            job_level=payload.job_level,
            cost_center=payload.cost_center,
            manager_id=payload.manager_id,
            join_date=payload.join_date,
            basic_salary=payload.basic_salary,
            allowances=payload.allowances,
            overtime_rate_multiplier=payload.overtime_rate_multiplier,
            bpjs_kesehatan_number=payload.bpjs_kesehatan_number,
            bpjs_ketenagakerjaan_number=payload.bpjs_ketenagakerjaan_number,
            bank_name=payload.bank_name,
            bank_account_number=payload.bank_account_number,
            bank_account_name=payload.bank_account_name,
            notes=payload.notes,
            created_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_employee_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except EmployeeDuplicateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except EmployeeServiceError as e:
        logger.warning(f"Employee service error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating employee: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        return to_employee_response(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/employees",
    response_model=list[EmployeeResponseModel],
    summary="List employees",
)
async def list_employees(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    status_filter: EmployeeStatusEnum | None = Query(None, alias="status", description="Filter by status"),
    search: str | None = Query(None, description="Search by name/code/nik/email"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> list[EmployeeResponseModel]:
    """
    List employees with filters. Pagination (`limit`/`offset`) is applied at
    the database query level.
    """
    try:
        results = await service.list_employees(
            legal_entity_id=legal_entity_id,
            status=status_filter.value if status_filter else None,
            search=search,
            limit=limit,
            offset=offset,
        )
        return [to_employee_response(e) for e in results]
    except Exception as e:
        logger.error(f"Error listing employees: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.patch(
    "/employees/{employee_id}",
    response_model=EmployeeResponseModel,
    summary="Update employee",
)
async def update_employee(
    request: Request,
    employee_id: UUID,
    payload: UpdateEmployeeRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update employee profile fields (partial update - only provided fields change).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_employee"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EmployeeResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_employee(
            employee_id=employee_id,
            full_name=payload.full_name,
            nik=payload.nik,
            npwp=payload.npwp,
            gender=payload.gender,
            birth_date=payload.birth_date,
            address=payload.address,
            city=payload.city,
            postal_code=payload.postal_code,
            phone=payload.phone,
            mobile=payload.mobile,
            email=payload.email,
            department=payload.department,
            division=payload.division,
            position=payload.position,
            job_level=payload.job_level,
            cost_center=payload.cost_center,
            manager_id=payload.manager_id,
            bank_name=payload.bank_name,
            bank_account_number=payload.bank_account_number,
            bank_account_name=payload.bank_account_name,
            notes=payload.notes,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        response = to_employee_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except EmployeeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    except EmployeeServiceError as e:
        logger.warning(f"Employee service error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete(
    "/employees/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete (soft-delete) an employee",
)
async def delete_employee(
    employee_id: UUID,
    permanent: bool = Query(False, description="Hard-delete instead of soft-delete (admin only, irreversible)"),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> Response:
    """
    Delete an employee.

    By default this is a SOFT delete (sets deleted_at + is_active=False):
    employees with payroll/attendance history should never be hard-deleted,
    as that would break referential integrity with Payslip/TimeEntry
    records. `permanent=true` performs a real DELETE and should be reserved
    for admins correcting a genuine data-entry mistake.
    """
    try:
        deleted = await service.delete_employee(employee_id, deleted_by=user.user_id, permanent=permanent)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update employee salary structure (basic salary, allowances, overtime multiplier).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_salary_structure"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EmployeeResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_salary_structure(
            employee_id=employee_id,
            basic_salary=payload.basic_salary,
            allowances=payload.allowances,
            overtime_rate_multiplier=payload.overtime_rate_multiplier,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        response = to_employee_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except EmployeeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    except Exception as e:
        logger.error(f"Error updating salary structure for employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update BPJS (health & employment insurance) membership numbers and rates.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_bpjs"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EmployeeResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_bpjs(
            employee_id=employee_id,
            bpjs_kesehatan_number=payload.bpjs_kesehatan_number,
            bpjs_ketenagakerjaan_number=payload.bpjs_ketenagakerjaan_number,
            bpjs_jht_rate_employee=payload.bpjs_jht_rate_employee,
            bpjs_jht_rate_employer=payload.bpjs_jht_rate_employer,
            bpjs_jkk_rate=payload.bpjs_jkk_rate,
            bpjs_jkm_rate=payload.bpjs_jkm_rate,
            bpjs_kesehatan_rate_employee=payload.bpjs_kesehatan_rate_employee,
            bpjs_kesehatan_rate_employer=payload.bpjs_kesehatan_rate_employer,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        response = to_employee_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except EmployeeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    except Exception as e:
        logger.error(f"Error updating BPJS for employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Update PTKP (marital status and number of dependents) for tax calculation.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_ptkp"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EmployeeResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_ptkp(
            employee_id=employee_id,
            marital_status=payload.marital_status,  # already str: use_enum_values=True
            dependents=payload.dependents,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        response = to_employee_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except EmployeeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    except Exception as e:
        logger.error(f"Error updating PTKP for employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: EmployeeService = Depends(get_service(EmployeeService)),
) -> EmployeeResponseModel:
    """
    Process employee resignation.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "resign_employee"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return EmployeeResponseModel(**cached)

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
        response = to_employee_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except EmployeeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    except Exception as e:
        logger.error(f"Error resigning employee {employee_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
    Get employee service statistics (internal monitoring, in-process counters
    since last restart - not a substitute for GET /employees/stats-db).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting employee stats: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
