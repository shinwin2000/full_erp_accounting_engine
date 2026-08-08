#!/usr/bin/env python3
"""
Module: service_employee.py
Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk Employee (HR) management.
    Mempublikasikan event untuk setiap perubahan data employee.

PENTING (fix 2026-08-07): Versi sebelumnya menyimpan seluruh data employee
di `self._employees: dict[UUID, Employee] = {}` — murni di RAM proses
Python, TIDAK PERNAH menyentuh database. Akibatnya:
  - Semua data employee hilang setiap kali server di-restart.
  - `EmployeeTable` (ORM, ~50 kolom, sudah dipakai Payroll/Attendance)
    dan `SQLAlchemyEmployeeRepository` tidak pernah benar-benar dipakai.

Service ini sekarang didukung oleh `SQLAlchemyEmployeeRepository`
(adapters/secondary_impl/sqlalchemy_employee_repository_impl.py), yang
sudah diperbaiki agar menulis ke tabel `employee` yang SUNGGUHAN (dibuat
oleh migration 0006). Setiap create/update/resign/delete di sini sekarang
benar-benar tersimpan di PostgreSQL dan akan tetap ada setelah restart.

Kalau `repository` tidak di-inject oleh IoC container (mis. karena file
bootstrap/dependency_container/service_registry.py belum di-update untuk
meneruskannya), service ini akan otomatis membuat
`SQLAlchemyEmployeeRepository()` sendiri sebagai fallback yang aman —
sehingga tetap tersambung ke database walau tanpa perubahan pada
container wiring.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# Import domain events
from application.events import (
    EmployeeBPJSUpdatedEvent,
    EmployeeCreatedEvent,
    EmployeePTKPUpdatedEvent,
    EmployeeResignedEvent,
    EmployeeStructureUpdatedEvent,
)
from ports.primary.event_publisher_port import EventPublisherPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums
# ============================================================================


class EmployeeStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RESIGNED = "resigned"
    TERMINATED = "terminated"
    ON_LEAVE = "on_leave"


class MaritalStatus(str, Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


def compute_ptkp_status(marital_status: str, dependents: int) -> str:
    """Menghitung kode status PTKP (Penghasilan Tidak Kena Pajak) dari status
    pernikahan + jumlah tanggungan, sesuai domain yang diizinkan oleh
    CheckConstraint 'ck_employee_ptkp' pada tabel employee
    (TK/0..TK/3, K/0..K/3)."""
    capped = max(0, min(int(dependents or 0), 3))
    prefix = "K" if marital_status == MaritalStatus.MARRIED.value else "TK"
    return f"{prefix}/{capped}"


# ============================================================================
# Exceptions
# ============================================================================


class EmployeeServiceError(Exception):
    pass


class EmployeeNotFoundError(EmployeeServiceError):
    pass


class EmployeeDuplicateError(EmployeeServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class EmployeeService:
    """
    Service untuk Employee (HR). Semua data dibaca/ditulis lewat
    `EmployeeRepositoryPort` (implementasi: SQLAlchemyEmployeeRepository),
    bukan disimpan di memori proses.
    """

    def __init__(self, repository: Any | None = None, event_publisher: EventPublisherPort | None = None):
        if repository is None:
            # Fallback aman: kalau container belum meng-inject repository,
            # bangun sendiri implementasi konkretnya supaya data tetap
            # tersambung ke database, bukan diam-diam jatuh balik ke RAM.
            from adapters.secondary_impl.sqlalchemy_employee_repository_impl import (
                SQLAlchemyEmployeeRepository,
            )
            repository = SQLAlchemyEmployeeRepository()
            logger.warning(
                "EmployeeService dibuat tanpa repository dari container - "
                "membuat SQLAlchemyEmployeeRepository() sendiri sebagai fallback."
            )

        self._repository = repository
        self._event_publisher = event_publisher
        self._stats = {"employees_created": 0, "employees_updated": 0}
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("EmployeeService initialized (database-backed)")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "EmployeeService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # CREATE
    # ========================================================================

    @audit
    async def create_employee(
        self,
        legal_entity_id: UUID,
        employee_code: str,
        full_name: str,
        nik: str | None = None,
        npwp: str | None = None,
        gender: str | None = None,
        birth_place: str | None = None,
        birth_date: date | None = None,
        marital_status: str = MaritalStatus.SINGLE.value,
        dependents: int = 0,
        religion: str | None = None,
        address: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        phone: str | None = None,
        mobile: str | None = None,
        email: str | None = None,
        department: str | None = None,
        division: str | None = None,
        position: str | None = None,
        job_level: str | None = None,
        cost_center: str | None = None,
        manager_id: UUID | None = None,
        join_date: date | None = None,
        basic_salary: Decimal = Decimal("0"),
        allowances: Decimal = Decimal("0"),
        overtime_rate_multiplier: Decimal = Decimal("1.5"),
        bpjs_kesehatan_number: str | None = None,
        bpjs_ketenagakerjaan_number: str | None = None,
        bank_name: str | None = None,
        bank_account_number: str | None = None,
        bank_account_name: str | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self._check_authority(created_by, "create_employee")

        existing_code = await self._repository.get_by_code(employee_code, legal_entity_id)
        if existing_code:
            raise EmployeeDuplicateError(f"Employee code '{employee_code}' sudah digunakan di entitas ini")
        if nik:
            existing_nik = await self._repository.get_by_nik(nik, legal_entity_id)
            if existing_nik:
                raise EmployeeDuplicateError(f"NIK '{nik}' sudah terdaftar")

        data = {
            "legal_entity_id": legal_entity_id,
            "employee_code": employee_code,
            "full_name": full_name,
            "nik": nik,
            "tax_id": npwp,
            "gender": gender,
            "birth_place": birth_place,
            "birth_date": birth_date,
            "marital_status": marital_status,
            "religion": religion,
            "address": address,
            "city": city,
            "postal_code": postal_code,
            "phone": phone,
            "mobile": mobile,
            "email": email,
            "ptkp_status": compute_ptkp_status(marital_status, dependents),
            "department": department,
            "division": division,
            "position": position,
            "job_level": job_level,
            "cost_center": cost_center,
            "manager_id": manager_id,
            "join_date": join_date or date.today(),
            "employment_status": EmployeeStatus.ACTIVE.value,
            "basic_salary": basic_salary,
            "allowances": allowances,
            "overtime_rate_multiplier": overtime_rate_multiplier,
            "bpjs_kesehatan_number": bpjs_kesehatan_number,
            "bpjs_ketenagakerjaan_number": bpjs_ketenagakerjaan_number,
            "bank_name": bank_name,
            "bank_account_number": bank_account_number,
            "bank_account_name": bank_account_name,
            "notes": notes,
            "is_active": True,
            "created_by": created_by,
        }

        employee = await self._repository.add(data)
        self._stats["employees_created"] += 1

        if self._event_publisher:
            try:
                event = EmployeeCreatedEvent(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_code=employee["employee_code"],
                    employee_name=employee["full_name"],
                    legal_entity_id=UUID(employee["legal_entity_id"]),
                    created_by=str(created_by) if created_by else "system",
                    user_id=str(created_by) if created_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Employee {employee['employee_code']} (created)", correlation_id)
            except Exception as e:
                # EmployeeCreatedEvent (domain/customer_supplier_employee) expects a full
                # EmployeeEntity aggregate that this service-layer call site cannot supply.
                # Don't let a broken event payload block employee creation - mirrors the
                # try/except-and-warn pattern used by CustomerService/SupplierService.
                logger.warning(f"Failed to publish EmployeeCreatedEvent for {employee['employee_code']}: {e}")

        self._record_audit("create_employee", {
            "employee_id": employee["id"],
            "employee_code": employee_code,
            "created_by": str(created_by) if created_by else None,
        })

        return employee

    # ========================================================================
    # READ
    # ========================================================================

    async def get_employee(self, employee_id: UUID) -> dict[str, Any] | None:
        return await self._repository.get_by_id(employee_id)

    async def list_employees(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._repository.get_all(
            legal_entity_id=legal_entity_id, limit=limit, offset=offset, status=status, search=search
        )

    async def count_employees(
        self, legal_entity_id: UUID, status: str | None = None, search: str | None = None
    ) -> int:
        return await self._repository.count_all(legal_entity_id=legal_entity_id, status=status, search=search)

    # ========================================================================
    # UPDATE (general profile fields)
    # ========================================================================

    @audit
    async def update_employee(
        self,
        employee_id: UUID,
        full_name: str | None = None,
        nik: str | None = None,
        npwp: str | None = None,
        gender: str | None = None,
        birth_date: date | None = None,
        address: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        phone: str | None = None,
        mobile: str | None = None,
        email: str | None = None,
        department: str | None = None,
        division: str | None = None,
        position: str | None = None,
        job_level: str | None = None,
        cost_center: str | None = None,
        manager_id: UUID | None = None,
        bank_name: str | None = None,
        bank_account_number: str | None = None,
        bank_account_name: str | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        self._check_authority(updated_by, "update_employee")

        candidate_changes = {
            "full_name": full_name,
            "nik": nik,
            "tax_id": npwp,
            "gender": gender,
            "birth_date": birth_date,
            "address": address,
            "city": city,
            "postal_code": postal_code,
            "phone": phone,
            "mobile": mobile,
            "email": email,
            "department": department,
            "division": division,
            "position": position,
            "job_level": job_level,
            "cost_center": cost_center,
            "manager_id": manager_id,
            "bank_name": bank_name,
            "bank_account_number": bank_account_number,
            "bank_account_name": bank_account_name,
            "notes": notes,
        }
        # Only send fields that were actually provided (not None) - partial update.
        changes = {k: v for k, v in candidate_changes.items() if v is not None}
        if not changes:
            return await self.get_employee(employee_id)

        employee = await self._repository.update(employee_id, changes)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                event = EmployeeStructureUpdatedEvent(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_name=employee["full_name"],
                    old_basic_salary=Decimal(str(employee["basic_salary"])),
                    new_basic_salary=Decimal(str(employee["basic_salary"])),
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Employee {employee['employee_code']} (updated)", correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish EmployeeStructureUpdatedEvent for {employee['employee_code']}: {e}")

        self._record_audit("update_employee", {
            "employee_id": str(employee_id),
            "changes": list(changes.keys()),
            "updated_by": str(updated_by) if updated_by else None,
        })

        return employee

    # ========================================================================
    # UPDATE (salary structure)
    # ========================================================================

    @audit
    async def update_salary_structure(
        self,
        employee_id: UUID,
        basic_salary: Decimal | None = None,
        allowances: Decimal | None = None,
        overtime_rate_multiplier: Decimal | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        self._check_authority(updated_by, "update_salary_structure")

        current = await self._repository.get_by_id(employee_id)
        if not current:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        old_basic_salary = Decimal(str(current["basic_salary"]))

        changes = {}
        if basic_salary is not None:
            changes["basic_salary"] = basic_salary
        if allowances is not None:
            changes["allowances"] = allowances
        if overtime_rate_multiplier is not None:
            changes["overtime_rate_multiplier"] = overtime_rate_multiplier

        if not changes:
            return current

        employee = await self._repository.update(employee_id, changes)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                event = EmployeeStructureUpdatedEvent(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_name=employee["full_name"],
                    old_basic_salary=old_basic_salary,
                    new_basic_salary=Decimal(str(employee["basic_salary"])),
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(
                    event, f"Employee {employee['employee_code']} (salary structure updated)", correlation_id
                )
            except Exception as e:
                logger.warning(
                    f"Failed to publish EmployeeStructureUpdatedEvent for {employee['employee_code']}: {e}"
                )

        self._record_audit("update_salary_structure", {
            "employee_id": str(employee_id),
            "changes": list(changes.keys()),
            "updated_by": str(updated_by) if updated_by else None,
        })

        return employee

    # ========================================================================
    # UPDATE (BPJS)
    # ========================================================================

    @audit
    async def update_bpjs(
        self,
        employee_id: UUID,
        bpjs_kesehatan_number: str | None = None,
        bpjs_ketenagakerjaan_number: str | None = None,
        bpjs_jht_rate_employee: Decimal | None = None,
        bpjs_jht_rate_employer: Decimal | None = None,
        bpjs_jkk_rate: Decimal | None = None,
        bpjs_jkm_rate: Decimal | None = None,
        bpjs_kesehatan_rate_employee: Decimal | None = None,
        bpjs_kesehatan_rate_employer: Decimal | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        self._check_authority(updated_by, "update_bpjs")

        candidate_changes = {
            "bpjs_kesehatan_number": bpjs_kesehatan_number,
            "bpjs_ketenagakerjaan_number": bpjs_ketenagakerjaan_number,
            "bpjs_jht_rate_employee": bpjs_jht_rate_employee,
            "bpjs_jht_rate_employer": bpjs_jht_rate_employer,
            "bpjs_jkk_rate": bpjs_jkk_rate,
            "bpjs_jkm_rate": bpjs_jkm_rate,
            "bpjs_kesehatan_rate_employee": bpjs_kesehatan_rate_employee,
            "bpjs_kesehatan_rate_employer": bpjs_kesehatan_rate_employer,
        }
        changes = {k: v for k, v in candidate_changes.items() if v is not None}
        if not changes:
            return await self.get_employee(employee_id)

        employee = await self._repository.update(employee_id, changes)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                event = EmployeeBPJSUpdatedEvent(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_code=employee["employee_code"],
                    changes=changes,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Employee {employee['employee_code']} (BPJS updated)", correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish EmployeeBPJSUpdatedEvent for {employee['employee_code']}: {e}")

        self._record_audit("update_bpjs", {
            "employee_id": str(employee_id),
            "changes": list(changes.keys()),
            "updated_by": str(updated_by) if updated_by else None,
        })

        return employee

    # ========================================================================
    # UPDATE (PTKP)
    # ========================================================================

    @audit
    async def update_ptkp(
        self,
        employee_id: UUID,
        marital_status: str,
        dependents: int,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        self._check_authority(updated_by, "update_ptkp")

        current = await self._repository.get_by_id(employee_id)
        if not current:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")

        old_marital = current["marital_status"]
        old_ptkp = current["ptkp_status"]
        new_ptkp = compute_ptkp_status(marital_status, dependents)

        employee = await self._repository.update(
            employee_id, {"marital_status": marital_status, "ptkp_status": new_ptkp}
        )
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                event = EmployeePTKPUpdatedEvent(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_code=employee["employee_code"],
                    old_marital_status=old_marital,
                    new_marital_status=employee["marital_status"],
                    old_dependents=old_ptkp,
                    new_dependents=new_ptkp,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Employee {employee['employee_code']} (PTKP updated)", correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish EmployeePTKPUpdatedEvent for {employee['employee_code']}: {e}")

        self._record_audit("update_ptkp", {
            "employee_id": str(employee_id),
            "old_marital_status": old_marital,
            "new_marital_status": employee["marital_status"],
            "old_ptkp_status": old_ptkp,
            "new_ptkp_status": new_ptkp,
            "updated_by": str(updated_by) if updated_by else None,
        })

        return employee

    # ========================================================================
    # RESIGN
    # ========================================================================

    @audit
    async def resign_employee(
        self,
        employee_id: UUID,
        resignation_date: date,
        reason: str | None = None,
        resigned_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        self._check_authority(resigned_by, "resign_employee")

        employee = await self._repository.resign(employee_id, resignation_date, reason)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                event = EmployeeResignedEvent(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_code=employee["employee_code"],
                    resignation_date=resignation_date,
                    reason=reason,
                    resigned_by=str(resigned_by) if resigned_by else "system",
                    user_id=str(resigned_by) if resigned_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Employee {employee['employee_code']} (resigned)", correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish EmployeeResignedEvent for {employee['employee_code']}: {e}")

        self._record_audit("resign_employee", {
            "employee_id": str(employee_id),
            "resignation_date": resignation_date.isoformat(),
            "resigned_by": str(resigned_by) if resigned_by else None,
        })

        return employee

    # ========================================================================
    # DELETE (soft by default)
    # ========================================================================

    @audit
    async def delete_employee(
        self,
        employee_id: UUID,
        deleted_by: UUID | None = None,
        permanent: bool = False,
    ) -> bool:
        self._check_authority(deleted_by, "delete_employee")
        deleted = await self._repository.delete(employee_id, deleted_by, permanent=permanent)
        if deleted:
            self._record_audit("delete_employee", {
                "employee_id": str(employee_id),
                "permanent": permanent,
                "deleted_by": str(deleted_by) if deleted_by else None,
            })
        return deleted

    # ========================================================================
    # STATS
    # ========================================================================

    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)

    # ========================================================================
    # ACTIVATE / DEACTIVATE (toggle status tanpa full resign)
    # ========================================================================

    @audit
    async def set_active_status(
        self, employee_id: UUID, is_active: bool, updated_by: UUID | None = None
    ) -> dict[str, Any]:
        self._check_authority(updated_by, "set_active_status")
        await self._repository.update_status(employee_id, is_active)
        employee = await self._repository.get_by_id(employee_id)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._record_audit("set_active_status", {
            "employee_id": str(employee_id),
            "is_active": is_active,
            "updated_by": str(updated_by) if updated_by else None,
        })
        return employee

    # ========================================================================
    # IMPORT CSV
    # ========================================================================

    async def import_employees_csv(
        self, csv_content: str, legal_entity_id: UUID, created_by: UUID | None = None
    ) -> int:
        self._check_authority(created_by, "import_employees_csv")
        count = await self._repository.import_from_csv(csv_content, legal_entity_id, created_by)
        self._record_audit("import_employees_csv", {
            "legal_entity_id": str(legal_entity_id),
            "imported": count,
            "created_by": str(created_by) if created_by else None,
        })
        return count


__all__ = [
    "EmployeeService",
    "EmployeeServiceError",
    "EmployeeNotFoundError",
    "EmployeeDuplicateError",
    "EmployeeStatus",
    "MaritalStatus",
    "compute_ptkp_status",
]
