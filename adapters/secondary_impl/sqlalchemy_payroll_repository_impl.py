#!/usr/bin/env python3
"""
Module: sqlalchemy_payroll_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Payroll menggunakan SQLAlchemy.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.employee_table import EmployeeTable
from infrastructure.persistence_orm.payroll_payslip_table import PayrollPayslipTable
from infrastructure.persistence_orm.payroll_run_table import PayrollRunTable
from infrastructure.persistence_orm.salary_component_table import SalaryComponentTable
from ports.primary.payroll_repository_port import PayrollRepositoryPort

logger = logging.getLogger(__name__)


class SQLAlchemyPayrollRepository(PayrollRepositoryPort):
    """SQLAlchemy implementation of PayrollRepositoryPort."""

    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========== Payroll Run ==========
    async def save_payroll_run(self, payroll_run: Any) -> Any:
        session = await self._get_session()
        # Ensure legal_entity_id is set if not provided
        if not getattr(payroll_run, "legal_entity_id", None):
            payroll_run.legal_entity_id = self._get_legal_entity_id()
        session.add(payroll_run)
        await session.flush()
        return payroll_run

    async def get_payroll_run(self, run_id: UUID, legal_entity_id: UUID) -> Any | None:
        session = await self._get_session()
        stmt = select(PayrollRunTable).where(
            PayrollRunTable.id == run_id,
            PayrollRunTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_payroll_runs_by_period(
        self, period_year: int, period_month: int, legal_entity_id: UUID
    ) -> list[Any]:
        session = await self._get_session()
        stmt = select(PayrollRunTable).where(
            PayrollRunTable.period_year == period_year,
            PayrollRunTable.period_month == period_month,
            PayrollRunTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def find_payrolls_by_period(
        self, period_year: int, period_month: int, legal_entity_id: UUID
    ) -> list[Any]:
        """Alias for get_payroll_runs_by_period."""
        return await self.get_payroll_runs_by_period(period_year, period_month, legal_entity_id)

    async def update_payroll_run_status(self, run_id: UUID, status: str) -> None:
        """Update payroll run status with pessimistic locking."""
        session = await self._get_session()
        async with session.begin():
            stmt_lock = select(PayrollRunTable).where(
                PayrollRunTable.id == run_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            run = result.scalar_one_or_none()
            if not run:
                raise ValueError(f"Payroll run {run_id} not found")
            run.status = status
            await session.flush()

    async def save_payroll(self, payroll: Any) -> None:
        session = await self._get_session()
        existing = await session.get(PayrollRunTable, payroll.id)
        if existing:
            for key, value in payroll.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(payroll)
        await session.flush()

    # ========== Payslip ==========
    async def save_payslip(self, payslip: Any) -> Any:
        session = await self._get_session()
        session.add(payslip)
        await session.flush()
        return payslip

    async def get_payslip_by_id(self, payslip_id: UUID) -> Any | None:
        session = await self._get_session()
        stmt = select(PayrollPayslipTable).where(PayrollPayslipTable.id == payslip_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_payslips_by_employee(
        self, employee_id: UUID, from_date: date, to_date: date
    ) -> list[Any]:
        session = await self._get_session()
        stmt = select(PayrollPayslipTable).where(
            PayrollPayslipTable.employee_id == employee_id,
            PayrollPayslipTable.period_year.between(from_date.year, to_date.year),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_payslips_by_run(self, payroll_run_id: UUID) -> list[Any]:
        session = await self._get_session()
        stmt = select(PayrollPayslipTable).where(
            PayrollPayslipTable.payroll_run_id == payroll_run_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_employee(self, employee_id: UUID) -> list[Any]:
        """Find payslips by employee ID (without date filter)."""
        session = await self._get_session()
        stmt = select(PayrollPayslipTable).where(
            PayrollPayslipTable.employee_id == employee_id,
            PayrollPayslipTable.deleted_at.is_(None)
        ).order_by(PayrollPayslipTable.period_year.desc(), PayrollPayslipTable.period_month.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========== Salary Components ==========
    async def get_salary_components_by_employee(
        self, employee_id: UUID, effective_date: date
    ) -> list[Any]:
        session = await self._get_session()
        stmt = select(SalaryComponentTable).where(
            SalaryComponentTable.employee_id == employee_id,
            SalaryComponentTable.effective_date <= effective_date,
            (
                SalaryComponentTable.end_date.is_(None)
                | (SalaryComponentTable.end_date >= effective_date)
            ),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========== Employee ==========
    async def get_employee(self, employee_id: UUID, legal_entity_id: UUID) -> Any | None:
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.id == employee_id,
            EmployeeTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_employee_by_id(self, employee_id: UUID) -> Any | None:
        session = await self._get_session()
        stmt = select(EmployeeTable).where(EmployeeTable.id == employee_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_employees(self, legal_entity_id: UUID) -> list[Any]:
        session = await self._get_session()
        stmt = select(EmployeeTable).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.status == "active",
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_employees(self, legal_entity_id: UUID) -> list[Any]:
        return await self.get_active_employees(legal_entity_id)


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

SQLAlchemyPayrollRepositoryImpl = SQLAlchemyPayrollRepository

__all__ = ["SQLAlchemyPayrollRepository", "SQLAlchemyPayrollRepositoryImpl"]