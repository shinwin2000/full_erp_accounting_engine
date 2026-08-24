#!/usr/bin/env python3
"""
Module: invariants.py
Layer: Domain / Subledger AR
Responsibility: Aturan: Saldo tidak boleh negatif, dll.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.subledger_ar.credit_note_entity import CreditNoteEntity
from domain.subledger_ar.invoice_entity import InvoiceEntity, InvoiceStatus
from domain.subledger_ar.payment_entity import PaymentEntity

logger = logging.getLogger(__name__)


# === 1. INVARIANT VALIDATION RESULT ===
class InvariantResult:
    """Hasil validasi invariant dengan metode entity dasar."""

    def __init__(self, is_valid: bool = True, errors: list[str] | None = None):
        self.is_valid = is_valid
        self.errors = errors or []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False
        self._record_audit("ADD_ERROR", "system", {"error": error})

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def __bool__(self) -> bool:
        return self.is_valid

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.is_valid, bool):
            errors.append("is_valid must be boolean")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvariantResult:
        instance = cls(
            is_valid=data.get("is_valid", True),
            errors=data.get("errors", []),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> InvariantResult:
        new = InvariantResult(is_valid=self.is_valid, errors=self.errors.copy())
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InvariantResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )


# === 2. AR INVARIANTS ===
class ARInvariants:
    """Kumpulan invariant untuk AR subledger."""

    @staticmethod
    def validate_invoice_amount(invoice: InvoiceEntity) -> InvariantResult:
        result = InvariantResult(True)
        if invoice.amount <= 0:
            result.add_error(
                f"Invoice {invoice.invoice_number} amount must be positive: {invoice.amount}"
            )
        return result

    @staticmethod
    def validate_payment_amount(
        payment: PaymentEntity, invoice: InvoiceEntity | None = None
    ) -> InvariantResult:
        result = InvariantResult(True)
        if payment.amount <= 0:
            result.add_error(
                f"Payment {payment.payment_number} amount must be positive: {payment.amount}"
            )
        if invoice and payment.amount > invoice.outstanding_amount:
            result.add_error(
                f"Payment amount {payment.amount} exceeds invoice outstanding {invoice.outstanding_amount}"
            )
        return result

    @staticmethod
    def validate_credit_note_amount(
        credit_note: CreditNoteEntity, invoice: InvoiceEntity | None = None
    ) -> InvariantResult:
        result = InvariantResult(True)
        if credit_note.amount <= 0:
            result.add_error(
                f"Credit note {credit_note.credit_note_number} amount must be positive"
            )
        if invoice and credit_note.amount > invoice.outstanding_amount:
            result.add_error(
                f"Credit note amount {credit_note.amount} exceeds invoice outstanding {invoice.outstanding_amount}"
            )
        return result

    @staticmethod
    def validate_customer_credit_limit(
        customer_id: UUID,
        requested_amount: Decimal,
        current_outstanding: Decimal,
        credit_limit: Decimal,
    ) -> InvariantResult:
        result = InvariantResult(True)
        if credit_limit > 0:
            new_total = current_outstanding + requested_amount
            if new_total > credit_limit:
                result.add_error(
                    f"Customer {customer_id} credit limit exceeded: current {current_outstanding} + requested {requested_amount} = {new_total} > limit {credit_limit}"
                )
        return result

    @staticmethod
    def validate_invoice_cancellation(invoice: InvoiceEntity) -> InvariantResult:
        result = InvariantResult(True)
        if invoice.status in (InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.FULLY_PAID):
            result.add_error(
                f"Cannot cancel invoice {invoice.invoice_number} with status {invoice.status.value}"
            )
        return result

    @staticmethod
    def validate_payment_refund(payment: PaymentEntity) -> InvariantResult:
        result = InvariantResult(True)
        if payment.status.value in ("refunded", "failed"):
            result.add_error(f"Payment {payment.payment_number} already {payment.status.value}")
        return result

    @staticmethod
    def validate_duplicate_invoice_number(
        invoice_number: str, existing_numbers: set[str]
    ) -> InvariantResult:
        result = InvariantResult(True)
        if invoice_number in existing_numbers:
            result.add_error(f"Invoice number {invoice_number} already exists")
        return result

    @staticmethod
    def validate_negative_balance(balance: Decimal, account_name: str) -> InvariantResult:
        result = InvariantResult(True)
        if balance < 0:
            result.add_error(f"{account_name} balance cannot be negative: {balance}")
        return result

    @staticmethod
    def validate_payment_allocation(
        payment: PaymentEntity, invoice: InvoiceEntity, allocated_amount: Decimal
    ) -> InvariantResult:
        result = InvariantResult(True)
        if allocated_amount <= 0:
            result.add_error(f"Allocation amount must be positive: {allocated_amount}")
        remaining_payment = payment.amount - payment.allocated_amount
        if allocated_amount > remaining_payment:
            result.add_error(
                f"Allocation amount {allocated_amount} exceeds remaining payment {remaining_payment}"
            )
        if allocated_amount > invoice.outstanding_amount:
            result.add_error(
                f"Allocation amount {allocated_amount} exceeds invoice outstanding {invoice.outstanding_amount}"
            )
        return result


# === 3. AR INVARIANT ENFORCER ===
class ARInvariantEnforcer:
    """Enforcer untuk semua invariant AR subledger."""

    def __init__(self, invoice_number_checker: callable, customer_credit_checker: callable):
        self._invoice_number_checker = invoice_number_checker
        self._customer_credit_checker = customer_credit_checker
        self._invariants = ARInvariants()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    async def enforce_invoice_create(self, invoice: InvoiceEntity) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self._invariants.validate_invoice_amount(invoice))
        existing_numbers = await self._invoice_number_checker()
        result.merge(
            self._invariants.validate_duplicate_invoice_number(
                invoice.invoice_number, existing_numbers
            )
        )
        if invoice.customer_id:
            credit_result = await self._customer_credit_checker(invoice.customer_id, invoice.amount)
            if not credit_result.is_valid:
                result.merge(credit_result)
        self._record_audit(
            "ENFORCE_INVOICE_CREATE", "system", {"invoice_number": invoice.invoice_number}
        )
        return result

    async def enforce_payment_create(
        self, payment: PaymentEntity, invoice: InvoiceEntity | None = None
    ) -> InvariantResult:
        result = self._invariants.validate_payment_amount(payment, invoice)
        self._record_audit(
            "ENFORCE_PAYMENT_CREATE", "system", {"payment_number": payment.payment_number}
        )
        return result

    async def enforce_payment_allocation(
        self, payment: PaymentEntity, invoice: InvoiceEntity, allocated_amount: Decimal
    ) -> InvariantResult:
        result = self._invariants.validate_payment_allocation(payment, invoice, allocated_amount)
        self._record_audit(
            "ENFORCE_PAYMENT_ALLOCATION",
            "system",
            {"payment_number": payment.payment_number, "allocated_amount": str(allocated_amount)},
        )
        return result

    async def enforce_credit_note_create(
        self, credit_note: CreditNoteEntity, invoice: InvoiceEntity
    ) -> InvariantResult:
        result = self._invariants.validate_credit_note_amount(credit_note, invoice)
        self._record_audit(
            "ENFORCE_CREDIT_NOTE_CREATE",
            "system",
            {"credit_note_number": credit_note.credit_note_number},
        )
        return result

    async def enforce_invoice_cancellation(self, invoice: InvoiceEntity) -> InvariantResult:
        result = self._invariants.validate_invoice_cancellation(invoice)
        self._record_audit(
            "ENFORCE_INVOICE_CANCELLATION", "system", {"invoice_number": invoice.invoice_number}
        )
        return result

    async def enforce_payment_refund(self, payment: PaymentEntity) -> InvariantResult:
        result = self._invariants.validate_payment_refund(payment)
        self._record_audit(
            "ENFORCE_PAYMENT_REFUND", "system", {"payment_number": payment.payment_number}
        )
        return result

    def enforce_negative_balance(self, balance: Decimal, account_name: str) -> InvariantResult:
        result = self._invariants.validate_negative_balance(balance, account_name)
        self._record_audit(
            "ENFORCE_NEGATIVE_BALANCE",
            "system",
            {"account_name": account_name, "balance": str(balance)},
        )
        return result

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"version": self._version, "type": "ARInvariantEnforcer"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ARInvariantEnforcer:
        # Note: invoice_number_checker and customer_credit_checker cannot be restored from dict
        instance = cls(
            invoice_number_checker=lambda: set(),
            customer_credit_checker=lambda x, y: InvariantResult(True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ARInvariantEnforcer:
        new = ARInvariantEnforcer(
            invoice_number_checker=self._invoice_number_checker,
            customer_credit_checker=self._customer_credit_checker,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "type": "ARInvariantEnforcer",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ARInvariantEnforcer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def reset(self) -> None:
        self._version = 1
        self._audit_trail = []
        self._snapshots = []

    def get_statistics(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "audit_count": len(self._audit_trail),
            "snapshot_count": len(self._snapshots),
        }


# === 4. COMPATIBILITY CLASS FOR service_ar.py ===
class ARInvariantsValidator:
    """Validator sederhana untuk digunakan di service layer."""

    def __init__(self):
        self._invariants = ARInvariants()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def validate_invoice_amount(self, invoice: InvoiceEntity) -> InvariantResult:
        return self._invariants.validate_invoice_amount(invoice)

    def validate_payment_amount(
        self, payment: PaymentEntity, invoice: InvoiceEntity | None = None
    ) -> InvariantResult:
        return self._invariants.validate_payment_amount(payment, invoice)

    def validate_credit_note_amount(
        self, credit_note: CreditNoteEntity, invoice: InvoiceEntity | None = None
    ) -> InvariantResult:
        return self._invariants.validate_credit_note_amount(credit_note, invoice)

    def validate_customer_credit_limit(
        self,
        customer_id: UUID,
        requested_amount: Decimal,
        current_outstanding: Decimal,
        credit_limit: Decimal,
    ) -> InvariantResult:
        return self._invariants.validate_customer_credit_limit(
            customer_id, requested_amount, current_outstanding, credit_limit
        )

    def validate_invoice_cancellation(self, invoice: InvoiceEntity) -> InvariantResult:
        return self._invariants.validate_invoice_cancellation(invoice)

    def validate_payment_refund(self, payment: PaymentEntity) -> InvariantResult:
        return self._invariants.validate_payment_refund(payment)

    def validate_duplicate_invoice_number(
        self, invoice_number: str, existing_numbers: set[str]
    ) -> InvariantResult:
        return self._invariants.validate_duplicate_invoice_number(invoice_number, existing_numbers)

    def validate_negative_balance(self, balance: Decimal, account_name: str) -> InvariantResult:
        return self._invariants.validate_negative_balance(balance, account_name)

    def validate_payment_allocation(
        self, payment: PaymentEntity, invoice: InvoiceEntity, allocated_amount: Decimal
    ) -> InvariantResult:
        return self._invariants.validate_payment_allocation(payment, invoice, allocated_amount)

    def validate_all(
        self, invoice: InvoiceEntity, payment: PaymentEntity | None = None
    ) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self.validate_invoice_amount(invoice))
        result.merge(self.validate_invoice_cancellation(invoice))
        if payment:
            result.merge(self.validate_payment_amount(payment, invoice))
        return result

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"version": self._version, "type": "ARInvariantsValidator"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ARInvariantsValidator:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ARInvariantsValidator:
        new = ARInvariantsValidator()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "type": "ARInvariantsValidator",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ARInvariantsValidator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def reset(self) -> None:
        self._version = 1
        self._audit_trail = []
        self._snapshots = []

    def get_statistics(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "audit_count": len(self._audit_trail),
            "snapshot_count": len(self._snapshots),
        }


# === 5. EXPORTS ===
__all__ = [
    "ARInvariantEnforcer",
    "ARInvariants",
    "ARInvariantsValidator",
    "InvariantResult",
]
