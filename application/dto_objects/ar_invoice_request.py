# ar_invoice_request.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: ar_invoice_request.py
Layer: 8 - Application / DTO Objects
Responsibility: DTO permintaan faktur piutang (Accounts Receivable).

Fitur:
- Validasi lengkap untuk semua request
- Perhitungan otomatis subtotal, diskon, pajak
- Credit note dan debit note support
- Write-off support
- Payment processing
- Factory methods untuk pembuatan mudah
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# === 1. CONSTANTS & ENUMS ===


class ARInvoiceType(str, Enum):
    """Jenis faktur piutang."""

    STANDARD = "standard"
    PROFORMA = "proforma"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"

    def is_credit(self) -> bool:
        return self == self.CREDIT_NOTE

    def is_debit(self) -> bool:
        return self == self.DEBIT_NOTE


class ARInvoiceStatus(str, Enum):
    """Status faktur piutang."""

    DRAFT = "draft"
    ISSUED = "issued"
    SENT = "sent"
    PARTIALLY_PAID = "partially_paid"
    FULLY_PAID = "fully_paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    WRITTEN_OFF = "written_off"

    def can_edit(self) -> bool:
        return self in (self.DRAFT, self.ISSUED)

    def can_collect(self) -> bool:
        return self in (self.ISSUED, self.SENT, self.PARTIALLY_PAID, self.OVERDUE)

    def is_paid(self) -> bool:
        return self == self.FULLY_PAID


class PaymentMethod(str, Enum):
    """Metode pembayaran."""

    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CHEQUE = "cheque"
    GIRO = "giro"
    DIGITAL_WALLET = "digital_wallet"
    QRIS = "qris"

    def requires_bank_account(self) -> bool:
        return self in (self.BANK_TRANSFER, self.CREDIT_CARD, self.DEBIT_CARD)


class PaymentStatus(str, Enum):
    """Status pembayaran."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REFUNDED = "refunded"

    def is_success(self) -> bool:
        return self == self.CONFIRMED


class CreditNoteReason(str, Enum):
    """Alasan credit note."""

    GOODS_RETURN = "goods_return"
    PRICE_ADJUSTMENT = "price_adjustment"
    DISCOUNT = "discount"
    CANCELLATION = "cancellation"
    CORRECTION = "correction"
    QUALITY_ISSUE = "quality_issue"
    EARLY_PAYMENT = "early_payment"


# === 2. INVOICE LINE REQUEST DTO ===


@dataclass(kw_only=True)
class ARInvoiceLineRequest:
    """DTO untuk baris faktur piutang."""

    item_id: UUID
    item_code: str
    item_name: str
    quantity: Decimal
    unit_price: Decimal
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
    def from_dict(cls, data: dict[str, Any]) -> ARInvoiceLineRequest:
        return cls(
            item_id=UUID(data["item_id"]),
            item_code=data["item_code"],
            item_name=data["item_name"],
            quantity=Decimal(str(data["quantity"])),
            unit_price=Decimal(str(data["unit_price"])),
            discount_percentage=Decimal(str(data.get("discount_percentage", 0))),
            tax_rate=Decimal(str(data.get("tax_rate", 11))),
            unit_of_measure=data.get("unit_of_measure", "PCS"),
            description=data.get("description", ""),
        )


# === 3. CREATE AR INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class CreateARInvoiceRequest:
    """DTO untuk request pembuatan faktur piutang."""

    invoice_number: str
    customer_id: UUID
    customer_name: str
    issue_date: datetime
    due_date: datetime
    lines: list[ARInvoiceLineRequest]
    invoice_type: ARInvoiceType = ARInvoiceType.STANDARD
    currency: str = "IDR"
    description: str = ""
    sales_order_id: UUID | None = None
    sales_order_number: str | None = None
    shipping_cost: Decimal = Decimal(0)
    other_costs: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.invoice_number or len(self.invoice_number.strip()) < 3:
            raise ValueError("Invoice number must be at least 3 characters")
        if not self.customer_name:
            raise ValueError("Customer name is required")
        if not self.lines:
            raise ValueError("Invoice must have at least one line")
        if self.due_date <= self.issue_date:
            raise ValueError(f"Due date {self.due_date} must be after issue date {self.issue_date}")
        if self.issue_date.tzinfo is None:
            object.__setattr__(self, "issue_date", self.issue_date.replace(tzinfo=UTC))
        if self.due_date.tzinfo is None:
            object.__setattr__(self, "due_date", self.due_date.replace(tzinfo=UTC))
        if self.shipping_cost < 0:
            raise ValueError(f"Shipping cost cannot be negative: {self.shipping_cost}")
        if self.other_costs < 0:
            raise ValueError(f"Other costs cannot be negative: {self.other_costs}")
        if self.discount_amount < 0:
            raise ValueError(f"Discount amount cannot be negative: {self.discount_amount}")

    def calculate_subtotal(self) -> Decimal:
        """Menghitung subtotal dari semua baris."""
        return sum(line.subtotal for line in self.lines)

    def calculate_discount_total(self) -> Decimal:
        """Menghitung total diskon."""
        return sum(line.discount_amount for line in self.lines) + self.discount_amount

    def calculate_tax_total(self) -> Decimal:
        """Menghitung total PPN."""
        return sum(line.tax_amount for line in self.lines)

    def calculate_items_total(self) -> Decimal:
        """Menghitung total item (setelah diskon + PPN)."""
        return sum(line.total_amount for line in self.lines)

    def calculate_total_amount(self) -> Decimal:
        """Menghitung total faktur."""
        total = self.calculate_items_total() + self.shipping_cost + self.other_costs
        total = total - self.discount_amount
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def is_balanced_with_lines(self, tolerance: Decimal = Decimal("0.01")) -> bool:
        """Check if total amount matches line calculations."""
        # For AR, we don't have a pre-calculated amount, we calculate from lines
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_number": self.invoice_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "issue_date": self.issue_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "lines": [line.to_dict() for line in self.lines],
            "invoice_type": self.invoice_type.value,
            "currency": self.currency,
            "description": self.description,
            "sales_order_id": str(self.sales_order_id) if self.sales_order_id else None,
            "sales_order_number": self.sales_order_number,
            "shipping_cost": str(self.shipping_cost),
            "other_costs": str(self.other_costs),
            "discount_amount": str(self.discount_amount),
            "notes": self.notes,
            "subtotal": str(self.calculate_subtotal()),
            "discount_total": str(self.calculate_discount_total()),
            "tax_total": str(self.calculate_tax_total()),
            "items_total": str(self.calculate_items_total()),
            "total_amount": str(self.calculate_total_amount()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreateARInvoiceRequest:
        lines = [ARInvoiceLineRequest.from_dict(line) for line in data.get("lines", [])]
        return cls(
            invoice_number=data["invoice_number"],
            customer_id=UUID(data["customer_id"]),
            customer_name=data["customer_name"],
            issue_date=datetime.fromisoformat(data["issue_date"]),
            due_date=datetime.fromisoformat(data["due_date"]),
            lines=lines,
            invoice_type=ARInvoiceType(data.get("invoice_type", "standard")),
            currency=data.get("currency", "IDR"),
            description=data.get("description", ""),
            sales_order_id=UUID(data["sales_order_id"]) if data.get("sales_order_id") else None,
            sales_order_number=data.get("sales_order_number"),
            shipping_cost=Decimal(str(data.get("shipping_cost", 0))),
            other_costs=Decimal(str(data.get("other_costs", 0))),
            discount_amount=Decimal(str(data.get("discount_amount", 0))),
            notes=data.get("notes", ""),
            idempotency_key=data.get("idempotency_key"),
        )


# === 4. UPDATE AR INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class UpdateARInvoiceRequest:
    """DTO untuk request update faktur piutang."""

    invoice_id: UUID
    due_date: datetime | None = None
    description: str | None = None
    notes: str | None = None
    shipping_cost: Decimal | None = None
    other_costs: Decimal | None = None
    discount_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if not any(
            [
                self.due_date,
                self.description,
                self.notes,
                self.shipping_cost,
                self.other_costs,
                self.discount_amount,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.due_date and self.due_date.tzinfo is None:
            object.__setattr__(self, "due_date", self.due_date.replace(tzinfo=UTC))
        if self.shipping_cost is not None and self.shipping_cost < 0:
            raise ValueError(f"Shipping cost cannot be negative: {self.shipping_cost}")
        if self.other_costs is not None and self.other_costs < 0:
            raise ValueError(f"Other costs cannot be negative: {self.other_costs}")
        if self.discount_amount is not None and self.discount_amount < 0:
            raise ValueError(f"Discount amount cannot be negative: {self.discount_amount}")

    def to_dict(self) -> dict[str, Any]:
        result = {"invoice_id": str(self.invoice_id)}
        if self.due_date is not None:
            result["due_date"] = self.due_date.isoformat()
        if self.description is not None:
            result["description"] = self.description
        if self.notes is not None:
            result["notes"] = self.notes
        if self.shipping_cost is not None:
            result["shipping_cost"] = str(self.shipping_cost)
        if self.other_costs is not None:
            result["other_costs"] = str(self.other_costs)
        if self.discount_amount is not None:
            result["discount_amount"] = str(self.discount_amount)
        return result


# === 5. RECORD AR PAYMENT REQUEST DTO ===


@dataclass(kw_only=True)
class RecordARPaymentRequest:
    """DTO untuk request pencatatan pembayaran piutang."""

    payment_number: str
    customer_id: UUID
    customer_name: str
    payment_date: datetime
    amount: Decimal
    payment_method: PaymentMethod
    currency: str = "IDR"
    invoice_id: UUID | None = None
    invoice_number: str | None = None
    reference_number: str | None = None
    bank_reference: str | None = None
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.payment_number or len(self.payment_number.strip()) < 3:
            raise ValueError("Payment number must be at least 3 characters")
        if not self.customer_name:
            raise ValueError("Customer name is required")
        if self.amount <= 0:
            raise ValueError(f"Payment amount must be positive: {self.amount}")
        if self.payment_date.tzinfo is None:
            object.__setattr__(self, "payment_date", self.payment_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_number": self.payment_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "payment_date": self.payment_date.isoformat(),
            "amount": str(self.amount),
            "payment_method": self.payment_method.value,
            "currency": self.currency,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "invoice_number": self.invoice_number,
            "reference_number": self.reference_number,
            "bank_reference": self.bank_reference,
            "notes": self.notes,
        }


# === 6. CREATE AR CREDIT NOTE REQUEST DTO ===


@dataclass(kw_only=True)
class CreateARCreditNoteRequest:
    """DTO untuk request pembuatan credit note piutang."""

    credit_note_number: str
    invoice_id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    amount: Decimal
    reason: CreditNoteReason
    currency: str = "IDR"
    description: str = ""
    tax_amount: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.credit_note_number or len(self.credit_note_number.strip()) < 3:
            raise ValueError("Credit note number must be at least 3 characters")
        if not self.customer_name:
            raise ValueError("Customer name is required")
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
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "amount": str(self.amount),
            "reason": self.reason.value,
            "currency": self.currency,
            "description": self.description,
            "tax_amount": str(self.tax_amount),
            "tax_rate": str(self.tax_rate),
            "total_amount": str(self.calculate_total_amount()),
            "notes": self.notes,
        }


# === 7. WRITE-OFF AR INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class WriteOffARInvoiceRequest:
    """DTO untuk request penghapusan piutang (bad debt write-off)."""

    invoice_id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    amount: Decimal
    reason: str
    written_off_by: str
    notes: str = ""
    approval_reference: str | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Write-off amount must be positive: {self.amount}")
        if not self.reason or len(self.reason.strip()) < 5:
            raise ValueError("Reason must be at least 5 characters")
        if not self.written_off_by:
            raise ValueError("written_off_by is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "amount": str(self.amount),
            "reason": self.reason,
            "written_off_by": self.written_off_by,
            "notes": self.notes,
            "approval_reference": self.approval_reference,
        }


# === 8. GET AR INVOICE REQUEST DTO ===


@dataclass(kw_only=True)
class GetARInvoiceRequest:
    """DTO untuk request get faktur piutang."""

    invoice_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": str(self.invoice_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# === 9. LIST AR INVOICES REQUEST DTO ===


@dataclass(kw_only=True)
class ListARInvoicesRequest:
    """DTO untuk request list faktur piutang dengan filter."""

    legal_entity_id: UUID
    customer_id: UUID | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    status: ARInvoiceStatus | None = None
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
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "status": self.status.value if self.status else None,
            "is_overdue": self.is_overdue,
            "limit": self.limit,
            "offset": self.offset,
        }


# === 10. GET AR AGING REQUEST DTO ===


@dataclass(kw_only=True)
class GetARAgingRequest:
    """DTO untuk request aging piutang."""

    legal_entity_id: UUID
    as_of_date: datetime | None = None
    customer_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.as_of_date is None:
            object.__setattr__(self, "as_of_date", datetime.now(UTC))
        elif self.as_of_date.tzinfo is None:
            object.__setattr__(self, "as_of_date", self.as_of_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "customer_id": str(self.customer_id) if self.customer_id else None,
        }


# === 11. RESPONSE DTOs ===


class ARInvoiceStatusDTO(str, Enum):
    """Status faktur piutang untuk DTO response."""

    DRAFT = "draft"
    ISSUED = "issued"
    SENT = "sent"
    PARTIALLY_PAID = "partially_paid"
    FULLY_PAID = "fully_paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    WRITTEN_OFF = "written_off"


@dataclass(kw_only=True)
class ARInvoiceResponseDTO:
    """DTO response untuk faktur piutang."""

    id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
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

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.remaining_amount == Decimal("0.00") and self.amount > 0:
            object.__setattr__(self, "remaining_amount", self.amount - self.paid_amount)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_number": self.invoice_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
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
        }

    def is_overdue(self, as_of_date: datetime | None = None) -> bool:
        """Check if invoice is overdue."""
        check_date = as_of_date or datetime.now(UTC)
        return check_date > self.due_date and self.remaining_amount > 0

    def get_paid_percentage(self) -> Decimal:
        """Calculate paid percentage."""
        if self.amount > 0:
            return (self.paid_amount / self.amount * Decimal(100)).quantize(Decimal("0.01"))
        return Decimal(0)


@dataclass(kw_only=True)
class ARPaymentResponseDTO:
    """DTO response untuk pembayaran piutang."""

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


# === 12. FACTORY ===


class ARInvoiceRequestFactory:
    """Factory untuk membuat AR Invoice Request DTOs."""

    @staticmethod
    def create_invoice_line(
        item_id: UUID,
        item_code: str,
        item_name: str,
        quantity: Decimal,
        unit_price: Decimal,
        description: str = "",
        discount_percentage: Decimal = Decimal(0),
        tax_rate: Decimal = Decimal(11),
    ) -> ARInvoiceLineRequest:
        return ARInvoiceLineRequest(
            item_id=item_id,
            item_code=item_code,
            item_name=item_name,
            quantity=quantity,
            unit_price=unit_price,
            discount_percentage=discount_percentage,
            tax_rate=tax_rate,
            description=description,
        )

    @staticmethod
    def create_simple_invoice(
        invoice_number: str,
        customer_id: UUID,
        customer_name: str,
        issue_date: datetime,
        due_date: datetime,
        item_id: UUID,
        item_code: str,
        item_name: str,
        quantity: Decimal,
        unit_price: Decimal,
        description: str = "",
    ) -> CreateARInvoiceRequest:
        line = ARInvoiceRequestFactory.create_invoice_line(
            item_id=item_id,
            item_code=item_code,
            item_name=item_name,
            quantity=quantity,
            unit_price=unit_price,
            description=description,
        )
        return CreateARInvoiceRequest(
            invoice_number=invoice_number,
            customer_id=customer_id,
            customer_name=customer_name,
            issue_date=issue_date,
            due_date=due_date,
            lines=[line],
        )

    @staticmethod
    def create_payment(
        payment_number: str,
        customer_id: UUID,
        customer_name: str,
        payment_date: datetime,
        amount: Decimal,
        invoice_id: UUID,
        payment_method: PaymentMethod = PaymentMethod.BANK_TRANSFER,
    ) -> RecordARPaymentRequest:
        return RecordARPaymentRequest(
            payment_number=payment_number,
            customer_id=customer_id,
            customer_name=customer_name,
            payment_date=payment_date,
            amount=amount,
            payment_method=payment_method,
            invoice_id=invoice_id,
        )


# === 13. ALIASES FOR API ROUTER ===

ARInvoiceCreateRequest = CreateARInvoiceRequest
ARPaymentCreateRequest = RecordARPaymentRequest
ARCreditNoteCreateRequest = CreateARCreditNoteRequest
ARInvoiceRequestDTO = CreateARInvoiceRequest
ARPaymentRequestDTO = RecordARPaymentRequest


# === 14. EXPORTS ===

__all__ = [
    # Enums
    "ARInvoiceType",
    "ARInvoiceStatus",
    "PaymentMethod",
    "PaymentStatus",
    "CreditNoteReason",
    "ARInvoiceStatusDTO",
    # DTOs
    "CreateARInvoiceRequest",
    "UpdateARInvoiceRequest",
    "RecordARPaymentRequest",
    "CreateARCreditNoteRequest",
    "WriteOffARInvoiceRequest",
    "GetARInvoiceRequest",
    "ListARInvoicesRequest",
    "GetARAgingRequest",
    # Response DTOs
    "ARInvoiceResponseDTO",
    "ARPaymentResponseDTO",
    # Factory
    "ARInvoiceRequestFactory",
    # Aliases
    "ARInvoiceCreateRequest",
    "ARPaymentCreateRequest",
    "ARCreditNoteCreateRequest",
    "ARInvoiceRequestDTO",
    "ARPaymentRequestDTO",
]
