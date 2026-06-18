#!/usr/bin/env python3
"""
Module: employee_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk master Employee (karyawan).
               Mendukung full CRUD, pencarian, filter departemen/jabatan, status aktif,
               payroll eligibility, BPJS, PTKP, NPWP, audit trail, import/export CSV,
               dan statistik SDM.
Audit: Setiap perubahan data karyawan tercatat.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class MaritalStatus(Enum):
    """Status perkawinan untuk PTKP."""

    SINGLE = "single"  # TK/0
    MARRIED = "married"  # K/0
    MARRIED_1 = "married_1"  # K/1
    MARRIED_2 = "married_2"  # K/2
    MARRIED_3 = "married_3"  # K/3
    DIVORCED = "divorced"  # Cerai


class Gender(Enum):
    MALE = "male"
    FEMALE = "female"


class EmploymentStatus(Enum):
    """Status kepegawaian."""

    PERMANENT = "permanent"
    CONTRACT = "contract"
    PROBATION = "probation"
    INTERN = "intern"
    PART_TIME = "part_time"
    FREELANCE = "freelance"


class EmployeeStatus(Enum):
    """Status aktif karyawan."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    RESIGNED = "resigned"
    TERMINATED = "terminated"
    ON_LEAVE = "on_leave"
    SUSPENDED = "suspended"


@dataclass(
    kw_only=True
)  # <--- Ditambahkan agar aman saat handling DTO/Aggregate di layer Ports & Application
class Employee:
    """
    Aggregate Root Employee / DTO Port Representation.
    """

    # ========== NON-DEFAULT FIELDS (Wajib Diisi / Tanpa Nilai Default) ==========
    id: UUID
    employee_nik: str  # Nomor Induk Karyawan unik
    full_name: str
    legal_entity_id: UUID
    gender: Gender
    birth_place: (
        str | None
    )  # Berstatus Optional tapi tidak memiliki default value bawaan instansiasi
    birth_date: (
        date | None
    )  # Berstatus Optional tapi tidak memiliki default value bawaan instansiasi
    marital_status: MaritalStatus
    npwp: str | None  # Nomor Pokok Wajib Pajak
    bpjs_ketenagakerjaan: str | None
    bpjs_kesehatan: str | None
    ptkp_status: MaritalStatus  # Untuk perhitungan PPh 21
    join_date: date  # <--- SEKARANG AMAN (Sudah digeser ke atas sebelum default fields)

    # ========== DEFAULT FIELDS (Boleh Kosong / Memiliki Nilai Default '=') ==========
    ptkp_dependents: int = 0  # Jumlah tanggungan (0-3)
    resign_date: date | None = None
    employment_status: EmploymentStatus = EmploymentStatus.PERMANENT
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    department_id: UUID | None = None
    position: str | None = None
    job_title: str | None = None
    level: int = 1  # Level jabatan (1-12)
    direct_supervisor_id: UUID | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    basic_salary: Decimal = Decimal(0)
    allowance: Decimal = Decimal(0)
    overtime_rate: Decimal = Decimal(
        "1.5"
    )  # Menggunakan string literal untuk akurasi presisi tinggi Decimal
    is_eligible_payroll: bool = True
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1
    deleted_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "employee_nik": self.employee_nik,
            "full_name": self.full_name,
            "legal_entity_id": str(self.legal_entity_id),
            "gender": self.gender.value,
            "birth_place": self.birth_place,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "marital_status": self.marital_status.value,
            "npwp": self.npwp,
            "bpjs_ketenagakerjaan": self.bpjs_ketenagakerjaan,
            "bpjs_kesehatan": self.bpjs_kesehatan,
            "ptkp_status": self.ptkp_status.value,
            "ptkp_dependents": self.ptkp_dependents,
            "join_date": self.join_date.isoformat(),
            "resign_date": self.resign_date.isoformat() if self.resign_date else None,
            "employment_status": self.employment_status.value,
            "status": self.status.value,
            "department_id": str(self.department_id) if self.department_id else None,
            "position": self.position,
            "job_title": self.job_title,
            "level": self.level,
            "direct_supervisor_id": str(self.direct_supervisor_id)
            if self.direct_supervisor_id
            else None,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "basic_salary": float(self.basic_salary),
            "allowance": float(self.allowance),
            "overtime_rate": float(self.overtime_rate),
            "is_eligible_payroll": self.is_eligible_payroll,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class EmployeeRepositoryPort:
    """
    In-memory repository untuk Employee.
    """

    def __init__(self):
        self._storage: dict[UUID, Employee] = {}
        self._nik_index: dict[tuple[str, UUID], Employee] = {}  # (employee_nik, legal_entity_id)
        self._department_index: dict[UUID, list[UUID]] = {}  # department_id -> employee ids
        self._status_index: dict[EmployeeStatus, list[UUID]] = {}
        self._employment_index: dict[EmploymentStatus, list[UUID]] = {}
        self._payroll_eligible_index: dict[UUID, list[UUID]] = {}  # legal_entity_id -> eligible ids
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, employee_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "employee_id": str(employee_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"EMPLOYEE AUDIT: {action} on {employee_id} by {user_id}")

    async def _update_indices(self, emp: Employee, is_insert: bool = True):
        nik_key = (emp.employee_nik, emp.legal_entity_id)
        if is_insert:
            self._nik_index[nik_key] = emp
        else:
            self._nik_index[nik_key] = emp
        # Department index
        if emp.department_id:
            if emp.department_id not in self._department_index:
                self._department_index[emp.department_id] = []
            if emp.id not in self._department_index[emp.department_id]:
                self._department_index[emp.department_id].append(emp.id)
        # Status index
        if emp.status not in self._status_index:
            self._status_index[emp.status] = []
        if emp.id not in self._status_index[emp.status]:
            self._status_index[emp.status].append(emp.id)
        # Employment status index
        if emp.employment_status not in self._employment_index:
            self._employment_index[emp.employment_status] = []
        if emp.id not in self._employment_index[emp.employment_status]:
            self._employment_index[emp.employment_status].append(emp.id)
        # Payroll eligible index
        if (
            emp.is_eligible_payroll
            and emp.deleted_at is None
            and emp.status == EmployeeStatus.ACTIVE
        ):
            if emp.legal_entity_id not in self._payroll_eligible_index:
                self._payroll_eligible_index[emp.legal_entity_id] = []
            if emp.id not in self._payroll_eligible_index[emp.legal_entity_id]:
                self._payroll_eligible_index[emp.legal_entity_id].append(emp.id)

    async def _remove_from_indices(self, emp: Employee):
        nik_key = (emp.employee_nik, emp.legal_entity_id)
        if nik_key in self._nik_index:
            del self._nik_index[nik_key]
        if emp.department_id and emp.department_id in self._department_index:
            if emp.id in self._department_index[emp.department_id]:
                self._department_index[emp.department_id].remove(emp.id)
        if emp.status in self._status_index and emp.id in self._status_index[emp.status]:
            self._status_index[emp.status].remove(emp.id)
        if (
            emp.employment_status in self._employment_index
            and emp.id in self._employment_index[emp.employment_status]
        ):
            self._employment_index[emp.employment_status].remove(emp.id)
        if (
            emp.legal_entity_id in self._payroll_eligible_index
            and emp.id in self._payroll_eligible_index[emp.legal_entity_id]
        ):
            self._payroll_eligible_index[emp.legal_entity_id].remove(emp.id)

    # ==================== CRUD ====================

    async def add(self, employee: Employee) -> None:
        if employee.id in self._storage:
            raise ValueError(f"Employee {employee.id} already exists")
        nik_key = (employee.employee_nik, employee.legal_entity_id)
        if nik_key in self._nik_index:
            raise ValueError(
                f"Employee NIK {employee.employee_nik} already exists for this legal entity"
            )
        employee.created_at = datetime.now(UTC)
        employee.updated_at = employee.created_at
        employee.version = 1
        async with self._lock:
            self._storage[employee.id] = employee
            await self._update_indices(employee, is_insert=True)
        await self._log_audit(
            "ADD",
            employee.id,
            employee.created_by,
            {
                "nik": employee.employee_nik,
                "name": employee.full_name,
            },
        )

    async def get_by_id(self, employee_id: UUID) -> Employee | None:
        emp = self._storage.get(employee_id)
        if emp and emp.deleted_at is not None:
            return None
        return emp

    async def get_by_nik(self, nik: str, legal_entity_id: UUID) -> Employee | None:
        emp = self._nik_index.get((nik, legal_entity_id))
        if emp and emp.deleted_at is not None:
            return None
        return emp

    async def update(self, employee: Employee) -> None:
        if employee.id not in self._storage:
            raise ValueError(f"Employee {employee.id} not found")
        old = self._storage[employee.id]
        if old.deleted_at is not None:
            raise ValueError("Cannot update deleted employee")
        # Update NIK index if changed
        old_key = (old.employee_nik, old.legal_entity_id)
        new_key = (employee.employee_nik, employee.legal_entity_id)
        if old_key != new_key:
            if new_key in self._nik_index and self._nik_index[new_key].id != employee.id:
                raise ValueError(f"NIK {employee.employee_nik} already exists")
            await self._remove_from_indices(old)
            await self._update_indices(employee, is_insert=True)
        else:
            await self._remove_from_indices(old)
            await self._update_indices(employee, is_insert=True)
        employee.updated_at = datetime.now(UTC)
        employee.version = old.version + 1
        employee.created_at = old.created_at
        employee.created_by = old.created_by
        self._storage[employee.id] = employee
        await self._log_audit("UPDATE", employee.id, employee.updated_by, {})

    async def delete(self, employee_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        emp = self._storage.get(employee_id)
        if not emp:
            return False
        if permanent:
            await self._remove_from_indices(emp)
            del self._storage[employee_id]
            await self._log_audit("DELETE_PERMANENT", employee_id, user_id, {})
        else:
            emp.deleted_at = datetime.now(UTC)
            emp.status = EmployeeStatus.INACTIVE
            emp.is_eligible_payroll = False
            emp.updated_by = user_id
            emp.updated_at = emp.deleted_at
            emp.version += 1
            await self._remove_from_indices(emp)
            await self._log_audit("DELETE_SOFT", employee_id, user_id, {})
        return True

    async def restore(self, employee_id: UUID, user_id: UUID) -> bool:
        emp = self._storage.get(employee_id)
        if not emp or emp.deleted_at is None:
            return False
        emp.deleted_at = None
        emp.status = EmployeeStatus.ACTIVE
        emp.is_eligible_payroll = True
        emp.updated_by = user_id
        emp.updated_at = datetime.now(UTC)
        emp.version += 1
        await self._update_indices(emp, is_insert=True)
        await self._log_audit("RESTORE", employee_id, user_id, {})
        return True

    # ==================== QUERY ====================

    async def find_active_for_payroll(
        self, as_of_date: date, legal_entity_id: UUID
    ) -> list[Employee]:
        """Karyawan aktif yang harus diproses payroll pada periode tertentu."""
        ids = self._payroll_eligible_index.get(legal_entity_id, [])
        result = []
        for eid in ids:
            emp = self._storage.get(eid)
            if emp and emp.join_date <= as_of_date:
                if emp.resign_date is None or emp.resign_date > as_of_date:
                    result.append(emp)
        return sorted(result, key=lambda x: x.employee_nik)

    async def find_by_department(
        self, department_id: UUID, legal_entity_id: UUID
    ) -> list[Employee]:
        ids = self._department_index.get(department_id, [])
        result = []
        for eid in ids:
            emp = self._storage.get(eid)
            if emp and emp.legal_entity_id == legal_entity_id and emp.deleted_at is None:
                result.append(emp)
        return result

    async def find_by_status(self, status: EmployeeStatus, legal_entity_id: UUID) -> list[Employee]:
        ids = self._status_index.get(status, [])
        return [
            self._storage[eid]
            for eid in ids
            if eid in self._storage
            and self._storage[eid].legal_entity_id == legal_entity_id
            and self._storage[eid].deleted_at is None
        ]

    async def find_by_employment_status(
        self, emp_status: EmploymentStatus, legal_entity_id: UUID
    ) -> list[Employee]:
        ids = self._employment_index.get(emp_status, [])
        return [
            self._storage[eid]
            for eid in ids
            if eid in self._storage
            and self._storage[eid].legal_entity_id == legal_entity_id
            and self._storage[eid].deleted_at is None
        ]

    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 20
    ) -> list[Employee]:
        fragment = name_fragment.lower()
        result = []
        for emp in self._storage.values():
            if emp.legal_entity_id == legal_entity_id and emp.deleted_at is None:
                if fragment in emp.full_name.lower() or fragment in emp.employee_nik.lower():
                    result.append(emp)
        return sorted(result, key=lambda x: x.full_name)[:limit]

    async def get_all(
        self,
        legal_entity_id: UUID,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Employee]:
        result = []
        for emp in self._storage.values():
            if emp.legal_entity_id == legal_entity_id:
                if not include_inactive and (
                    emp.deleted_at is not None or emp.status != EmployeeStatus.ACTIVE
                ):
                    continue
                result.append(emp)
        result.sort(key=lambda x: x.employee_nik)
        return result[offset : offset + limit]

    async def get_by_supervisor(self, supervisor_id: UUID, legal_entity_id: UUID) -> list[Employee]:
        return [
            emp
            for emp in self._storage.values()
            if emp.direct_supervisor_id == supervisor_id
            and emp.legal_entity_id == legal_entity_id
            and emp.deleted_at is None
        ]

    async def resign(self, employee_id: UUID, resign_date: date, user_id: UUID) -> bool:
        emp = await self.get_by_id(employee_id)
        if not emp:
            return False
        emp.status = EmployeeStatus.RESIGNED
        emp.resign_date = resign_date
        emp.is_eligible_payroll = False
        emp.updated_by = user_id
        emp.updated_at = datetime.now(UTC)
        emp.version += 1
        await self.update(emp)
        await self._log_audit(
            "RESIGN", employee_id, user_id, {"resign_date": resign_date.isoformat()}
        )
        return True

    # ==================== PAYROLL UTILITIES ====================

    async def get_ptkp_value(self, employee_id: UUID, year: int) -> int:
        """Hitung PTKP berdasarkan status dan tanggungan."""
        emp = await self.get_by_id(employee_id)
        if not emp:
            return 0
        base = 54000000  # PTKP untuk TK/0 (2024)
        if emp.ptkp_status == MaritalStatus.MARRIED:
            base += 4500000
        elif emp.ptkp_status == MaritalStatus.MARRIED_1:
            base += 4500000 + 4500000
        elif emp.ptkp_status == MaritalStatus.MARRIED_2:
            base += 4500000 + 9000000
        elif emp.ptkp_status == MaritalStatus.MARRIED_3:
            base += 4500000 + 13500000
        # Tanggungan
        dependents = min(emp.ptkp_dependents, 3)
        base += dependents * 4500000
        return base

    async def get_total_salary_cost(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> Decimal:
        total = Decimal(0)
        for emp in self._storage.values():
            if emp.legal_entity_id == legal_entity_id and emp.deleted_at is None:
                if emp.join_date <= end_date and (
                    emp.resign_date is None or emp.resign_date >= start_date
                ):
                    total += emp.basic_salary + emp.allowance
        return total

    # ==================== IMPORT/EXPORT ====================

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        employees = await self.get_all(legal_entity_id, include_inactive=True)
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "nik",
                "full_name",
                "gender",
                "join_date",
                "employment_status",
                "status",
                "department_id",
                "position",
                "basic_salary",
                "allowance",
                "npwp",
                "bpjs",
            ]
        )
        for e in employees:
            writer.writerow(
                [
                    e.employee_nik,
                    e.full_name,
                    e.gender.value,
                    e.join_date.isoformat(),
                    e.employment_status.value,
                    e.status.value,
                    str(e.department_id) if e.department_id else "",
                    e.position or "",
                    float(e.basic_salary),
                    float(e.allowance),
                    e.npwp or "",
                    e.bpjs_ketenagakerjaan or "",
                ]
            )
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        import io

        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                emp = Employee(
                    id=uuid4(),
                    employee_nik=row["nik"],
                    full_name=row["full_name"],
                    legal_entity_id=legal_entity_id,
                    gender=Gender(row["gender"]),
                    birth_place=None,
                    birth_date=None,
                    marital_status=MaritalStatus.SINGLE,
                    npwp=row.get("npwp"),
                    bpjs_ketenagakerjaan=row.get("bpjs"),
                    bpjs_kesehatan=None,
                    ptkp_status=MaritalStatus.SINGLE,
                    ptkp_dependents=0,
                    join_date=date.fromisoformat(row["join_date"]),
                    employment_status=EmploymentStatus(row["employment_status"]),
                    status=EmployeeStatus(row["status"]),
                    department_id=UUID(row["department_id"]) if row.get("department_id") else None,
                    position=row.get("position"),
                    basic_salary=Decimal(row.get("basic_salary", "0")),
                    allowance=Decimal(row.get("allowance", "0")),
                    created_by=user_id,
                    updated_by=user_id,
                )
                await self.add(emp)
                count += 1
            except Exception as e:
                logger.warning(f"Import employee failed: {e}")
        return count

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        employees = [
            e
            for e in self._storage.values()
            if e.legal_entity_id == legal_entity_id and e.deleted_at is None
        ]
        total = len(employees)
        active = sum(1 for e in employees if e.status == EmployeeStatus.ACTIVE)
        resigned = sum(1 for e in employees if e.status == EmployeeStatus.RESIGNED)
        total_salary = sum(e.basic_salary + e.allowance for e in employees)
        return {
            "total_employees": total,
            "active": active,
            "resigned": resigned,
            "on_leave": sum(1 for e in employees if e.status == EmployeeStatus.ON_LEAVE),
            "by_employment_status": {
                es.value: sum(1 for e in employees if e.employment_status == es)
                for es in EmploymentStatus
            },
            "total_monthly_salary": float(total_salary),
            "average_salary": float(total_salary / total) if total > 0 else 0,
            "by_department": {},
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "total_employees": len(self._storage),
            "payroll_eligible": sum(len(lst) for lst in self._payroll_eligible_index.values()),
            "audit_log_size": len(self._audit_log),
        }
