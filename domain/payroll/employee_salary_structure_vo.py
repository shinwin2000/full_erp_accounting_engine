#!/usr/bin/env python3
"""
Module: employee_salary_structure_vo.py
Layer: 6 - Domain / Payroll
Responsibility: Employee salary structure value object.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import EmployeeBPJSEnrollmentVO
from domain.customer_supplier_employee.employee_ptkp_status_vo import EmployeePTKPStatusVO
from domain.payroll.salary_component_entity import ComponentType, SalaryComponentEntity

logger = logging.getLogger(__name__)

SalaryComponent = SalaryComponentEntity
SalaryComponentType = ComponentType


@dataclass(frozen=True)
class EmployeeSalaryStructureVO:
    structure_id: UUID
    employee_id: UUID
    employee_name: str
    legal_entity_id: UUID
    basic_salary: Decimal
    currency: str
    salary_components: list[SalaryComponentEntity]
    ptkp_status: EmployeePTKPStatusVO
    bpjs_employment: EmployeeBPJSEnrollmentVO
    employee_nik: str | None = None
    employee_position: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    bank_code: str | None = None
    effective_date: datetime | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        if self.basic_salary <= 0:
            raise ValueError(f"Basic salary must be positive: {self.basic_salary}")
        if self.currency not in ("IDR", "USD", "EUR", "SGD"):
            raise ValueError(f"Unsupported currency: {self.currency}")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if self.effective_date and self.effective_date.tzinfo is None:
            raise ValueError("effective_date must be timezone-aware")

    # ==================== PROPERTIES ====================

    @property
    def total_allowances(self) -> Decimal:
        total = Decimal(0)
        for comp in self.salary_components:
            if comp.component_type == ComponentType.ALLOWANCE:
                total += comp.amount
        return total

    @property
    def total_deductions(self) -> Decimal:
        total = Decimal(0)
        for comp in self.salary_components:
            if comp.component_type == ComponentType.DEDUCTION:
                total += abs(comp.amount)
        return total

    @property
    def total_salary(self) -> Decimal:
        return self.basic_salary + self.total_allowances - self.total_deductions

    @property
    def bpjs_employee_contribution(self) -> Decimal:
        return self.bpjs_employment.employee_contribution

    @property
    def bpjs_employer_contribution(self) -> Decimal:
        return self.bpjs_employment.employer_contribution

    # ==================== UPDATE METHODS ====================

    def add_component(
        self, component: SalaryComponentEntity, added_by: str
    ) -> EmployeeSalaryStructureVO:
        new_components = [*self.salary_components, component]
        return EmployeeSalaryStructureVO(
            structure_id=self.structure_id,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            legal_entity_id=self.legal_entity_id,
            basic_salary=self.basic_salary,
            currency=self.currency,
            salary_components=new_components,
            ptkp_status=self.ptkp_status,
            bpjs_employment=self.bpjs_employment,
            employee_nik=self.employee_nik,
            employee_position=self.employee_position,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            bank_code=self.bank_code,
            effective_date=self.effective_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_component(self, component_id: UUID, removed_by: str) -> EmployeeSalaryStructureVO:
        new_components = [c for c in self.salary_components if c.component_id != component_id]
        return EmployeeSalaryStructureVO(
            structure_id=self.structure_id,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            legal_entity_id=self.legal_entity_id,
            basic_salary=self.basic_salary,
            currency=self.currency,
            salary_components=new_components,
            ptkp_status=self.ptkp_status,
            bpjs_employment=self.bpjs_employment,
            employee_nik=self.employee_nik,
            employee_position=self.employee_position,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            bank_code=self.bank_code,
            effective_date=self.effective_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    def update_basic_salary(
        self, new_basic_salary: Decimal, updated_by: str
    ) -> EmployeeSalaryStructureVO:
        return EmployeeSalaryStructureVO(
            structure_id=self.structure_id,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            legal_entity_id=self.legal_entity_id,
            basic_salary=new_basic_salary,
            currency=self.currency,
            salary_components=self.salary_components,
            ptkp_status=self.ptkp_status,
            bpjs_employment=self.bpjs_employment,
            employee_nik=self.employee_nik,
            employee_position=self.employee_position,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            bank_code=self.bank_code,
            effective_date=self.effective_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_ptkp_status(
        self, new_ptkp_status: EmployeePTKPStatusVO, updated_by: str
    ) -> EmployeeSalaryStructureVO:
        return EmployeeSalaryStructureVO(
            structure_id=self.structure_id,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            legal_entity_id=self.legal_entity_id,
            basic_salary=self.basic_salary,
            currency=self.currency,
            salary_components=self.salary_components,
            ptkp_status=new_ptkp_status,
            bpjs_employment=self.bpjs_employment,
            employee_nik=self.employee_nik,
            employee_position=self.employee_position,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            bank_code=self.bank_code,
            effective_date=self.effective_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_bank_account(
        self, account_number: str, account_name: str, bank_code: str, updated_by: str
    ) -> EmployeeSalaryStructureVO:
        return EmployeeSalaryStructureVO(
            structure_id=self.structure_id,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            legal_entity_id=self.legal_entity_id,
            basic_salary=self.basic_salary,
            currency=self.currency,
            salary_components=self.salary_components,
            ptkp_status=self.ptkp_status,
            bpjs_employment=self.bpjs_employment,
            employee_nik=self.employee_nik,
            employee_position=self.employee_position,
            bank_account_number=account_number,
            bank_account_name=account_name,
            bank_code=bank_code,
            effective_date=self.effective_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_effective_date(
        self, new_effective_date: datetime, updated_by: str
    ) -> EmployeeSalaryStructureVO:
        return EmployeeSalaryStructureVO(
            structure_id=self.structure_id,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            legal_entity_id=self.legal_entity_id,
            basic_salary=self.basic_salary,
            currency=self.currency,
            salary_components=self.salary_components,
            ptkp_status=self.ptkp_status,
            bpjs_employment=self.bpjs_employment,
            employee_nik=self.employee_nik,
            employee_position=self.employee_position,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            bank_code=self.bank_code,
            effective_date=new_effective_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    # ==================== QUERY METHODS ====================

    def is_active_at(self, date: datetime) -> bool:
        """Return True if the structure is effective on the given date."""
        return not (self.effective_date and date < self.effective_date)

    def get_component_by_name(self, name: str) -> SalaryComponentEntity | None:
        for comp in self.salary_components:
            if comp.component_name.lower() == name.lower():
                return comp
        return None

    def get_component_by_type(self, comp_type: ComponentType) -> list[SalaryComponentEntity]:
        return [c for c in self.salary_components if c.component_type == comp_type]

    def normalize(self) -> EmployeeSalaryStructureVO:
        normalized_components = [c.normalize() for c in self.salary_components]
        return EmployeeSalaryStructureVO(
            structure_id=self.structure_id,
            employee_id=self.employee_id,
            employee_name=self.employee_name.strip().title(),
            legal_entity_id=self.legal_entity_id,
            basic_salary=self.basic_salary.quantize(Decimal("0.01")),
            currency=self.currency.strip().upper(),
            salary_components=normalized_components,
            ptkp_status=self.ptkp_status,
            bpjs_employment=self.bpjs_employment,
            employee_nik=self.employee_nik.strip() if self.employee_nik else None,
            employee_position=self.employee_position.strip().title()
            if self.employee_position
            else None,
            bank_account_number=self.bank_account_number.strip()
            if self.bank_account_number
            else None,
            bank_account_name=self.bank_account_name.strip().title()
            if self.bank_account_name
            else None,
            bank_code=self.bank_code.strip().upper() if self.bank_code else None,
            effective_date=self.effective_date,
            notes=self.notes.strip() if self.notes else None,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure_id": str(self.structure_id),
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "employee_nik": self.employee_nik,
            "employee_position": self.employee_position,
            "legal_entity_id": str(self.legal_entity_id),
            "basic_salary": str(self.basic_salary),
            "currency": self.currency,
            "total_allowances": str(self.total_allowances),
            "total_deductions": str(self.total_deductions),
            "total_salary": str(self.total_salary),
            "ptkp_status": self.ptkp_status.to_dict(),
            "bpjs_employee_contribution": str(self.bpjs_employee_contribution),
            "bpjs_employer_contribution": str(self.bpjs_employer_contribution),
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "bank_code": self.bank_code,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "components": [c.to_dict() for c in self.salary_components],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmployeeSalaryStructureVO:
        from domain.payroll.salary_component_entity import SalaryComponentEntity

        components = [SalaryComponentEntity.from_dict(c) for c in data.get("components", [])]
        return cls(
            structure_id=UUID(data["structure_id"]),
            employee_id=UUID(data["employee_id"]),
            employee_name=data["employee_name"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            basic_salary=Decimal(data["basic_salary"]),
            currency=data["currency"],
            salary_components=components,
            ptkp_status=EmployeePTKPStatusVO.from_dict(data["ptkp_status"]),
            bpjs_employment=EmployeeBPJSEnrollmentVO.from_dict(data["bpjs_employment"]),
            employee_nik=data.get("employee_nik"),
            employee_position=data.get("employee_position"),
            bank_account_number=data.get("bank_account_number"),
            bank_account_name=data.get("bank_account_name"),
            bank_code=data.get("bank_code"),
            effective_date=datetime.fromisoformat(data["effective_date"])
            if data.get("effective_date")
            else None,
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        employee_id: UUID,
        employee_name: str,
        legal_entity_id: UUID,
        basic_salary: Decimal,
        currency: str,
        ptkp_status: EmployeePTKPStatusVO,
        bpjs_employment: EmployeeBPJSEnrollmentVO,
        created_by: str = "system",
    ) -> EmployeeSalaryStructureVO:
        return cls(
            structure_id=uuid4(),
            employee_id=employee_id,
            employee_name=employee_name,
            legal_entity_id=legal_entity_id,
            basic_salary=basic_salary,
            currency=currency,
            salary_components=[],
            ptkp_status=ptkp_status,
            bpjs_employment=bpjs_employment,
            created_by=created_by,
        )


EmployeeSalaryStructure = EmployeeSalaryStructureVO

__all__ = [
    "EmployeeSalaryStructure",
    "EmployeeSalaryStructureVO",
    "SalaryComponent",
    "SalaryComponentType",
]
