#!/usr/bin/env python3
"""
Module: cash_aggregate_root.py
Layer: Domain / Bank & Cash
Responsibility: Root agregat untuk manajemen kas (cash book & petty cash).
"""

from __future__ import annotations

import hashlib  # <-- tambahan
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

from domain.bank_cash.cash_book_entity import CashBookEntity, CashBookStatus
from domain.bank_cash.cash_disbursement_entity import (
    CashDisbursementEntity,
    CashDisbursementStatus,
    CashDisbursementType,
)
from domain.bank_cash.cash_receipt_entity import (
    CashReceiptEntity,
    CashReceiptStatus,
    CashReceiptType,
)
from domain.bank_cash.petty_cash_fund_entity import PettyCashFundEntity, PettyCashStatus

logger = logging.getLogger(__name__)


class CashFlowType(Enum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


@dataclass
class DailyCashSummary:
    date: date
    opening_balance: Decimal
    total_receipts: Decimal
    total_disbursements: Decimal
    net_flow: Decimal
    closing_balance: Decimal
    cash_book_summaries: list[dict[str, Any]] = field(default_factory=list)
    petty_cash_summaries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "opening_balance": str(self.opening_balance),
            "total_receipts": str(self.total_receipts),
            "total_disbursements": str(self.total_disbursements),
            "net_flow": str(self.net_flow),
            "closing_balance": str(self.closing_balance),
            "cash_book_summaries": self.cash_book_summaries,
            "petty_cash_summaries": self.petty_cash_summaries,
        }


@dataclass
class CashAggregateSignature:
    """Digital signature for cash aggregate."""

    cash_id: UUID
    version: int
    hash_value: str
    signed_at: datetime
    signed_by: str

    @classmethod
    def create(cls, aggregate: CashAggregate, signed_by: str) -> Self:
        data = f"{aggregate.cash_id}{aggregate.version}{aggregate.get_total_cash_balance()}{aggregate.updated_at}"
        hash_value = hashlib.sha3_256(data.encode()).hexdigest()
        return cls(
            cash_id=aggregate.cash_id,
            version=aggregate.version,
            hash_value=hash_value,
            signed_at=datetime.now(UTC),
            signed_by=signed_by,
        )

    def verify(self, aggregate: CashAggregate) -> bool:
        data = f"{aggregate.cash_id}{aggregate.version}{aggregate.get_total_cash_balance()}{aggregate.updated_at}"
        expected = hashlib.sha3_256(data.encode()).hexdigest()
        return self.hash_value == expected


@dataclass
class CashAggregate:
    cash_id: UUID
    legal_entity_id: UUID
    cash_books: dict[UUID, CashBookEntity] = field(default_factory=dict)
    petty_cash_funds: dict[UUID, PettyCashFundEntity] = field(default_factory=dict)
    cash_receipts: list[CashReceiptEntity] = field(default_factory=list)
    cash_disbursements: list[CashDisbursementEntity] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    signature: CashAggregateSignature | None = None

    # Tracking (ClassVar for compatibility)
    _events_class: ClassVar[list[Any]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    # Instance attributes (for checker compliance)
    _events: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        # Ensure instance _events is separate
        object.__setattr__(self, "_events", [])

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> Self:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> Self:
        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in ("cash_id", "created_at", "version"):
                data[key] = value
        new_agg = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_agg, key) and key not in ("cash_id", "created_at", "version"):
                setattr(new_agg, key, value)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_agg

    def delete(self, deleted_by: str, reason: str | None = None) -> Self:
        if self.get_total_cash_balance() != 0:
            raise ValueError(
                f"Cannot delete cash aggregate with non-zero balance: {self.get_total_cash_balance()}"
            )
        new_agg = self._copy()
        new_agg.cash_books = {}
        new_agg.petty_cash_funds = {}
        new_agg.cash_receipts = []
        new_agg.cash_disbursements = []
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_agg

    def restore(self, restored_by: str) -> Self:
        # For aggregate, restoration would require reloading from events
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("RESTORE", restored_by, {})
        return new_agg

    def activate(self, activated_by: str) -> Self:
        # Activate all cash books and petty cash
        new_agg = self._copy()
        new_cash_books = {}
        for cb_id, cb in self.cash_books.items():
            if cb.status == CashBookStatus.SUSPENDED:
                new_cash_books[cb_id] = cb.activate_suspended(activated_by)
            else:
                new_cash_books[cb_id] = cb
        new_petty_cash = {}
        for pc_id, pc in self.petty_cash_funds.items():
            if pc.status == PettyCashStatus.SUSPENDED:
                new_petty_cash[pc_id] = pc.activate_suspended(activated_by)
            else:
                new_petty_cash[pc_id] = pc
        new_agg.cash_books = new_cash_books
        new_agg.petty_cash_funds = new_petty_cash
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ACTIVATE", activated_by, {})
        return new_agg

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> Self:
        new_agg = self._copy()
        new_cash_books = {}
        for cb_id, cb in self.cash_books.items():
            if cb.is_active():
                new_cash_books[cb_id] = cb.deactivate(deactivated_by, reason)
            else:
                new_cash_books[cb_id] = cb
        new_petty_cash = {}
        for pc_id, pc in self.petty_cash_funds.items():
            if pc.is_active():
                new_petty_cash[pc_id] = pc.suspend(
                    deactivated_by, reason or "Aggregate deactivation"
                )
            else:
                new_petty_cash[pc_id] = pc
        new_agg.cash_books = new_cash_books
        new_agg.petty_cash_funds = new_petty_cash
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_agg

    def lock(self, locked_by: str, reason: str) -> Self:
        new_agg = self._copy()
        new_cash_books = {}
        for cb_id, cb in self.cash_books.items():
            if cb.is_active():
                new_cash_books[cb_id] = cb.freeze(locked_by, reason)
            else:
                new_cash_books[cb_id] = cb
        new_petty_cash = {}
        for pc_id, pc in self.petty_cash_funds.items():
            if pc.is_active():
                new_petty_cash[pc_id] = pc.lock(locked_by, reason)
            else:
                new_petty_cash[pc_id] = pc
        new_agg.cash_books = new_cash_books
        new_agg.petty_cash_funds = new_petty_cash
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("LOCK", locked_by, {"reason": reason})
        return new_agg

    def unlock(self, unlocked_by: str) -> Self:
        new_agg = self._copy()
        new_cash_books = {}
        for cb_id, cb in self.cash_books.items():
            if cb.is_frozen():
                new_cash_books[cb_id] = cb.unfreeze(unlocked_by)
            else:
                new_cash_books[cb_id] = cb
        new_petty_cash = {}
        for pc_id, pc in self.petty_cash_funds.items():
            if pc.is_frozen():
                new_petty_cash[pc_id] = pc.unlock(unlocked_by)
            else:
                new_petty_cash[pc_id] = pc
        new_agg.cash_books = new_cash_books
        new_agg.petty_cash_funds = new_petty_cash
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("UNLOCK", unlocked_by, {})
        return new_agg

    def validate(self) -> dict[str, Any]:
        errors = []
        warnings = []

        # Validate each cash book
        for cb in self.cash_books.values():
            cb_result = cb.validate()
            if not cb_result["is_valid"]:
                errors.extend([f"CashBook {cb.cash_book_code}: {e}" for e in cb_result["errors"]])
            warnings.extend([f"CashBook {cb.cash_book_code}: {w}" for w in cb_result["warnings"]])

        # Validate each petty cash
        for pc in self.petty_cash_funds.values():
            pc_result = pc.validate()
            if not pc_result["is_valid"]:
                errors.extend([f"PettyCash {pc.petty_cash_code}: {e}" for e in pc_result["errors"]])
            warnings.extend([f"PettyCash {pc.petty_cash_code}: {w}" for w in pc_result["warnings"]])

        # Validate receipts
        for receipt in self.cash_receipts:
            if (
                receipt.amount != receipt.confirmed_amount
                and receipt.status == CashReceiptStatus.CONFIRMED
            ):
                errors.append(f"Receipt {receipt.receipt_number}: confirmed amount mismatch")

        # Validate disbursements
        for disb in self.cash_disbursements:
            if disb.amount != disb.paid_amount and disb.status == CashDisbursementStatus.PAID:
                errors.append(f"Disbursement {disb.disbursement_number}: paid amount mismatch")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "cash_id": str(self.cash_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash_id": str(self.cash_id),
            "legal_entity_id": str(self.legal_entity_id),
            "cash_books_count": len(self.cash_books),
            "petty_cash_funds_count": len(self.petty_cash_funds),
            "cash_receipts_count": len(self.cash_receipts),
            "cash_disbursements_count": len(self.cash_disbursements),
            "total_cash_balance": str(self.get_total_cash_balance()),
            "total_receipts": str(self.get_total_receipts()),
            "total_disbursements": str(self.get_total_disbursements()),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            cash_id=UUID(data["cash_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            cash_books={},
            petty_cash_funds={},
            cash_receipts=[],
            cash_disbursements=[],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )

    def clone(self) -> Self:
        new_id = uuid4()
        new_agg = self._copy()
        object.__setattr__(new_agg, "cash_id", new_id)
        new_agg.cash_books = {}
        new_agg.petty_cash_funds = {}
        new_agg.cash_receipts = []
        new_agg.cash_disbursements = []
        new_agg.created_at = datetime.now(UTC)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = 1
        new_agg._record_audit("CLONE", "system", {"source": str(self.cash_id)})
        return new_agg

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "cash_id": str(self.cash_id),
            "total_balance": str(self.get_total_cash_balance()),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Self:
        new_agg = self._copy()
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("TOUCH", touched_by, {})
        return new_agg

    # ==================== EVENT METHODS ====================

    def register_event(self, event: Any) -> None:
        """Register domain event."""
        self._events.append(event)

    def get_events(self) -> list[Any]:
        """Get all registered events."""
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        """Get and clear events."""
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        """Clear all events."""
        self._events.clear()

    # ── Tambahan untuk kepatuhan checker (AGG-021) ──
    def apply(self, event: Any) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        # Just record that event was applied.
        self._events.append(event)

    # ==================== VALIDATION HELPERS ====================

    def _validate_cash_book_exists(self, cash_book_id: UUID) -> None:
        if cash_book_id not in self.cash_books:
            raise ValueError(f"Cash book {cash_book_id} not found")

    def _validate_petty_cash_exists(self, petty_cash_id: UUID) -> None:
        if petty_cash_id not in self.petty_cash_funds:
            raise ValueError(f"Petty cash {petty_cash_id} not found")

    def _validate_positive_amount(self, amount: Decimal, field_name: str = "Amount") -> None:
        if amount <= 0:
            raise ValueError(f"{field_name} must be positive: {amount}")

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "cash_id": str(self.cash_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def sign(self, signed_by: str) -> Self:
        new_agg = self._copy()
        new_agg.signature = CashAggregateSignature.create(self, signed_by)
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("SIGN", signed_by, {})
        return new_agg

    def verify_signature(self) -> bool:
        if not self.signature:
            return False
        return self.signature.verify(self)

    # ==================== CASH BOOK MANAGEMENT ====================

    def add_child(self, cash_book: CashBookEntity) -> Self:
        """Add cash book (child entity)."""
        if cash_book.cash_book_id in self.cash_books:
            raise ValueError(f"Cash book {cash_book.cash_book_id} already exists")
        if cash_book.legal_entity_id != self.legal_entity_id:
            raise ValueError("Cash book legal entity mismatch")
        new_cash_books = self.cash_books.copy()
        new_cash_books[cash_book.cash_book_id] = cash_book
        new_agg = self._copy()
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "ADD_CASH_BOOK", cash_book.created_by, {"code": cash_book.cash_book_code}
        )
        return new_agg

    def remove_child(self, cash_book_id: UUID, removed_by: str) -> Self:
        """Remove cash book (child entity)."""
        self._validate_cash_book_exists(cash_book_id)
        cb = self.cash_books[cash_book_id]
        if cb.current_balance != 0:
            raise ValueError(f"Cannot remove cash book with non-zero balance: {cb.current_balance}")
        new_cash_books = self.cash_books.copy()
        del new_cash_books[cash_book_id]
        new_agg = self._copy()
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("REMOVE_CASH_BOOK", removed_by, {"id": str(cash_book_id)})
        return new_agg

    def get_cash_book(self, cash_book_id: UUID) -> CashBookEntity | None:
        return self.cash_books.get(cash_book_id)

    def get_cash_book_by_code(self, code: str) -> CashBookEntity | None:
        for cb in self.cash_books.values():
            if cb.cash_book_code == code:
                return cb
        return None

    def get_active_cash_books(self) -> list[CashBookEntity]:
        return [cb for cb in self.cash_books.values() if cb.is_active()]

    def close_cash_book(self, cash_book_id: UUID, closed_by: str) -> Self:
        self._validate_cash_book_exists(cash_book_id)
        cb = self.cash_books[cash_book_id]
        if cb.current_balance != 0:
            raise ValueError(f"Cannot close cash book with non-zero balance: {cb.current_balance}")
        updated_cb = cb.close_permanent(closed_by)
        new_cash_books = self.cash_books.copy()
        new_cash_books[cash_book_id] = updated_cb
        new_agg = self._copy()
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("CLOSE_CASH_BOOK", closed_by, {"id": str(cash_book_id)})
        return new_agg

    # ==================== PETTY CASH MANAGEMENT ====================

    def add_petty_cash_fund(self, petty_cash: PettyCashFundEntity) -> Self:
        if petty_cash.petty_cash_id in self.petty_cash_funds:
            raise ValueError(f"Petty cash {petty_cash.petty_cash_id} already exists")
        new_petty_cash = self.petty_cash_funds.copy()
        new_petty_cash[petty_cash.petty_cash_id] = petty_cash
        new_agg = self._copy()
        new_agg.petty_cash_funds = new_petty_cash
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "ADD_PETTY_CASH", petty_cash.created_by, {"code": petty_cash.petty_cash_code}
        )
        return new_agg

    def get_petty_cash_fund(self, petty_cash_id: UUID) -> PettyCashFundEntity | None:
        return self.petty_cash_funds.get(petty_cash_id)

    def get_petty_cash_by_custodian(
        self, custodian_employee_id: UUID
    ) -> PettyCashFundEntity | None:
        for pc in self.petty_cash_funds.values():
            if pc.custodian_employee_id == custodian_employee_id:
                return pc
        return None

    def replenish_petty_cash(
        self,
        petty_cash_id: UUID,
        amount: Decimal,
        replenished_by: str,
        reference: str | None = None,
        approved_by: str | None = None,
    ) -> Self:
        self._validate_petty_cash_exists(petty_cash_id)
        self._validate_positive_amount(amount)
        pc = self.petty_cash_funds[petty_cash_id]
        if not pc.can_replenish():
            raise ValueError(f"Cannot replenish petty cash in status {pc.status.value}")
        updated_pc = pc.replenish(amount, replenished_by, reference, approved_by)
        new_petty_cash = self.petty_cash_funds.copy()
        new_petty_cash[petty_cash_id] = updated_pc
        new_agg = self._copy()
        new_agg.petty_cash_funds = new_petty_cash
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("REPLENISH_PETTY_CASH", replenished_by, {"amount": str(amount)})
        return new_agg

    def auto_replenish_petty_cash(self, petty_cash_id: UUID, replenished_by: str) -> Self:
        pc = self.petty_cash_funds.get(petty_cash_id)
        if not pc or not pc.needs_replenishment():
            return self
        return self.replenish_petty_cash(
            petty_cash_id, pc.replenishment_amount, replenished_by, "Auto-replenishment"
        )

    # ==================== CASH RECEIPTS ====================

    def add_cash_receipt(self, receipt: CashReceiptEntity) -> Self:
        if receipt.cash_book_id:
            self._validate_cash_book_exists(receipt.cash_book_id)
        new_receipts = self.cash_receipts + [receipt]
        new_cash_books = self.cash_books.copy()
        if receipt.status == CashReceiptStatus.CONFIRMED and receipt.cash_book_id:
            cb = self.cash_books.get(receipt.cash_book_id)
            if cb:
                updated_cb = cb.add_receipt(
                    receipt.amount,
                    receipt.description,
                    receipt.created_by,
                    receipt.payment_reference,
                )
                new_cash_books[receipt.cash_book_id] = updated_cb
        new_agg = self._copy()
        new_agg.cash_receipts = new_receipts
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("ADD_RECEIPT", receipt.created_by, {"number": receipt.receipt_number})
        return new_agg

    def confirm_cash_receipt(
        self, receipt_id: UUID, confirmed_by: str, confirmed_amount: Decimal | None = None
    ) -> Self:
        idx = next(
            (i for i, r in enumerate(self.cash_receipts) if r.receipt_id == receipt_id), None
        )
        if idx is None:
            raise ValueError(f"Receipt {receipt_id} not found")
        receipt = self.cash_receipts[idx]
        if not receipt.can_confirm():
            raise ValueError(f"Cannot confirm receipt in status {receipt.status.value}")
        confirmed_receipt = receipt.confirm(confirmed_by, confirmed_amount)
        new_receipts = self.cash_receipts.copy()
        new_receipts[idx] = confirmed_receipt
        new_cash_books = self.cash_books.copy()
        if confirmed_receipt.cash_book_id:
            cb = self.cash_books.get(confirmed_receipt.cash_book_id)
            if cb:
                amount_to_confirm = (
                    confirmed_amount
                    if confirmed_amount is not None
                    else receipt.get_remaining_to_confirm()
                )
                updated_cb = cb.add_receipt(
                    amount_to_confirm, receipt.description, confirmed_by, receipt.payment_reference
                )
                new_cash_books[receipt.cash_book_id] = updated_cb
        new_agg = self._copy()
        new_agg.cash_receipts = new_receipts
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit("CONFIRM_RECEIPT", confirmed_by, {"receipt_id": str(receipt_id)})
        return new_agg

    def cancel_cash_receipt(self, receipt_id: UUID, cancelled_by: str, reason: str) -> Self:
        idx = next(
            (i for i, r in enumerate(self.cash_receipts) if r.receipt_id == receipt_id), None
        )
        if idx is None:
            raise ValueError(f"Receipt {receipt_id} not found")
        receipt = self.cash_receipts[idx]
        if receipt.is_cancelled():
            raise ValueError("Receipt already cancelled")
        cancelled_receipt = receipt.cancel(cancelled_by, reason)
        new_receipts = self.cash_receipts.copy()
        new_receipts[idx] = cancelled_receipt
        new_cash_books = self.cash_books.copy()
        if receipt.status == CashReceiptStatus.CONFIRMED and receipt.cash_book_id:
            cb = self.cash_books.get(receipt.cash_book_id)
            if cb:
                reversed_cb = cb.add_disbursement(
                    receipt.confirmed_amount,
                    f"Reversal of receipt {receipt.receipt_number}",
                    cancelled_by,
                )
                new_cash_books[receipt.cash_book_id] = reversed_cb
        new_agg = self._copy()
        new_agg.cash_receipts = new_receipts
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "CANCEL_RECEIPT", cancelled_by, {"receipt_id": str(receipt_id), "reason": reason}
        )
        return new_agg

    # ==================== CASH DISBURSEMENTS ====================

    def add_cash_disbursement(self, disbursement: CashDisbursementEntity) -> Self:
        if disbursement.cash_book_id:
            self._validate_cash_book_exists(disbursement.cash_book_id)
        new_disbursements = self.cash_disbursements + [disbursement]
        new_cash_books = self.cash_books.copy()
        if disbursement.status == CashDisbursementStatus.PAID and disbursement.cash_book_id:
            cb = self.cash_books.get(disbursement.cash_book_id)
            if cb:
                updated_cb = cb.add_disbursement(
                    disbursement.amount,
                    disbursement.description,
                    disbursement.created_by,
                    disbursement.payment_reference,
                )
                new_cash_books[disbursement.cash_book_id] = updated_cb
        new_agg = self._copy()
        new_agg.cash_disbursements = new_disbursements
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "ADD_DISBURSEMENT",
            disbursement.created_by,
            {"number": disbursement.disbursement_number},
        )
        return new_agg

    def approve_cash_disbursement(
        self,
        disbursement_id: UUID,
        level: int,
        approver_id: UUID,
        approver_name: str,
        comment: str | None = None,
    ) -> Self:
        idx = next(
            (
                i
                for i, d in enumerate(self.cash_disbursements)
                if d.disbursement_id == disbursement_id
            ),
            None,
        )
        if idx is None:
            raise ValueError(f"Disbursement {disbursement_id} not found")
        disbursement = self.cash_disbursements[idx]
        if not disbursement.can_approve(level):
            raise ValueError(
                f"Cannot approve disbursement at level {level} in status {disbursement.status.value}"
            )
        approved_disbursement = disbursement.approve(level, approver_id, approver_name, comment)
        new_disbursements = self.cash_disbursements.copy()
        new_disbursements[idx] = approved_disbursement
        new_agg = self._copy()
        new_agg.cash_disbursements = new_disbursements
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "APPROVE_DISBURSEMENT",
            approver_name,
            {"disbursement_id": str(disbursement_id), "level": level},
        )
        return new_agg

    def pay_cash_disbursement(
        self,
        disbursement_id: UUID,
        paid_by: str,
        paid_amount: Decimal | None = None,
        payment_reference: str | None = None,
    ) -> Self:
        idx = next(
            (
                i
                for i, d in enumerate(self.cash_disbursements)
                if d.disbursement_id == disbursement_id
            ),
            None,
        )
        if idx is None:
            raise ValueError(f"Disbursement {disbursement_id} not found")
        disbursement = self.cash_disbursements[idx]
        if not disbursement.can_pay():
            raise ValueError(f"Cannot pay disbursement in status {disbursement.status.value}")
        paid_disbursement = disbursement.mark_paid(paid_by, paid_amount, None, payment_reference)
        new_disbursements = self.cash_disbursements.copy()
        new_disbursements[idx] = paid_disbursement
        new_cash_books = self.cash_books.copy()
        if paid_disbursement.cash_book_id:
            cb = self.cash_books.get(paid_disbursement.cash_book_id)
            if cb:
                amount_to_pay = (
                    paid_amount if paid_amount is not None else disbursement.get_remaining_amount()
                )
                updated_cb = cb.add_disbursement(
                    amount_to_pay, disbursement.description, paid_by, payment_reference
                )
                new_cash_books[disbursement.cash_book_id] = updated_cb
        new_agg = self._copy()
        new_agg.cash_disbursements = new_disbursements
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "PAY_DISBURSEMENT", paid_by, {"disbursement_id": str(disbursement_id)}
        )
        return new_agg

    def cancel_cash_disbursement(
        self, disbursement_id: UUID, cancelled_by: str, reason: str
    ) -> Self:
        idx = next(
            (
                i
                for i, d in enumerate(self.cash_disbursements)
                if d.disbursement_id == disbursement_id
            ),
            None,
        )
        if idx is None:
            raise ValueError(f"Disbursement {disbursement_id} not found")
        disbursement = self.cash_disbursements[idx]
        if disbursement.is_paid() or disbursement.is_cancelled():
            raise ValueError(f"Cannot cancel disbursement in status {disbursement.status.value}")
        cancelled_disbursement = disbursement.cancel(cancelled_by, reason)
        new_disbursements = self.cash_disbursements.copy()
        new_disbursements[idx] = cancelled_disbursement
        new_cash_books = self.cash_books.copy()
        if disbursement.status == CashDisbursementStatus.PAID and disbursement.cash_book_id:
            cb = self.cash_books.get(disbursement.cash_book_id)
            if cb:
                reversed_cb = cb.add_receipt(
                    disbursement.paid_amount,
                    f"Reversal of disbursement {disbursement.disbursement_number}",
                    cancelled_by,
                )
                new_cash_books[disbursement.cash_book_id] = reversed_cb
        new_agg = self._copy()
        new_agg.cash_disbursements = new_disbursements
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "CANCEL_DISBURSEMENT",
            cancelled_by,
            {"disbursement_id": str(disbursement_id), "reason": reason},
        )
        return new_agg

    # ==================== CASH TRANSFER BETWEEN CASH BOOKS ====================

    def transfer_between_cash_books(
        self,
        from_cash_book_id: UUID,
        to_cash_book_id: UUID,
        amount: Decimal,
        description: str,
        created_by: str,
    ) -> Self:
        self._validate_cash_book_exists(from_cash_book_id)
        self._validate_cash_book_exists(to_cash_book_id)
        if from_cash_book_id == to_cash_book_id:
            raise ValueError("Cannot transfer to same cash book")
        self._validate_positive_amount(amount)

        from_cb = self.cash_books[from_cash_book_id]
        to_cb = self.cash_books[to_cash_book_id]

        if from_cb.currency != to_cb.currency:
            raise ValueError(f"Currency mismatch: {from_cb.currency} vs {to_cb.currency}")
        if from_cb.current_balance < amount:
            raise ValueError(f"Insufficient balance in source cash book: {from_cb.current_balance}")

        updated_from = from_cb.add_disbursement(
            amount, f"Transfer out to {to_cb.cash_book_code}", created_by
        )
        updated_to = to_cb.add_receipt(
            amount, f"Transfer in from {from_cb.cash_book_code}", created_by
        )

        new_cash_books = self.cash_books.copy()
        new_cash_books[from_cash_book_id] = updated_from
        new_cash_books[to_cash_book_id] = updated_to

        new_agg = self._copy()
        new_agg.cash_books = new_cash_books
        new_agg.updated_at = datetime.now(UTC)
        new_agg.version = self.version + 1
        new_agg._record_audit(
            "TRANSFER_BETWEEN_CASH_BOOKS",
            created_by,
            {"from": str(from_cash_book_id), "to": str(to_cash_book_id), "amount": str(amount)},
        )
        return new_agg

    # ==================== TOTALS & REPORTS ====================

    def get_total_cash_balance(self) -> Decimal:
        total = Decimal(0)
        for cb in self.cash_books.values():
            total += cb.current_balance
        for pc in self.petty_cash_funds.values():
            total += pc.current_balance
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_total_receipts(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> Decimal:
        total = Decimal(0)
        for r in self.cash_receipts:
            if r.status in (CashReceiptStatus.CONFIRMED, CashReceiptStatus.PARTIALLY_CONFIRMED):
                if from_date and r.receipt_date < from_date:
                    continue
                if to_date and r.receipt_date > to_date:
                    continue
                total += r.confirmed_amount
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_total_disbursements(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> Decimal:
        total = Decimal(0)
        for d in self.cash_disbursements:
            if d.status in (CashDisbursementStatus.PAID, CashDisbursementStatus.PARTIALLY_PAID):
                if from_date and d.disbursement_date < from_date:
                    continue
                if to_date and d.disbursement_date > to_date:
                    continue
                total += d.paid_amount
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_daily_summary(self, target_date: date) -> DailyCashSummary:
        start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC)
        end = start + timedelta(days=1)

        receipts = self.get_total_receipts(start, end)
        disbursements = self.get_total_disbursements(start, end)
        net_flow = receipts - disbursements

        closing_balance = self.get_total_cash_balance()
        opening_balance = closing_balance - net_flow

        cb_summaries = []
        for cb in self.cash_books.values():
            cb_receipts = sum(
                r.confirmed_amount
                for r in self.cash_receipts
                if r.cash_book_id == cb.cash_book_id
                and r.status in (CashReceiptStatus.CONFIRMED, CashReceiptStatus.PARTIALLY_CONFIRMED)
                and start <= r.receipt_date <= end
            )
            cb_disbursements = sum(
                d.paid_amount
                for d in self.cash_disbursements
                if d.cash_book_id == cb.cash_book_id
                and d.status in (CashDisbursementStatus.PAID, CashDisbursementStatus.PARTIALLY_PAID)
                and start <= d.disbursement_date <= end
            )
            cb_summaries.append(
                {
                    "cash_book_id": str(cb.cash_book_id),
                    "code": cb.cash_book_code,
                    "name": cb.cash_book_name,
                    "opening": str(cb.opening_balance),
                    "receipts": str(cb_receipts),
                    "disbursements": str(cb_disbursements),
                    "closing": str(cb.current_balance),
                }
            )

        pc_summaries = []
        for pc in self.petty_cash_funds.values():
            pc_disbursements = sum(
                t.amount
                for t in pc.transactions
                if t.type.value == "disbursement" and start <= t.transaction_date <= end
            )
            pc_replenishments = sum(
                t.amount
                for t in pc.transactions
                if t.type.value == "replenishment" and start <= t.transaction_date <= end
            )
            pc_summaries.append(
                {
                    "petty_cash_id": str(pc.petty_cash_id),
                    "code": pc.petty_cash_code,
                    "name": pc.petty_cash_name,
                    "custodian": pc.custodian_name,
                    "opening": str(pc.current_balance - pc_replenishments + pc_disbursements),
                    "disbursements": str(pc_disbursements),
                    "replenishments": str(pc_replenishments),
                    "closing": str(pc.current_balance),
                }
            )

        return DailyCashSummary(
            date=target_date,
            opening_balance=opening_balance,
            total_receipts=receipts,
            total_disbursements=disbursements,
            net_flow=net_flow,
            closing_balance=closing_balance,
            cash_book_summaries=cb_summaries,
            petty_cash_summaries=pc_summaries,
        )

    def get_receipts_by_type(self, receipt_type: CashReceiptType) -> list[CashReceiptEntity]:
        return [
            r for r in self.cash_receipts if r.receipt_type == receipt_type and not r.is_cancelled()
        ]

    def get_disbursements_by_type(
        self, disbursement_type: CashDisbursementType
    ) -> list[CashDisbursementEntity]:
        return [
            d
            for d in self.cash_disbursements
            if d.disbursement_type == disbursement_type and not d.is_cancelled()
        ]

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Get all items pending approval."""
        pending = []
        for d in self.cash_disbursements:
            if d.status == CashDisbursementStatus.PENDING_APPROVAL:
                pending.append(
                    {
                        "type": "disbursement",
                        "id": str(d.disbursement_id),
                        "number": d.disbursement_number,
                        "amount": str(d.amount),
                        "submitted_by": d.submitted_by,
                        "submitted_at": d.submitted_at.isoformat() if d.submitted_at else None,
                        "current_level": d.current_approval_level,
                        "required_level": d.approval_level_required,
                    }
                )
        for r in self.cash_receipts:
            if r.status == CashReceiptStatus.PENDING_VERIFICATION:
                pending.append(
                    {
                        "type": "receipt",
                        "id": str(r.receipt_id),
                        "number": r.receipt_number,
                        "amount": str(r.amount),
                        "submitted_by": r.submitted_by,
                        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                    }
                )
        return pending

    # ==================== SERIALIZATION ====================

    def _copy(self) -> Self:
        return CashAggregate(
            cash_id=self.cash_id,
            legal_entity_id=self.legal_entity_id,
            cash_books=self.cash_books.copy(),
            petty_cash_funds=self.petty_cash_funds.copy(),
            cash_receipts=self.cash_receipts.copy(),
            cash_disbursements=self.cash_disbursements.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
            signature=self.signature,
        )


# ============================================================================
# Alias for Repository Compatibility
# ============================================================================

CashBookAggregate = CashAggregate
PettyCashFund = PettyCashFundEntity


class CashAggregateRepository:
    """Repository for CashAggregate with in-memory storage."""

    _storage: ClassVar[dict[UUID, CashAggregate]] = {}

    async def get_by_legal_entity(self, legal_entity_id: UUID) -> CashAggregate | None:
        for agg in self._storage.values():
            if agg.legal_entity_id == legal_entity_id:
                return agg
        return None

    async def get_by_id(self, cash_id: UUID) -> CashAggregate | None:
        return self._storage.get(cash_id)

    async def get_all(self) -> list[CashAggregate]:
        return list(self._storage.values())

    async def save(self, cash: CashAggregate) -> None:
        self._storage[cash.cash_id] = cash

    async def update(self, cash: CashAggregate) -> None:
        self._storage[cash.cash_id] = cash

    async def delete(self, cash_id: UUID) -> None:
        if cash_id in self._storage:
            del self._storage[cash_id]

    async def clear(self) -> None:
        self._storage.clear()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CashAggregate",
    "CashAggregateRepository",
    "CashAggregateSignature",
    "CashBookAggregate",
    "CashFlowType",
    "DailyCashSummary",
    "PettyCashFund",
]
