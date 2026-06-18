# ap_response.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: ap_response.py
Layer: 8 - Application / DTO Objects
Responsibility: DTO response untuk Accounts Payable (AP).

Fitur:
- Response DTOs untuk faktur, pembayaran, credit note
- Aging buckets dan laporan vendor balance
- Three-way match result
- Payment run response
- Validasi dan serialisasi lengkap
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

# === 1. RESPONSE DTOs ===


@dataclass(kw_only=True)
class APInvoiceResponseDTO:
    """Response DTO untuk faktur hutang."""

    id: UUID
    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    invoice_date: date
    due_date: date
    amount: Decimal
    invoice_type: str
    description: str | None
    po_number: str | None
    grn_number: str | None
    paid_amount: Decimal = Decimal("0.00")
    remaining_amount: Decimal = Decimal("0.00")
    currency: str = "IDR"
    status: str | None = None
    tax_amount: Decimal = Decimal("0.00")
    withholding_amount: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        # Calculate remaining amount if not set
        if self.remaining_amount == Decimal("0.00") and self.amount > 0:
            object.__setattr__(self, "remaining_amount", self.amount - self.paid_amount)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_number": self.invoice_number,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "amount": str(self.amount),
            "paid_amount": str(self.paid_amount),
            "remaining_amount": str(self.remaining_amount),
            "currency": self.currency,
            "status": self.status,
            "invoice_type": self.invoice_type,
            "tax_amount": str(self.tax_amount),
            "withholding_amount": str(self.withholding_amount),
            "description": self.description,
            "po_number": self.po_number,
            "grn_number": self.grn_number,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "version": self.version,
        }

    def is_overdue(self, as_of_date: date | None = None) -> bool:
        """Check if invoice is overdue."""
        check_date = as_of_date or date.today()
        return check_date > self.due_date and self.remaining_amount > 0

    def get_paid_percentage(self) -> Decimal:
        """Calculate paid percentage."""
        if self.amount > 0:
            return (self.paid_amount / self.amount * Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
        return Decimal(0)

    def get_aging_bucket(self, as_of_date: date | None = None) -> str:
        """Get aging bucket for the invoice."""
        check_date = as_of_date or date.today()
        if self.remaining_amount <= 0:
            return "PAID"

        days_overdue = (check_date - self.due_date).days
        if days_overdue <= 0:
            return "CURRENT"
        elif days_overdue <= 30:
            return "1-30 DAYS"
        elif days_overdue <= 60:
            return "31-60 DAYS"
        elif days_overdue <= 90:
            return "61-90 DAYS"
        else:
            return "OVER 90 DAYS"


@dataclass(kw_only=True)
class APPaymentResponseDTO:
    """Response DTO untuk pembayaran hutang."""

    id: UUID
    payment_number: str
    vendor_id: UUID
    vendor_name: str
    payment_date: date
    amount: Decimal
    applied_amount: Decimal
    remaining_to_allocate: Decimal
    payment_method: str
    reference_number: str | None
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    payment_run_id: UUID | None = None
    bank_account_id: UUID | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.remaining_to_allocate == Decimal("0.00") and self.amount > 0:
            object.__setattr__(self, "remaining_to_allocate", self.amount - self.applied_amount)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "payment_number": self.payment_number,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "payment_date": self.payment_date.isoformat(),
            "amount": str(self.amount),
            "applied_amount": str(self.applied_amount),
            "remaining_to_allocate": str(self.remaining_to_allocate),
            "payment_method": self.payment_method,
            "reference_number": self.reference_number,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "payment_run_id": str(self.payment_run_id) if self.payment_run_id else None,
            "bank_account_id": str(self.bank_account_id) if self.bank_account_id else None,
            "notes": self.notes,
        }

    def is_fully_applied(self) -> bool:
        """Check if payment is fully applied."""
        return self.remaining_to_allocate <= 0

    def get_applied_percentage(self) -> Decimal:
        """Calculate applied percentage."""
        if self.amount > 0:
            return (self.applied_amount / self.amount * Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
        return Decimal(0)


@dataclass(kw_only=True)
class APCreditNoteResponseDTO:
    """Response DTO untuk credit note hutang."""

    id: UUID
    credit_note_number: str
    vendor_id: UUID
    original_invoice_id: UUID | None
    issue_date: date
    amount: Decimal
    applied_amount: Decimal
    reason: str
    remaining_amount: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tax_amount: Decimal = Decimal("0.00")
    currency: str = "IDR"

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.remaining_amount == Decimal("0.00") and self.amount > 0:
            object.__setattr__(self, "remaining_amount", self.amount - self.applied_amount)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "credit_note_number": self.credit_note_number,
            "vendor_id": str(self.vendor_id),
            "original_invoice_id": str(self.original_invoice_id)
            if self.original_invoice_id
            else None,
            "issue_date": self.issue_date.isoformat(),
            "amount": str(self.amount),
            "applied_amount": str(self.applied_amount),
            "remaining_amount": str(self.remaining_amount),
            "reason": self.reason,
            "tax_amount": str(self.tax_amount),
            "currency": self.currency,
            "created_at": self.created_at.isoformat(),
        }

    def is_fully_applied(self) -> bool:
        """Check if credit note is fully applied."""
        return self.remaining_amount <= 0


@dataclass(kw_only=True)
class APVendorBalanceDTO:
    """Response DTO untuk saldo vendor."""

    vendor_id: UUID
    vendor_name: str
    vendor_code: str
    total_invoiced: Decimal
    total_payments: Decimal
    total_credit_notes: Decimal
    net_balance: Decimal
    currency: str = "IDR"
    as_of_date: date = field(default_factory=date.today)
    overdue_amount: Decimal = Decimal("0.00")

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "vendor_code": self.vendor_code,
            "total_invoiced": str(self.total_invoiced),
            "total_payments": str(self.total_payments),
            "total_credit_notes": str(self.total_credit_notes),
            "net_balance": str(self.net_balance),
            "overdue_amount": str(self.overdue_amount),
            "currency": self.currency,
            "as_of_date": self.as_of_date.isoformat(),
        }

    def get_balance_direction(self) -> str:
        """Get balance direction (debit/credit)."""
        if self.net_balance > 0:
            return "CREDIT"  # We owe to vendor
        elif self.net_balance < 0:
            return "DEBIT"  # Vendor owes us
        return "ZERO"


@dataclass(kw_only=True)
class APAgingBucketDTO:
    """DTO untuk satu bucket aging."""

    bucket_name: str
    amount: Decimal
    percentage: float
    invoice_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket_name": self.bucket_name,
            "amount": str(self.amount),
            "percentage": self.percentage,
            "invoice_count": self.invoice_count,
        }

    @classmethod
    def create(
        cls, bucket_name: str, amount: Decimal, total: Decimal, invoice_count: int = 0
    ) -> APAgingBucketDTO:
        """Create bucket with percentage calculation."""
        percentage = float(amount / total * 100) if total > 0 else 0.0
        return cls(
            bucket_name=bucket_name,
            amount=amount,
            percentage=round(percentage, 2),
            invoice_count=invoice_count,
        )


@dataclass(kw_only=True)
class APAgingReportDTO:
    """Response DTO untuk laporan aging hutang."""

    legal_entity_id: UUID
    legal_entity_name: str
    as_of_date: date
    buckets: list[APAgingBucketDTO]
    total_ap: Decimal
    vendor_balances: dict[str, str]  # vendor_id -> balance as string
    vendor_details: list[dict[str, Any]] | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            object.__setattr__(self, "generated_at", self.generated_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "legal_entity_name": self.legal_entity_name,
            "as_of_date": self.as_of_date.isoformat(),
            "buckets": [b.to_dict() for b in self.buckets],
            "total_ap": str(self.total_ap),
            "vendor_balances": self.vendor_balances,
            "vendor_details": self.vendor_details,
            "generated_at": self.generated_at.isoformat(),
        }

    def get_bucket_by_name(self, bucket_name: str) -> APAgingBucketDTO | None:
        """Get bucket by name."""
        for bucket in self.buckets:
            if bucket.bucket_name == bucket_name:
                return bucket
        return None


@dataclass(kw_only=True)
class APPaymentRunResponseDTO:
    """Response DTO untuk payment run."""

    run_id: UUID
    run_number: str
    run_date: date
    total_amount: Decimal
    payment_count: int
    status: str | None = None
    payments: list[APPaymentResponseDTO] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.processed_at and self.processed_at.tzinfo is None:
            object.__setattr__(self, "processed_at", self.processed_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "run_number": self.run_number,
            "run_date": self.run_date.isoformat(),
            "total_amount": str(self.total_amount),
            "payment_count": self.payment_count,
            "status": self.status,
            "payments": [p.to_dict() for p in self.payments] if self.payments else [],
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": self.approved_by,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }

    def is_approved(self) -> bool:
        """Check if payment run is approved."""
        return self.status == "APPROVED"

    def is_processed(self) -> bool:
        """Check if payment run is processed."""
        return self.status == "PROCESSED"


@dataclass(kw_only=True)
class ThreeWayMatchResultDTO:
    """Response DTO untuk hasil three-way matching."""

    is_match: bool
    discrepancies: list[str]
    matched_amount: Decimal
    po_amount: Decimal
    grn_amount: Decimal
    invoice_amount: Decimal
    po_number: str
    grn_number: str
    invoice_number: str
    tolerance: Decimal = Decimal("0.01")

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_match": self.is_match,
            "discrepancies": self.discrepancies,
            "matched_amount": str(self.matched_amount),
            "po_amount": str(self.po_amount),
            "grn_amount": str(self.grn_amount),
            "invoice_amount": str(self.invoice_amount),
            "po_number": self.po_number,
            "grn_number": self.grn_number,
            "invoice_number": self.invoice_number,
            "tolerance": str(self.tolerance),
        }

    def get_variance_amount(self) -> Decimal:
        """Calculate variance amount."""
        return abs(self.invoice_amount - self.matched_amount)

    def get_variance_percentage(self) -> Decimal:
        """Calculate variance percentage."""
        if self.matched_amount > 0:
            return (self.get_variance_amount() / self.matched_amount * Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
        return Decimal(0)


# === 2. EXPORTS ===

__all__ = [
    "APAgingBucketDTO",
    "APAgingReportDTO",
    "APCreditNoteResponseDTO",
    "APInvoiceResponseDTO",
    "APPaymentResponseDTO",
    "APPaymentRunResponseDTO",
    "APVendorBalanceDTO",
    "ThreeWayMatchResultDTO",
]
