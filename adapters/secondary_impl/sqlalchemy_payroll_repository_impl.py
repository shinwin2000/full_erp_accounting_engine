#!/usr/bin/env python3
"""
Module: sqlalchemy_payroll_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Payroll menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.employee_table import EmployeeTable
from infrastructure.persistence_orm.payroll_payslip_table import PayrollPayslipTable
from infrastructure.persistence_orm.payroll_run_table import PayrollRunTable
from infrastructure.persistence_orm.salary_component_table import SalaryComponentTable
from ports.primary.payroll_repository_port import PayrollRepositoryPort


class SQLAlchemyPayrollRepository(PayrollRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    # ========== Payroll Run ==========
    async def save_payroll_run(self, run: PayrollRunTable) -> PayrollRunTable:
        self._session.add(run)
        await self._session.flush()
        return run

    async def get_payroll_run_by_id(self, run_id: uuid.UUID) -> PayrollRunTable | None:
        stmt = select(PayrollRunTable).where(PayrollRunTable.id == run_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_payroll_runs_by_period(
        self, period_year: int, period_month: int, legal_entity_id: uuid.UUID
    ) -> list[PayrollRunTable]:
        stmt = select(PayrollRunTable).where(
            PayrollRunTable.period_year == period_year,
            PayrollRunTable.period_month == period_month,
            PayrollRunTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_payroll_run_status(self, run_id: uuid.UUID, status: str) -> None:
        stmt = update(PayrollRunTable).where(PayrollRunTable.id == run_id).values(status=status)
        await self._session.execute(stmt)

    # ========== Payslip ==========
    async def save_payslip(self, payslip: PayrollPayslipTable) -> PayrollPayslipTable:
        self._session.add(payslip)
        await self._session.flush()
        return payslip

    async def get_payslip_by_id(self, payslip_id: uuid.UUID) -> PayrollPayslipTable | None:
        stmt = select(PayrollPayslipTable).where(PayrollPayslipTable.id == payslip_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_payslips_by_employee(
        self, employee_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[PayrollPayslipTable]:
        stmt = select(PayrollPayslipTable).where(
            PayrollPayslipTable.employee_id == employee_id,
            PayrollPayslipTable.period_year.between(from_date.year, to_date.year),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_payslips_by_run(self, payroll_run_id: uuid.UUID) -> list[PayrollPayslipTable]:
        stmt = select(PayrollPayslipTable).where(
            PayrollPayslipTable.payroll_run_id == payroll_run_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ========== Salary Components ==========
    async def get_salary_components_by_employee(
        self, employee_id: uuid.UUID, effective_date: date
    ) -> list[SalaryComponentTable]:
        stmt = select(SalaryComponentTable).where(
            SalaryComponentTable.employee_id == employee_id,
            SalaryComponentTable.effective_date <= effective_date,
            (
                SalaryComponentTable.end_date.is_(None)
                | (SalaryComponentTable.end_date >= effective_date)
            ),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ========== Employee ==========
    async def get_employee_by_id(self, employee_id: uuid.UUID) -> EmployeeTable | None:
        stmt = select(EmployeeTable).where(EmployeeTable.id == employee_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_employees(self, legal_entity_id: uuid.UUID) -> list[EmployeeTable]:
        stmt = select(EmployeeTable).where(
            EmployeeTable.legal_entity_id == legal_entity_id,
            EmployeeTable.status == "active",
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


__all__ = ["SQLAlchemyPayrollRepository"]
