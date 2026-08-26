#!/usr/bin/env python3
"""
Module: salary_component_entity.py
Layer: 6 - Domain / Payroll
Responsibility: Salary components (basic, allowance, deduction).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class ComponentType(Enum):
    BASIC = "basic"
    ALLOWANCE = "allowance"
    DEDUCTION = "deduction"
    TAX = "tax"
    BONUS = "bonus"
    OVERTIME = "overtime"

    @classmethod
    def from_string(cls, value: str) -> ComponentType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.ALLOWANCE


SalaryComponentType = ComponentType


class ComponentFrequency(Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"
    ONE_TIME = "one_time"

    @classmethod
    def from_string(cls, value: str) -> ComponentFrequency:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.MONTHLY


@dataclass(frozen=True)
class SalaryComponentEntity:
    component_id: UUID
    component_name: str
    component_type: ComponentType
    amount: Decimal
    currency: str
    frequency: ComponentFrequency
    description: str = ""
    is_taxable: bool = True
    is_mandatory: bool = False
    effective_date: datetime | None = None
    expiry_date: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        if len(self.component_name.strip()) < 2:
            raise ValueError("Component name must be at least 2 characters")
        if self.amount == 0:
            raise ValueError("Component amount cannot be zero")
        if self.currency not in ("IDR", "USD", "EUR", "SGD"):
            raise ValueError(f"Unsupported currency: {self.currency}")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if self.effective_date and self.effective_date.tzinfo is None:
            raise ValueError("effective_date must be timezone-aware")
        if self.expiry_date and self.expiry_date.tzinfo is None:
            raise ValueError("expiry_date must be timezone-aware")
        if self.effective_date and self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("expiry_date must be after effective_date")

    def is_positive(self) -> bool:
        return self.amount > 0

    def is_negative(self) -> bool:
        return self.amount < 0

    def is_active_at(self, date: datetime) -> bool:
        """
        Check if the component is active on the given date.
        Returns True if effective_date <= date <= expiry_date (or no expiry) and date >= effective_date (or no effective).
        """
        return (not self.effective_date or date >= self.effective_date) and (
            not self.expiry_date or date <= self.expiry_date
        )

    def normalize(self) -> SalaryComponentEntity:
        return SalaryComponentEntity(
            component_id=self.component_id,
            component_name=self.component_name.strip().title(),
            component_type=self.component_type,
            amount=self.amount.quantize(Decimal("0.01")),
            currency=self.currency.strip().upper(),
            frequency=self.frequency,
            description=self.description.strip() if self.description else "",
            is_taxable=self.is_taxable,
            is_mandatory=self.is_mandatory,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def update_amount(self, new_amount: Decimal, updated_by: str) -> SalaryComponentEntity:
        if new_amount == 0:
            raise ValueError("Component amount cannot be zero")
        return SalaryComponentEntity(
            component_id=self.component_id,
            component_name=self.component_name,
            component_type=self.component_type,
            amount=new_amount,
            currency=self.currency,
            frequency=self.frequency,
            description=self.description,
            is_taxable=self.is_taxable,
            is_mandatory=self.is_mandatory,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_description(self, new_description: str, updated_by: str) -> SalaryComponentEntity:
        return SalaryComponentEntity(
            component_id=self.component_id,
            component_name=self.component_name,
            component_type=self.component_type,
            amount=self.amount,
            currency=self.currency,
            frequency=self.frequency,
            description=new_description,
            is_taxable=self.is_taxable,
            is_mandatory=self.is_mandatory,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_effective_date(
        self, new_effective_date: datetime, updated_by: str
    ) -> SalaryComponentEntity:
        return SalaryComponentEntity(
            component_id=self.component_id,
            component_name=self.component_name,
            component_type=self.component_type,
            amount=self.amount,
            currency=self.currency,
            frequency=self.frequency,
            description=self.description,
            is_taxable=self.is_taxable,
            is_mandatory=self.is_mandatory,
            effective_date=new_effective_date,
            expiry_date=self.expiry_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": str(self.component_id),
            "component_name": self.component_name,
            "component_type": self.component_type.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "frequency": self.frequency.value,
            "description": self.description,
            "is_taxable": self.is_taxable,
            "is_mandatory": self.is_mandatory,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SalaryComponentEntity:
        return cls(
            component_id=UUID(data["component_id"]),
            component_name=data["component_name"],
            component_type=ComponentType.from_string(data["component_type"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            frequency=ComponentFrequency.from_string(data["frequency"]),
            description=data.get("description", ""),
            is_taxable=data.get("is_taxable", True),
            is_mandatory=data.get("is_mandatory", False),
            effective_date=datetime.fromisoformat(data["effective_date"])
            if data.get("effective_date")
            else None,
            expiry_date=datetime.fromisoformat(data["expiry_date"])
            if data.get("expiry_date")
            else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        component_name: str,
        component_type: ComponentType,
        amount: Decimal,
        currency: str,
        frequency: ComponentFrequency,
        created_by: str = "system",
    ) -> SalaryComponentEntity:
        return cls(
            component_id=uuid4(),
            component_name=component_name,
            component_type=component_type,
            amount=amount,
            currency=currency,
            frequency=frequency,
            created_by=created_by,
        )


@dataclass
class SalaryComponent:
    id: UUID
    employee_id: UUID
    component_type: SalaryComponentType
    amount: Decimal
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "employee_id": str(self.employee_id),
            "component_type": self.component_type.value,
            "amount": str(self.amount),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SalaryComponent:
        return cls(
            id=UUID(data["id"]),
            employee_id=UUID(data["employee_id"]),
            component_type=SalaryComponentType.from_string(data["component_type"]),
            amount=Decimal(data["amount"]),
            description=data.get("description", ""),
        )


class SalaryComponentRepository:
    async def get_by_id(
        self, component_id: UUID, legal_entity_id: UUID
    ) -> SalaryComponentEntity | None:
        raise NotImplementedError

    async def get_by_type(
        self, component_type: ComponentType, legal_entity_id: UUID
    ) -> list[SalaryComponentEntity]:
        raise NotImplementedError

    async def get_active(
        self, legal_entity_id: UUID, as_of_date: datetime | None = None
    ) -> list[SalaryComponentEntity]:
        raise NotImplementedError

    async def save(self, component: SalaryComponentEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, component_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "ComponentFrequency",
    "ComponentType",
    "SalaryComponent",
    "SalaryComponentEntity",
    "SalaryComponentRepository",
    "SalaryComponentType",
]
