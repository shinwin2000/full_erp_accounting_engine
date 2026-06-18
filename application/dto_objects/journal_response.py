# journal_response.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: journal_response.py
Layer: 8 - Application / DTO Objects
Responsibility: Mendefinisikan Data Transfer Object (DTO) untuk response
               setelah operasi jurnal berhasil diproses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class JournalLineResponseDTO:
    """DTO untuk representasi data baris jurnal yang dikembalikan ke client."""

    account_code: str
    description: str
    debit: Decimal
    credit: Decimal
    cost_center: str | None = None
    department: str | None = None
    project_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_code": self.account_code,
            "description": self.description,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "cost_center": self.cost_center,
            "department": self.department,
            "project_code": self.project_code,
        }

    @property
    def net_amount(self) -> Decimal:
        """Calculate net amount (debit - credit)."""
        return self.debit - self.credit

    def is_debit(self) -> bool:
        """Check if this is a debit line."""
        return self.debit > 0

    def is_credit(self) -> bool:
        """Check if this is a credit line."""
        return self.credit > 0


@dataclass(frozen=True)
class JournalEntryResponseDTO:
    """DTO Utama untuk representasi data Jurnal setelah diproses."""

    id: UUID
    journal_number: str
    journal_date: datetime
    period: str
    description: str
    lines: list[JournalLineResponseDTO]
    total_debit: Decimal
    total_credit: Decimal
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None
    original_journal_id: UUID | None = None
    posted_at: datetime | None = None
    posted_by: UUID | None = None
    version: int = 1

    def __post_init__(self) -> None:
        # Normalize timezones
        if self.journal_date.tzinfo is None:
            object.__setattr__(self, "journal_date", self.journal_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.reversed_at and self.reversed_at.tzinfo is None:
            object.__setattr__(self, "reversed_at", self.reversed_at.replace(tzinfo=UTC))
        if self.posted_at and self.posted_at.tzinfo is None:
            object.__setattr__(self, "posted_at", self.posted_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "journal_number": self.journal_number,
            "journal_date": self.journal_date.isoformat(),
            "period": self.period,
            "description": self.description,
            "lines": [line.to_dict() for line in self.lines],
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
            "reversed_by": str(self.reversed_by) if self.reversed_by else None,
            "original_journal_id": str(self.original_journal_id)
            if self.original_journal_id
            else None,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "posted_by": str(self.posted_by) if self.posted_by else None,
            "version": self.version,
        }

    def is_balanced(self, tolerance: Decimal = Decimal("0.0001")) -> bool:
        """Check if journal is balanced."""
        return abs(self.total_debit - self.total_credit) <= tolerance

    def is_posted(self) -> bool:
        """Check if journal is posted."""
        return self.status == "POSTED"

    def is_reversed(self) -> bool:
        """Check if journal is reversed."""
        return self.status == "REVERSED"

    def is_draft(self) -> bool:
        """Check if journal is draft."""
        return self.status == "DRAFT"

    def get_reversal_info(self) -> dict[str, Any] | None:
        """Get reversal information if this is a reversal journal."""
        if self.original_journal_id:
            return {
                "original_journal_id": str(self.original_journal_id),
                "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
                "reversed_by": str(self.reversed_by) if self.reversed_by else None,
            }
        return None

    @classmethod
    def from_domain_entity(cls, journal: Any) -> JournalEntryResponseDTO:
        """Mapper Otomatis dari Domain Entity (JournalEntry) ke DTO."""
        dto_lines = []
        for line in journal.lines:
            acc_code = (
                line.account_code.value
                if hasattr(line.account_code, "value")
                else str(line.account_code)
            )
            dto_lines.append(
                JournalLineResponseDTO(
                    account_code=acc_code,
                    description=line.description,
                    debit=line.debit,
                    credit=line.credit,
                    cost_center=getattr(line, "cost_center", None),
                    department=getattr(line, "department", None),
                )
            )

        jnl_num = (
            journal.journal_number.value
            if hasattr(journal.journal_number, "value")
            else str(journal.journal_number)
        )

        if hasattr(journal.period, "year") and hasattr(journal.period, "month"):
            period_str = f"{journal.period.year}-{journal.period.month:02d}"
        else:
            period_str = str(journal.period)

        return cls(
            id=journal.id,
            journal_number=jnl_num,
            journal_date=journal.journal_date,
            period=period_str,
            description=journal.description,
            lines=dto_lines,
            total_debit=journal.total_debit,
            total_credit=journal.total_credit,
            status=journal.status.value
            if hasattr(journal.status, "value")
            else str(journal.status),
            created_at=journal.created_at,
            created_by=getattr(journal, "created_by", None),
            approved_at=getattr(journal, "approved_at", None),
            approved_by=getattr(journal, "approved_by", None),
            reversed_at=getattr(journal, "reversed_at", None),
            reversed_by=getattr(journal, "reversed_by", None),
            original_journal_id=getattr(journal, "original_journal_id", None),
            posted_at=getattr(journal, "posted_at", None),
            posted_by=getattr(journal, "posted_by", None),
            version=getattr(journal, "version", 1),
        )


@dataclass(kw_only=True)
class JournalValidationResultDTO:
    """DTO untuk hasil validasi jurnal sebelum disimpan."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_debit: Decimal = Decimal("0.00")
    total_credit: Decimal = Decimal("0.00")

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
        }

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)

    def is_balanced(self, tolerance: Decimal = Decimal("0.0001")) -> bool:
        """Check if journal is balanced."""
        return abs(self.total_debit - self.total_credit) <= tolerance


# ============================================================================
# Aliases for test compatibility
# ============================================================================
JournalResponse = JournalEntryResponseDTO
JournalLine = JournalLineResponseDTO
JournalValidationResult = JournalValidationResultDTO


# === EXPORTS ===
__all__ = [
    "JournalEntryResponseDTO",
    "JournalLine",
    "JournalLineResponseDTO",
    "JournalResponse",
    "JournalValidationResult",
    "JournalValidationResultDTO",
]
