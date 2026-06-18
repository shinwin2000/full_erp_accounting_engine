# payroll_saga_state.py - Complete implementation

#!/usr/bin/env python3

"""
Module: payroll_saga_state.py

Layer: 8 - Application / Sagas

Responsibility:
    Definisi state untuk payroll saga.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class PayrollSagaState:
    """State untuk payroll saga."""

    saga_id: UUID
    legal_entity_id: UUID
    period_year: int
    period_month: int
    payroll_date: date
    user_id: UUID | None = None
    correlation_id: str | None = None
    employee_ids: list[UUID] = field(default_factory=list)
    payroll_run_id: UUID | None = None
    payslip_ids: list[UUID] = field(default_factory=list)
    journal_id: UUID | None = None
    bank_file_path: str | None = None
    total_gross: Decimal = Decimal("0")
    total_deductions: Decimal = Decimal("0")
    total_net: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")
    status: str = "INITIATED"
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_error(self, error: str) -> None:
        """Add error message."""
        self.errors.append(error)
        self.updated_at = datetime.utcnow()

    def set_payroll_run(self, run_id: UUID) -> None:
        """Set payroll run ID."""
        self.payroll_run_id = run_id
        self.updated_at = datetime.utcnow()

    def add_payslip(self, payslip_id: UUID) -> None:
        """Add payslip ID."""
        self.payslip_ids.append(payslip_id)
        self.updated_at = datetime.utcnow()

    def set_journal(self, journal_id: UUID) -> None:
        """Set journal ID."""
        self.journal_id = journal_id
        self.updated_at = datetime.utcnow()

    def set_bank_file(self, file_path: str) -> None:
        """Set bank file path."""
        self.bank_file_path = file_path
        self.updated_at = datetime.utcnow()

    def set_totals(self, gross: Decimal, deductions: Decimal, net: Decimal, tax: Decimal) -> None:
        """Set totals."""
        self.total_gross = gross
        self.total_deductions = deductions
        self.total_net = net
        self.total_tax = tax
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "saga_id": str(self.saga_id),
            "legal_entity_id": str(self.legal_entity_id),
            "period_year": self.period_year,
            "period_month": self.period_month,
            "payroll_date": self.payroll_date.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "employee_ids": [str(eid) for eid in self.employee_ids],
            "payroll_run_id": str(self.payroll_run_id) if self.payroll_run_id else None,
            "payslip_ids": [str(pid) for pid in self.payslip_ids],
            "journal_id": str(self.journal_id) if self.journal_id else None,
            "bank_file_path": self.bank_file_path,
            "total_gross": str(self.total_gross),
            "total_deductions": str(self.total_deductions),
            "total_net": str(self.total_net),
            "total_tax": str(self.total_tax),
            "status": self.status,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PayrollSagaState:
        """Create from dictionary."""
        return cls(
            saga_id=UUID(data["saga_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            period_year=data["period_year"],
            period_month=data["period_month"],
            payroll_date=date.fromisoformat(data["payroll_date"]),
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            correlation_id=data.get("correlation_id"),
            employee_ids=[UUID(eid) for eid in data.get("employee_ids", [])],
            payroll_run_id=UUID(data["payroll_run_id"]) if data.get("payroll_run_id") else None,
            payslip_ids=[UUID(pid) for pid in data.get("payslip_ids", [])],
            journal_id=UUID(data["journal_id"]) if data.get("journal_id") else None,
            bank_file_path=data.get("bank_file_path"),
            total_gross=Decimal(str(data.get("total_gross", 0))),
            total_deductions=Decimal(str(data.get("total_deductions", 0))),
            total_net=Decimal(str(data.get("total_net", 0))),
            total_tax=Decimal(str(data.get("total_tax", 0))),
            status=data.get("status", "INITIATED"),
            errors=data.get("errors", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


__all__ = ["PayrollSagaState"]
