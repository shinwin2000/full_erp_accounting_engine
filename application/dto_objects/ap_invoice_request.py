# ap_invoice_request.py - Hardened version with complete implementation (FIXED)
# Added APInvoiceUpdateRequest alias for compatibility with fastapi_ap_router.py

#!/usr/bin/env python3
"""
Module: ap_invoice_request.py
Layer: 8 - Application / DTO Objects
Responsibility: DTO permintaan faktur hutang (Accounts Payable).

Fitur:
- Validasi lengkap untuk semua request
- Perhitungan otomatis subtotal, diskon, pajak
- Three-way matching support
- Payment run support
- Credit note and debit note
- Factory methods untuk pembuatan mudah
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# === 1. CONSTANTS & ENUMS ===


class APInvoiceType(str, Enum):
    """Jenis faktur hutang."""

    STANDARD = "standard"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    PREPAYMENT = "prepayment"

    def is_credit(self) -> bool:
        return self in (self.CREDIT_NOTE, self.DEBIT_NOTE)

    def is_reduction(self) -> bool:
        return self == self.CREDIT_NOTE


class APInvoiceStatus(str, Enum):
    """Status faktur hutang."""

    DRAFT = "draft"
    RECEIVED = "received"
    VERIFIED = "verified"
    APPROVED = "approved"
    PARTIALLY_PAID = "partially_paid"
    FULLY_PAID = "fully_paid"
    OVERDUE = "overdue"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"

    def can_edit(self) -> bool:
        return self in (self.DRAFT, self.RECEIVED)

    def can_pay(self) -> bool:
        return self in (self.APPROVED, self.PARTIALLY_PAID)

    def is_paid(self) -> bool:
        return self == self.FULLY_PAID


class APPaymentMethod(str, Enum):
    """Metode pembayaran hutang."""

    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    CHEQUE = "cheque"
    GIRO = "giro"
    WIRE_TRANSFER = "wire_transfer"
    ONLINE_PAYMENT = "online_payment"

    def requires_bank_account(self) -> bool:
        return self in (self.BANK_TRANSFER, self.WIRE_TRANSFER, self.ONLINE_PAYMENT)


class APPaymentStatus(str, Enum):
    """Status pembayaran hutang."""

    PENDING = "pending"
    APPROVED = "approved"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class APCreditNoteReason(str, Enum):
    """Alasan credit note dari vendor."""

    GOODS_RETURN = "goods_return"
    PRICE_ADJUSTMENT = "price_adjustment"
    DISCOUNT = "discount"
    CANCELLATION = "cancellation"
    CORRECTION = "correction"
    QUALITY_ISSUE = "quality_issue"
    DAMAGE = "damage"


class WithholdingArticle(str, Enum):
    """Pasal pemotongan PPh."""

    PPH_21 = "21"
    PPH_22 = "22"
    PPH_23 = "23"
    PPH_26 = "26"
    PPH_4_2 = "4(2)"
    NONE = "none"

    def get_rate(self) -> Decimal:
        """Get default withholding rate for article."""
        rates = {
            self.PPH_21: Decimal("5"),
            self.PPH_22: Decimal("1.5"),
            self.PPH_23: Decimal("2"),
            self.PPH_26: Decimal("20"),
            self.PPH_4_2: Decimal("10"),
            self.NONE: Decimal("0"),
        }
        return rates.get(self, Decimal("0"))


# === 2. INVOICE LINE REQUEST DTO ===


@dataclass(kw_only=True)
class APInvoiceLineRequest:
    """DTO untuk baris faktur hutang."""

    item_id: UUID
    item_code: str
    item_name: str
    quantity: Decimal
    unit_price: Decimal
    po_item_id: UUID | None = None
    discount_percentage: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)  # PPN 11%
    unit_of_measure: str = "PCS"
    description: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"Unit price cannot be negative: {self.unit_price}")
        if self.discount_percentage < 0 or self.discount_percentage > 100:
            raise ValueError(
                f"Discount percentage must be between 0 and 100: {self.discount_percentage}"
            )
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {self.tax_rate}")

    @property
    def subtotal(self) -> Decimal:
        """Subtotal sebelum diskon."""
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    @property
    def discount_amount(self) -> Decimal:
        """Jumlah diskon."""
        return (self.subtotal * self.discount_percentage / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def net_amount(self) -> Decimal:
        """Jumlah setelah diskon."""
        return (self.subtotal - self.discount_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def tax_amount(self) -> Decimal:
        """Jumlah PPN."""
        return (self.net_amount * self.tax_rate / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def total_amount(self) -> Decimal:
        """Total jumlah (setelah diskon + PPN)."""
        return (self.net_amount + self.tax_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "po_item_id": str(self.po_item_id) if self.po_item_id else None,
            "discount_percentage": str(self.discount_percentage),
            "tax_rate": str(self.tax_rate),
            "unit_of_measure": self.unit_of_measure,
            "description": self.description,
            "subtotal": str(self.subtotal),
            "discount_amount": str(self.discount_amount),
            "net_amount": str(self.net_amount),
            "tax_amount": str(self.tax_amount),
            "total_amount": str(self.total_amount),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> APInvoiceLineRequest:
        return cls(
            item_id=UUID(data["item_id"]),
            item_code=data["item_code"],
            item_name=data["item_name"],
            quantity=Decimal(str(data["quantity"])),
            unit_price=Decimal(str(data["unit_price"])),
            po_item_id=UUID(data["po_item_id"]) if data.get("po_item_id") else None,
            discount_percentage=Decimal(str(data.get("discount_percentage", 0))),
            tax_rate=Decimal(str(data.get("tax_rate", 11))),
            unit_of_measure=data.get("unit_of_measure", "PCS"),
            description=data.get("description", ""),
        )


# === 3. CREATE AP INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class CreateAPInvoiceRequest:
    """DTO untuk request pembuatan faktur hutang."""

    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    invoice_date: datetime
    due_date: datetime
    amount: Decimal
    lines: list[APInvoiceLineRequest]
    invoice_type: APInvoiceType = APInvoiceType.STANDARD
    currency: str = "IDR"
    description: str = ""
    po_id: UUID | None = None
    po_number: str | None = None
    grn_id: UUID | None = None
    grn_number: str | None = None
    tax_amount: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    shipping_cost: Decimal = Decimal(0)
    other_costs: Decimal = Decimal(0)
    withholding_article: WithholdingArticle = WithholdingArticle.NONE
    withholding_rate: Decimal = Decimal(0)
    withholding_amount: Decimal = Decimal(0)
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.invoice_number or len(self.invoice_number.strip()) < 3:
            raise ValueError("Invoice number must be at least 3 characters")
        if not self.vendor_name:
            raise ValueError("Vendor name is required")
        if self.amount <= 0:
            raise ValueError(f"Invoice amount must be positive: {self.amount}")
        if not self.lines:
            raise ValueError("Invoice must have at least one line")
        if self.due_date <= self.invoice_date:
            raise ValueError(
                f"Due date {self.due_date} must be after invoice date {self.invoice_date}"
            )
        if self.invoice_date.tzinfo is None:
            object.__setattr__(self, "invoice_date", self.invoice_date.replace(tzinfo=UTC))
        if self.due_date.tzinfo is None:
            object.__setattr__(self, "due_date", self.due_date.replace(tzinfo=UTC))
        if self.tax_amount < 0:
            raise ValueError(f"Tax amount cannot be negative: {self.tax_amount}")
        if self.discount_amount < 0:
            raise ValueError(f"Discount amount cannot be negative: {self.discount_amount}")
        if self.shipping_cost < 0:
            raise ValueError(f"Shipping cost cannot be negative: {self.shipping_cost}")
        if self.other_costs < 0:
            raise ValueError(f"Other costs cannot be negative: {self.other_costs}")
        if self.withholding_rate < 0 or self.withholding_rate > 100:
            raise ValueError(f"Withholding rate must be between 0 and 100: {self.withholding_rate}")
        if self.withholding_amount < 0:
            raise ValueError(f"Withholding amount cannot be negative: {self.withholding_amount}")

    def calculate_subtotal(self) -> Decimal:
        """Menghitung subtotal dari semua baris."""
        return sum(line.subtotal for line in self.lines)

    def calculate_discount_total(self) -> Decimal:
        """Menghitung total diskon."""
        return sum(line.discount_amount for line in self.lines) + self.discount_amount

    def calculate_tax_total(self) -> Decimal:
        """Menghitung total PPN."""
        return sum(line.tax_amount for line in self.lines) + self.tax_amount

    def calculate_items_total(self) -> Decimal:
        """Menghitung total item (setelah diskon + PPN)."""
        return sum(line.total_amount for line in self.lines)

    def calculate_total_amount(self) -> Decimal:
        """Menghitung total faktur."""
        total = self.calculate_items_total() + self.shipping_cost + self.other_costs
        total = total - self.discount_amount + self.tax_amount
        total = total - self.withholding_amount
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def is_balanced_with_lines(self, tolerance: Decimal = Decimal("0.01")) -> bool:
        """Check if total amount matches line calculations."""
        calculated_total = self.calculate_total_amount()
        return abs(calculated_total - self.amount) <= tolerance

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_number": self.invoice_number,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "amount": str(self.amount),
            "lines": [line.to_dict() for line in self.lines],
            "invoice_type": self.invoice_type.value,
            "currency": self.currency,
            "description": self.description,
            "po_id": str(self.po_id) if self.po_id else None,
            "po_number": self.po_number,
            "grn_id": str(self.grn_id) if self.grn_id else None,
            "grn_number": self.grn_number,
            "tax_amount": str(self.tax_amount),
            "discount_amount": str(self.discount_amount),
            "shipping_cost": str(self.shipping_cost),
            "other_costs": str(self.other_costs),
            "withholding_article": self.withholding_article.value,
            "withholding_rate": str(self.withholding_rate),
            "withholding_amount": str(self.withholding_amount),
            "notes": self.notes,
            "subtotal": str(self.calculate_subtotal()),
            "items_total": str(self.calculate_items_total()),
            "total_amount": str(self.calculate_total_amount()),
            "is_balanced": self.is_balanced_with_lines(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreateAPInvoiceRequest:
        lines = [APInvoiceLineRequest.from_dict(line) for line in data.get("lines", [])]
        return cls(
            invoice_number=data["invoice_number"],
            vendor_id=UUID(data["vendor_id"]),
            vendor_name=data["vendor_name"],
            invoice_date=datetime.fromisoformat(data["invoice_date"]),
            due_date=datetime.fromisoformat(data["due_date"]),
            amount=Decimal(str(data["amount"])),
            lines=lines,
            invoice_type=APInvoiceType(data.get("invoice_type", "standard")),
            currency=data.get("currency", "IDR"),
            description=data.get("description", ""),
            po_id=UUID(data["po_id"]) if data.get("po_id") else None,
            po_number=data.get("po_number"),
            grn_id=UUID(data["grn_id"]) if data.get("grn_id") else None,
            grn_number=data.get("grn_number"),
            tax_amount=Decimal(str(data.get("tax_amount", 0))),
            discount_amount=Decimal(str(data.get("discount_amount", 0))),
            shipping_cost=Decimal(str(data.get("shipping_cost", 0))),
            other_costs=Decimal(str(data.get("other_costs", 0))),
            withholding_article=WithholdingArticle(data.get("withholding_article", "none")),
            withholding_rate=Decimal(str(data.get("withholding_rate", 0))),
            withholding_amount=Decimal(str(data.get("withholding_amount", 0))),
            notes=data.get("notes", ""),
            idempotency_key=data.get("idempotency_key"),
        )


# === 4. UPDATE AP INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class UpdateAPInvoiceRequest:
    """DTO untuk request update faktur hutang."""

    invoice_id: UUID
    due_date: datetime | None = None
    description: str | None = None
    notes: str | None = None
    discount_amount: Decimal | None = None
    shipping_cost: Decimal | None = None
    other_costs: Decimal | None = None

    def __post_init__(self) -> None:
        if not any(
            [
                self.due_date,
                self.description,
                self.notes,
                self.discount_amount,
                self.shipping_cost,
                self.other_costs,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.due_date and self.due_date.tzinfo is None:
            object.__setattr__(self, "due_date", self.due_date.replace(tzinfo=UTC))
        if self.discount_amount is not None and self.discount_amount < 0:
            raise ValueError(f"Discount amount cannot be negative: {self.discount_amount}")
        if self.shipping_cost is not None and self.shipping_cost < 0:
            raise ValueError(f"Shipping cost cannot be negative: {self.shipping_cost}")
        if self.other_costs is not None and self.other_costs < 0:
            raise ValueError(f"Other costs cannot be negative: {self.other_costs}")

    def to_dict(self) -> dict[str, Any]:
        result = {"invoice_id": str(self.invoice_id)}
        if self.due_date is not None:
            result["due_date"] = self.due_date.isoformat()
        if self.description is not None:
            result["description"] = self.description
        if self.notes is not None:
            result["notes"] = self.notes
        if self.discount_amount is not None:
            result["discount_amount"] = str(self.discount_amount)
        if self.shipping_cost is not None:
            result["shipping_cost"] = str(self.shipping_cost)
        if self.other_costs is not None:
            result["other_costs"] = str(self.other_costs)
        return result


# === 5. VERIFY AP INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class VerifyAPInvoiceRequest:
    """DTO untuk request verifikasi faktur hutang (3-way matching)."""

    invoice_id: UUID
    po_id: UUID
    grn_id: UUID
    verified_by: str

    def __post_init__(self) -> None:
        if not self.verified_by:
            raise ValueError("verified_by is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": str(self.invoice_id),
            "po_id": str(self.po_id),
            "grn_id": str(self.grn_id),
            "verified_by": self.verified_by,
        }


# === 6. APPROVE AP INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class ApproveAPInvoiceRequest:
    """DTO untuk request approval faktur hutang."""

    invoice_id: UUID
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
            "invoice_id": str(self.invoice_id),
            "approved_by": self.approved_by,
            "approval_level": self.approval_level,
            "notes": self.notes,
        }


# === 7. RECORD AP PAYMENT REQUEST DTO ===


@dataclass(kw_only=True)
class RecordAPPaymentRequest:
    """DTO untuk request pencatatan pembayaran hutang."""

    payment_number: str
    vendor_id: UUID
    vendor_name: str
    payment_date: datetime
    amount: Decimal
    payment_method: APPaymentMethod
    currency: str = "IDR"
    invoice_id: UUID | None = None
    invoice_number: str | None = None
    bank_account_from: str | None = None
    bank_account_to: str | None = None
    reference_number: str | None = None
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.payment_number or len(self.payment_number.strip()) < 3:
            raise ValueError("Payment number must be at least 3 characters")
        if not self.vendor_name:
            raise ValueError("Vendor name is required")
        if self.amount <= 0:
            raise ValueError(f"Payment amount must be positive: {self.amount}")
        if self.payment_date.tzinfo is None:
            object.__setattr__(self, "payment_date", self.payment_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_number": self.payment_number,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "payment_date": self.payment_date.isoformat(),
            "amount": str(self.amount),
            "payment_method": self.payment_method.value,
            "currency": self.currency,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "invoice_number": self.invoice_number,
            "bank_account_from": self.bank_account_from,
            "bank_account_to": self.bank_account_to,
            "reference_number": self.reference_number,
            "notes": self.notes,
        }


# === 8. CREATE AP CREDIT NOTE REQUEST DTO ===


@dataclass(kw_only=True)
class CreateAPCreditNoteRequest:
    """DTO untuk request pembuatan credit note dari vendor."""

    credit_note_number: str
    invoice_id: UUID
    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    amount: Decimal
    reason: APCreditNoteReason
    currency: str = "IDR"
    description: str = ""
    tax_amount: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.credit_note_number or len(self.credit_note_number.strip()) < 3:
            raise ValueError("Credit note number must be at least 3 characters")
        if not self.vendor_name:
            raise ValueError("Vendor name is required")
        if self.amount <= 0:
            raise ValueError(f"Credit note amount must be positive: {self.amount}")
        if self.tax_amount < 0:
            raise ValueError(f"Tax amount cannot be negative: {self.tax_amount}")
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {self.tax_rate}")

    def calculate_total_amount(self) -> Decimal:
        """Menghitung total credit note (termasuk pajak)."""
        return (self.amount + self.tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit_note_number": self.credit_note_number,
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "amount": str(self.amount),
            "reason": self.reason.value,
            "currency": self.currency,
            "description": self.description,
            "tax_amount": str(self.tax_amount),
            "tax_rate": str(self.tax_rate),
            "total_amount": str(self.calculate_total_amount()),
            "notes": self.notes,
        }


# === 9. GET AP INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class GetAPInvoiceRequest:
    """DTO untuk request get faktur hutang."""

    invoice_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": str(self.invoice_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# === 10. LIST AP INVOICES REQUEST DTO ===


@dataclass(kw_only=True)
class ListAPInvoicesRequest:
    """DTO untuk request list faktur hutang dengan filter."""

    legal_entity_id: UUID
    vendor_id: UUID | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    status: APInvoiceStatus | None = None
    is_overdue: bool | None = None
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
            "vendor_id": str(self.vendor_id) if self.vendor_id else None,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "status": self.status.value if self.status else None,
            "is_overdue": self.is_overdue,
            "limit": self.limit,
            "offset": self.offset,
        }


# === 11. GET AP AGING REQUEST DTO ===


@dataclass(kw_only=True)
class GetAPAgingRequest:
    """DTO untuk request aging hutang."""

    legal_entity_id: UUID
    as_of_date: datetime | None = None
    vendor_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.as_of_date is None:
            object.__setattr__(self, "as_of_date", datetime.now(UTC))
        elif self.as_of_date.tzinfo is None:
            object.__setattr__(self, "as_of_date", self.as_of_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "vendor_id": str(self.vendor_id) if self.vendor_id else None,
        }


# === 12. PAYMENT RUN REQUEST DTO ===


@dataclass(kw_only=True)
class APPaymentRunRequestDTO:
    """DTO untuk request generate payment run (batch payment)."""

    legal_entity_id: UUID
    payment_date: date
    payment_method: str
    bank_account_id: UUID | None = None
    vendor_id: UUID | None = None
    max_total_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.payment_method:
            raise ValueError("payment_method is required")
        if self.max_total_amount is not None and self.max_total_amount <= 0:
            raise ValueError("max_total_amount must be positive if provided")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "payment_date": self.payment_date.isoformat(),
            "payment_method": self.payment_method,
            "bank_account_id": str(self.bank_account_id) if self.bank_account_id else None,
            "vendor_id": str(self.vendor_id) if self.vendor_id else None,
            "max_total_amount": str(self.max_total_amount) if self.max_total_amount else None,
        }


# === 13. THREE-WAY MATCH REQUEST DTO ===


@dataclass(kw_only=True)
class ThreeWayMatchRequestDTO:
    """DTO untuk request three-way matching (PO, GRN, Invoice)."""

    po_number: str
    grn_number: str
    invoice_amount: Decimal
    vendor_id: UUID

    def __post_init__(self) -> None:
        if not self.po_number or not self.grn_number:
            raise ValueError("po_number and grn_number are required")
        if self.invoice_amount <= 0:
            raise ValueError("invoice_amount must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "po_number": self.po_number,
            "grn_number": self.grn_number,
            "invoice_amount": str(self.invoice_amount),
            "vendor_id": str(self.vendor_id),
        }


# === 14. SIMPLE AP INVOICE REQUEST (for test compatibility) ===


@dataclass(kw_only=True)
class ApInvoiceRequest:
    """Simple AP invoice request DTO for basic invoice creation."""

    supplier_id: str
    amount: Decimal
    tax: Decimal = Decimal(0)
    due_date: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(days=30))

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive: {self.amount}")
        if self.tax < 0:
            raise ValueError(f"Tax cannot be negative: {self.tax}")
        if self.due_date.tzinfo is None:
            object.__setattr__(self, "due_date", self.due_date.replace(tzinfo=UTC))

    @property
    def total(self) -> Decimal:
        return self.amount + self.tax


# === 15. FACTORY ===


class APInvoiceRequestFactory:
    """Factory untuk membuat AP Invoice Request DTOs."""

    @staticmethod
    def create_invoice_line(
        item_id: UUID,
        item_code: str,
        item_name: str,
        quantity: Decimal,
        unit_price: Decimal,
        description: str = "",
        po_item_id: UUID | None = None,
        discount_percentage: Decimal = Decimal(0),
        tax_rate: Decimal = Decimal(11),
    ) -> APInvoiceLineRequest:
        return APInvoiceLineRequest(
            item_id=item_id,
            item_code=item_code,
            item_name=item_name,
            quantity=quantity,
            unit_price=unit_price,
            po_item_id=po_item_id,
            discount_percentage=discount_percentage,
            tax_rate=tax_rate,
            description=description,
        )

    @staticmethod
    def create_simple_invoice(
        invoice_number: str,
        vendor_id: UUID,
        vendor_name: str,
        invoice_date: datetime,
        due_date: datetime,
        amount: Decimal,
        item_id: UUID,
        item_code: str,
        item_name: str,
        quantity: Decimal,
        unit_price: Decimal,
        description: str = "",
    ) -> CreateAPInvoiceRequest:
        line = APInvoiceRequestFactory.create_invoice_line(
            item_id=item_id,
            item_code=item_code,
            item_name=item_name,
            quantity=quantity,
            unit_price=unit_price,
            description=description,
        )
        return CreateAPInvoiceRequest(
            invoice_number=invoice_number,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            invoice_date=invoice_date,
            due_date=due_date,
            amount=amount,
            lines=[line],
        )

    @staticmethod
    def create_payment(
        payment_number: str,
        vendor_id: UUID,
        vendor_name: str,
        payment_date: datetime,
        amount: Decimal,
        invoice_id: UUID,
        payment_method: APPaymentMethod = APPaymentMethod.BANK_TRANSFER,
    ) -> RecordAPPaymentRequest:
        return RecordAPPaymentRequest(
            payment_number=payment_number,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            payment_date=payment_date,
            amount=amount,
            payment_method=payment_method,
            invoice_id=invoice_id,
        )


# === 16. RESPONSE DTOs ===


class APInvoiceStatusDTO(str, Enum):
    """Status faktur hutang untuk DTO response."""

    DRAFT = "draft"
    RECEIVED = "received"
    VERIFIED = "verified"
    APPROVED = "approved"
    PARTIALLY_PAID = "partially_paid"
    FULLY_PAID = "fully_paid"
    OVERDUE = "overdue"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"


@dataclass(kw_only=True)
class APInvoiceResponseDTO:
    """Response DTO untuk faktur hutang."""

    id: UUID
    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    invoice_date: datetime
    due_date: datetime
    amount: Decimal
    paid_amount: Decimal = Decimal("0.00")
    remaining_amount: Decimal = Decimal("0.00")
    currency: str = "IDR"
    status: str | None = None
    tax_amount: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    tax_code: str | None = None
    description: str | None = None
    po_reference: str | None = None
    grn_reference: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

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
            "tax_amount": str(self.tax_amount),
            "created_at": self.created_at.isoformat(),
            "version": self.version,
            "tax_code": self.tax_code,
            "description": self.description,
            "po_reference": self.po_reference,
            "grn_reference": self.grn_reference,
        }

    def is_overdue(self, as_of_date: datetime | None = None) -> bool:
        """Check if invoice is overdue."""
        check_date = as_of_date or datetime.now(UTC)
        return check_date > self.due_date and self.remaining_amount > 0

    def get_payment_percentage(self) -> Decimal:
        """Calculate payment percentage."""
        if self.amount > 0:
            return (self.paid_amount / self.amount * 100).quantize(Decimal("0.01"))
        return Decimal(0)


@dataclass(kw_only=True)
class APPaymentResponseDTO:
    """Response DTO untuk pembayaran hutang."""

    id: UUID
    invoice_id: UUID
    payment_number: str
    payment_date: datetime
    amount: Decimal
    payment_method: str
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reference_number: str | None = None
    bank_account_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_id": str(self.invoice_id),
            "payment_number": self.payment_number,
            "payment_date": self.payment_date.isoformat(),
            "amount": str(self.amount),
            "payment_method": self.payment_method,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "reference_number": self.reference_number,
            "bank_account_id": str(self.bank_account_id) if self.bank_account_id else None,
        }


# === 17. ALIASES FOR FASTAPI ROUTER COMPATIBILITY ===

# Core DTO aliases (used by fastapi_ap_router.py)
APInvoiceCreateRequest = CreateAPInvoiceRequest
APInvoiceUpdateRequest = UpdateAPInvoiceRequest  # <--- ADDED for compatibility
APPaymentCreateRequest = RecordAPPaymentRequest
APCreditNoteCreateRequest = CreateAPCreditNoteRequest
APPaymentRunRequest = APPaymentRunRequestDTO

# Additional aliases for flexibility
APInvoiceRequestDTO = CreateAPInvoiceRequest
APInvoiceCreateRequestDTO = CreateAPInvoiceRequest
APInvoiceUpdateRequestDTO = UpdateAPInvoiceRequest
APPaymentRequestDTO = RecordAPPaymentRequest
APPaymentRecordRequestDTO = RecordAPPaymentRequest
APCreditNoteRequestDTO = CreateAPCreditNoteRequest
APDebitNoteRequestDTO = CreateAPInvoiceRequest


# === 18. EXPORTS ===

__all__ = [
    # Enums
    "APInvoiceType",
    "APInvoiceStatus",
    "APPaymentMethod",
    "APPaymentStatus",
    "APCreditNoteReason",
    "WithholdingArticle",
    "APInvoiceStatusDTO",
    # Core DTOs
    "APInvoiceLineRequest",
    "CreateAPInvoiceRequest",
    "UpdateAPInvoiceRequest",
    "VerifyAPInvoiceRequest",
    "ApproveAPInvoiceRequest",
    "RecordAPPaymentRequest",
    "CreateAPCreditNoteRequest",
    "GetAPInvoiceRequest",
    "ListAPInvoicesRequest",
    "GetAPAgingRequest",
    "APPaymentRunRequestDTO",
    "ThreeWayMatchRequestDTO",
    "ApInvoiceRequest",
    # Response DTOs
    "APInvoiceResponseDTO",
    "APPaymentResponseDTO",
    # Factory
    "APInvoiceRequestFactory",
    # Aliases (important for router)
    "APInvoiceCreateRequest",
    "APInvoiceUpdateRequest",  # <--- ADDED to exports
    "APPaymentCreateRequest",
    "APCreditNoteCreateRequest",
    "APPaymentRunRequest",
    "APInvoiceRequestDTO",
    "APInvoiceCreateRequestDTO",
    "APInvoiceUpdateRequestDTO",
    "APPaymentRequestDTO",
    "APPaymentRecordRequestDTO",
    "APCreditNoteRequestDTO",
    "APDebitNoteRequestDTO",
]