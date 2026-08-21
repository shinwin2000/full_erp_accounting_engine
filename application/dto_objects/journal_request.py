# journal_request.py - Hardened version with complete implementation (fixing syntax errors)

#!/usr/bin/env python3
"""
Module: journal_request.py
Layer: 8 - Application / DTO Objects
Responsibility: DTO permintaan jurnal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from typing import Any
from uuid import UUID

# === 1. CONSTANTS ===

VALID_JOURNAL_TYPES = [
    "GENERAL",
    "ADJUSTING",
    "CLOSING",
    "REVERSAL",
    "CORRECTION",
    "INTERCOMPANY",
    "CONSOLIDATION",
]
VALID_SIDES = ["debit", "credit"]


# === 2. JOURNAL LINE REQUEST DTO ===


@dataclass(kw_only=True)
class JournalLineRequest:
    """DTO untuk baris jurnal dalam request."""

    account_id: UUID
    account_code: str
    account_name: str
    side: str  # "debit" or "credit"
    amount: Decimal
    description: str
    cost_center: str | None = None
    department: str | None = None
    project_id: UUID | None = None
    customer_id: UUID | None = None
    supplier_id: UUID | None = None
    employee_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive: {self.amount}")
        if self.side.lower() not in VALID_SIDES:
            raise ValueError(f"Side must be 'debit' or 'credit', got: {self.side}")
        if not self.account_code:
            raise ValueError("Account code is required")
        if not self.description:
            raise ValueError("Description is required")

    def is_debit(self) -> bool:
        return self.side.lower() == "debit"

    def is_credit(self) -> bool:
        return self.side.lower() == "credit"

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "account_name": self.account_name,
            "side": self.side,
            "amount": str(self.amount),
            "description": self.description,
            "cost_center": self.cost_center,
            "department": self.department,
            "project_id": str(self.project_id) if self.project_id else None,
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "employee_id": str(self.employee_id) if self.employee_id else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalLineRequest:
        return cls(
            account_id=UUID(data["account_id"]),
            account_code=data["account_code"],
            account_name=data["account_name"],
            side=data["side"],
            amount=Decimal(str(data["amount"])),
            description=data["description"],
            cost_center=data.get("cost_center"),
            department=data.get("department"),
            project_id=UUID(data["project_id"]) if data.get("project_id") else None,
            customer_id=UUID(data["customer_id"]) if data.get("customer_id") else None,
            supplier_id=UUID(data["supplier_id"]) if data.get("supplier_id") else None,
            employee_id=UUID(data["employee_id"]) if data.get("employee_id") else None,
        )


# === 3. CREATE JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class CreateJournalRequest:
    """DTO untuk request pembuatan jurnal."""

    journal_type: str
    transaction_date: datetime
    description: str
    lines: list[JournalLineRequest]
    reference: str | None = None
    idempotency_key: str | None = None
    source_system: str = "ERP"

    def __post_init__(self) -> None:
        if self.journal_type not in VALID_JOURNAL_TYPES:
            raise ValueError(
                f"Invalid journal_type: {self.journal_type}. Valid: {VALID_JOURNAL_TYPES}"
            )
        if not self.description or len(self.description.strip()) < 3:
            raise ValueError("Description must be at least 3 characters")
        if not self.lines or len(self.lines) < 2:
            raise ValueError("Journal must have at least 2 lines")
        if self.transaction_date.tzinfo is None:
            object.__setattr__(self, "transaction_date", self.transaction_date.replace(tzinfo=UTC))

    def calculate_total_debit(self) -> Decimal:
        total = Decimal(0)
        for line in self.lines:
            if line.is_debit():
                total += line.amount
        return total

    def calculate_total_credit(self) -> Decimal:
        total = Decimal(0)
        for line in self.lines:
            if line.is_credit():
                total += line.amount
        return total

    def is_balanced(self, tolerance: Decimal = Decimal("0.0001")) -> bool:
        return abs(self.calculate_total_debit() - self.calculate_total_credit()) <= tolerance

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_type": self.journal_type,
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "lines": [line.to_dict() for line in self.lines],
            "reference": self.reference,
            "idempotency_key": self.idempotency_key,
            "source_system": self.source_system,
            "total_debit": str(self.calculate_total_debit()),
            "total_credit": str(self.calculate_total_credit()),
            "is_balanced": self.is_balanced(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreateJournalRequest:
        lines = [JournalLineRequest.from_dict(line) for line in data.get("lines", [])]
        return cls(
            journal_type=data["journal_type"],
            transaction_date=datetime.fromisoformat(data["transaction_date"]),
            description=data["description"],
            lines=lines,
            reference=data.get("reference"),
            idempotency_key=data.get("idempotency_key"),
            source_system=data.get("source_system", "ERP"),
        )


# === 4. UPDATE JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class UpdateJournalRequest:
    """DTO untuk request update jurnal."""

    journal_id: UUID
    description: str | None = None
    lines: list[JournalLineRequest] | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        if not self.description and not self.lines and not self.reference:
            raise ValueError("At least one field to update must be provided")
        if self.description and len(self.description.strip()) < 3:
            raise ValueError("Description must be at least 3 characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "description": self.description,
            "lines": [line.to_dict() for line in self.lines] if self.lines else None,
            "reference": self.reference,
        }


# === 5. SUBMIT JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class SubmitJournalRequest:
    """DTO untuk request submit jurnal."""

    journal_id: UUID
    submitted_by: str
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.submitted_by:
            raise ValueError("submitted_by is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "submitted_by": self.submitted_by,
            "notes": self.notes,
        }


# === 6. APPROVE JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class ApproveJournalRequest:
    """DTO untuk request approval jurnal."""

    journal_id: UUID
    approved_by: str
    approval_level: int = 1
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.approved_by:
            raise ValueError("approved_by is required")
        if self.approval_level < 1:
            raise ValueError("approval_level must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "approved_by": self.approved_by,
            "approval_level": self.approval_level,
            "notes": self.notes,
        }


# === 7. REJECT JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class RejectJournalRequest:
    """DTO untuk request reject jurnal."""

    journal_id: UUID
    rejected_by: str
    reason: str

    def __post_init__(self) -> None:
        if not self.rejected_by:
            raise ValueError("rejected_by is required")
        if not self.reason or len(self.reason.strip()) < 5:
            raise ValueError("Reason must be at least 5 characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "rejected_by": self.rejected_by,
            "reason": self.reason,
        }


# === 8. POST JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class PostJournalRequest:
    """DTO untuk request posting jurnal."""

    journal_id: UUID
    posted_by: str
    force_post: bool = False

    def __post_init__(self) -> None:
        if not self.posted_by:
            raise ValueError("posted_by is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "posted_by": self.posted_by,
            "force_post": self.force_post,
        }


# === 9. REVERSE JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class ReverseJournalRequest:
    """DTO untuk request reversal jurnal."""

    journal_id: UUID
    reversed_by: str
    reason: str
    reversal_date: datetime | None = None

    def __post_init__(self) -> None:
        if not self.reversed_by:
            raise ValueError("reversed_by is required")
        if not self.reason or len(self.reason.strip()) < 5:
            raise ValueError("Reason must be at least 5 characters")
        if self.reversal_date and self.reversal_date.tzinfo is None:
            object.__setattr__(self, "reversal_date", self.reversal_date.replace(tzinfo=UTC))
        if self.reversal_date is None:
            object.__setattr__(self, "reversal_date", datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        # reversal_date is guaranteed non-None after __post_init__
        assert self.reversal_date is not None
        return {
            "journal_id": str(self.journal_id),
            "reversed_by": self.reversed_by,
            "reason": self.reason,
            "reversal_date": self.reversal_date.isoformat(),
        }


# === 10. GET JOURNAL REQUEST DTO ===


@dataclass(kw_only=True)
class GetJournalRequest:
    """DTO untuk request get jurnal."""

    journal_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# === 11. LIST JOURNALS REQUEST DTO ===


@dataclass(kw_only=True)
class ListJournalsRequest:
    """DTO untuk request list jurnal."""

    legal_entity_id: UUID
    from_date: datetime | None = None
    to_date: datetime | None = None
    journal_type: str | None = None
    status: str | None = None
    created_by: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")
        if self.from_date and self.from_date.tzinfo is None:
            object.__setattr__(self, "from_date", self.from_date.replace(tzinfo=UTC))
        if self.to_date and self.to_date.tzinfo is None:
            object.__setattr__(self, "to_date", self.to_date.replace(tzinfo=UTC))
        if self.journal_type and self.journal_type not in VALID_JOURNAL_TYPES:
            raise ValueError(f"Invalid journal_type: {self.journal_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "journal_type": self.journal_type,
            "status": self.status,
            "created_by": self.created_by,
            "limit": self.limit,
            "offset": self.offset,
        }


# === 12. JOURNAL QUERY PARAMS DTO ===


@dataclass(kw_only=True)
class JournalQueryParams:
    """DTO untuk parameter query string pada API endpoint jurnal."""

    legal_entity_id: UUID
    start_date: datetime | None = None
    end_date: datetime | None = None
    journal_type: str | None = None
    source_type: str | None = None
    status: str | None = None
    journal_number: str | None = None
    reference_number: str | None = None
    account_code: str | None = None
    created_by: UUID | None = None
    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        if self.start_date and self.start_date.tzinfo is None:
            object.__setattr__(self, "start_date", self.start_date.replace(tzinfo=UTC))
        if self.end_date and self.end_date.tzinfo is None:
            object.__setattr__(self, "end_date", self.end_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "journal_type": self.journal_type,
            "source_type": self.source_type,
            "status": self.status,
            "journal_number": self.journal_number,
            "reference_number": self.reference_number,
            "account_code": self.account_code,
            "created_by": str(self.created_by) if self.created_by else None,
            "page": self.page,
            "page_size": self.page_size,
        }

    def get_offset(self) -> int:
        """Calculate offset for pagination."""
        return (self.page - 1) * self.page_size

# === 13. RECURRING JOURNAL TEMPLATE DTO ===


@dataclass(kw_only=True)
class RecurringJournalTemplateDTO:
    """DTO untuk Template Jurnal Berulang (Recurring Journal)."""

    template_id: UUID
    template_name: str
    description: str
    schedule_type: str  # MONTHLY, WEEKLY, dll
    lines: list[JournalLineRequest]
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": str(self.template_id),
            "template_name": self.template_name,
            "schedule_type": self.schedule_type,
            "description": self.description,
            "lines": [line.to_dict() for line in self.lines],
            "is_active": self.is_active,
        }


# === 14. SIMPLE JOURNAL REQUEST (for test compatibility) ===


@dataclass(kw_only=True)
class JournalRequest:
    """Simple journal request DTO for unit tests."""

    description: str
    lines: list[dict[str, Any]]

    def __post_init__(self) -> None:
        new_lines = []
        for line in self.lines:
            obj = SimpleNamespace()
            obj.account = line.get("account")
            obj.debit = Decimal(str(line.get("debit", 0)))
            obj.credit = Decimal(str(line.get("credit", 0)))
            new_lines.append(obj)
        object.__setattr__(self, "lines", new_lines)

    def is_valid(self) -> bool:
        return len(self.lines) >= 2


# === 15. ENUMS FOR RESPONSE ===


class JournalEntryStatusDTO(str, Enum):
    """Status jurnal untuk DTO response."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    REVERSED = "reversed"
    CANCELLED = "cancelled"


# === 16. RESPONSE DTO ===


@dataclass(kw_only=True)
class JournalResponseDTO:
    """DTO response untuk jurnal."""

    id: UUID
    journal_number: str
    journal_date: date
    period: str
    description: str
    total_debit: Decimal
    total_credit: Decimal
    lines: list[JournalLineRequest]
    approved_at: datetime | None = None
    status: JournalEntryStatusDTO | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    approved_by: str | None = None
    version: int = 1


# === 17. FACTORY ===


class JournalRequestFactory:
    """Factory untuk membuat Journal Request DTOs."""

    @staticmethod
    def create_journal_line(
        account_id: UUID,
        account_code: str,
        account_name: str,
        side: str,
        amount: Decimal,
        description: str,
        cost_center: str | None = None,
        department: str | None = None,
        project_id: UUID | None = None,
    ) -> JournalLineRequest:
        return JournalLineRequest(
            account_id=account_id,
            account_code=account_code,
            account_name=account_name,
            side=side,
            amount=amount,
            description=description,
            cost_center=cost_center,
            department=department,
            project_id=project_id,
        )

    @staticmethod
    def create_debit_line(
        account_id: UUID,
        account_code: str,
        account_name: str,
        amount: Decimal,
        description: str,
        **kwargs,
    ) -> JournalLineRequest:
        return JournalRequestFactory.create_journal_line(
            account_id=account_id,
            account_code=account_code,
            account_name=account_name,
            side="debit",
            amount=amount,
            description=description,
            **kwargs,
        )

    @staticmethod
    def create_credit_line(
        account_id: UUID,
        account_code: str,
        account_name: str,
        amount: Decimal,
        description: str,
        **kwargs,
    ) -> JournalLineRequest:
        return JournalRequestFactory.create_journal_line(
            account_id=account_id,
            account_code=account_code,
            account_name=account_name,
            side="credit",
            amount=amount,
            description=description,
            **kwargs,
        )

    @staticmethod
    def create_simple_journal(
        journal_type: str,
        transaction_date: datetime,
        description: str,
        debit_account_id: UUID,
        debit_account_code: str,
        debit_account_name: str,
        credit_account_id: UUID,
        credit_account_code: str,
        credit_account_name: str,
        amount: Decimal,
        reference: str | None = None,
    ) -> CreateJournalRequest:
        lines = [
            JournalRequestFactory.create_debit_line(
                account_id=debit_account_id,
                account_code=debit_account_code,
                account_name=debit_account_name,
                amount=amount,
                description=description,
            ),
            JournalRequestFactory.create_credit_line(
                account_id=credit_account_id,
                account_code=credit_account_code,
                account_name=credit_account_name,
                amount=amount,
                description=description,
            ),
        ]
        return CreateJournalRequest(
            journal_type=journal_type,
            transaction_date=transaction_date,
            description=description,
            lines=lines,
            reference=reference,
        )


# === 18. COMPATIBILITY ALIASES ===

JournalEntryRequestDTO = CreateJournalRequest
JournalLineRequestDTO = JournalLineRequest
AdjustingJournalRequestDTO = CreateJournalRequest
JournalCreateRequest = CreateJournalRequest
JournalUpdateRequest = UpdateJournalRequest
JournalEntryRequest = CreateJournalRequest
CreateJournalEntryRequest = CreateJournalRequest


# === 19. EXPORTS ===

__all__ = [
    # Constants
    "VALID_JOURNAL_TYPES",
    "VALID_SIDES",
    "AdjustingJournalRequestDTO",
    "ApproveJournalRequest",
    "CreateJournalEntryRequest",
    "CreateJournalRequest",
    "GetJournalRequest",
    "JournalCreateRequest",
    "JournalEntryRequest",
    # Compatibility aliases
    "JournalEntryRequestDTO",
    "JournalEntryStatusDTO",
    # Core DTOs
    "JournalLineRequest",
    "JournalLineRequestDTO",
    "JournalQueryParams",
    # Test compatibility
    "JournalRequest",
    # Factory
    "JournalRequestFactory",
    "JournalResponseDTO",
    "JournalUpdateRequest",
    "ListJournalsRequest",
    "PostJournalRequest",
    "RecurringJournalTemplateDTO",
    "RejectJournalRequest",
    "ReverseJournalRequest",
    "SubmitJournalRequest",
    "UpdateJournalRequest",
]
