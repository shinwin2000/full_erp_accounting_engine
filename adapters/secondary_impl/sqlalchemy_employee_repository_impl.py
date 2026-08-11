#!/usr/bin/env python3
"""
Module: sqlalchemy_employee_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of EmployeeRepositoryPort.

PENTING (fix 2026-08-07): Versi sebelumnya mendefinisikan `EmployeeTable`-nya
SENDIRI lewat `declarative_base()` terpisah, menunjuk ke tabel "employees"
(jamak) yang TIDAK PERNAH dibuat oleh migration manapun — migration
0006_customer_supplier_employee_master.py membuat tabel "employee" (tunggal)
lewat `infrastructure.persistence_orm.employee_table.EmployeeTable`, yang
juga sudah dipakai oleh Payslip/TimeEntry/SalaryComponent (relationship).
Akibatnya setiap query repository lama akan gagal dengan
`relation "employees" does not exist` begitu benar-benar disentuh DB.

Repository ini sekarang HANYA memakai `EmployeeTable` yang asli (metadata
Base yang sama dengan seluruh aplikasi), sehingga data yang disimpan lewat
API benar-benar tersimpan di database dan konsisten dengan modul lain
(Payroll, Attendance) yang sudah bergantung pada skema tabel `employee`.

Semua method mengembalikan `dict` hasil `EmployeeTable.to_dict()` (dibangun
SEBELUM transaksi commit/keluar dari `async with`), supaya pemanggil tidak
pernah menyentuh instance ORM yang sudah detached dari session (yang akan
meledak jadi `MissingGreenlet`/`DetachedInstanceError` pada SQLAlchemy async).
"""

from __future__ import annotations

import csv
import io
import logging
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update

from infrastructure.persistence_orm.employee_table import EmployeeTable
from ports.primary.employee_repository_port import EmployeeRepositoryPort

logger = logging.getLogger(__name__)


class _Unset:
    """Sentinel distinguishing 'field not provided' from 'field explicitly set to None'."""

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()


class EmployeeRecord(dict):
    """Dict yang juga bisa diakses lewat notasi atribut (`.id`, `.full_name`,
    dst), bukan cuma `["id"]`.

    Kenapa: EmployeeRepositoryPort dipakai juga oleh
    `application/service_layer/service_payroll.py` dan
    `transformers/hr_to_payroll.py`, dan keduanya mengakses hasil query
    lewat atribut (mis. `employee.employee_code`, `[e.id for e in
    employees]`) - warisan dari implementasi lama yang mengembalikan
    `SimpleNamespace`. Kelas ini mempertahankan kompatibilitas itu sambil
    tetap bisa dipakai sebagai dict biasa (`.get()`, `["key"]`) di
    service_employee.py sendiri.
    """

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value) -> None:
        self[name] = value


class SQLAlchemyEmployeeRepository(EmployeeRepositoryPort):
    """SQLAlchemy implementation of EmployeeRepositoryPort backed by the
    real `employee` table (infrastructure.persistence_orm.employee_table)."""

    def __init__(self, session: Any | None = None):
        # `session` di sini hanya untuk kasus caller yang SENGAJA ingin
        # mengelola siklus hidup session sendiri (mis. unit test). Untuk
        # pemakaian normal (lewat IoC container), biarkan None.
        self._injected_session = session
        self._audit_log: list[dict[str, Any]] = []

    @asynccontextmanager
    async def _session_scope(self):
        """Selalu membuka AsyncSession BARU per pemanggilan (via
        `get_async_session_direct()`) dan selalu menutupnya di akhir -
        KECUALI session sudah di-inject eksplisit lewat konstruktor, di
        mana lifecycle-nya jadi tanggung jawab caller.

        PENTING (fix 2026-08-07): sebelumnya method ini (`_get_session`)
        meng-cache SATU AsyncSession di `self._session` dan memakainya
        ulang di semua pemanggilan berikutnya. Ini berbahaya karena
        `EmployeeService`/`SQLAlchemyEmployeeRepository` didaftarkan
        sebagai SINGLETON di IoC container (lihat
        bootstrap/dependency_container/service_registry.py) - satu
        AsyncSession yang sama akan dipakai bersamaan oleh SEMUA request
        yang datang selama server hidup. `AsyncSession` SQLAlchemy tidak
        aman dipakai oleh beberapa coroutine/request secara bersamaan;
        ini bisa menyebabkan data salah nyasar ke request lain atau error
        acak di bawah beban. Bug inilah juga penyebab error
        `TypeError: object async_generator can't be used in 'await'
        expression` sebelumnya - `get_async_session()` (tanpa `_direct`)
        adalah FastAPI dependency generator (dipakai lewat `Depends(...)`,
        bukan untuk di-`await` langsung). Perbaikannya memakai
        `get_async_session_direct()`, yang memang didesain untuk dipakai
        oleh repository yang mengurus siklus hidup session-nya sendiri.
        """
        if self._injected_session is not None:
            yield self._injected_session
            return

        from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct
        session = await get_async_session_direct()
        try:
            yield session
        finally:
            await session.close()

    async def _log_audit(self, action: str, employee_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "employee_id": str(employee_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    @staticmethod
    def _apply_fields(row: EmployeeTable, data: dict[str, Any]) -> None:
        """Assign only the attributes that are present (and not the sentinel
        `_UNSET`) in `data`, so partial updates never clobber existing values
        with None."""
        for key, value in data.items():
            if value is _UNSET:
                continue
            if hasattr(row, key):
                setattr(row, key, value)

    # ==================== CRUD ====================

    async def add(self, employee_data: dict[str, Any]) -> dict[str, Any]:
        """Insert a new employee row. `employee_data` keys must match
        EmployeeTable column names (see to_dict() for the canonical set)."""
        async with self._session_scope() as session:
            async with session.begin():
                row = EmployeeTable(id=employee_data.get("id") or uuid4())
                self._apply_fields(row, employee_data)
                session.add(row)
                await session.flush()
                result = EmployeeRecord(row.to_dict())
                await self._log_audit("ADD", row.id, {"employee_code": row.employee_code})
            return result

    async def update(self, employee_id: UUID, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Partial update: only keys present in `changes` are written."""
        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(EmployeeTable).where(
                    EmployeeTable.id == employee_id, EmployeeTable.deleted_at.is_(None)
                ).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                self._apply_fields(row, changes)
                row.increment_version()
                await session.flush()
                # `updated_at` uses a server-side onupdate (func.now()), so after an
                # UPDATE it's expired in-memory. Refresh explicitly (awaited) instead
                # of letting to_dict() trigger an implicit lazy-load, which crashes
                # with "MissingGreenlet" since sync attribute access can't await IO.
                await session.refresh(row)
                data = EmployeeRecord(row.to_dict())
                await self._log_audit("UPDATE", employee_id, {"changes": list(changes.keys())})
            return data

    async def save(self, employee_id: UUID | None, employee_data: dict[str, Any]) -> dict[str, Any]:
        """Upsert helper: update if `employee_id` exists, otherwise insert."""
        if employee_id is not None:
            existing = await self.update(employee_id, employee_data)
            if existing is not None:
                return existing
        return await self.add(employee_data)

    async def get_by_id(self, employee_id: UUID) -> dict[str, Any] | None:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.id == employee_id, EmployeeTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return EmployeeRecord(row.to_dict()) if row else None

    async def get_by_code(self, employee_code: str, legal_entity_id: UUID) -> dict[str, Any] | None:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.employee_code == employee_code,
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return EmployeeRecord(row.to_dict()) if row else None

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.email == email, EmployeeTable.deleted_at.is_(None)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return EmployeeRecord(row.to_dict()) if row else None

    async def get_by_nik(self, nik: str, legal_entity_id: UUID) -> dict[str, Any] | None:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.nik == nik,
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return EmployeeRecord(row.to_dict()) if row else None

    async def delete(self, employee_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(EmployeeTable).where(EmployeeTable.id == employee_id).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return False

                if permanent:
                    await session.delete(row)
                else:
                    row.deleted_at = datetime.now(UTC)
                    row.is_active = False
                    row.employment_status = "inactive"
                    row.increment_version()

                await self._log_audit(
                    "DELETE_PERMANENT" if permanent else "SOFT_DELETE", employee_id, {"user_id": str(user_id)}
                )
                return True

    async def restore(self, employee_id: UUID, user_id: UUID) -> bool:
        async with self._session_scope() as session:
            stmt = (
                update(EmployeeTable)
                .where(EmployeeTable.id == employee_id, EmployeeTable.deleted_at.is_not(None))
                .values(deleted_at=None, is_active=True, employment_status="active")
            )
            result = await session.execute(stmt)
            await session.commit()
            if result.rowcount > 0:
                await self._log_audit("RESTORE", employee_id, {"user_id": str(user_id)})
                return True
            return False

    async def resign(self, employee_id: UUID, resignation_date_value: date, reason: str | None) -> dict[str, Any] | None:
        async with self._session_scope() as session:
            async with session.begin():
                stmt = select(EmployeeTable).where(EmployeeTable.id == employee_id).with_for_update()
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if not row:
                    return None
                row.resign(resignation_date_value)
                if reason:
                    if row.extra_metadata is None:
                        row.extra_metadata = {}
                    row.extra_metadata["resignation_reason"] = reason
                await session.flush()
                # See update() above: updated_at has a server-side onupdate, so it's
                # expired after an UPDATE flush and must be refreshed explicitly.
                await session.refresh(row)
                data = EmployeeRecord(row.to_dict())
                await self._log_audit("RESIGN", employee_id, {"reason": reason, "date": resignation_date_value.isoformat()})
            return data

    # ==================== QUERY ====================

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list[dict[str, Any]]:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            if is_active is not None:
                stmt = stmt.where(EmployeeTable.is_active == is_active)
            stmt = stmt.order_by(EmployeeTable.employee_code)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [EmployeeRecord(row.to_dict()) for row in rows]

    async def get_all(
        self,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            if status:
                stmt = stmt.where(EmployeeTable.employment_status == status)
            if search:
                like = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        EmployeeTable.full_name.ilike(like),
                        EmployeeTable.employee_code.ilike(like),
                        EmployeeTable.nik.ilike(like),
                        EmployeeTable.email.ilike(like),
                    )
                )
            stmt = stmt.order_by(EmployeeTable.employee_code).limit(limit).offset(offset)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [EmployeeRecord(row.to_dict()) for row in rows]

    async def count_all(
        self, legal_entity_id: UUID, status: str | None = None, search: str | None = None
    ) -> int:
        async with self._session_scope() as session:
            stmt = select(func.count()).select_from(EmployeeTable).where(
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            if status:
                stmt = stmt.where(EmployeeTable.employment_status == status)
            if search:
                like = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        EmployeeTable.full_name.ilike(like),
                        EmployeeTable.employee_code.ilike(like),
                        EmployeeTable.nik.ilike(like),
                        EmployeeTable.email.ilike(like),
                    )
                )
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.full_name.ilike(f"%{name_fragment}%"),
                EmployeeTable.deleted_at.is_(None),
            ).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [EmployeeRecord(row.to_dict()) for row in rows]

    async def find_by_department(self, department: str, legal_entity_id: UUID) -> list[dict[str, Any]]:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.department == department,
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [EmployeeRecord(row.to_dict()) for row in rows]

    async def find_by_status(self, employment_status: str, legal_entity_id: UUID) -> list[dict[str, Any]]:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.employment_status == employment_status,
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [EmployeeRecord(row.to_dict()) for row in rows]

    async def find_by_employment_status(self, employment_status: str, legal_entity_id: UUID) -> list[dict[str, Any]]:
        return await self.find_by_status(employment_status, legal_entity_id)

    async def find_by_manager(self, manager_id: UUID, legal_entity_id: UUID) -> list[dict[str, Any]]:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.manager_id == manager_id,
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [EmployeeRecord(row.to_dict()) for row in rows]

    # kept for backward-compat naming used by earlier callers
    find_by_supervisor = find_by_manager
    get_by_supervisor = find_by_manager

    async def update_status(self, employee_id: UUID, is_active: bool) -> None:
        async with self._session_scope() as session, session.begin():
            stmt = select(EmployeeTable).where(EmployeeTable.id == employee_id).with_for_update()
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                if is_active:
                    row.activate()
                else:
                    row.deactivate()

    async def find_active_for_payroll(self, legal_entity_id: UUID, cutoff_date: datetime) -> list[dict[str, Any]]:
        async with self._session_scope() as session:
            stmt = select(EmployeeTable).where(
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.is_active == True,  # noqa: E712
                EmployeeTable.employment_status == "active",
                EmployeeTable.basic_salary > 0,
                EmployeeTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [EmployeeRecord(row.to_dict()) for row in rows]

    # application/service_layer/service_payroll.py memanggil method ini dengan
    # nama `list_active_employees(legal_entity_id, cutoff_date)` - urutan
    # parameternya sudah sama persis dengan find_active_for_payroll di atas,
    # jadi cukup di-alias tanpa perlu menukar urutan argumen.
    list_active_employees = find_active_for_payroll

    # ==================== STATISTICS ====================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        async with self._session_scope() as session:
            base_filter = (
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.deleted_at.is_(None),
            )
            total = (await session.execute(
                select(func.count()).where(*base_filter)
            )).scalar() or 0
            active = (await session.execute(
                select(func.count()).where(*base_filter, EmployeeTable.is_active == True)  # noqa: E712
            )).scalar() or 0
            resigned = (await session.execute(
                select(func.count()).where(*base_filter, EmployeeTable.employment_status == "resigned")
            )).scalar() or 0
            dept_result = await session.execute(
                select(EmployeeTable.department, func.count())
                .where(*base_filter)
                .group_by(EmployeeTable.department)
            )
            departments = {row[0] or "(tanpa departemen)": row[1] for row in dept_result.all()}
            return {
                "total_employees": total,
                "active_employees": active,
                "resigned_employees": resigned,
                "departments": departments,
            }

    async def get_total_salary_cost(
        self, legal_entity_id: UUID, month: int | None = None, year: int | None = None
    ) -> Decimal:
        # month/year diterima untuk mencocokkan EmployeeRepositoryPort persis
        # (dipertahankan untuk kompatibilitas API port, walau tabel employee
        # saat ini hanya menyimpan gaji "current", bukan histori per bulan -
        # jadi hasilnya sama untuk periode manapun sampai ada tabel histori gaji).
        async with self._session_scope() as session:
            stmt = select(func.coalesce(func.sum(EmployeeTable.basic_salary + EmployeeTable.allowances), 0)).where(
                EmployeeTable.legal_entity_id == legal_entity_id,
                EmployeeTable.is_active == True,  # noqa: E712
                EmployeeTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            total = result.scalar() or 0
            return Decimal(str(total))

    async def get_ptkp_value(self, employee_id: UUID, year: int | None = None) -> Decimal:
        # year diterima untuk mencocokkan EmployeeRepositoryPort persis (nilai
        # PTKP resmi bisa berubah per tahun pajak - saat ini hanya tabel UU
        # HPP 2022 yang tersedia, jadi year belum dipakai untuk membedakan).
        ptkp_map = {
            "TK/0": Decimal("54000000"), "TK/1": Decimal("58500000"),
            "TK/2": Decimal("63000000"), "TK/3": Decimal("67500000"),
            "K/0": Decimal("58500000"), "K/1": Decimal("63000000"),
            "K/2": Decimal("67500000"), "K/3": Decimal("72000000"),
        }
        employee = await self.get_by_id(employee_id)
        if not employee:
            return Decimal(0)
        return ptkp_map.get(employee.get("ptkp_status", "TK/0"), Decimal("54000000"))

    # ==================== EXPORT / IMPORT ====================

    _CSV_COLUMNS = [
        "employee_code", "full_name", "nik", "tax_id", "email", "phone", "mobile",
        "address", "city", "postal_code", "position", "department", "division",
        "employment_status", "ptkp_status", "basic_salary", "allowances",
        "bank_account_number", "bank_name", "is_active",
    ]

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        employees = await self.list_by_legal_entity(legal_entity_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(self._CSV_COLUMNS)
        for emp in employees:
            writer.writerow([emp.get(col, "") for col in self._CSV_COLUMNS])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                await self.add({
                    "legal_entity_id": legal_entity_id,
                    "employee_code": row["employee_code"],
                    "full_name": row["full_name"],
                    "nik": row.get("nik") or None,
                    "tax_id": row.get("tax_id") or None,
                    "email": row.get("email") or None,
                    "phone": row.get("phone") or None,
                    "mobile": row.get("mobile") or None,
                    "address": row.get("address") or None,
                    "city": row.get("city") or None,
                    "postal_code": row.get("postal_code") or None,
                    "position": row.get("position") or None,
                    "department": row.get("department") or None,
                    "division": row.get("division") or None,
                    "employment_status": row.get("employment_status") or "active",
                    "ptkp_status": row.get("ptkp_status") or "TK/0",
                    "basic_salary": Decimal(row.get("basic_salary") or "0"),
                    "allowances": Decimal(row.get("allowances") or "0"),
                    "bank_account_number": row.get("bank_account_number") or None,
                    "bank_name": row.get("bank_name") or None,
                    "is_active": (row.get("is_active", "1") in ("1", "true", "True")),
                    "created_by": created_by,
                })
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import employee row {row.get('employee_code')}: {e}")
        return count

    # ==================== AUDIT & HEALTH ====================

    async def get_audit_log(self, employee_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if employee_id:
            logs = [entry for entry in logs if entry.get("employee_id") == str(employee_id)]
        logs = sorted(logs, key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[:limit]

    async def health_check(self) -> dict[str, Any]:
        try:
            async with self._session_scope() as session:
                await session.execute(select(1))
            return {"status": "healthy", "repository": "EmployeeRepository", "table": EmployeeTable.__tablename__}
        except Exception as e:
            return {"status": "unhealthy", "repository": "EmployeeRepository", "error": str(e)}


# Alias for backward compatibility
SQLAlchemyEmployeeRepositoryImpl = SQLAlchemyEmployeeRepository

__all__ = [
    "SQLAlchemyEmployeeRepository",
    "SQLAlchemyEmployeeRepositoryImpl",
]
