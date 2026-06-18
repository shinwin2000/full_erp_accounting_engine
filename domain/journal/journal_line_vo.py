#!/usr/bin/env python3
"""
Module: journal_line_vo.py
Layer: 6 - Domain / Journal
Responsibility: Value object baris jurnal: akun, debit, kredit, deskripsi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class JournalSide(Enum):
    DEBIT = "debit"
    CREDIT = "credit"

    def opposite(self) -> JournalSide:
        return JournalSide.CREDIT if self == JournalSide.DEBIT else JournalSide.DEBIT

    def is_debit(self) -> bool:
        return self == JournalSide.DEBIT

    def is_credit(self) -> bool:
        return self == JournalSide.CREDIT

    @classmethod
    def from_string(cls, value: str) -> JournalSide:
        if value.lower() in ("debit", "dr", "d"):
            return cls.DEBIT
        if value.lower() in ("credit", "cr", "c"):
            return cls.CREDIT
        raise ValueError(f"Invalid journal side: {value}")


@dataclass(frozen=True)
class JournalLineVO:
    line_id: UUID
    journal_id: UUID
    account_id: UUID
    account_code: str
    account_name: str
    side: JournalSide
    amount: Decimal
    description: str
    legal_entity_id: UUID
    cost_center: str | None = None
    department: str | None = None
    project_id: UUID | None = None
    customer_id: UUID | None = None
    supplier_id: UUID | None = None
    employee_id: UUID | None = None
    currency: str = "IDR"
    tax_rate: Decimal = Decimal(0)
    tax_amount: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive: {self.amount}")
        if self.amount > Decimal("9999999999999.99"):
            raise ValueError(f"Amount exceeds maximum: {self.amount}")
        if not self.account_code:
            raise ValueError("Account code cannot be empty")
        if not self.description:
            raise ValueError("Description cannot be empty")
        if len(self.description.strip()) < 2:
            raise ValueError("Description too short (min 2 chars)")
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {self.tax_rate}")
        if self.tax_amount < 0:
            raise ValueError(f"Tax amount cannot be negative: {self.tax_amount}")

    def is_debit(self) -> bool:
        return self.side == JournalSide.DEBIT

    def is_credit(self) -> bool:
        return self.side == JournalSide.CREDIT

    def net_amount(self) -> Decimal:
        return self.amount

    def total_with_tax(self) -> Decimal:
        return self.amount + self.tax_amount

    def normalize(self) -> JournalLineVO:
        return JournalLineVO(
            line_id=self.line_id,
            journal_id=self.journal_id,
            account_id=self.account_id,
            account_code=self.account_code.strip().upper(),
            account_name=self.account_name.strip().title(),
            side=self.side,
            amount=self.amount.quantize(Decimal("0.01")),
            description=self.description.strip(),
            legal_entity_id=self.legal_entity_id,
            cost_center=self.cost_center.strip().upper() if self.cost_center else None,
            department=self.department.strip().upper() if self.department else None,
            project_id=self.project_id,
            customer_id=self.customer_id,
            supplier_id=self.supplier_id,
            employee_id=self.employee_id,
            currency=self.currency.strip().upper(),
            tax_rate=self.tax_rate.quantize(Decimal("0.01")),
            tax_amount=self.tax_amount.quantize(Decimal("0.01")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": str(self.line_id),
            "journal_id": str(self.journal_id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "account_name": self.account_name,
            "side": self.side.value,
            "amount": str(self.amount),
            "description": self.description,
            "legal_entity_id": str(self.legal_entity_id),
            "cost_center": self.cost_center,
            "department": self.department,
            "project_id": str(self.project_id) if self.project_id else None,
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "employee_id": str(self.employee_id) if self.employee_id else None,
            "currency": self.currency,
            "tax_rate": str(self.tax_rate),
            "tax_amount": str(self.tax_amount),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalLineVO:
        return cls(
            line_id=UUID(data["line_id"]) if data.get("line_id") else uuid4(),
            journal_id=UUID(data["journal_id"]),
            account_id=UUID(data["account_id"]),
            account_code=data["account_code"],
            account_name=data["account_name"],
            side=JournalSide.from_string(data["side"]),
            amount=Decimal(data["amount"]),
            description=data["description"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            cost_center=data.get("cost_center"),
            department=data.get("department"),
            project_id=UUID(data["project_id"]) if data.get("project_id") else None,
            customer_id=UUID(data["customer_id"]) if data.get("customer_id") else None,
            supplier_id=UUID(data["supplier_id"]) if data.get("supplier_id") else None,
            employee_id=UUID(data["employee_id"]) if data.get("employee_id") else None,
            currency=data.get("currency", "IDR"),
            tax_rate=Decimal(data.get("tax_rate", "0")),
            tax_amount=Decimal(data.get("tax_amount", "0")),
        )

    @classmethod
    def create_debit(
        cls,
        journal_id: UUID,
        account_id: UUID,
        account_code: str,
        account_name: str,
        amount: Decimal,
        description: str,
        legal_entity_id: UUID,
        **kwargs,
    ) -> JournalLineVO:
        return cls(
            line_id=uuid4(),
            journal_id=journal_id,
            account_id=account_id,
            account_code=account_code,
            account_name=account_name,
            side=JournalSide.DEBIT,
            amount=amount,
            description=description,
            legal_entity_id=legal_entity_id,
            **kwargs,
        )

    @classmethod
    def create_credit(
        cls,
        journal_id: UUID,
        account_id: UUID,
        account_code: str,
        account_name: str,
        amount: Decimal,
        description: str,
        legal_entity_id: UUID,
        **kwargs,
    ) -> JournalLineVO:
        return cls(
            line_id=uuid4(),
            journal_id=journal_id,
            account_id=account_id,
            account_code=account_code,
            account_name=account_name,
            side=JournalSide.CREDIT,
            amount=amount,
            description=description,
            legal_entity_id=legal_entity_id,
            **kwargs,
        )

    def __hash__(self) -> int:
        return hash((self.line_id, self.journal_id, self.account_id, self.side, self.amount))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, JournalLineVO):
            return False
        return self.line_id == other.line_id

    def to_string(self) -> str:
        return f"{self.account_code}|{self.side.value}|{self.amount}|{self.description}"

    @classmethod
    def from_string(cls, data: str) -> JournalLineVO:
        parts = data.split("|")
        if len(parts) < 4:
            raise ValueError(f"Invalid line string: {data}")
        return cls(
            line_id=uuid4(),
            journal_id=uuid4(),
            account_id=uuid4(),
            account_code=parts[0],
            account_name=parts[0],
            side=JournalSide.from_string(parts[1]),
            amount=Decimal(parts[2]),
            description=parts[3],
            legal_entity_id=uuid4(),
        )


JournalLine = JournalLineVO


class JournalLineRepository:
    async def get_by_journal(self, journal_id: UUID, legal_entity_id: UUID) -> list[JournalLineVO]:
        raise NotImplementedError

    async def get_by_account(
        self,
        account_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[JournalLineVO]:
        raise NotImplementedError

    async def save(self, line: JournalLineVO) -> None:
        raise NotImplementedError

    async def save_many(self, lines: list[JournalLineVO]) -> None:
        raise NotImplementedError

    async def delete_by_journal(self, journal_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "JournalLine",
    "JournalLineRepository",
    "JournalLineVO",
    "JournalSide",
]
