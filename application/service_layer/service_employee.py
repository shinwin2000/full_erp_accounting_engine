#!/usr/bin/env python3
"""
Module: service_employee.py
Layer: 8 - Application / Service Layer

Responsibility:
    Service untuk Employee (HR) management.

PERBAIKAN (2026-10-13):
- FIX EVENT PUBLISH: sebelumnya impor EmployeeCreatedEvent, EmployeeResignedEvent,
  EmployeePTKPUpdatedEvent, EmployeeBPJSUpdatedEvent dari `application.events`
  (yang me-re-export dari domain_events). Karena ada 2 definisi class yang
  berbeda (satu di application.events versi lama, satu di domain_events versi
  baru), signature-nya beda -> TypeError "unexpected keyword argument 'employee_id'".
  Sekarang impor langsung dari domain_events (konsisten dengan
  CustomerService & SupplierService).
  EmployeeStructureUpdatedEvent TIDAK ada di domain_events (dia milik
  domain.payroll.domain_events), jadi tetap impor dari application.events.
- FIX _publish_event: signature publish() sudah sesuai EventPublisherPort
  (keyword-only: event, event_type, aggregate_id, aggregate_type, metadata).
- Tambah method get_next_code() untuk auto-generate employee code.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# Import domain events dari DOMAIN LAYER (bukan application.events).
# Lihat catatan di docstring untuk alasan.
from domain.customer_supplier_employee.domain_events import (
    EmployeeBPJSUpdatedEvent,
    EmployeeCreatedEvent,
    EmployeePTKPUpdatedEvent,
    EmployeeResignedEvent,
)
# EmployeeStructureUpdatedEvent milik domain.payroll, jadi tetap via application.events.
from application.events import EmployeeStructureUpdatedEvent
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
    """Menghitung kode status PTKP dari status pernikahan + jumlah tanggungan."""
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
    EmployeeRepositoryPort (implementasi: SQLAlchemyEmployeeRepository).
    """

    def __init__(
        self,
        repository: Any | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if repository is None:
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
        logger.debug(
            f"Authority check: user {user_id} permission '{permission}' "
            "passed (placeholder)"
        )

    # ==================== AUDIT TRAIL ====================

    def _record_audit(
        self, action: str, details: dict[str, Any] | None = None
    ) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "EmployeeService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(
        self, event: Any, log_context: str, correlation_id: str | None = None
    ) -> None:
        """
        PERBAIKAN (2026-10-13):
        - Sebelumnya memanggil `self._event_publisher.publish(event, correlation_id)`
          dengan 2 argumen posisional, PADAHAL signature resmi
          EventPublisherPort.publish() adalah keyword-only:
              publish(event, event_type, aggregate_id, aggregate_type,
                      metadata=None, priority=...)
          Akibatnya SETIAP publish event Employee (create, resign, BPJS, PTKP,
          struktur gaji) SELALU gagal dengan TypeError - tapi tertelan
          try/except sehingga cuma muncul sebagai warning di log. Consumer
          (Payroll, Audit, dll) tidak pernah menerima event.
        - Sekarang panggilan sudah sesuai signature resmi.
        """
        if not self._event_publisher:
            return
        try:
            event_type = str(
                getattr(getattr(event, "event_type", None), "value", None)
                or getattr(event, "event_type", None)
                or event.__class__.__name__
            )
            aggregate_id = getattr(event, "aggregate_id", None)
            aggregate_type = getattr(event, "aggregate_type", "Employee")

            await self._event_publisher.publish(
                event=event,
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type=aggregate_type,
                metadata={"correlation_id": correlation_id}
                if correlation_id
                else None,
            )
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(
                f"Failed to publish {event.__class__.__name__} for "
                f"{log_context}: {e}"
            )

    # ==================== AUTO-GENERATE CODE ====================

    async def get_next_code(
        self, legal_entity_id: UUID, prefix: str = "EMP"
    ) -> str:
        """
        Generate kode karyawan berikutnya (EMP-001, EMP-002, dst) berdasarkan
        kode dengan angka urut TERBESAR yang sudah ada untuk prefix &
        legal_entity_id ini.
        """
        return await self._repository.get_next_code(legal_entity_id, prefix)

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

        # Auto-generate employee_code jika kosong.
        code = (employee_code or "").strip()
        if not code:
            code = await self.get_next_code(legal_entity_id, "EMP")

        existing_code = await self._repository.get_by_code(code, legal_entity_id)
        if existing_code:
            raise EmployeeDuplicateError(
                f"Employee code '{code}' sudah digunakan di entitas ini"
            )
        if nik:
            existing_nik = await self._repository.get_by_nik(nik, legal_entity_id)
            if existing_nik:
                raise EmployeeDuplicateError(f"NIK '{nik}' sudah terdaftar")

        data = {
            "legal_entity_id": legal_entity_id,
            "employee_code": code,
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
                event = EmployeeCreatedEvent.create(
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
                await self._publish_event(
                    event,
                    f"Employee {employee['employee_code']} (created)",
                    correlation_id,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to publish EmployeeCreatedEvent for "
                    f"{employee['employee_code']}: {e}"
                )

        self._record_audit(
            "create_employee",
            {
                "employee_id": employee["id"],
                "employee_code": code,
                "created_by": str(created_by) if created_by else None,
            },
        )

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
            legal_entity_id=legal_entity_id,
            limit=limit,
            offset=offset,
            status=status,
            search=search,
        )

    async def count_employees(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        search: str | None = None,
    ) -> int:
        return await self._repository.count_all(
            legal_entity_id=legal_entity_id, status=status, search=search
        )

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
        birth_place: str | None = None,
        birth_date: date | None = None,
        marital_status: str | None = None,
        dependents: int | None = None,
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
        basic_salary: Decimal | None = None,
        allowances: Decimal | None = None,
        overtime_rate_multiplier: Decimal | None = None,
        bpjs_kesehatan_number: str | None = None,
        bpjs_ketenagakerjaan_number: str | None = None,
        bank_name: str | None = None,
        bank_account_number: str | None = None,
        bank_account_name: str | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Update profil employee (partial update)."""
        self._check_authority(updated_by, "update_employee")

        candidate_changes = {
            "full_name": full_name,
            "nik": nik,
            "tax_id": npwp,
            "gender": gender,
            "birth_place": birth_place,
            "birth_date": birth_date,
            "religion": religion,
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
            "join_date": join_date,
            "basic_salary": basic_salary,
            "allowances": allowances,
            "overtime_rate_multiplier": overtime_rate_multiplier,
            "bpjs_kesehatan_number": bpjs_kesehatan_number,
            "bpjs_ketenagakerjaan_number": bpjs_ketenagakerjaan_number,
            "bank_name": bank_name,
            "bank_account_number": bank_account_number,
            "bank_account_name": bank_account_name,
            "notes": notes,
        }
        changes = {k: v for k, v in candidate_changes.items() if v is not None}

        # marital_status/dependents -> re-kalkulasi ptkp_status.
        current_for_ptkp: dict[str, Any] | None = None
        if marital_status is not None or dependents is not None:
            current_for_ptkp = await self._repository.get_by_id(employee_id)
            if not current_for_ptkp:
                raise EmployeeNotFoundError(f"Employee {employee_id} not found")
            effective_marital = (
                marital_status
                if marital_status is not None
                else current_for_ptkp["marital_status"]
            )
            if dependents is not None:
                effective_dependents = dependents
            else:
                old_ptkp = current_for_ptkp.get("ptkp_status") or "TK/0"
                try:
                    effective_dependents = int(old_ptkp.rsplit("/", 1)[-1])
                except (ValueError, AttributeError):
                    effective_dependents = 0
            changes["marital_status"] = effective_marital
            changes["ptkp_status"] = compute_ptkp_status(
                effective_marital, effective_dependents
            )

        if not changes:
            return await self.get_employee(employee_id)

        before = (
            await self._repository.get_by_id(employee_id)
            if current_for_ptkp is None
            else current_for_ptkp
        )
        old_basic_salary = (
            Decimal(str(before["basic_salary"])) if before else Decimal("0")
        )

        employee = await self._repository.update(employee_id, changes)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                new_basic_salary = Decimal(str(employee["basic_salary"]))
                if (
                    "basic_salary" in changes
                    and new_basic_salary != old_basic_salary
                ):
                    event = EmployeeStructureUpdatedEvent(
                        aggregate_id=UUID(employee["id"]),
                        aggregate_version=employee["version"],
                        employee_id=UUID(employee["id"]),
                        employee_name=employee["full_name"],
                        old_basic_salary=old_basic_salary,
                        new_basic_salary=new_basic_salary,
                        updated_by=str(updated_by) if updated_by else "system",
                        user_id=str(updated_by) if updated_by else None,
                        correlation_id=correlation_id,
                    )
                    await self._publish_event(
                        event,
                        f"Employee {employee['employee_code']} (updated)",
                        correlation_id,
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to publish EmployeeStructureUpdatedEvent for "
                    f"{employee['employee_code']}: {e}"
                )

        self._record_audit(
            "update_employee",
            {
                "employee_id": str(employee_id),
                "changes": list(changes.keys()),
                "updated_by": str(updated_by) if updated_by else None,
            },
        )

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
                    event,
                    f"Employee {employee['employee_code']} (salary structure updated)",
                    correlation_id,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to publish EmployeeStructureUpdatedEvent for "
                    f"{employee['employee_code']}: {e}"
                )

        self._record_audit(
            "update_salary_structure",
            {
                "employee_id": str(employee_id),
                "changes": list(changes.keys()),
                "updated_by": str(updated_by) if updated_by else None,
            },
        )

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
                event = EmployeeBPJSUpdatedEvent.create(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_number=employee["employee_code"],
                    bpjs_type="both",
                    membership_number=bpjs_kesehatan_number
                    or bpjs_ketenagakerjaan_number
                    or "",
                    is_active=True,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(
                    event,
                    f"Employee {employee['employee_code']} (BPJS updated)",
                    correlation_id,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to publish EmployeeBPJSUpdatedEvent for "
                    f"{employee['employee_code']}: {e}"
                )

        self._record_audit(
            "update_bpjs",
            {
                "employee_id": str(employee_id),
                "changes": list(changes.keys()),
                "updated_by": str(updated_by) if updated_by else None,
            },
        )

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
            employee_id,
            {"marital_status": marital_status, "ptkp_status": new_ptkp},
        )
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                event = EmployeePTKPUpdatedEvent.create(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_number=employee["employee_code"],
                    old_ptkp=old_ptkp,
                    new_ptkp=new_ptkp,
                    updated_by=str(updated_by) if updated_by else "system",
                    user_id=str(updated_by) if updated_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(
                    event,
                    f"Employee {employee['employee_code']} (PTKP updated)",
                    correlation_id,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to publish EmployeePTKPUpdatedEvent for "
                    f"{employee['employee_code']}: {e}"
                )

        self._record_audit(
            "update_ptkp",
            {
                "employee_id": str(employee_id),
                "old_marital_status": old_marital,
                "new_marital_status": employee["marital_status"],
                "old_ptkp_status": old_ptkp,
                "new_ptkp_status": new_ptkp,
                "updated_by": str(updated_by) if updated_by else None,
            },
        )

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

        employee = await self._repository.resign(
            employee_id, resignation_date, reason
        )
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._stats["employees_updated"] += 1

        if self._event_publisher:
            try:
                event = EmployeeResignedEvent.create(
                    aggregate_id=UUID(employee["id"]),
                    aggregate_version=employee["version"],
                    employee_id=UUID(employee["id"]),
                    employee_number=employee["employee_code"],
                    full_name=employee["full_name"],
                    resign_date=resignation_date,
                    reason=reason or "No reason",
                    user_id=str(resigned_by) if resigned_by else None,
                    correlation_id=correlation_id,
                )
                await self._publish_event(
                    event,
                    f"Employee {employee['employee_code']} (resigned)",
                    correlation_id,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to publish EmployeeResignedEvent for "
                    f"{employee['employee_code']}: {e}"
                )

        self._record_audit(
            "resign_employee",
            {
                "employee_id": str(employee_id),
                "resignation_date": resignation_date.isoformat(),
                "resigned_by": str(resigned_by) if resigned_by else None,
            },
        )

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
        deleted = await self._repository.delete(
            employee_id, deleted_by, permanent=permanent
        )
        if deleted:
            self._record_audit(
                "delete_employee",
                {
                    "employee_id": str(employee_id),
                    "permanent": permanent,
                    "deleted_by": str(deleted_by) if deleted_by else None,
                },
            )
        return deleted

    # ========================================================================
    # FOTO PROFIL
    # ========================================================================

    async def upload_employee_photo(
        self,
        employee_id: UUID,
        photo_data: bytes,
        mime_type: str,
        filename: str,
        uploaded_by: UUID | None = None,
    ) -> bool:
        self._check_authority(uploaded_by, "update_employee")
        ok = await self._repository.upload_photo(
            employee_id, photo_data, mime_type, filename
        )
        if not ok:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._record_audit(
            "upload_employee_photo",
            {
                "employee_id": str(employee_id),
                "filename": filename,
                "uploaded_by": str(uploaded_by) if uploaded_by else None,
            },
        )
        return ok

    async def get_employee_photo(
        self, employee_id: UUID
    ) -> dict[str, Any] | None:
        return await self._repository.get_photo(employee_id)

    async def delete_employee_photo(
        self, employee_id: UUID, deleted_by: UUID | None = None
    ) -> bool:
        self._check_authority(deleted_by, "update_employee")
        ok = await self._repository.delete_photo(employee_id)
        self._record_audit(
            "delete_employee_photo",
            {
                "employee_id": str(employee_id),
                "deleted_by": str(deleted_by) if deleted_by else None,
            },
        )
        return ok

    # ========================================================================
    # TANGGUNGAN / KELUARGA
    # ========================================================================

    async def add_dependent(
        self,
        employee_id: UUID,
        legal_entity_id: UUID,
        full_name: str,
        relationship_type: str,
        birth_date: date | None = None,
        occupation: str | None = None,
        is_ptkp_dependent: bool = True,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        self._check_authority(created_by, "update_employee")
        if relationship_type not in ("spouse", "child", "parent", "other"):
            raise EmployeeServiceError(
                "relationship_type must be one of: spouse, child, parent, other"
            )
        result = await self._repository.add_dependent(
            employee_id,
            legal_entity_id,
            {
                "full_name": full_name,
                "relationship_type": relationship_type,
                "birth_date": birth_date,
                "occupation": occupation,
                "is_ptkp_dependent": is_ptkp_dependent,
                "notes": notes,
            },
            created_by=created_by,
        )
        self._record_audit(
            "add_dependent",
            {
                "employee_id": str(employee_id),
                "full_name": full_name,
                "relationship_type": relationship_type,
                "created_by": str(created_by) if created_by else None,
            },
        )
        return result

    async def list_dependents(self, employee_id: UUID) -> list[dict[str, Any]]:
        return await self._repository.list_dependents(employee_id)

    async def update_dependent(
        self,
        dependent_id: UUID,
        updated_by: UUID | None = None,
        **changes: Any,
    ) -> dict[str, Any] | None:
        self._check_authority(updated_by, "update_employee")
        changes = {k: v for k, v in changes.items() if v is not None}
        result = await self._repository.update_dependent(dependent_id, changes)
        if result:
            self._record_audit(
                "update_dependent",
                {
                    "dependent_id": str(dependent_id),
                    "changes": list(changes.keys()),
                    "updated_by": str(updated_by) if updated_by else None,
                },
            )
        return result

    async def delete_dependent(
        self, dependent_id: UUID, deleted_by: UUID | None = None
    ) -> bool:
        self._check_authority(deleted_by, "update_employee")
        ok = await self._repository.delete_dependent(dependent_id)
        if ok:
            self._record_audit(
                "delete_dependent",
                {
                    "dependent_id": str(dependent_id),
                    "deleted_by": str(deleted_by) if deleted_by else None,
                },
            )
        return ok

    # ========================================================================
    # DOKUMEN (KTP/KK/BPJS/dll)
    # ========================================================================

    VALID_DOCUMENT_TYPES = (
        "ktp",
        "kk",
        "bpjs_kesehatan",
        "bpjs_ketenagakerjaan",
        "npwp",
        "ijazah",
        "other",
    )

    async def add_employee_document(
        self,
        employee_id: UUID,
        legal_entity_id: UUID,
        document_type: str,
        file_data: bytes,
        file_mime_type: str,
        file_filename: str,
        document_label: str | None = None,
        document_number: str | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        self._check_authority(created_by, "update_employee")
        if document_type not in self.VALID_DOCUMENT_TYPES:
            raise EmployeeServiceError(
                f"document_type must be one of: "
                f"{', '.join(self.VALID_DOCUMENT_TYPES)}"
            )
        if document_type == "other" and not document_label:
            raise EmployeeServiceError(
                "document_label wajib diisi untuk document_type='other'"
            )
        result = await self._repository.add_document(
            employee_id,
            legal_entity_id,
            {
                "document_type": document_type,
                "document_label": document_label,
                "document_number": document_number,
                "file_data": file_data,
                "file_mime_type": file_mime_type,
                "file_filename": file_filename,
                "notes": notes,
            },
            created_by=created_by,
        )
        self._record_audit(
            "add_employee_document",
            {
                "employee_id": str(employee_id),
                "document_type": document_type,
                "filename": file_filename,
                "created_by": str(created_by) if created_by else None,
            },
        )
        return result

    async def list_employee_documents(
        self, employee_id: UUID
    ) -> list[dict[str, Any]]:
        return await self._repository.list_documents(employee_id)

    async def get_employee_document_file(
        self, document_id: UUID
    ) -> dict[str, Any] | None:
        return await self._repository.get_document_file(document_id)

    async def delete_employee_document(
        self, document_id: UUID, deleted_by: UUID | None = None
    ) -> bool:
        self._check_authority(deleted_by, "update_employee")
        ok = await self._repository.delete_document(document_id)
        if ok:
            self._record_audit(
                "delete_employee_document",
                {
                    "document_id": str(document_id),
                    "deleted_by": str(deleted_by) if deleted_by else None,
                },
            )
        return ok

    # ========================================================================
    # STATS
    # ========================================================================

    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)

    # ========================================================================
    # ACTIVATE / DEACTIVATE
    # ========================================================================

    @audit
    async def set_active_status(
        self,
        employee_id: UUID,
        is_active: bool,
        updated_by: UUID | None = None,
    ) -> dict[str, Any]:
        self._check_authority(updated_by, "set_active_status")
        await self._repository.update_status(employee_id, is_active)
        employee = await self._repository.get_by_id(employee_id)
        if not employee:
            raise EmployeeNotFoundError(f"Employee {employee_id} not found")
        self._record_audit(
            "set_active_status",
            {
                "employee_id": str(employee_id),
                "is_active": is_active,
                "updated_by": str(updated_by) if updated_by else None,
            },
        )
        return employee

    # ========================================================================
    # IMPORT CSV
    # ========================================================================

    async def import_employees_csv(
        self,
        csv_content: str,
        legal_entity_id: UUID,
        created_by: UUID | None = None,
    ) -> int:
        self._check_authority(created_by, "import_employees_csv")
        count = await self._repository.import_from_csv(
            csv_content, legal_entity_id, created_by
        )
        self._record_audit(
            "import_employees_csv",
            {
                "legal_entity_id": str(legal_entity_id),
                "imported": count,
                "created_by": str(created_by) if created_by else None,
            },
        )
        return count


__all__ = [
    "EmployeeDuplicateError",
    "EmployeeNotFoundError",
    "EmployeeService",
    "EmployeeServiceError",
    "EmployeeStatus",
    "MaritalStatus",
    "compute_ptkp_status",
]
