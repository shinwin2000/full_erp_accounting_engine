#!/usr/bin/env python3
"""
Module: payroll_repository_port.py
Layer: Ports / Primary
Responsibility: Port for payroll repository.
"""

from __future__ import annotations

from uuid import UUID


class PayrollRepositoryPort:
    """Port for payroll repository."""

    async def get_employee(self, employee_id: UUID, legal_entity_id: UUID) -> Any | None:
        raise NotImplementedError

    async def get_employees(self, legal_entity_id: UUID) -> list[Any]:
        raise NotImplementedError

    async def get_payroll_run(self, run_id: UUID, legal_entity_id: UUID) -> Any | None:
        raise NotImplementedError

    async def save_payroll_run(self, payroll_run: Any) -> None:
        raise NotImplementedError


__all__ = ["PayrollRepositoryPort"]
