#!/usr/bin/env python3
"""
Module: payroll_repository_port.py
Layer: Ports / Primary
Responsibility: Port interface for payroll repository.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any
from uuid import UUID


class PayrollRepositoryPort(ABC):
    """
    Port interface untuk repository Payroll.
    """

    # ---------- Payroll Run ----------
    @abstractmethod
    async def save_payroll_run(self, payroll_run: Any) -> Any:
        """Save or update a payroll run."""
        pass

    @abstractmethod
    async def get_payroll_run(self, run_id: UUID, legal_entity_id: UUID) -> Any | None:
        """Get a payroll run by ID and legal entity."""
        pass

    @abstractmethod
    async def get_payroll_runs_by_period(
        self, period_year: int, period_month: int, legal_entity_id: UUID
    ) -> list[Any]:
        """Get all payroll runs for a specific period."""
        pass

    @abstractmethod
    async def find_payrolls_by_period(
        self, period_year: int, period_month: int, legal_entity_id: UUID
    ) -> list[Any]:
        """Alias for get_payroll_runs_by_period."""
        pass

    @abstractmethod
    async def update_payroll_run_status(self, run_id: UUID, status: str) -> None:
        """Update the status of a payroll run."""
        pass

    @abstractmethod
    async def save_payroll(self, payroll: Any) -> None:
        """Save or update a payroll record."""
        pass

    # ---------- Payslip ----------
    @abstractmethod
    async def save_payslip(self, payslip: Any) -> Any:
        """Save or update a payslip."""
        pass

    @abstractmethod
    async def get_payslip_by_id(self, payslip_id: UUID) -> Any | None:
        """Get a payslip by ID."""
        pass

    @abstractmethod
    async def get_payslips_by_employee(
        self, employee_id: UUID, from_date: date, to_date: date
    ) -> list[Any]:
        """Get payslips for an employee within a date range."""
        pass

    @abstractmethod
    async def get_payslips_by_run(self, payroll_run_id: UUID) -> list[Any]:
        """Get all payslips for a payroll run."""
        pass

    @abstractmethod
    async def find_by_employee(self, employee_id: UUID) -> list[Any]:
        """Find payslips by employee ID (without date filter)."""
        pass

    # ---------- Salary Components ----------
    @abstractmethod
    async def get_salary_components_by_employee(
        self, employee_id: UUID, effective_date: date
    ) -> list[Any]:
        """Get salary components for an employee at a specific date."""
        pass

    # ---------- Employee ----------
    @abstractmethod
    async def get_employee(self, employee_id: UUID, legal_entity_id: UUID) -> Any | None:
        """Get an employee by ID and legal entity."""
        pass

    @abstractmethod
    async def get_employee_by_id(self, employee_id: UUID) -> Any | None:
        """Get an employee by ID (without legal entity)."""
        pass

    @abstractmethod
    async def get_active_employees(self, legal_entity_id: UUID) -> list[Any]:
        """Get all active employees for a legal entity."""
        pass

    @abstractmethod
    async def get_employees(self, legal_entity_id: UUID) -> list[Any]:
        """Get all employees for a legal entity (alias)."""
        pass


__all__ = ["PayrollRepositoryPort"]