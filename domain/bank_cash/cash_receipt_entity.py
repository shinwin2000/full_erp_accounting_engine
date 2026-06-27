#!/usr/bin/env python3
"""
Module: cash_receipt_entity.py
Layer: Domain / Bank & Cash
Responsibility: Entitas penerimaan kas (cash receipt) dengan workflow,
               validasi, integrasi ke invoice, dan audit trail.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class CashReceiptStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"

    @classmethod
    def can_transition(cls, from_status: CashReceiptStatus, to_status: CashReceiptStatus) -> bool:
        allowed = {
            cls.DRAFT: {cls.SUBMITTED, cls.CANCELLED},
            cls.SUBMITTED: {cls.PENDING_VERIFICATION, cls.REJECTED, cls.CANCELLED},
            cls.PENDING_VERIFICATION: {cls.VERIFIED, cls.REJECTED},
            cls.VERIFIED: {cls.CONFIRMED, cls.PARTIALLY_CONFIRMED},
            cls.CONFIRMED: {cls.CANCELLED},
            cls.PARTIALLY_CONFIRMED: {cls.CONFIRMED, cls.CANCELLED},
            cls.REJECTED: {cls.DRAFT},
            cls.CANCELLED: set(),
        }
        return to_status in allowed.get(from_status, set())


class CashReceiptType(Enum):
    CUSTOMER_PAYMENT = "customer_payment"
    LOAN_RECEIPT = "loan_receipt"
    CAPITAL_CONTRIBUTION = "capital_contribution"
    OTHER_INCOME = "other_income"
    REFUND = "refund"
    INTEREST = "interest"
    DIVIDEND = "dividend"
    TAX_REFUND = "tax_refund"
    INSURANCE_CLAIM = "insurance_claim"
    GRANT = "grant"
    DEPOSIT_RETURN = "deposit_return"


class PaymentMethod(Enum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    GIRO = "giro"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    E_WALLET = "e_wallet"
    QRIS = "qris"
    CRYPTO = "crypto"
    OTHER = "other"


# ============================================================================
# Value Objects
# ============================================================================


@dataclass
class ReceiptAllocation:
    """Alokasi penerimaan ke invoice tertentu."""

    allocation_id: UUID
    invoice_id: UUID
    invoice_number: str
    allocated_amount: Decimal
    remaining_invoice_amount: Decimal
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": str(self.allocation_id),
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "allocated_amount": str(self.allocated_amount),
            "remaining_invoice_amount": str(self.remaining_invoice_amount),
            "created_at": self.created_at.isoformat(),
        }

    def update_allocation(self, new_amount: Decimal, new_remaining: Decimal) -> ReceiptAllocation:
        return ReceiptAllocation(
            allocation_id=self.allocation_id,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            allocated_amount=new_amount,
            remaining_invoice_amount=new_remaining,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class ReceiptSignature:
    """Digital signature for receipt."""

    receipt_id: UUID
    version: int
    hash_value: str
    signed_at: datetime
    signed_by: str

    @classmethod
    def create(cls, receipt: CashReceiptEntity, signed_by: str) -> Self:
        data = f"{receipt.receipt_id}{receipt.version}{receipt.amount}{receipt.receipt_date}"
        hash_value = hashlib.sha3_256(data.encode()).hexdigest()
        return cls(
            receipt_id=receipt.receipt_id,
            version=receipt.version,
            hash_value=hash_value,
            signed_at=datetime.now(UTC),
            signed_by=signed_by,
        )

    def verify(self, receipt: CashReceiptEntity) -> bool:
        data = f"{receipt.receipt_id}{receipt.version}{receipt.amount}{receipt.receipt_date}"
        expected = hashlib.sha3_256(data.encode()).hexdigest()
        return self.hash_value == expected


# ============================================================================
# Cash Receipt Entity
# ============================================================================


@dataclass
class CashReceiptEntity:
    receipt_id: UUID
    receipt_number: str
    receipt_type: CashReceiptType
    receipt_date: datetime
    amount: Decimal
    currency: str
    status: CashReceiptStatus

    # Pihak yang membayar
    customer_id: UUID | None = None
    customer_name: str | None = None
    customer_npwp: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None

    # Referensi invoice
    invoice_id: UUID | None = None
    invoice_number: str | None = None
    sales_order_id: UUID | None = None
    sales_order_number: str | None = None

    # Akun kas
    cash_book_id: UUID | None = None
    bank_account_id: UUID | None = None
    petty_cash_id: UUID | None = None

    # Pembayaran
    payment_method: PaymentMethod = PaymentMethod.CASH
    payment_reference: str | None = None
    cheque_number: str | None = None
    giro_number: str | None = None
    card_last_four: str | None = None
    e_wallet_transaction_id: str | None = None
    qris_transaction_id: str | None = None

    # Alokasi
    allocations: list[ReceiptAllocation] = field(default_factory=list)
    confirmed_amount: Decimal = Decimal(0)
    confirmed_date: datetime | None = None

    # Approval/Verification
    requires_verification: bool = False
    verified_by: str | None = None
    verified_at: datetime | None = None
    verification_notes: str | None = None
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None

    # Dokumentasi
    attachment_urls: list[str] = field(default_factory=list)
    description: str = ""
    notes: str | None = None
    received_by: str = ""
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    deleted_at: datetime | None = None
    signature: ReceiptSignature | None = None

    # Tracking
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if not self.receipt_number or len(self.receipt_number.strip()) < 3:
            raise ValueError("Receipt number must be at least 3 characters")
        if self.amount <= 0:
            raise ValueError(f"Receipt amount must be positive: {self.amount}")
        self.amount = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if self.confirmed_amount < 0:
            raise ValueError(f"Confirmed amount cannot be negative: {self.confirmed_amount}")
        self.confirmed_amount = self.confirmed_amount.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        if self.receipt_date > datetime.now(UTC):
            raise ValueError("Receipt date cannot be in the future")
        if self.confirmed_amount > self.amount:
            raise ValueError(
                f"Confirmed amount {self.confirmed_amount} exceeds total amount {self.amount}"
            )
        if not CashReceiptStatus.can_transition(self.status, self.status):
            if self.status not in CashReceiptStatus:
                raise ValueError(f"Invalid status: {self.status}")

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "receipt_id": str(self.receipt_id),
            "receipt_number": self.receipt_number,
            "details": details,
        }
        self._audit_trail.append(entry)

    def _calculate_signature(self) -> ReceiptSignature:
        return ReceiptSignature.create(self, self.created_by)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> Self:
        self._record_audit("CREATE", created_by, {"amount": str(self.amount)})
        return self

    def update(self, updated_by: str, **kwargs) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot update receipt in status {self.status.value}")

        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in (
                "receipt_id",
                "created_at",
                "created_by",
                "version",
            ):
                data[key] = value

        new_receipt = self.from_dict(data)
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_receipt

    def delete(self, deleted_by: str, reason: str | None = None) -> Self:
        if self.status in (CashReceiptStatus.CONFIRMED, CashReceiptStatus.PARTIALLY_CONFIRMED):
            raise ValueError(f"Cannot delete confirmed receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.CANCELLED
        new_receipt.cancelled_by = deleted_by
        new_receipt.cancelled_at = datetime.now(UTC)
        new_receipt.cancellation_reason = reason
        new_receipt.deleted_at = datetime.now(UTC)
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_receipt

    def restore(self, restored_by: str) -> Self:
        if self.status != CashReceiptStatus.CANCELLED:
            raise ValueError(f"Cannot restore receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.DRAFT
        new_receipt.cancelled_by = None
        new_receipt.cancelled_at = None
        new_receipt.cancellation_reason = None
        new_receipt.deleted_at = None
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("RESTORE", restored_by, {})
        return new_receipt

    def activate(self, activated_by: str) -> Self:
        if self.status != CashReceiptStatus.DRAFT:
            raise ValueError(f"Cannot activate receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.SUBMITTED
        new_receipt.submitted_by = activated_by
        new_receipt.submitted_at = datetime.now(UTC)
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("ACTIVATE", activated_by, {})
        return new_receipt

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> Self:
        if self.status != CashReceiptStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.DRAFT
        new_receipt.submitted_by = None
        new_receipt.submitted_at = None
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_receipt

    def lock(self, locked_by: str, reason: str) -> Self:
        new_receipt = self._copy()
        new_receipt.requires_verification = True
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("LOCK", locked_by, {"reason": reason})
        return new_receipt

    def unlock(self, unlocked_by: str) -> Self:
        new_receipt = self._copy()
        new_receipt.requires_verification = False
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("UNLOCK", unlocked_by, {})
        return new_receipt

    def validate(self) -> dict[str, Any]:
        errors = []
        warnings = []

        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))

        total_allocated = sum(a.allocated_amount for a in self.allocations)
        if total_allocated > self.amount:
            errors.append(f"Total allocated {total_allocated} exceeds receipt amount {self.amount}")

        if (
            self.status == CashReceiptStatus.SUBMITTED
            and (datetime.now(UTC) - self.submitted_at).days > 7
        ):
            warnings.append("Receipt has been pending verification for over 7 days")

        if (
            self.status == CashReceiptStatus.PARTIALLY_CONFIRMED
            and self.get_remaining_to_confirm() > 0
        ):
            warnings.append(
                f"Receipt has remaining amount to confirm: {self.get_remaining_to_confirm()}"
            )

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "receipt_id": str(self.receipt_id),
            "receipt_number": self.receipt_number,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": str(self.receipt_id),
            "receipt_number": self.receipt_number,
            "receipt_type": self.receipt_type.value,
            "receipt_date": self.receipt_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status.value,
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "customer_name": self.customer_name,
            "customer_npwp": self.customer_npwp,
            "customer_email": self.customer_email,
            "customer_phone": self.customer_phone,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "invoice_number": self.invoice_number,
            "sales_order_id": str(self.sales_order_id) if self.sales_order_id else None,
            "sales_order_number": self.sales_order_number,
            "cash_book_id": str(self.cash_book_id) if self.cash_book_id else None,
            "bank_account_id": str(self.bank_account_id) if self.bank_account_id else None,
            "petty_cash_id": str(self.petty_cash_id) if self.petty_cash_id else None,
            "payment_method": self.payment_method.value,
            "payment_reference": self.payment_reference,
            "cheque_number": self.cheque_number,
            "giro_number": self.giro_number,
            "card_last_four": self.card_last_four,
            "e_wallet_transaction_id": self.e_wallet_transaction_id,
            "qris_transaction_id": self.qris_transaction_id,
            "confirmed_amount": str(self.confirmed_amount),
            "confirmed_date": self.confirmed_date.isoformat() if self.confirmed_date else None,
            "remaining_to_confirm": str(self.get_remaining_to_confirm()),
            "requires_verification": self.requires_verification,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verification_notes": self.verification_notes,
            "submitted_by": self.submitted_by,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "rejected_by": self.rejected_by,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejection_reason": self.rejection_reason,
            "allocation_summary": self.get_allocation_summary(),
            "payment_summary": self.get_payment_summary(),
            "attachments": self.attachment_urls,
            "description": self.description,
            "notes": self.notes,
            "received_by": self.received_by,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancellation_reason": self.cancellation_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            receipt_id=UUID(data["receipt_id"]),
            receipt_number=data["receipt_number"],
            receipt_type=CashReceiptType(data["receipt_type"]),
            receipt_date=datetime.fromisoformat(data["receipt_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            status=CashReceiptStatus(data["status"]),
            customer_id=UUID(data["customer_id"]) if data.get("customer_id") else None,
            customer_name=data.get("customer_name"),
            customer_npwp=data.get("customer_npwp"),
            customer_email=data.get("customer_email"),
            customer_phone=data.get("customer_phone"),
            invoice_id=UUID(data["invoice_id"]) if data.get("invoice_id") else None,
            invoice_number=data.get("invoice_number"),
            sales_order_id=UUID(data["sales_order_id"]) if data.get("sales_order_id") else None,
            sales_order_number=data.get("sales_order_number"),
            cash_book_id=UUID(data["cash_book_id"]) if data.get("cash_book_id") else None,
            bank_account_id=UUID(data["bank_account_id"]) if data.get("bank_account_id") else None,
            petty_cash_id=UUID(data["petty_cash_id"]) if data.get("petty_cash_id") else None,
            payment_method=PaymentMethod(data["payment_method"]),
            payment_reference=data.get("payment_reference"),
            cheque_number=data.get("cheque_number"),
            giro_number=data.get("giro_number"),
            card_last_four=data.get("card_last_four"),
            e_wallet_transaction_id=data.get("e_wallet_transaction_id"),
            qris_transaction_id=data.get("qris_transaction_id"),
            confirmed_amount=Decimal(data.get("confirmed_amount", "0")),
            confirmed_date=datetime.fromisoformat(data["confirmed_date"])
            if data.get("confirmed_date")
            else None,
            requires_verification=data.get("requires_verification", False),
            verified_by=data.get("verified_by"),
            verified_at=datetime.fromisoformat(data["verified_at"])
            if data.get("verified_at")
            else None,
            verification_notes=data.get("verification_notes"),
            submitted_by=data.get("submitted_by"),
            submitted_at=datetime.fromisoformat(data["submitted_at"])
            if data.get("submitted_at")
            else None,
            rejected_by=data.get("rejected_by"),
            rejected_at=datetime.fromisoformat(data["rejected_at"])
            if data.get("rejected_at")
            else None,
            rejection_reason=data.get("rejection_reason"),
            attachments=data.get("attachment_urls", []),
            description=data.get("description", ""),
            notes=data.get("notes"),
            received_by=data.get("received_by", ""),
            confirmed_by=data.get("confirmed_by"),
            confirmed_at=datetime.fromisoformat(data["confirmed_at"])
            if data.get("confirmed_at")
            else None,
            cancelled_by=data.get("cancelled_by"),
            cancelled_at=datetime.fromisoformat(data["cancelled_at"])
            if data.get("cancelled_at")
            else None,
            cancellation_reason=data.get("cancellation_reason"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data["created_by"],
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
        )

    def clone(self) -> Self:
        new_id = uuid4()
        cloned = self._copy()
        object.__setattr__(cloned, "receipt_id", new_id)
        cloned.receipt_number = f"{self.receipt_number}_COPY_{uuid4().hex[:4]}"
        cloned.status = CashReceiptStatus.DRAFT
        cloned.confirmed_amount = Decimal(0)
        cloned.confirmed_date = None
        cloned.allocations = []
        cloned.version = 1
        cloned.created_at = datetime.now(UTC)
        cloned.updated_at = datetime.now(UTC)
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.receipt_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "receipt_id": str(self.receipt_id),
            "receipt_number": self.receipt_number,
            "amount": str(self.amount),
            "confirmed_amount": str(self.confirmed_amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Self:
        new_receipt = self._copy()
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("TOUCH", touched_by, {})
        return new_receipt

    # ==================== STATUS CHECKERS ====================

    def is_draft(self) -> bool:
        return self.status == CashReceiptStatus.DRAFT

    def is_submitted(self) -> bool:
        return self.status == CashReceiptStatus.SUBMITTED

    def is_confirmed(self) -> bool:
        return self.status == CashReceiptStatus.CONFIRMED

    def is_cancelled(self) -> bool:
        return self.status == CashReceiptStatus.CANCELLED

    def is_rejected(self) -> bool:
        return self.status == CashReceiptStatus.REJECTED

    def is_partially_confirmed(self) -> bool:
        return self.status == CashReceiptStatus.PARTIALLY_CONFIRMED

    def is_pending_verification(self) -> bool:
        return self.status == CashReceiptStatus.PENDING_VERIFICATION

    def is_verified(self) -> bool:
        return self.status == CashReceiptStatus.VERIFIED

    def can_edit(self) -> bool:
        return self.status in (CashReceiptStatus.DRAFT, CashReceiptStatus.REJECTED)

    def can_submit(self) -> bool:
        return self.status == CashReceiptStatus.DRAFT

    def can_verify(self) -> bool:
        return self.status == CashReceiptStatus.PENDING_VERIFICATION

    def can_confirm(self) -> bool:
        return (
            self.status in (CashReceiptStatus.VERIFIED, CashReceiptStatus.PARTIALLY_CONFIRMED)
            and self.confirmed_amount < self.amount
        )

    def can_cancel(self) -> bool:
        return self.status not in (CashReceiptStatus.CANCELLED, CashReceiptStatus.REJECTED)

    def can_reject(self) -> bool:
        return self.status in (CashReceiptStatus.SUBMITTED, CashReceiptStatus.PENDING_VERIFICATION)

    def is_fully_confirmed(self) -> bool:
        return self.confirmed_amount >= self.amount

    def get_remaining_to_confirm(self) -> Decimal:
        return (self.amount - self.confirmed_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    # ==================== WORKFLOW ACTIONS ====================

    def submit(self, submitted_by: str) -> Self:
        if not self.can_submit():
            raise ValueError(f"Cannot submit receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.SUBMITTED
        new_receipt.submitted_by = submitted_by
        new_receipt.submitted_at = datetime.now(UTC)
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("SUBMIT", submitted_by, {})
        return new_receipt

    def verify(self, verified_by: str, notes: str | None = None) -> Self:
        if not self.can_verify():
            raise ValueError(f"Cannot verify receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.VERIFIED
        new_receipt.verified_by = verified_by
        new_receipt.verified_at = datetime.now(UTC)
        new_receipt.verification_notes = notes
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("VERIFY", verified_by, {"notes": notes})
        return new_receipt

    def confirm(
        self,
        confirmed_by: str,
        confirmed_amount: Decimal | None = None,
        confirmed_date: datetime | None = None,
    ) -> Self:
        if not self.can_confirm():
            raise ValueError(f"Cannot confirm receipt in status {self.status.value}")

        amount_to_confirm = (
            confirmed_amount if confirmed_amount is not None else self.get_remaining_to_confirm()
        )
        if amount_to_confirm <= 0:
            raise ValueError("Confirm amount must be positive")
        if amount_to_confirm > self.get_remaining_to_confirm():
            raise ValueError(
                f"Confirm amount {amount_to_confirm} exceeds remaining {self.get_remaining_to_confirm()}"
            )

        amount_to_confirm = amount_to_confirm.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        new_confirmed = self.confirmed_amount + amount_to_confirm
        new_status = (
            CashReceiptStatus.CONFIRMED
            if new_confirmed >= self.amount
            else CashReceiptStatus.PARTIALLY_CONFIRMED
        )

        # Update allocations
        new_allocations = self.allocations.copy()
        remaining_to_allocate = amount_to_confirm
        for i, alloc in enumerate(new_allocations):
            if remaining_to_allocate <= 0:
                break
            if alloc.allocated_amount < alloc.remaining_invoice_amount:
                take = min(
                    remaining_to_allocate, alloc.remaining_invoice_amount - alloc.allocated_amount
                )
                new_allocations[i] = alloc.update_allocation(
                    alloc.allocated_amount + take, alloc.remaining_invoice_amount
                )
                remaining_to_allocate -= take

        new_receipt = self._copy()
        new_receipt.status = new_status
        new_receipt.confirmed_amount = new_confirmed
        new_receipt.confirmed_date = confirmed_date or datetime.now(UTC)
        new_receipt.confirmed_by = confirmed_by
        new_receipt.confirmed_at = datetime.now(UTC)
        new_receipt.allocations = new_allocations
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("CONFIRM", confirmed_by, {"amount": str(amount_to_confirm)})
        return new_receipt

    def reject(self, rejected_by: str, reason: str) -> Self:
        if not self.can_reject():
            raise ValueError(f"Cannot reject receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.REJECTED
        new_receipt.rejected_by = rejected_by
        new_receipt.rejected_at = datetime.now(UTC)
        new_receipt.rejection_reason = reason
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("REJECT", rejected_by, {"reason": reason})
        return new_receipt

    def cancel(self, cancelled_by: str, reason: str) -> Self:
        if not self.can_cancel():
            raise ValueError(f"Cannot cancel receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.status = CashReceiptStatus.CANCELLED
        new_receipt.cancelled_by = cancelled_by
        new_receipt.cancelled_at = datetime.now(UTC)
        new_receipt.cancellation_reason = reason
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_receipt

    # ==================== UPDATE METHODS ====================

    def update_description(self, new_description: str, updated_by: str) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot edit receipt in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.description = new_description
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("UPDATE_DESCRIPTION", updated_by, {})
        return new_receipt

    def update_amount(self, new_amount: Decimal, updated_by: str, reason: str) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot edit amount in status {self.status.value}")

        new_amount = new_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if new_amount <= 0:
            raise ValueError("New amount must be positive")
        if self.confirmed_amount > new_amount:
            raise ValueError(
                f"Cannot reduce amount below already confirmed {self.confirmed_amount}"
            )

        new_receipt = self._copy()
        new_receipt.amount = new_amount
        new_receipt.description = f"{self.description}\n[AMOUNT CHANGE] from {self.amount} to {new_amount}. Reason: {reason}"
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit(
            "UPDATE_AMOUNT", updated_by, {"new_amount": str(new_amount), "reason": reason}
        )
        return new_receipt

    def update_payment_method(self, new_method: PaymentMethod, updated_by: str) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot edit payment method in status {self.status.value}")

        new_receipt = self._copy()
        new_receipt.payment_method = new_method
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit(
            "UPDATE_PAYMENT_METHOD", updated_by, {"new_method": new_method.value}
        )
        return new_receipt

    def add_allocation(
        self,
        invoice_id: UUID,
        invoice_number: str,
        allocated_amount: Decimal,
        remaining_invoice: Decimal,
    ) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot add allocation in status {self.status.value}")

        allocated_amount = allocated_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        new_allocation = ReceiptAllocation(
            allocation_id=uuid4(),
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            allocated_amount=allocated_amount,
            remaining_invoice_amount=remaining_invoice,
        )

        new_allocations = self.allocations + [new_allocation]
        total_allocated = sum(a.allocated_amount for a in new_allocations)
        if total_allocated > self.amount:
            raise ValueError(
                f"Total allocated {total_allocated} exceeds receipt amount {self.amount}"
            )

        new_receipt = self._copy()
        new_receipt.allocations = new_allocations
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit(
            "ADD_ALLOCATION",
            self.created_by,
            {
                "invoice_id": str(invoice_id),
                "amount": str(allocated_amount),
            },
        )
        return new_receipt

    def remove_allocation(self, allocation_id: UUID, updated_by: str) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot remove allocation in status {self.status.value}")

        new_allocations = [a for a in self.allocations if a.allocation_id != allocation_id]
        if len(new_allocations) == len(self.allocations):
            raise ValueError(f"Allocation {allocation_id} not found")

        new_receipt = self._copy()
        new_receipt.allocations = new_allocations
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit(
            "REMOVE_ALLOCATION", updated_by, {"allocation_id": str(allocation_id)}
        )
        return new_receipt

    def attach_file(self, file_url: str, uploaded_by: str) -> Self:
        new_attachments = self.attachment_urls + [file_url]
        new_receipt = self._copy()
        new_receipt.attachment_urls = new_attachments
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("ATTACH_FILE", uploaded_by, {"file_url": file_url})
        return new_receipt

    def remove_attachment(self, file_url: str, removed_by: str) -> Self:
        new_attachments = [f for f in self.attachment_urls if f != file_url]
        new_receipt = self._copy()
        new_receipt.attachment_urls = new_attachments
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("REMOVE_ATTACHMENT", removed_by, {"file_url": file_url})
        return new_receipt

    # ==================== HELPER METHODS ====================

    def get_allocation_summary(self) -> dict[str, Any]:
        total_allocated = sum(a.allocated_amount for a in self.allocations)
        return {
            "total_allocated": str(total_allocated),
            "unallocated": str(self.amount - total_allocated),
            "allocations": [a.to_dict() for a in self.allocations],
            "allocation_percentage": float(total_allocated / self.amount * 100)
            if self.amount > 0
            else 0,
        }

    def get_payment_summary(self) -> dict[str, Any]:
        return {
            "total_amount": str(self.amount),
            "confirmed_amount": str(self.confirmed_amount),
            "remaining_to_confirm": str(self.get_remaining_to_confirm()),
            "confirmation_percentage": float(self.confirmed_amount / self.amount * 100)
            if self.amount > 0
            else 0,
            "confirmed_date": self.confirmed_date.isoformat() if self.confirmed_date else None,
            "payment_method": self.payment_method.value,
            "payment_reference": self.payment_reference,
        }

    def get_verification_status(self) -> dict[str, Any]:
        return {
            "requires_verification": self.requires_verification,
            "verified": self.is_verified(),
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verification_notes": self.verification_notes,
            "submitted_by": self.submitted_by,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
        }

    def sign(self, signed_by: str) -> Self:
        new_receipt = self._copy()
        new_receipt.signature = ReceiptSignature.create(self, signed_by)
        new_receipt.updated_at = datetime.now(UTC)
        new_receipt.version = self.version + 1
        new_receipt._record_audit("SIGN", signed_by, {})
        return new_receipt

    def verify_signature(self) -> bool:
        if not self.signature:
            return False
        return self.signature.verify(self)

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> Self:
        return CashReceiptEntity(
            receipt_id=self.receipt_id,
            receipt_number=self.receipt_number,
            receipt_type=self.receipt_type,
            receipt_date=self.receipt_date,
            amount=self.amount,
            currency=self.currency,
            status=self.status,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            customer_npwp=self.customer_npwp,
            customer_email=self.customer_email,
            customer_phone=self.customer_phone,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            sales_order_id=self.sales_order_id,
            sales_order_number=self.sales_order_number,
            cash_book_id=self.cash_book_id,
            bank_account_id=self.bank_account_id,
            petty_cash_id=self.petty_cash_id,
            payment_method=self.payment_method,
            payment_reference=self.payment_reference,
            cheque_number=self.cheque_number,
            giro_number=self.giro_number,
            card_last_four=self.card_last_four,
            e_wallet_transaction_id=self.e_wallet_transaction_id,
            qris_transaction_id=self.qris_transaction_id,
            allocations=self.allocations.copy(),
            confirmed_amount=self.confirmed_amount,
            confirmed_date=self.confirmed_date,
            requires_verification=self.requires_verification,
            verified_by=self.verified_by,
            verified_at=self.verified_at,
            verification_notes=self.verification_notes,
            submitted_by=self.submitted_by,
            submitted_at=self.submitted_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejection_reason=self.rejection_reason,
            attachment_urls=self.attachment_urls.copy(),
            description=self.description,
            notes=self.notes,
            received_by=self.received_by,
            confirmed_by=self.confirmed_by,
            confirmed_at=self.confirmed_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancellation_reason=self.cancellation_reason,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            deleted_at=self.deleted_at,
            signature=self.signature,
        )


# ============================================================================
# Alias for Service Layer
# ============================================================================

CashReceipt = CashReceiptEntity


# ============================================================================
# Repository Interface (Real Implementation)
# ============================================================================


class CashReceiptRepository:
    """Repository for CashReceipt with in-memory storage."""

    _storage: ClassVar[dict[UUID, dict[UUID, CashReceiptEntity]]] = {}
    _storage_by_number: ClassVar[dict[UUID, dict[str, CashReceiptEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, CashReceiptEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    def _get_number_storage(cls, legal_entity_id: UUID) -> dict[str, CashReceiptEntity]:
        if legal_entity_id not in cls._storage_by_number:
            cls._storage_by_number[legal_entity_id] = {}
        return cls._storage_by_number[legal_entity_id]

    async def get_by_id(self, receipt_id: UUID, legal_entity_id: UUID) -> CashReceiptEntity | None:
        storage = self._get_storage(legal_entity_id)
        return storage.get(receipt_id)

    async def get_by_number(
        self, receipt_number: str, legal_entity_id: UUID
    ) -> CashReceiptEntity | None:
        number_storage = self._get_number_storage(legal_entity_id)
        return number_storage.get(receipt_number)

    async def get_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[CashReceiptEntity]:
        storage = self._get_storage(legal_entity_id)
        result = [r for r in storage.values() if r.customer_id == customer_id]
        if from_date:
            result = [r for r in result if r.receipt_date >= from_date]
        if to_date:
            result = [r for r in result if r.receipt_date <= to_date]
        result.sort(key=lambda x: x.receipt_date, reverse=True)
        return result

    async def get_by_invoice(
        self, invoice_id: UUID, legal_entity_id: UUID
    ) -> list[CashReceiptEntity]:
        storage = self._get_storage(legal_entity_id)
        return [r for r in storage.values() if r.invoice_id == invoice_id]

    async def get_by_cash_book(
        self,
        cash_book_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[CashReceiptEntity]:
        storage = self._get_storage(legal_entity_id)
        result = [r for r in storage.values() if r.cash_book_id == cash_book_id]
        if from_date:
            result = [r for r in result if r.receipt_date >= from_date]
        if to_date:
            result = [r for r in result if r.receipt_date <= to_date]
        return result

    async def get_by_status(
        self, status: CashReceiptStatus, legal_entity_id: UUID
    ) -> list[CashReceiptEntity]:
        storage = self._get_storage(legal_entity_id)
        return [r for r in storage.values() if r.status == status]

    async def get_pending_verification(self, legal_entity_id: UUID) -> list[CashReceiptEntity]:
        storage = self._get_storage(legal_entity_id)
        return [r for r in storage.values() if r.status == CashReceiptStatus.PENDING_VERIFICATION]

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CashReceiptEntity]:
        storage = self._get_storage(legal_entity_id)
        result = [r for r in storage.values() if start_date <= r.receipt_date <= end_date]
        result.sort(key=lambda x: x.receipt_date)
        return result

    async def get_total_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> Decimal:
        receipts = await self.get_by_customer(customer_id, legal_entity_id, from_date, to_date)
        total = sum(
            r.confirmed_amount for r in receipts if r.is_confirmed() or r.is_partially_confirmed()
        )
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    async def count(self, legal_entity_id: UUID) -> int:
        storage = self._get_storage(legal_entity_id)
        return len(storage)

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CashReceiptEntity]:
        receipts = await self.get_all(legal_entity_id)
        receipts.sort(key=lambda x: x.receipt_date, reverse=True)
        return receipts[offset : offset + limit]

    async def get_all(self, legal_entity_id: UUID) -> list[CashReceiptEntity]:
        storage = self._get_storage(legal_entity_id)
        return list(storage.values())

    async def save(self, receipt: CashReceiptEntity, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        number_storage = self._get_number_storage(legal_entity_id)
        storage[receipt.receipt_id] = receipt
        number_storage[receipt.receipt_number] = receipt

    async def update(self, receipt: CashReceiptEntity, legal_entity_id: UUID) -> None:
        await self.save(receipt, legal_entity_id)

    async def delete(self, receipt_id: UUID, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        number_storage = self._get_number_storage(legal_entity_id)
        if receipt_id in storage:
            receipt = storage[receipt_id]
            if receipt.receipt_number in number_storage:
                del number_storage[receipt.receipt_number]
            del storage[receipt_id]

    async def clear(self, legal_entity_id: UUID) -> None:
        if legal_entity_id in self._storage:
            self._storage[legal_entity_id] = {}
        if legal_entity_id in self._storage_by_number:
            self._storage_by_number[legal_entity_id] = {}


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CashReceipt",
    "CashReceiptEntity",
    "CashReceiptRepository",
    "CashReceiptStatus",
    "CashReceiptType",
    "PaymentMethod",
    "ReceiptAllocation",
    "ReceiptSignature",
]
