# payment_run_request.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: payment_run_request.py
Layer: 8 - Application / DTO Objects
Responsibility: DTO permintaan proses pembayaran massal (payment run).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# === 1. CONSTANTS & ENUMS ===


class PaymentRunType(Enum):
    """Jenis payment run."""

    AP_PAYMENT = "ap_payment"  # Pembayaran ke vendor (hutang)
    AR_COLLECTION = "ar_collection"  # Penagihan dari pelanggan (piutang)


class PaymentRunStatus(Enum):
    """Status payment run."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentSelectionMethod(Enum):
    """Metode seleksi faktur untuk dibayar/ditagih."""

    DUE_DATE = "due_date"
    INVOICE_DATE = "invoice_date"
    PRIORITY = "priority"
    CUSTOM = "custom"


class PaymentPriority(Enum):
    """Prioritas pembayaran."""

    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


class PaymentRunSchedule(Enum):
    """Jadwal payment run."""

    IMMEDIATE = "immediate"
    SCHEDULED_DATE = "scheduled_date"
    RECURRING_DAILY = "recurring_daily"
    RECURRING_WEEKLY = "recurring_weekly"
    RECURRING_MONTHLY = "recurring_monthly"


# === 2. INVOICE SELECTION CRITERIA DTO ===


@dataclass(kw_only=True)
class InvoiceSelectionCriteria:
    """Kriteria seleksi faktur untuk payment run."""

    vendor_ids: list[UUID] | None = None
    customer_ids: list[UUID] | None = None
    due_date_from: datetime | None = None
    due_date_to: datetime | None = None
    invoice_date_from: datetime | None = None
    invoice_date_to: datetime | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    include_partially_paid: bool = True
    include_fully_paid: bool = False
    include_overdue: bool = True
    priority: PaymentPriority | None = None
    specific_invoice_ids: list[UUID] | None = None

    def __post_init__(self) -> None:
        if self.due_date_from and self.due_date_from.tzinfo is None:
            object.__setattr__(self, "due_date_from", self.due_date_from.replace(tzinfo=UTC))
        if self.due_date_to and self.due_date_to.tzinfo is None:
            object.__setattr__(self, "due_date_to", self.due_date_to.replace(tzinfo=UTC))
        if self.invoice_date_from and self.invoice_date_from.tzinfo is None:
            object.__setattr__(
                self, "invoice_date_from", self.invoice_date_from.replace(tzinfo=UTC)
            )
        if self.invoice_date_to and self.invoice_date_to.tzinfo is None:
            object.__setattr__(self, "invoice_date_to", self.invoice_date_to.replace(tzinfo=UTC))
        if self.min_amount is not None and self.min_amount < 0:
            raise ValueError(f"min_amount cannot be negative: {self.min_amount}")
        if self.max_amount is not None and self.max_amount < 0:
            raise ValueError(f"max_amount cannot be negative: {self.max_amount}")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError(f"min_amount {self.min_amount} > max_amount {self.max_amount}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor_ids": [str(vid) for vid in self.vendor_ids] if self.vendor_ids else None,
            "customer_ids": [str(cid) for cid in self.customer_ids] if self.customer_ids else None,
            "due_date_from": self.due_date_from.isoformat() if self.due_date_from else None,
            "due_date_to": self.due_date_to.isoformat() if self.due_date_to else None,
            "invoice_date_from": self.invoice_date_from.isoformat()
            if self.invoice_date_from
            else None,
            "invoice_date_to": self.invoice_date_to.isoformat() if self.invoice_date_to else None,
            "min_amount": str(self.min_amount) if self.min_amount else None,
            "max_amount": str(self.max_amount) if self.max_amount else None,
            "include_partially_paid": self.include_partially_paid,
            "include_fully_paid": self.include_fully_paid,
            "include_overdue": self.include_overdue,
            "priority": self.priority.value if self.priority else None,
            "specific_invoice_ids": [str(iid) for iid in self.specific_invoice_ids]
            if self.specific_invoice_ids
            else None,
        }

    def is_empty(self) -> bool:
        """Check if criteria has any filters."""
        return not (
            self.vendor_ids
            or self.customer_ids
            or self.due_date_from
            or self.due_date_to
            or self.invoice_date_from
            or self.invoice_date_to
            or self.min_amount
            or self.max_amount
            or self.specific_invoice_ids
        )


# === 3. PAYMENT INSTRUCTION DTO ===


@dataclass(kw_only=True)
class PaymentInstruction:
    """Instruksi pembayaran untuk satu invoice."""

    invoice_id: UUID
    invoice_number: str
    amount_to_pay: Decimal
    original_amount: Decimal
    payment_method: str
    bank_account_from: str | None = None
    bank_account_to: str | None = None
    reference: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.amount_to_pay <= 0:
            raise ValueError(f"amount_to_pay must be positive: {self.amount_to_pay}")
        if self.amount_to_pay > self.original_amount:
            raise ValueError(
                f"amount_to_pay {self.amount_to_pay} exceeds original_amount {self.original_amount}"
            )

    @property
    def is_full_payment(self) -> bool:
        return self.amount_to_pay >= self.original_amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "amount_to_pay": str(self.amount_to_pay),
            "original_amount": str(self.original_amount),
            "payment_method": self.payment_method,
            "bank_account_from": self.bank_account_from,
            "bank_account_to": self.bank_account_to,
            "reference": self.reference,
            "notes": self.notes,
            "is_full_payment": self.is_full_payment,
        }


# === 4. CREATE PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class CreatePaymentRunRequest:
    """DTO untuk request pembuatan payment run."""

    run_number: str
    run_type: PaymentRunType
    legal_entity_id: UUID
    selection_criteria: InvoiceSelectionCriteria
    payment_method: str = "BANK_TRANSFER"
    payment_date: datetime | None = None
    schedule: PaymentRunSchedule = PaymentRunSchedule.IMMEDIATE
    bank_account_from: str | None = None
    currency: str = "IDR"
    created_by: str = "system"
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.run_number or len(self.run_number.strip()) < 3:
            raise ValueError("Run number must be at least 3 characters")
        if not self.selection_criteria:
            raise ValueError("selection_criteria is required")
        if self.payment_date and self.payment_date.tzinfo is None:
            object.__setattr__(self, "payment_date", self.payment_date.replace(tzinfo=UTC))
        if self.payment_date is None and self.schedule == PaymentRunSchedule.SCHEDULED_DATE:
            raise ValueError("payment_date is required for SCHEDULED_DATE schedule")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_number": self.run_number,
            "run_type": self.run_type.value,
            "legal_entity_id": str(self.legal_entity_id),
            "selection_criteria": self.selection_criteria.to_dict(),
            "payment_method": self.payment_method,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "schedule": self.schedule.value,
            "bank_account_from": self.bank_account_from,
            "currency": self.currency,
            "created_by": self.created_by,
            "notes": self.notes,
        }


# === 5. UPDATE PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class UpdatePaymentRunRequest:
    """DTO untuk request update payment run."""

    run_id: UUID
    payment_date: datetime | None = None
    bank_account_from: str | None = None
    notes: str | None = None
    status: PaymentRunStatus | None = None

    def __post_init__(self) -> None:
        if not any([self.payment_date, self.bank_account_from, self.notes, self.status]):
            raise ValueError("At least one field to update must be provided")
        if self.payment_date and self.payment_date.tzinfo is None:
            object.__setattr__(self, "payment_date", self.payment_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "bank_account_from": self.bank_account_from,
            "notes": self.notes,
            "status": self.status.value if self.status else None,
        }


# === 6. PROCESS PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class ProcessPaymentRunRequest:
    """DTO untuk request proses payment run."""

    run_id: UUID
    processed_by: str
    instructions: list[PaymentInstruction] | None = None
    force_process: bool = False

    def __post_init__(self) -> None:
        if not self.processed_by:
            raise ValueError("processed_by is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "processed_by": self.processed_by,
            "instructions": [inst.to_dict() for inst in self.instructions]
            if self.instructions
            else None,
            "force_process": self.force_process,
        }


# === 7. APPROVE PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class ApprovePaymentRunRequest:
    """DTO untuk request approval payment run."""

    run_id: UUID
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
            "run_id": str(self.run_id),
            "approved_by": self.approved_by,
            "approval_level": self.approval_level,
            "notes": self.notes,
        }


# === 8. REJECT PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class RejectPaymentRunRequest:
    """DTO untuk request reject payment run."""

    run_id: UUID
    rejected_by: str
    reason: str

    def __post_init__(self) -> None:
        if not self.rejected_by:
            raise ValueError("rejected_by is required")
        if not self.reason or len(self.reason.strip()) < 5:
            raise ValueError("Reason must be at least 5 characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "rejected_by": self.rejected_by,
            "reason": self.reason,
        }


# === 9. CANCEL PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class CancelPaymentRunRequest:
    """DTO untuk request cancel payment run."""

    run_id: UUID
    cancelled_by: str
    reason: str

    def __post_init__(self) -> None:
        if not self.cancelled_by:
            raise ValueError("cancelled_by is required")
        if not self.reason or len(self.reason.strip()) < 5:
            raise ValueError("Reason must be at least 5 characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "cancelled_by": self.cancelled_by,
            "reason": self.reason,
        }


# === 10. GET PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class GetPaymentRunRequest:
    """DTO untuk request get payment run."""

    run_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# === 11. LIST PAYMENT RUNS REQUEST DTO ===


@dataclass(kw_only=True)
class ListPaymentRunsRequest:
    """DTO untuk request list payment runs dengan filter."""

    legal_entity_id: UUID
    run_type: PaymentRunType | None = None
    status: PaymentRunStatus | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "run_type": self.run_type.value if self.run_type else None,
            "status": self.status.value if self.status else None,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "created_by": self.created_by,
            "limit": self.limit,
            "offset": self.offset,
        }


# === 12. PAYMENT RUN SUMMARY REQUEST DTO ===


@dataclass(kw_only=True)
class PaymentRunSummaryRequest:
    """DTO untuk request summary payment run."""

    run_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# === 13. RESPONSE DTOS ===


class PaymentRunStatusDTO(str, Enum):
    """Status payment run untuk DTO response."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(kw_only=True)
class PaymentRunResponseDTO:
    """DTO response untuk payment run."""

    id: UUID
    run_number: str
    run_date: date
    total_amount: Decimal
    payment_ids: list[UUID]
    status: PaymentRunStatusDTO | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.completed_at and self.completed_at.tzinfo is None:
            object.__setattr__(self, "completed_at", self.completed_at.replace(tzinfo=UTC))


# === 14. FACTORY ===


class PaymentRunRequestFactory:
    """Factory untuk membuat Payment Run Request DTOs."""

    @staticmethod
    def create_ap_payment_run(
        run_number: str,
        legal_entity_id: UUID,
        vendor_ids: list[UUID],
        due_date_to: datetime,
        created_by: str,
        payment_date: datetime | None = None,
    ) -> CreatePaymentRunRequest:
        criteria = InvoiceSelectionCriteria(
            vendor_ids=vendor_ids,
            due_date_to=due_date_to,
            include_overdue=True,
        )
        if payment_date is None:
            payment_date = datetime.now(UTC)
        return CreatePaymentRunRequest(
            run_number=run_number,
            run_type=PaymentRunType.AP_PAYMENT,
            legal_entity_id=legal_entity_id,
            selection_criteria=criteria,
            payment_date=payment_date,
            created_by=created_by,
        )

    @staticmethod
    def create_ar_collection_run(
        run_number: str,
        legal_entity_id: UUID,
        customer_ids: list[UUID],
        due_date_to: datetime,
        created_by: str,
    ) -> CreatePaymentRunRequest:
        criteria = InvoiceSelectionCriteria(
            customer_ids=customer_ids,
            due_date_to=due_date_to,
            include_overdue=True,
        )
        return CreatePaymentRunRequest(
            run_number=run_number,
            run_type=PaymentRunType.AR_COLLECTION,
            legal_entity_id=legal_entity_id,
            selection_criteria=criteria,
            created_by=created_by,
        )


# === 15. EXPORTS ===

PaymentRunRequestDTO = CreatePaymentRunRequest

__all__ = [
    "ApprovePaymentRunRequest",
    "CancelPaymentRunRequest",
    "CreatePaymentRunRequest",
    "GetPaymentRunRequest",
    "InvoiceSelectionCriteria",
    "ListPaymentRunsRequest",
    "PaymentInstruction",
    "PaymentPriority",
    "PaymentRunRequestDTO",
    "PaymentRunRequestFactory",
    "PaymentRunResponseDTO",
    "PaymentRunSchedule",
    "PaymentRunStatus",
    "PaymentRunStatusDTO",
    "PaymentRunSummaryRequest",
    "PaymentRunType",
    "PaymentSelectionMethod",
    "ProcessPaymentRunRequest",
    "RejectPaymentRunRequest",
    "UpdatePaymentRunRequest",
]
