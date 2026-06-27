#!/usr/bin/env python3
"""
Module: sqlalchemy_employee_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of EmployeeRepositoryPort - LENGKAP.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.employee_repository_port import EmployeeRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# SQLAlchemy ORM Model (with added fields for completeness)
# ============================================================================

Base = declarative_base()


class EmployeeTable(Base):
    __tablename__ = "employees"
    __table_args__ = (
        Index("idx_employee_legal_entity", "legal_entity_id"),
        Index("idx_employee_code", "employee_code", unique=True),
        Index("idx_employee_npwp", "npwp"),
        Index("idx_employee_email", "email"),
        Index("idx_employee_nik", "nik"),
        Index("idx_employee_supervisor", "supervisor_id"),
        Index("idx_employee_deleted", "deleted_at"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    employee_code = Column(String(50), nullable=False, unique=True)
    employee_name = Column(String(200), nullable=False)
    nik = Column(String(30), nullable=True)  # National ID
    npwp = Column(String(20), nullable=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    province = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(String(100), nullable=True, default="Indonesia")
    position = Column(String(100), nullable=True)
    department = Column(String(100), nullable=True)
    supervisor_id = Column(PGUUID(as_uuid=True), nullable=True)  # Reference to another employee
    employment_status = Column(String(50), nullable=True)  # active, resigned, terminated, on_leave
    ptkp_status = Column(String(20), nullable=True)  # TK0, K1, etc.
    hourly_rate = Column(Numeric(20, 2), nullable=False, default=0)
    monthly_salary = Column(Numeric(20, 2), nullable=False, default=0)
    bank_account = Column(String(50), nullable=True)
    bank_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    def to_domain(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            employee_code=self.employee_code,
            employee_name=self.employee_name,
            nik=self.nik,
            npwp=self.npwp,
            email=self.email,
            phone=self.phone,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            country=self.country,
            position=self.position,
            department=self.department,
            supervisor_id=self.supervisor_id,
            employment_status=self.employment_status or "active",
            ptkp_status=self.ptkp_status or "TK0",
            hourly_rate=self.hourly_rate,
            monthly_salary=self.monthly_salary,
            bank_account=self.bank_account,
            bank_name=self.bank_name,
            is_active=self.is_active,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
            deleted_at=self.deleted_at,
        )


# ============================================================================
# Repository Implementation
# ============================================================================

class SQLAlchemyEmployeeRepository(EmployeeRepositoryPort):
    """SQLAlchemy implementation of EmployeeRepositoryPort - LENGKAP."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def _log_audit(self, action: str, employee_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "employee_id": str(employee_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # CRUD METHODS
    # ========================================================================

    async def add(self, employee) -> None:
        """Add a new employee."""
        await self.save(employee)

    async def update(self, employee) -> None:
        """Update an existing employee."""
        await self.save(employee)

    async def save(self, employee) -> None:
        """Save or update an employee."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(EmployeeTable).where(EmployeeTable.id == employee.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.employee_code = employee.employee_code
                existing.employee_name = employee.employee_name
                existing.nik = getattr(employee, "nik", None)
                existing.npwp = employee.npwp
                existing.email = employee.email
                existing.phone = employee.phone
                existing.address = employee.address
                existing.city = employee.city
                existing.province = employee.province
                existing.postal_code = employee.postal_code
                existing.country = employee.country
                existing.position = employee.position
                existing.department = employee.department
                existing.supervisor_id = getattr(employee, "supervisor_id", None)
                existing.employment_status = getattr(employee, "employment_status", "active")
                existing.ptkp_status = getattr(employee, "ptkp_status", "TK0")
                existing.hourly_rate = employee.hourly_rate
                existing.monthly_salary = employee.monthly_salary
                existing.bank_account = employee.bank_account
                existing.bank_name = employee.bank_name
                existing.is_active = employee.is_active
                existing.updated_at = datetime.now(UTC)
                await self._log_audit("UPDATE", employee.id, {"employee_code": employee.employee_code})
            else:
                # Insert new
                new_row = EmployeeTable(
                    id=employee.id or uuid4(),
                    legal_entity_id=employee.legal_entity_id,
                    employee_code=employee.employee_code,
                    employee_name=employee.employee_name,
                    nik=getattr(employee, "nik", None),
                    npwp=employee.npwp,
                    email=employee.email,
                    phone=employee.phone,
                    address=employee.address,
                    city=employee.city,
                    province=employee.province,
                    postal_code=employee.postal_code,
                    country=employee.country,
                    position=employee.position,
                    department=employee.department,
                    supervisor_id=getattr(employee, "supervisor_id", None),
                    employment_status=getattr(employee, "employment_status", "active"),
                    ptkp_status=getattr(employee, "ptkp_status", "TK0"),
                    hourly_rate=employee.hourly_rate,
                    monthly_salary=employee.monthly_salary,
                    bank_account=employee.bank_account,
                    bank_name=employee.bank_name,
                    is_active=employee.is_active,
                    created_by=employee.created_by,
                )
                session.add(new_row)
                await self._log_audit("ADD", new_row.id, {"employee_code": employee.employee_code})

    async def get_by_id(self, employee_id: UUID):
        """Get employee by ID."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.id == employee_id,
            EmployeeTable.deleted_at.is_(None)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return row.to_domain()

    async def get_by_code(self, employee_code: str, legal_entity_id: UUID):
        """Get employee by code within legal entity."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.employee_code == employee_code,
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return row.to_domain()

    async def get_by_email(self, email: str) -> Optional:
        """Get employee by email."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.email == email,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return row.to_domain()

    async def get_by_nik(self, nik: str, legal_entity_id: UUID):
        """Get employee by NIK (National ID)."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.nik == nik,
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return row.to_domain()

    # ===== FIX: delete signature sesuai port (2 required: employee_id, user_id) =====
    async def delete(self, employee_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Delete an employee (soft by default, hard if permanent=True)."""
        session = await self._get_session()
        async with session.begin():
            if permanent:
                stmt = delete(EmployeeTable).where(EmployeeTable.id == employee_id)
                result = await session.execute(stmt)
                success = result.rowcount > 0
            else:
                stmt = (
                    update(EmployeeTable)
                    .where(EmployeeTable.id == employee_id)
                    .values(deleted_at=datetime.now(UTC), is_active=False)
                )
                result = await session.execute(stmt)
                success = result.rowcount > 0
            if success:
                await self._log_audit("DELETE" if permanent else "SOFT_DELETE", employee_id, {"permanent": permanent, "user_id": str(user_id)})
            return success

    # ===== FIX: restore signature sesuai port (2 required: employee_id, user_id) =====
    async def restore(self, employee_id: UUID, user_id: UUID) -> bool:
        """Restore a soft-deleted employee."""
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(EmployeeTable)
                .where(EmployeeTable.id == employee_id)
                .values(deleted_at=None, is_active=True, updated_at=datetime.now(UTC))
            )
            result = await session.execute(stmt)
            if result.rowcount > 0:
                await self._log_audit("RESTORE", employee_id, {"user_id": str(user_id)})
                return True
            return False

    async def resign(self, employee_id: UUID, resignation_date: datetime, reason: str) -> bool:
        """Mark employee as resigned."""
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(EmployeeTable)
                .where(EmployeeTable.id == employee_id)
                .values(
                    employment_status="resigned",
                    is_active=False,
                    updated_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            if result.rowcount > 0:
                await self._log_audit("RESIGN", employee_id, {"reason": reason, "date": resignation_date.isoformat()})
                return True
            return False

    # ========================================================================
    # QUERY METHODS
    # ========================================================================

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, is_active: bool | None = None
    ) -> list:
        """List employees for a legal entity."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        )
        if is_active is not None:
            stmt = stmt.where(EmployeeTable.is_active == is_active)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [row.to_domain() for row in rows]

    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list:
        """Get all employees with pagination."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        ).order_by(EmployeeTable.employee_code).limit(limit).offset(offset)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [row.to_domain() for row in rows]

    async def find_by_name_contains(
        self, name_fragment: str, legal_entity_id: UUID, limit: int = 50
    ) -> list:
        """Search employees by name (partial match)."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.employee_name.ilike(f"%{name_fragment}%"),
            EmployeeTable.deleted_at.is_(None),
        ).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [row.to_domain() for row in rows]

    async def find_by_department(
        self, department: str, legal_entity_id: UUID
    ) -> list:
        """Find employees by department."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.department == department,
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [row.to_domain() for row in rows]

    async def find_by_status(
        self, status: str, legal_entity_id: UUID
    ) -> list:
        """Find employees by employment status."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.employment_status == status,
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [row.to_domain() for row in rows]

    async def find_by_employment_status(
        self, status: str, legal_entity_id: UUID
    ) -> list:
        """Alias for find_by_status."""
        return await self.find_by_status(status, legal_entity_id)

    async def find_by_supervisor(
        self, supervisor_id: UUID, legal_entity_id: UUID
    ) -> list:
        """Find employees reporting to a supervisor."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.supervisor_id == supervisor_id,
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [row.to_domain() for row in rows]

    async def get_by_supervisor(
        self, supervisor_id: UUID, legal_entity_id: UUID
    ) -> list:
        """Get employees by supervisor ID (alias for find_by_supervisor)."""
        return await self.find_by_supervisor(supervisor_id, legal_entity_id)

    async def find_active_for_payroll(
        self, legal_entity_id: UUID, cutoff_date: datetime
    ) -> list:
        """Find active employees that should be included in payroll."""
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.is_active == True,
            EmployeeTable.employment_status == "active",
            EmployeeTable.monthly_salary > 0,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [row.to_domain() for row in rows]

    async def update_status(self, employee_id: UUID, is_active: bool) -> None:
        """Update employee active status."""
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(EmployeeTable)
                .where(EmployeeTable.id == employee_id)
                .values(is_active=is_active, updated_at=datetime.now(UTC))
            )
            await session.execute(stmt)

    # ========================================================================
    # STATISTICS & SUMMARY
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Get employee statistics."""
        session = await self._get_session()
        total_stmt = select(func.count()).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        )
        total = (await session.execute(total_stmt)).scalar() or 0
        active_stmt = select(func.count()).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.is_active == True,
            EmployeeTable.deleted_at.is_(None),
        )
        active = (await session.execute(active_stmt)).scalar() or 0
        resigned_stmt = select(func.count()).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.employment_status == "resigned",
            EmployeeTable.deleted_at.is_(None),
        )
        resigned = (await session.execute(resigned_stmt)).scalar() or 0
        dept_stmt = select(EmployeeTable.department, func.count()).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.deleted_at.is_(None),
        ).group_by(EmployeeTable.department)
        dept_result = await session.execute(dept_stmt)
        departments = {row[0]: row[1] for row in dept_result.all()}
        return {
            "total_employees": total,
            "active_employees": active,
            "resigned_employees": resigned,
            "departments": departments,
        }

    async def get_total_salary_cost(
        self, legal_entity_id: UUID, month: int, year: int
    ) -> Decimal:
        """Get total monthly salary cost for a period."""
        session = await self._get_session()
        stmt = select(func.coalesce(func.sum(EmployeeTable.monthly_salary), 0)).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.is_active == True,
            EmployeeTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        total = result.scalar() or 0
        return Decimal(str(total))

    # ===== FIX: get_ptkp_value signature sesuai port (2 required: employee_id, year) =====
    async def get_ptkp_value(self, employee_id: UUID, year: int) -> Decimal:
        """Get PTKP (tax allowance) for employee based on ptkp_status."""
        employee = await self.get_by_id(employee_id)
        if not employee:
            return Decimal(0)
        # PTKP amounts for 2024 (same for all years, but we could make it configurable)
        ptkp_map = {
            "TK0": Decimal("54000000"),
            "TK1": Decimal("58500000"),
            "TK2": Decimal("63000000"),
            "TK3": Decimal("67500000"),
            "K0": Decimal("58500000"),
            "K1": Decimal("63000000"),
            "K2": Decimal("67500000"),
            "K3": Decimal("72000000"),
        }
        status = getattr(employee, "ptkp_status", "TK0")
        # year parameter can be used for future adjustment (different rates per year)
        # Currently using fixed rates
        return ptkp_map.get(status, Decimal("54000000"))

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        """Export employees to CSV string."""
        employees = await self.list_by_legal_entity(legal_entity_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "employee_code", "employee_name", "nik", "npwp", "email", "phone",
            "address", "city", "province", "postal_code", "country",
            "position", "department", "employment_status", "ptkp_status",
            "hourly_rate", "monthly_salary", "bank_account", "bank_name", "is_active"
        ])
        for emp in employees:
            writer.writerow([
                emp.employee_code,
                emp.employee_name,
                getattr(emp, "nik", ""),
                emp.npwp or "",
                emp.email or "",
                emp.phone or "",
                emp.address or "",
                emp.city or "",
                emp.province or "",
                emp.postal_code or "",
                emp.country or "",
                emp.position or "",
                emp.department or "",
                getattr(emp, "employment_status", "active"),
                getattr(emp, "ptkp_status", "TK0"),
                float(emp.hourly_rate),
                float(emp.monthly_salary),
                emp.bank_account or "",
                emp.bank_name or "",
                "1" if emp.is_active else "0",
            ])
        return output.getvalue()

    async def import_from_csv(
        self, csv_content: str, legal_entity_id: UUID, created_by: UUID
    ) -> int:
        """Import employees from CSV string."""
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        session = await self._get_session()
        async with session.begin():
            for row in reader:
                try:
                    from types import SimpleNamespace
                    emp = SimpleNamespace(
                        id=uuid4(),
                        legal_entity_id=legal_entity_id,
                        employee_code=row["employee_code"],
                        employee_name=row["employee_name"],
                        nik=row.get("nik"),
                        npwp=row.get("npwp"),
                        email=row.get("email"),
                        phone=row.get("phone"),
                        address=row.get("address"),
                        city=row.get("city"),
                        province=row.get("province"),
                        postal_code=row.get("postal_code"),
                        country=row.get("country", "Indonesia"),
                        position=row.get("position"),
                        department=row.get("department"),
                        supervisor_id=None,
                        employment_status=row.get("employment_status", "active"),
                        ptkp_status=row.get("ptkp_status", "TK0"),
                        hourly_rate=Decimal(row.get("hourly_rate", "0")),
                        monthly_salary=Decimal(row.get("monthly_salary", "0")),
                        bank_account=row.get("bank_account"),
                        bank_name=row.get("bank_name"),
                        is_active=row.get("is_active", "1") == "1",
                        created_by=created_by,
                    )
                    await self.save(emp)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to import employee row: {e}")
        return count

    # ========================================================================
    # AUDIT LOG
    # ========================================================================

    async def get_audit_log(
        self, employee_id: UUID | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get audit log for employee operations."""
        logs = self._audit_log
        if employee_id:
            logs = [l for l in logs if l.get("employee_id") == str(employee_id)]
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[:limit]

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    async def health_check(self) -> dict[str, Any]:
        """Check health of the repository."""
        try:
            session = await self._get_session()
            await session.execute(select(1))
            return {"status": "healthy", "repository": "EmployeeRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "EmployeeRepository", "error": str(e)}


# ============================================================================
# ALIAS FOR ADAPTER REGISTRY
# ============================================================================

SQLAlchemyEmployeeRepositoryImpl = SQLAlchemyEmployeeRepository

__all__ = [
    "EmployeeTable",
    "SQLAlchemyEmployeeRepository",
    "SQLAlchemyEmployeeRepositoryImpl",
]
