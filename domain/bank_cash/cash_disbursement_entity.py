#!/usr/bin/env python3
"""
Module: cash_disbursement_entity.py
Layer: Domain / Bank & Cash
Responsibility: Entitas pengeluaran kas (cash disbursement) dengan workflow approval,
               pembayaran, pembatalan, integrasi ke cash book/petty cash,
               audit trail, validasi budget, approval matrix, dan notifikasi.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class CashDisbursementStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"
    CANCELLED = "cancelled"
    PARTIALLY_PAID = "partially_paid"
    ON_HOLD = "on_hold"
    READY_FOR_PAYMENT = "ready_for_payment"
    PROCESSING = "processing"
    FAILED = "failed"

    @classmethod
    def can_transition(
        cls, from_status: CashDisbursementStatus, to_status: CashDisbursementStatus
    ) -> bool:
        allowed = {
            cls.DRAFT: {cls.SUBMITTED, cls.CANCELLED},
            cls.SUBMITTED: {cls.PENDING_APPROVAL, cls.REJECTED, cls.CANCELLED},
            cls.PENDING_APPROVAL: {cls.APPROVED, cls.REJECTED, cls.ON_HOLD},
            cls.APPROVED: {cls.READY_FOR_PAYMENT, cls.PARTIALLY_PAID, cls.CANCELLED},
            cls.READY_FOR_PAYMENT: {cls.PROCESSING, cls.ON_HOLD},
            cls.PROCESSING: {cls.PAID, cls.FAILED},
            cls.PARTIALLY_PAID: {cls.PAID, cls.CANCELLED},
            cls.ON_HOLD: {cls.PENDING_APPROVAL, cls.CANCELLED},
            cls.REJECTED: {cls.DRAFT},
            cls.FAILED: {cls.DRAFT, cls.READY_FOR_PAYMENT},
            cls.PAID: {cls.CANCELLED},
            cls.CANCELLED: set(),
        }
        return to_status in allowed.get(from_status, set())


class CashDisbursementType(Enum):
    SUPPLIER_PAYMENT = "supplier_payment"
    SALARY_PAYMENT = "salary_payment"
    OPERATING_EXPENSE = "operating_expense"
    TAX_PAYMENT = "tax_payment"
    LOAN_REPAYMENT = "loan_repayment"
    CAPITAL_EXPENDITURE = "capital_expenditure"
    PETTY_CASH_REPLENISHMENT = "petty_cash_replenishment"
    REFUND = "refund"
    OTHER = "other"
    UTILITY_PAYMENT = "utility_payment"
    RENT_PAYMENT = "rent_payment"
    INSURANCE_PREMIUM = "insurance_premium"
    DIVIDEND_PAYMENT = "dividend_payment"
    COMMISSION_PAYMENT = "commission_payment"
    BONUS_PAYMENT = "bonus_payment"


class PaymentMethod(Enum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    GIRO = "giro"
    CREDIT_CARD = "credit_card"
    E_WALLET = "e_wallet"
    QRIS = "qris"
    CROSS_CHEQUE = "cross_cheque"
    POSTAL_ORDER = "postal_order"


class ApprovalLevel(Enum):
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4
    LEVEL_5 = 5


# ============================================================================
# Value Objects
# ============================================================================


@dataclass
class ApprovalHistoryEntry:
    """Riwayat approval."""

    level: ApprovalLevel
    approver_id: UUID
    approver_name: str
    action: str  # APPROVED, REJECTED, HOLD, REQUEST_CHANGE
    comment: str | None
    timestamp: datetime
    previous_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "approver_id": str(self.approver_id),
            "approver_name": self.approver_name,
            "action": self.action,
            "comment": self.comment,
            "timestamp": self.timestamp.isoformat(),
            "previous_status": self.previous_status,
        }


@dataclass
class PaymentAllocation:
    """Alokasi pembayaran (misal untuk invoice)."""

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

    def update_allocation(self, new_amount: Decimal, new_remaining: Decimal) -> PaymentAllocation:
        return PaymentAllocation(
            allocation_id=self.allocation_id,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            allocated_amount=new_amount,
            remaining_invoice_amount=new_remaining,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class DisbursementSignature:
    """Digital signature for disbursement."""

    disbursement_id: UUID
    version: int
    hash_value: str
    signed_at: datetime
    signed_by: str

    @classmethod
    def create(cls, disbursement: CashDisbursementEntity, signed_by: str) -> Self:
        data = f"{disbursement.disbursement_id}{disbursement.version}{disbursement.amount}{disbursement.disbursement_date}"
        hash_value = hashlib.sha3_256(data.encode()).hexdigest()
        return cls(
            disbursement_id=disbursement.disbursement_id,
            version=disbursement.version,
            hash_value=hash_value,
            signed_at=datetime.now(UTC),
            signed_by=signed_by,
        )

    def verify(self, disbursement: CashDisbursementEntity) -> bool:
        data = f"{disbursement.disbursement_id}{disbursement.version}{disbursement.amount}{disbursement.disbursement_date}"
        expected = hashlib.sha3_256(data.encode()).hexdigest()
        return self.hash_value == expected


@dataclass
class BankAccountInfo:
    """Bank account information for payment."""

    bank_name: str
    bank_code: str
    account_number: str
    account_name: str
    branch_name: str | None = None
    swift_code: str | None = None
    iban: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_name": self.bank_name,
            "bank_code": self.bank_code,
            "account_number": self.account_number,
            "account_name": self.account_name,
            "branch_name": self.branch_name,
            "swift_code": self.swift_code,
            "iban": self.iban,
        }


@dataclass
class TaxWithholdingInfo:
    """Tax withholding information."""

    tax_type: str  # PPH21, PPH23, PPH4(2), etc.
    tax_rate: Decimal
    tax_amount: Decimal
    tax_id: str | None = None
    certificate_number: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tax_type": self.tax_type,
            "tax_rate": str(self.tax_rate),
            "tax_amount": str(self.tax_amount),
            "tax_id": self.tax_id,
            "certificate_number": self.certificate_number,
        }


# ============================================================================
# Cash Disbursement Entity
# ============================================================================


@dataclass
class CashDisbursementEntity:
    """
    Entitas bukti pengeluaran kas dengan workflow lengkap.
    """

    disbursement_id: UUID
    disbursement_number: str
    disbursement_type: CashDisbursementType
    disbursement_date: datetime
    amount: Decimal
    currency: str
    status: CashDisbursementStatus

    # Pihak penerima
    supplier_id: UUID | None = None
    supplier_name: str | None = None
    supplier_npwp: str | None = None
    supplier_bank_account: BankAccountInfo | None = None
    supplier_email: str | None = None
    supplier_phone: str | None = None

    # Karyawan (untuk salary, reimbursement, etc.)
    employee_id: UUID | None = None
    employee_name: str | None = None
    employee_nik: str | None = None

    # Referensi invoice
    invoice_id: UUID | None = None
    invoice_number: str | None = None
    purchase_order_id: UUID | None = None
    purchase_order_number: str | None = None
    contract_id: UUID | None = None
    contract_number: str | None = None

    # Akun kas
    cash_book_id: UUID | None = None
    petty_cash_id: UUID | None = None
    bank_account_id: UUID | None = None

    # Pembayaran
    payment_method: PaymentMethod = PaymentMethod.CASH
    payment_reference: str | None = None
    cheque_number: str | None = None
    giro_number: str | None = None
    cheque_due_date: date | None = None
    swift_code: str | None = None

    # Alokasi
    allocations: list[PaymentAllocation] = field(default_factory=list)
    paid_amount: Decimal = Decimal(0)
    paid_date: datetime | None = None
    paid_by: str | None = None

    # Tax
    tax_withholdings: list[TaxWithholdingInfo] = field(default_factory=list)
    total_tax_withheld: Decimal = Decimal(0)

    # Approval (multi-level)
    approval_level_required: int = 1
    current_approval_level: int = 0
    approval_history: list[ApprovalHistoryEntry] = field(default_factory=list)
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    hold_reason: str | None = None
    held_by: str | None = None
    held_at: datetime | None = None

    # Budget & cost center
    budget_code: str | None = None
    budget_year: int | None = None
    cost_center: str | None = None
    department_id: UUID | None = None
    project_id: UUID | None = None
    activity_id: UUID | None = None

    # Dokumentasi
    attachment_urls: list[str] = field(default_factory=list)
    supporting_documents: list[str] = field(default_factory=list)
    description: str = ""
    notes: str | None = None
    internal_notes: str | None = None

    # Urgency
    is_urgent: bool = False
    urgency_reason: str | None = None
    requested_by: str | None = None
    requested_date: datetime | None = None

    # Bank fee
    bank_fee: Decimal = Decimal(0)
    bank_fee_currency: str = "IDR"

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    deleted_at: datetime | None = None
    signature: DisbursementSignature | None = None

    # Tracking
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if not self.disbursement_number or len(self.disbursement_number.strip()) < 3:
            raise ValueError("Disbursement number must be at least 3 characters")
        if self.amount <= 0:
            raise ValueError(f"Disbursement amount must be positive: {self.amount}")
        self.amount = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if self.paid_amount < 0:
            raise ValueError(f"Paid amount cannot be negative: {self.paid_amount}")
        self.paid_amount = self.paid_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if self.disbursement_date > datetime.now(UTC):
            raise ValueError("Disbursement date cannot be in the future")
        if self.paid_date and self.paid_date < self.disbursement_date:
            raise ValueError("Paid date cannot be before disbursement date")
        if self.paid_amount > self.amount:
            raise ValueError(f"Paid amount {self.paid_amount} exceeds total amount {self.amount}")
        if self.approval_level_required not in (1, 2, 3, 4, 5):
            raise ValueError(f"Invalid approval level required: {self.approval_level_required}")
        if not CashDisbursementStatus.can_transition(self.status, self.status):
            if self.status not in CashDisbursementStatus:
                raise ValueError(f"Invalid status: {self.status}")

        # Validate tax withholding total
        total_tax = sum(t.tax_amount for t in self.tax_withholdings)
        if total_tax > self.amount:
            raise ValueError(f"Total tax withheld {total_tax} exceeds amount {self.amount}")

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "disbursement_id": str(self.disbursement_id),
            "disbursement_number": self.disbursement_number,
            "details": details,
        }
        self._audit_trail.append(entry)

    def _calculate_signature(self) -> DisbursementSignature:
        return DisbursementSignature.create(self, self.created_by)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> Self:
        self._record_audit("CREATE", created_by, {"amount": str(self.amount)})
        return self

    def update(self, updated_by: str, **kwargs) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot update disbursement in status {self.status.value}")

        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in (
                "disbursement_id",
                "created_at",
                "created_by",
                "version",
            ):
                data[key] = value

        new_disbursement = self.from_dict(data)
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_disbursement

    def delete(self, deleted_by: str, reason: str | None = None) -> Self:
        if self.status in (CashDisbursementStatus.PAID, CashDisbursementStatus.PROCESSING):
            raise ValueError(f"Cannot delete disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.CANCELLED
        new_disbursement.deleted_at = datetime.now(UTC)
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_disbursement

    def restore(self, restored_by: str) -> Self:
        if self.status != CashDisbursementStatus.CANCELLED:
            raise ValueError(f"Cannot restore disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.DRAFT
        new_disbursement.deleted_at = None
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("RESTORE", restored_by, {})
        return new_disbursement

    def activate(self, activated_by: str) -> Self:
        if self.status != CashDisbursementStatus.DRAFT:
            raise ValueError(f"Cannot activate disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.SUBMITTED
        new_disbursement.submitted_by = activated_by
        new_disbursement.submitted_at = datetime.now(UTC)
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("ACTIVATE", activated_by, {})
        return new_disbursement

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> Self:
        if self.status != CashDisbursementStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.DRAFT
        new_disbursement.submitted_by = None
        new_disbursement.submitted_at = None
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_disbursement

    def lock(self, locked_by: str, reason: str) -> Self:
        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.ON_HOLD
        new_disbursement.hold_reason = reason
        new_disbursement.held_by = locked_by
        new_disbursement.held_at = datetime.now(UTC)
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("LOCK", locked_by, {"reason": reason})
        return new_disbursement

    def unlock(self, unlocked_by: str) -> Self:
        if self.status != CashDisbursementStatus.ON_HOLD:
            raise ValueError(f"Cannot unlock disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.PENDING_APPROVAL
        new_disbursement.hold_reason = None
        new_disbursement.held_by = None
        new_disbursement.held_at = None
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("UNLOCK", unlocked_by, {})
        return new_disbursement

    def validate(self) -> dict[str, Any]:
        errors = []
        warnings = []

        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))

        total_allocated = sum(a.allocated_amount for a in self.allocations)
        if total_allocated > self.amount:
            errors.append(
                f"Total allocated {total_allocated} exceeds disbursement amount {self.amount}"
            )

        if self.is_urgent and not self.urgency_reason:
            warnings.append("Urgent disbursement has no urgency reason")

        if (
            self.status == CashDisbursementStatus.PENDING_APPROVAL
            and (datetime.now(UTC) - self.submitted_at).days > 7
        ):
            warnings.append("Disbursement has been pending approval for over 7 days")

        if self.get_remaining_amount() > 0 and self.status == CashDisbursementStatus.PAID:
            errors.append("Disbursement marked as PAID but has remaining amount")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "disbursement_id": str(self.disbursement_id),
            "disbursement_number": self.disbursement_number,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "disbursement_id": str(self.disbursement_id),
            "disbursement_number": self.disbursement_number,
            "disbursement_type": self.disbursement_type.value,
            "disbursement_date": self.disbursement_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status.value,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "supplier_name": self.supplier_name,
            "supplier_npwp": self.supplier_npwp,
            "supplier_bank_account": self.supplier_bank_account.to_dict()
            if self.supplier_bank_account
            else None,
            "supplier_email": self.supplier_email,
            "supplier_phone": self.supplier_phone,
            "employee_id": str(self.employee_id) if self.employee_id else None,
            "employee_name": self.employee_name,
            "employee_nik": self.employee_nik,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "invoice_number": self.invoice_number,
            "purchase_order_id": str(self.purchase_order_id) if self.purchase_order_id else None,
            "purchase_order_number": self.purchase_order_number,
            "contract_id": str(self.contract_id) if self.contract_id else None,
            "contract_number": self.contract_number,
            "cash_book_id": str(self.cash_book_id) if self.cash_book_id else None,
            "petty_cash_id": str(self.petty_cash_id) if self.petty_cash_id else None,
            "bank_account_id": str(self.bank_account_id) if self.bank_account_id else None,
            "payment_method": self.payment_method.value,
            "payment_reference": self.payment_reference,
            "cheque_number": self.cheque_number,
            "giro_number": self.giro_number,
            "cheque_due_date": self.cheque_due_date.isoformat() if self.cheque_due_date else None,
            "swift_code": self.swift_code,
            "paid_amount": str(self.paid_amount),
            "paid_date": self.paid_date.isoformat() if self.paid_date else None,
            "paid_by": self.paid_by,
            "remaining_amount": str(self.get_remaining_amount()),
            "tax_withholdings": [t.to_dict() for t in self.tax_withholdings],
            "total_tax_withheld": str(self.total_tax_withheld),
            "net_amount": str(self.get_net_amount()),
            "approval_level_required": self.approval_level_required,
            "current_approval_level": self.current_approval_level,
            "approval_history": [h.to_dict() for h in self.approval_history],
            "approval_summary": self.get_approval_summary(),
            "payment_summary": self.get_payment_summary(),
            "budget_code": self.budget_code,
            "budget_year": self.budget_year,
            "cost_center": self.cost_center,
            "department_id": str(self.department_id) if self.department_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "activity_id": str(self.activity_id) if self.activity_id else None,
            "attachments": self.attachment_urls,
            "supporting_documents": self.supporting_documents,
            "description": self.description,
            "notes": self.notes,
            "internal_notes": self.internal_notes,
            "is_urgent": self.is_urgent,
            "urgency_reason": self.urgency_reason,
            "requested_by": self.requested_by,
            "requested_date": self.requested_date.isoformat() if self.requested_date else None,
            "bank_fee": str(self.bank_fee),
            "bank_fee_currency": self.bank_fee_currency,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        # Parse supplier_bank_account if present
        supplier_bank_account = None
        if data.get("supplier_bank_account"):
            bank_data = data["supplier_bank_account"]
            supplier_bank_account = BankAccountInfo(
                bank_name=bank_data["bank_name"],
                bank_code=bank_data["bank_code"],
                account_number=bank_data["account_number"],
                account_name=bank_data["account_name"],
                branch_name=bank_data.get("branch_name"),
                swift_code=bank_data.get("swift_code"),
                iban=bank_data.get("iban"),
            )

        # Parse tax withholdings
        tax_withholdings = []
        for t in data.get("tax_withholdings", []):
            tax_withholdings.append(
                TaxWithholdingInfo(
                    tax_type=t["tax_type"],
                    tax_rate=Decimal(t["tax_rate"]),
                    tax_amount=Decimal(t["tax_amount"]),
                    tax_id=t.get("tax_id"),
                    certificate_number=t.get("certificate_number"),
                )
            )

        # Parse approval history
        approval_history = []
        for h in data.get("approval_history", []):
            approval_history.append(
                ApprovalHistoryEntry(
                    level=ApprovalLevel(h["level"]),
                    approver_id=UUID(h["approver_id"]),
                    approver_name=h["approver_name"],
                    action=h["action"],
                    comment=h.get("comment"),
                    timestamp=datetime.fromisoformat(h["timestamp"]),
                    previous_status=h.get("previous_status"),
                )
            )

        return cls(
            disbursement_id=UUID(data["disbursement_id"]),
            disbursement_number=data["disbursement_number"],
            disbursement_type=CashDisbursementType(data["disbursement_type"]),
            disbursement_date=datetime.fromisoformat(data["disbursement_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            status=CashDisbursementStatus(data["status"]),
            supplier_id=UUID(data["supplier_id"]) if data.get("supplier_id") else None,
            supplier_name=data.get("supplier_name"),
            supplier_npwp=data.get("supplier_npwp"),
            supplier_bank_account=supplier_bank_account,
            supplier_email=data.get("supplier_email"),
            supplier_phone=data.get("supplier_phone"),
            employee_id=UUID(data["employee_id"]) if data.get("employee_id") else None,
            employee_name=data.get("employee_name"),
            employee_nik=data.get("employee_nik"),
            invoice_id=UUID(data["invoice_id"]) if data.get("invoice_id") else None,
            invoice_number=data.get("invoice_number"),
            purchase_order_id=UUID(data["purchase_order_id"])
            if data.get("purchase_order_id")
            else None,
            purchase_order_number=data.get("purchase_order_number"),
            contract_id=UUID(data["contract_id"]) if data.get("contract_id") else None,
            contract_number=data.get("contract_number"),
            cash_book_id=UUID(data["cash_book_id"]) if data.get("cash_book_id") else None,
            petty_cash_id=UUID(data["petty_cash_id"]) if data.get("petty_cash_id") else None,
            bank_account_id=UUID(data["bank_account_id"]) if data.get("bank_account_id") else None,
            payment_method=PaymentMethod(data["payment_method"]),
            payment_reference=data.get("payment_reference"),
            cheque_number=data.get("cheque_number"),
            giro_number=data.get("giro_number"),
            cheque_due_date=date.fromisoformat(data["cheque_due_date"])
            if data.get("cheque_due_date")
            else None,
            swift_code=data.get("swift_code"),
            allocations=[],
            paid_amount=Decimal(data.get("paid_amount", "0")),
            paid_date=datetime.fromisoformat(data["paid_date"]) if data.get("paid_date") else None,
            paid_by=data.get("paid_by"),
            tax_withholdings=tax_withholdings,
            total_tax_withheld=Decimal(data.get("total_tax_withheld", "0")),
            approval_level_required=data.get("approval_level_required", 1),
            current_approval_level=data.get("current_approval_level", 0),
            approval_history=approval_history,
            submitted_by=data.get("submitted_by"),
            submitted_at=datetime.fromisoformat(data["submitted_at"])
            if data.get("submitted_at")
            else None,
            approved_by=data.get("approved_by"),
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            rejected_by=data.get("rejected_by"),
            rejected_at=datetime.fromisoformat(data["rejected_at"])
            if data.get("rejected_at")
            else None,
            rejection_reason=data.get("rejection_reason"),
            hold_reason=data.get("hold_reason"),
            held_by=data.get("held_by"),
            held_at=datetime.fromisoformat(data["held_at"]) if data.get("held_at") else None,
            budget_code=data.get("budget_code"),
            budget_year=data.get("budget_year"),
            cost_center=data.get("cost_center"),
            department_id=UUID(data["department_id"]) if data.get("department_id") else None,
            project_id=UUID(data["project_id"]) if data.get("project_id") else None,
            activity_id=UUID(data["activity_id"]) if data.get("activity_id") else None,
            attachment_urls=data.get("attachment_urls", []),
            supporting_documents=data.get("supporting_documents", []),
            description=data.get("description", ""),
            notes=data.get("notes"),
            internal_notes=data.get("internal_notes"),
            is_urgent=data.get("is_urgent", False),
            urgency_reason=data.get("urgency_reason"),
            requested_by=data.get("requested_by"),
            requested_date=datetime.fromisoformat(data["requested_date"])
            if data.get("requested_date")
            else None,
            bank_fee=Decimal(data.get("bank_fee", "0")),
            bank_fee_currency=data.get("bank_fee_currency", "IDR"),
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
        object.__setattr__(cloned, "disbursement_id", new_id)
        cloned.disbursement_number = f"{self.disbursement_number}_COPY_{uuid4().hex[:4]}"
        cloned.status = CashDisbursementStatus.DRAFT
        cloned.paid_amount = Decimal(0)
        cloned.paid_date = None
        cloned.paid_by = None
        cloned.allocations = []
        cloned.approval_history = []
        cloned.current_approval_level = 0
        cloned.submitted_by = None
        cloned.submitted_at = None
        cloned.approved_by = None
        cloned.approved_at = None
        cloned.version = 1
        cloned.created_at = datetime.now(UTC)
        cloned.updated_at = datetime.now(UTC)
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.disbursement_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "disbursement_id": str(self.disbursement_id),
            "disbursement_number": self.disbursement_number,
            "amount": str(self.amount),
            "paid_amount": str(self.paid_amount),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> Self:
        new_disbursement = self._copy()
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("TOUCH", touched_by, {})
        return new_disbursement

    # ==================== STATUS CHECKERS ====================

    def is_draft(self) -> bool:
        return self.status == CashDisbursementStatus.DRAFT

    def is_submitted(self) -> bool:
        return self.status == CashDisbursementStatus.SUBMITTED

    def is_pending_approval(self) -> bool:
        return self.status == CashDisbursementStatus.PENDING_APPROVAL

    def is_approved(self) -> bool:
        return self.status == CashDisbursementStatus.APPROVED

    def is_rejected(self) -> bool:
        return self.status == CashDisbursementStatus.REJECTED

    def is_paid(self) -> bool:
        return self.status == CashDisbursementStatus.PAID

    def is_cancelled(self) -> bool:
        return self.status == CashDisbursementStatus.CANCELLED

    def is_partially_paid(self) -> bool:
        return self.status == CashDisbursementStatus.PARTIALLY_PAID

    def is_on_hold(self) -> bool:
        return self.status == CashDisbursementStatus.ON_HOLD

    def is_ready_for_payment(self) -> bool:
        return self.status == CashDisbursementStatus.READY_FOR_PAYMENT

    def is_processing(self) -> bool:
        return self.status == CashDisbursementStatus.PROCESSING

    def is_failed(self) -> bool:
        return self.status == CashDisbursementStatus.FAILED

    def can_edit(self) -> bool:
        return self.status in (
            CashDisbursementStatus.DRAFT,
            CashDisbursementStatus.REJECTED,
            CashDisbursementStatus.FAILED,
        )

    def can_submit(self) -> bool:
        return self.status == CashDisbursementStatus.DRAFT

    def can_approve(self, level: int) -> bool:
        return (
            self.status == CashDisbursementStatus.PENDING_APPROVAL
            and self.current_approval_level == level - 1
            and level <= self.approval_level_required
        )

    def can_reject(self) -> bool:
        return self.status in (
            CashDisbursementStatus.PENDING_APPROVAL,
            CashDisbursementStatus.SUBMITTED,
        )

    def can_hold(self) -> bool:
        return self.status in (
            CashDisbursementStatus.PENDING_APPROVAL,
            CashDisbursementStatus.APPROVED,
            CashDisbursementStatus.READY_FOR_PAYMENT,
        )

    def can_pay(self) -> bool:
        return (
            self.status == CashDisbursementStatus.READY_FOR_PAYMENT
            and self.paid_amount < self.amount
        )

    def can_cancel(self) -> bool:
        return self.status not in (
            CashDisbursementStatus.PAID,
            CashDisbursementStatus.CANCELLED,
            CashDisbursementStatus.PROCESSING,
        )

    def is_fully_paid(self) -> bool:
        return self.paid_amount >= self.amount

    def get_remaining_amount(self) -> Decimal:
        return (self.amount - self.paid_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_net_amount(self) -> Decimal:
        """Amount after tax withholding."""
        return (self.amount - self.total_tax_withheld).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    # ==================== WORKFLOW ACTIONS ====================

    def submit(self, submitted_by: str) -> Self:
        if not self.can_submit():
            raise ValueError(f"Cannot submit disbursement in status {self.status.value}")

        new_status = (
            CashDisbursementStatus.PENDING_APPROVAL
            if self.approval_level_required > 0
            else CashDisbursementStatus.APPROVED
        )

        new_disbursement = self._copy()
        new_disbursement.status = new_status
        new_disbursement.submitted_by = submitted_by
        new_disbursement.submitted_at = datetime.now(UTC)
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("SUBMIT", submitted_by, {})
        return new_disbursement

    def approve(
        self,
        level: int,
        approver_id: UUID,
        approver_name: str,
        comment: str | None = None,
    ) -> Self:
        if not self.can_approve(level):
            raise ValueError(f"Cannot approve at level {level} in status {self.status.value}")

        new_history = self.approval_history + [
            ApprovalHistoryEntry(
                level=ApprovalLevel(level),
                approver_id=approver_id,
                approver_name=approver_name,
                action="APPROVED",
                comment=comment,
                timestamp=datetime.now(UTC),
                previous_status=self.status.value,
            )
        ]

        new_current_level = level
        new_status = self.status
        new_approved_by = self.approved_by
        new_approved_at = self.approved_at

        if level == self.approval_level_required:
            new_status = CashDisbursementStatus.APPROVED
            new_approved_by = approver_name
            new_approved_at = datetime.now(UTC)

        new_disbursement = self._copy()
        new_disbursement.approval_history = new_history
        new_disbursement.current_approval_level = new_current_level
        new_disbursement.status = new_status
        new_disbursement.approved_by = new_approved_by
        new_disbursement.approved_at = new_approved_at
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit(
            "APPROVE", approver_name, {"level": level, "comment": comment}
        )
        return new_disbursement

    def reject(self, rejected_by: str, reason: str) -> Self:
        if not self.can_reject():
            raise ValueError(f"Cannot reject disbursement in status {self.status.value}")

        new_history = self.approval_history + [
            ApprovalHistoryEntry(
                level=ApprovalLevel(self.current_approval_level + 1),
                approver_id=UUID(int=0),
                approver_name=rejected_by,
                action="REJECTED",
                comment=reason,
                timestamp=datetime.now(UTC),
                previous_status=self.status.value,
            )
        ]

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.REJECTED
        new_disbursement.approval_history = new_history
        new_disbursement.rejected_by = rejected_by
        new_disbursement.rejected_at = datetime.now(UTC)
        new_disbursement.rejection_reason = reason
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("REJECT", rejected_by, {"reason": reason})
        return new_disbursement

    def hold(self, held_by: str, reason: str) -> Self:
        if not self.can_hold():
            raise ValueError(f"Cannot hold disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.ON_HOLD
        new_disbursement.hold_reason = reason
        new_disbursement.held_by = held_by
        new_disbursement.held_at = datetime.now(UTC)
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("HOLD", held_by, {"reason": reason})
        return new_disbursement

    def release_hold(self, released_by: str) -> Self:
        if self.status != CashDisbursementStatus.ON_HOLD:
            raise ValueError(f"Cannot release hold on disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.PENDING_APPROVAL
        new_disbursement.hold_reason = None
        new_disbursement.held_by = None
        new_disbursement.held_at = None
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("RELEASE_HOLD", released_by, {})
        return new_disbursement

    def mark_ready_for_payment(self, marked_by: str) -> Self:
        if self.status != CashDisbursementStatus.APPROVED:
            raise ValueError(f"Cannot mark ready for payment in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.READY_FOR_PAYMENT
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("READY_FOR_PAYMENT", marked_by, {})
        return new_disbursement

    def mark_processing(self, processed_by: str) -> Self:
        if self.status != CashDisbursementStatus.READY_FOR_PAYMENT:
            raise ValueError(f"Cannot mark processing in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.PROCESSING
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("PROCESSING", processed_by, {})
        return new_disbursement

    def mark_paid(
        self,
        paid_by: str,
        paid_amount: Decimal | None = None,
        paid_date: datetime | None = None,
        payment_reference: str | None = None,
    ) -> Self:
        if not self.can_pay():
            raise ValueError(f"Cannot pay disbursement in status {self.status.value}")

        amount_to_pay = paid_amount if paid_amount is not None else self.get_remaining_amount()
        if amount_to_pay <= 0:
            raise ValueError("Paid amount must be positive")
        if amount_to_pay > self.get_remaining_amount():
            raise ValueError(
                f"Paid amount {amount_to_pay} exceeds remaining {self.get_remaining_amount()}"
            )

        amount_to_pay = amount_to_pay.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        new_paid_amount = self.paid_amount + amount_to_pay
        new_status = (
            CashDisbursementStatus.PAID
            if new_paid_amount >= self.amount
            else CashDisbursementStatus.PARTIALLY_PAID
        )

        # Update allocations
        new_allocations = self.allocations.copy()
        remaining_to_allocate = amount_to_pay
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

        new_disbursement = self._copy()
        new_disbursement.status = new_status
        new_disbursement.paid_amount = new_paid_amount
        new_disbursement.paid_date = paid_date or datetime.now(UTC)
        new_disbursement.paid_by = paid_by
        if payment_reference:
            new_disbursement.payment_reference = payment_reference
        new_disbursement.allocations = new_allocations
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit(
            "PAY", paid_by, {"amount": str(amount_to_pay), "reference": payment_reference}
        )
        return new_disbursement

    def mark_failed(self, failed_by: str, reason: str, failure_code: str | None = None) -> Self:
        if self.status != CashDisbursementStatus.PROCESSING:
            raise ValueError(f"Cannot mark failed in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.FAILED
        new_disbursement.failure_reason = reason
        new_disbursement.failure_code = failure_code
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("FAIL", failed_by, {"reason": reason, "code": failure_code})
        return new_disbursement

    def cancel(self, cancelled_by: str, reason: str) -> Self:
        if not self.can_cancel():
            raise ValueError(f"Cannot cancel disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.status = CashDisbursementStatus.CANCELLED
        new_disbursement.description = f"{self.description}\n[CANCELLED] {reason}"
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_disbursement

    # ==================== TAX METHODS ====================

    def add_tax_withholding(
        self, tax_type: str, tax_rate: Decimal, tax_amount: Decimal, tax_id: str | None = None
    ) -> Self:
        if self.status != CashDisbursementStatus.DRAFT:
            raise ValueError(f"Cannot add tax withholding in status {self.status.value}")

        tax_withholding = TaxWithholdingInfo(
            tax_type=tax_type,
            tax_rate=tax_rate,
            tax_amount=tax_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
            tax_id=tax_id,
        )

        new_withholdings = self.tax_withholdings + [tax_withholding]
        new_total_tax = sum(t.tax_amount for t in new_withholdings)

        if new_total_tax > self.amount:
            raise ValueError(f"Total tax withheld {new_total_tax} exceeds amount {self.amount}")

        new_disbursement = self._copy()
        new_disbursement.tax_withholdings = new_withholdings
        new_disbursement.total_tax_withheld = new_total_tax
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit(
            "ADD_TAX", self.created_by, {"tax_type": tax_type, "amount": str(tax_amount)}
        )
        return new_disbursement

    def remove_tax_withholding(self, tax_index: int, removed_by: str) -> Self:
        if self.status != CashDisbursementStatus.DRAFT:
            raise ValueError(f"Cannot remove tax withholding in status {self.status.value}")

        if tax_index >= len(self.tax_withholdings):
            raise ValueError(f"Tax withholding index {tax_index} out of range")

        new_withholdings = (
            self.tax_withholdings[:tax_index] + self.tax_withholdings[tax_index + 1 :]
        )
        new_total_tax = sum(t.tax_amount for t in new_withholdings)

        new_disbursement = self._copy()
        new_disbursement.tax_withholdings = new_withholdings
        new_disbursement.total_tax_withheld = new_total_tax
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("REMOVE_TAX", removed_by, {"index": tax_index})
        return new_disbursement

    # ==================== UPDATE METHODS ====================

    def update_description(self, new_description: str, updated_by: str) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot edit disbursement in status {self.status.value}")

        new_disbursement = self._copy()
        new_disbursement.description = new_description
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("UPDATE_DESCRIPTION", updated_by, {})
        return new_disbursement

    def update_amount(self, new_amount: Decimal, updated_by: str, reason: str) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot edit amount in status {self.status.value}")

        new_amount = new_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if new_amount <= 0:
            raise ValueError("New amount must be positive")
        if self.paid_amount > new_amount:
            raise ValueError(f"Cannot reduce amount below already paid {self.paid_amount}")

        # Adjust tax withholdings proportionally if needed
        new_withholdings = []
        for tax in self.tax_withholdings:
            new_tax_amount = tax.tax_amount * new_amount / self.amount
            new_withholdings.append(
                TaxWithholdingInfo(
                    tax_type=tax.tax_type,
                    tax_rate=tax.tax_rate,
                    tax_amount=new_tax_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
                    tax_id=tax.tax_id,
                    certificate_number=tax.certificate_number,
                )
            )

        new_disbursement = self._copy()
        new_disbursement.amount = new_amount
        new_disbursement.tax_withholdings = new_withholdings
        new_disbursement.total_tax_withheld = sum(t.tax_amount for t in new_withholdings)
        new_disbursement.description = f"{self.description}\n[AMOUNT CHANGE] from {self.amount} to {new_amount}. Reason: {reason}"
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit(
            "UPDATE_AMOUNT", updated_by, {"new_amount": str(new_amount), "reason": reason}
        )
        return new_disbursement

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
        new_allocation = PaymentAllocation(
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
                f"Total allocated {total_allocated} exceeds disbursement amount {self.amount}"
            )

        new_disbursement = self._copy()
        new_disbursement.allocations = new_allocations
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit(
            "ADD_ALLOCATION",
            self.created_by,
            {
                "invoice_id": str(invoice_id),
                "amount": str(allocated_amount),
            },
        )
        return new_disbursement

    def remove_allocation(self, allocation_id: UUID, removed_by: str) -> Self:
        if not self.can_edit():
            raise ValueError(f"Cannot remove allocation in status {self.status.value}")

        new_allocations = [a for a in self.allocations if a.allocation_id != allocation_id]
        if len(new_allocations) == len(self.allocations):
            raise ValueError(f"Allocation {allocation_id} not found")

        new_disbursement = self._copy()
        new_disbursement.allocations = new_allocations
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit(
            "REMOVE_ALLOCATION", removed_by, {"allocation_id": str(allocation_id)}
        )
        return new_disbursement

    def attach_file(self, file_url: str, uploaded_by: str, is_supporting: bool = False) -> Self:
        if is_supporting:
            new_attachments = self.supporting_documents + [file_url]
            new_disbursement = self._copy()
            new_disbursement.supporting_documents = new_attachments
        else:
            new_attachments = self.attachment_urls + [file_url]
            new_disbursement = self._copy()
            new_disbursement.attachment_urls = new_attachments

        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit(
            "ATTACH_FILE", uploaded_by, {"file_url": file_url, "is_supporting": is_supporting}
        )
        return new_disbursement

    def remove_attachment(
        self, file_url: str, removed_by: str, is_supporting: bool = False
    ) -> Self:
        if is_supporting:
            new_attachments = [f for f in self.supporting_documents if f != file_url]
            new_disbursement = self._copy()
            new_disbursement.supporting_documents = new_attachments
        else:
            new_attachments = [f for f in self.attachment_urls if f != file_url]
            new_disbursement = self._copy()
            new_disbursement.attachment_urls = new_attachments

        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("REMOVE_ATTACHMENT", removed_by, {"file_url": file_url})
        return new_disbursement

    def mark_urgent(self, urgent_by: str, reason: str) -> Self:
        new_disbursement = self._copy()
        new_disbursement.is_urgent = True
        new_disbursement.urgency_reason = reason
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("MARK_URGENT", urgent_by, {"reason": reason})
        return new_disbursement

    def unmark_urgent(self, unmarked_by: str) -> Self:
        new_disbursement = self._copy()
        new_disbursement.is_urgent = False
        new_disbursement.urgency_reason = None
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("UNMARK_URGENT", unmarked_by, {})
        return new_disbursement

    # ==================== HELPER METHODS ====================

    def get_approval_summary(self) -> dict[str, Any]:
        return {
            "required_level": self.approval_level_required,
            "current_level": self.current_approval_level,
            "completed": self.current_approval_level >= self.approval_level_required,
            "next_required_level": self.current_approval_level + 1
            if self.current_approval_level < self.approval_level_required
            else None,
            "history": [h.to_dict() for h in self.approval_history],
            "status": self.status.value,
        }

    def get_payment_summary(self) -> dict[str, Any]:
        return {
            "total_amount": str(self.amount),
            "paid_amount": str(self.paid_amount),
            "remaining_amount": str(self.get_remaining_amount()),
            "paid_date": self.paid_date.isoformat() if self.paid_date else None,
            "paid_by": self.paid_by,
            "payment_method": self.payment_method.value,
            "payment_reference": self.payment_reference,
            "bank_fee": str(self.bank_fee),
            "net_amount": str(self.get_net_amount()),
            "total_tax_withheld": str(self.total_tax_withheld),
            "taxes": [t.to_dict() for t in self.tax_withholdings],
            "allocations": [a.to_dict() for a in self.allocations],
            "allocation_summary": {
                "total_allocated": str(sum(a.allocated_amount for a in self.allocations)),
                "unallocated": str(self.amount - sum(a.allocated_amount for a in self.allocations)),
            },
        }

    def sign(self, signed_by: str) -> Self:
        new_disbursement = self._copy()
        new_disbursement.signature = DisbursementSignature.create(self, signed_by)
        new_disbursement.updated_at = datetime.now(UTC)
        new_disbursement.version = self.version + 1
        new_disbursement._record_audit("SIGN", signed_by, {})
        return new_disbursement

    def verify_signature(self) -> bool:
        if not self.signature:
            return False
        return self.signature.verify(self)

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> Self:
        return CashDisbursementEntity(
            disbursement_id=self.disbursement_id,
            disbursement_number=self.disbursement_number,
            disbursement_type=self.disbursement_type,
            disbursement_date=self.disbursement_date,
            amount=self.amount,
            currency=self.currency,
            status=self.status,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            supplier_npwp=self.supplier_npwp,
            supplier_bank_account=self.supplier_bank_account,
            supplier_email=self.supplier_email,
            supplier_phone=self.supplier_phone,
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            employee_nik=self.employee_nik,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            purchase_order_id=self.purchase_order_id,
            purchase_order_number=self.purchase_order_number,
            contract_id=self.contract_id,
            contract_number=self.contract_number,
            cash_book_id=self.cash_book_id,
            petty_cash_id=self.petty_cash_id,
            bank_account_id=self.bank_account_id,
            payment_method=self.payment_method,
            payment_reference=self.payment_reference,
            cheque_number=self.cheque_number,
            giro_number=self.giro_number,
            cheque_due_date=self.cheque_due_date,
            swift_code=self.swift_code,
            allocations=self.allocations.copy(),
            paid_amount=self.paid_amount,
            paid_date=self.paid_date,
            paid_by=self.paid_by,
            tax_withholdings=self.tax_withholdings.copy(),
            total_tax_withheld=self.total_tax_withheld,
            approval_level_required=self.approval_level_required,
            current_approval_level=self.current_approval_level,
            approval_history=self.approval_history.copy(),
            submitted_by=self.submitted_by,
            submitted_at=self.submitted_at,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rejected_by=self.rejected_by,
            rejected_at=self.rejected_at,
            rejection_reason=self.rejection_reason,
            hold_reason=self.hold_reason,
            held_by=self.held_by,
            held_at=self.held_at,
            budget_code=self.budget_code,
            budget_year=self.budget_year,
            cost_center=self.cost_center,
            department_id=self.department_id,
            project_id=self.project_id,
            activity_id=self.activity_id,
            attachment_urls=self.attachment_urls.copy(),
            supporting_documents=self.supporting_documents.copy(),
            description=self.description,
            notes=self.notes,
            internal_notes=self.internal_notes,
            is_urgent=self.is_urgent,
            urgency_reason=self.urgency_reason,
            requested_by=self.requested_by,
            requested_date=self.requested_date,
            bank_fee=self.bank_fee,
            bank_fee_currency=self.bank_fee_currency,
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

CashDisbursement = CashDisbursementEntity


# ============================================================================
# Repository Interface (Real Implementation)
# ============================================================================


class CashDisbursementRepository:
    """Repository for CashDisbursement with in-memory storage."""

    _storage: ClassVar[dict[UUID, dict[UUID, CashDisbursementEntity]]] = {}
    _storage_by_number: ClassVar[dict[UUID, dict[str, CashDisbursementEntity]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, CashDisbursementEntity]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    def _get_number_storage(cls, legal_entity_id: UUID) -> dict[str, CashDisbursementEntity]:
        if legal_entity_id not in cls._storage_by_number:
            cls._storage_by_number[legal_entity_id] = {}
        return cls._storage_by_number[legal_entity_id]

    async def get_by_id(
        self, disbursement_id: UUID, legal_entity_id: UUID
    ) -> CashDisbursementEntity | None:
        storage = self._get_storage(legal_entity_id)
        return storage.get(disbursement_id)

    async def get_by_number(
        self, disbursement_number: str, legal_entity_id: UUID
    ) -> CashDisbursementEntity | None:
        number_storage = self._get_number_storage(legal_entity_id)
        return number_storage.get(disbursement_number)

    async def get_by_supplier(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[CashDisbursementEntity]:
        storage = self._get_storage(legal_entity_id)
        result = [d for d in storage.values() if d.supplier_id == supplier_id]
        if from_date:
            result = [d for d in result if d.disbursement_date >= from_date]
        if to_date:
            result = [d for d in result if d.disbursement_date <= to_date]
        result.sort(key=lambda x: x.disbursement_date, reverse=True)
        return result

    async def get_by_invoice(
        self, invoice_id: UUID, legal_entity_id: UUID
    ) -> list[CashDisbursementEntity]:
        storage = self._get_storage(legal_entity_id)
        return [d for d in storage.values() if d.invoice_id == invoice_id]

    async def get_by_status(
        self, status: CashDisbursementStatus, legal_entity_id: UUID
    ) -> list[CashDisbursementEntity]:
        storage = self._get_storage(legal_entity_id)
        return [d for d in storage.values() if d.status == status]

    async def get_pending_approval(
        self, legal_entity_id: UUID, approver_level: int | None = None
    ) -> list[CashDisbursementEntity]:
        storage = self._get_storage(legal_entity_id)
        result = [
            d for d in storage.values() if d.status == CashDisbursementStatus.PENDING_APPROVAL
        ]
        if approver_level is not None:
            result = [d for d in result if d.current_approval_level + 1 == approver_level]
        return result

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CashDisbursementEntity]:
        storage = self._get_storage(legal_entity_id)
        result = [d for d in storage.values() if start_date <= d.disbursement_date <= end_date]
        result.sort(key=lambda x: x.disbursement_date)
        return result

    async def get_urgent(self, legal_entity_id: UUID) -> list[CashDisbursementEntity]:
        storage = self._get_storage(legal_entity_id)
        return [
            d
            for d in storage.values()
            if d.is_urgent
            and d.status not in (CashDisbursementStatus.PAID, CashDisbursementStatus.CANCELLED)
        ]

    async def get_total_by_supplier(
        self, supplier_id: UUID, legal_entity_id: UUID, year: int | None = None
    ) -> Decimal:
        storage = self._get_storage(legal_entity_id)
        result = [
            d
            for d in storage.values()
            if d.supplier_id == supplier_id and d.status == CashDisbursementStatus.PAID
        ]
        if year:
            result = [d for d in result if d.disbursement_date.year == year]
        total = sum(d.amount for d in result)
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    async def count(self, legal_entity_id: UUID) -> int:
        storage = self._get_storage(legal_entity_id)
        return len(storage)

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CashDisbursementEntity]:
        disbursements = await self.get_all(legal_entity_id)
        disbursements.sort(key=lambda x: x.disbursement_date, reverse=True)
        return disbursements[offset : offset + limit]

    async def get_all(self, legal_entity_id: UUID) -> list[CashDisbursementEntity]:
        storage = self._get_storage(legal_entity_id)
        return list(storage.values())

    async def save(self, disbursement: CashDisbursementEntity, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        number_storage = self._get_number_storage(legal_entity_id)
        storage[disbursement.disbursement_id] = disbursement
        number_storage[disbursement.disbursement_number] = disbursement

    async def update(self, disbursement: CashDisbursementEntity, legal_entity_id: UUID) -> None:
        await self.save(disbursement, legal_entity_id)

    async def delete(self, disbursement_id: UUID, legal_entity_id: UUID) -> None:
        storage = self._get_storage(legal_entity_id)
        number_storage = self._get_number_storage(legal_entity_id)
        if disbursement_id in storage:
            disbursement = storage[disbursement_id]
            if disbursement.disbursement_number in number_storage:
                del number_storage[disbursement.disbursement_number]
            del storage[disbursement_id]

    async def clear(self, legal_entity_id: UUID) -> None:
        if legal_entity_id in self._storage:
            self._storage[legal_entity_id] = {}
        if legal_entity_id in self._storage_by_number:
            self._storage_by_number[legal_entity_id] = {}


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "ApprovalHistoryEntry",
    "ApprovalLevel",
    "BankAccountInfo",
    "CashDisbursement",
    "CashDisbursementEntity",
    "CashDisbursementRepository",
    "CashDisbursementStatus",
    "CashDisbursementType",
    "DisbursementSignature",
    "PaymentAllocation",
    "PaymentMethod",
    "TaxWithholdingInfo",
]
