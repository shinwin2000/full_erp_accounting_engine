#!/usr/bin/env python3
"""
Module: journal_entry.py
Layer: Domain / Journal
Responsibility: Journal entry and line entities (simplified).

All datetime.now() replaced with datetime.now(UTC) for timezone awareness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class JournalEntryStatus(Enum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"
    ADJUSTED = "adjusted"
    CANCELLED = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> JournalEntryStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


@dataclass(frozen=True)
class JournalLine:
    account_code: str
    debit: Decimal
    credit: Decimal
    description: str = ""
    cost_center: str | None = None
    department: str | None = None

    def __post_init__(self):
        if self.debit < 0 or self.credit < 0:
            raise ValueError("Debit and credit cannot be negative")
        if self.debit > 0 and self.credit > 0:
            raise ValueError("A line cannot have both debit and credit")
        if self.debit == 0 and self.credit == 0:
            raise ValueError("Line must have non-zero amount")
        if not self.account_code:
            raise ValueError("Account code cannot be empty")

    @property
    def amount(self) -> Decimal:
        return self.debit if self.debit > 0 else self.credit

    @property
    def side(self) -> str:
        return "debit" if self.debit > 0 else "credit"

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_code": self.account_code,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "description": self.description,
            "cost_center": self.cost_center,
            "department": self.department,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalLine:
        return cls(
            account_code=data["account_code"],
            debit=Decimal(data.get("debit", "0")),
            credit=Decimal(data.get("credit", "0")),
            description=data.get("description", ""),
            cost_center=data.get("cost_center"),
            department=data.get("department"),
        )


@dataclass(frozen=True)
class JournalEntry:
    id: UUID
    legal_entity_id: UUID
    journal_number: str | None
    journal_date: date
    period: str
    description: str
    source_system: str
    status: JournalEntryStatus
    created_by: UUID | None
    created_at: datetime
    lines: list[JournalLine]
    reference: str | None = None
    posted_by: UUID | None = None
    posted_at: datetime | None = None
    reversed_by: UUID | None = None
    reversed_at: datetime | None = None
    reversal_of: UUID | None = None

    def __post_init__(self):
        if not self.description or len(self.description.strip()) < 2:
            raise ValueError("Description must be at least 2 characters")
        if not self.lines:
            raise ValueError("Journal must have at least one line")
        if not self.is_balanced():
            raise ValueError(
                f"Journal not balanced: debit={self.total_debit}, credit={self.total_credit}"
            )

    @property
    def total_debit(self) -> Decimal:
        return sum(line.debit for line in self.lines)

    @property
    def total_credit(self) -> Decimal:
        return sum(line.credit for line in self.lines)

    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    def is_posted(self) -> bool:
        return self.status == JournalEntryStatus.POSTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "journal_number": self.journal_number,
            "journal_date": self.journal_date.isoformat(),
            "period": self.period,
            "description": self.description,
            "source_system": self.source_system,
            "status": self.status.value,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "lines": [line.to_dict() for line in self.lines],
            "reference": self.reference,
            "posted_by": str(self.posted_by) if self.posted_by else None,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "reversed_by": str(self.reversed_by) if self.reversed_by else None,
            "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
            "reversal_of": str(self.reversal_of) if self.reversal_of else None,
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
        }

    @classmethod
    def create_draft(
        cls,
        legal_entity_id: UUID,
        journal_number: str,
        journal_date: date,
        period: str,
        description: str,
        lines: list[JournalLine],
        created_by: UUID,
        source_system: str = "ERP",
        reference: str | None = None,
    ) -> JournalEntry:
        return cls(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            journal_number=journal_number,
            journal_date=journal_date,
            period=period,
            description=description,
            source_system=source_system,
            status=JournalEntryStatus.DRAFT,
            created_by=created_by,
            created_at=datetime.now(UTC),  # Fixed: timezone-aware
            lines=lines,
            reference=reference,
        )


__all__ = ["JournalEntry", "JournalEntryStatus", "JournalLine"]