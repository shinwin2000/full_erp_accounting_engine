#!/usr/bin/env python3
"""
Module: accrual_basis.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: pengakuan pendapatan/beban saat terjadi, bukan saat kas.

Fixed syntax errors and hardened with validation, logging, and thread-safety.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class RecognitionTiming(Enum):
    EARNED = auto()
    INCURRED = auto()
    REALIZABLE = auto()
    PROBABLE = auto()


class AccrualType(Enum):
    ACCRUED_REVENUE = auto()
    ACCRUED_EXPENSE = auto()
    DEFERRED_REVENUE = auto()
    PREPAID_EXPENSE = auto()
    ESTIMATED_LIABILITY = auto()
    PROVISION = auto()


class AccrualBasisSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class RevenueRecognitionModel(Enum):
    AT_A_POINT_IN_TIME = auto()
    OVER_TIME = auto()
    HYBRID = auto()


class ExpenseMatchingMethod(Enum):
    DIRECT_MATCHING = auto()
    SYSTEMATIC_ALLOCATION = auto()
    IMMEDIATE_RECOGNITION = auto()


# ==================== EXCEPTIONS ====================


class AccrualBasisViolationError(Exception):
    pass


class InvalidRevenueCriteriaError(Exception):
    pass


class InvalidExpenseCriteriaError(Exception):
    pass


# ==================== VALUE OBJECTS ====================


@dataclass(frozen=True, kw_only=True)
class RevenueRecognitionCriteria:
    contract_identified: bool
    performance_obligations: list[str]
    transaction_price: Decimal
    allocated_price: dict[str, Decimal]
    performance_satisfied: bool
    satisfaction_date: datetime | None
    evidence_of_satisfaction: list[str]
    recognition_model: RevenueRecognitionModel = RevenueRecognitionModel.AT_A_POINT_IN_TIME
    progress_percentage: Decimal = Decimal(0)
    cryptographic_hash: str = ""

    def __post_init__(self) -> None:
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Hash mismatch")

    def compute_hash(self) -> str:
        content = f"{self.contract_identified}|{self.performance_satisfied}|{self.transaction_price}|{self.recognition_model.value}|{self.progress_percentage}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def is_ready_for_recognition(self) -> bool:
        return (
            self.contract_identified
            and self.performance_satisfied
            and len(self.evidence_of_satisfaction) > 0
        )

    def get_recognizable_amount(self) -> Decimal:
        if not self.is_ready_for_recognition():
            return Decimal(0)
        if self.recognition_model == RevenueRecognitionModel.OVER_TIME:
            return self.transaction_price * self.progress_percentage / Decimal(100)
        return self.transaction_price


@dataclass(frozen=True, kw_only=True)
class ExpenseRecognitionCriteria:
    economic_benefit_consumed: bool
    liability_incurred: bool
    recognition_date: datetime
    supporting_document: str
    matching_revenue_id: UUID | None = None
    matching_method: ExpenseMatchingMethod = ExpenseMatchingMethod.IMMEDIATE_RECOGNITION
    is_allocated: bool = False
    allocation_method: str | None = None
    allocation_periods: int = 1
    cryptographic_hash: str = ""

    def __post_init__(self) -> None:
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Hash mismatch")

    def compute_hash(self) -> str:
        content = f"{self.economic_benefit_consumed}|{self.liability_incurred}|{self.recognition_date.isoformat()}|{self.matching_method.value}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def is_ready_for_recognition(self) -> bool:
        return self.economic_benefit_consumed or self.liability_incurred


# ==================== ENTITY: ACCRUAL ENTRY ====================


@dataclass(kw_only=True)
class AccrualEntry:
    accrual_id: UUID
    accrual_type: AccrualType
    amount: Decimal
    currency: str
    recognition_date: datetime
    reversal_date: datetime | None
    journal_entry_id: UUID | None
    description: str
    created_by: str
    created_at: datetime
    approved_by: list[str]
    reversed: bool = False
    reversed_at: datetime | None = None
    reversed_by: str | None = None
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.amount <= 0:
            raise ValueError("Amount must be positive")
        if not self.approved_by:
            raise ValueError("At least one approver required")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.accrual_id}|{self.accrual_type.value}|{self.amount}|{self.recognition_date.isoformat()}|{self.reversal_date.isoformat() if self.reversal_date else ''}|{self.reversed}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "accrual_id": str(self.accrual_id),
                "amount": str(self.amount),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "accrual_id": str(self.accrual_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> AccrualEntry:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> AccrualEntry:
        if self.reversed:
            raise ValueError("Cannot update reversed accrual")
        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in (
                "accrual_id",
                "created_at",
                "created_by",
                "version",
            ):
                data[key] = value
        new_entry = AccrualEntry.from_dict(data)
        new_entry.version = self.version + 1
        new_entry._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_entry

    def delete(self, deleted_by: str, reason: str | None = None) -> AccrualEntry:
        if self.reversed:
            raise ValueError("Cannot delete reversed accrual")
        new_entry = self._copy()
        new_entry.deleted_at = datetime.now(UTC)
        new_entry.deleted_by = deleted_by
        new_entry.version = self.version + 1
        new_entry._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_entry

    def restore(self, restored_by: str) -> AccrualEntry:
        if self.deleted_at is None:
            raise ValueError("Accrual not deleted")
        new_entry = self._copy()
        new_entry.deleted_at = None
        new_entry.deleted_by = None
        new_entry.version = self.version + 1
        new_entry._record_audit("RESTORE", restored_by, {})
        return new_entry

    def activate(self, activated_by: str) -> AccrualEntry:
        # No active/inactive state for accrual
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AccrualEntry:
        return self

    def lock(self, locked_by: str, reason: str) -> AccrualEntry:
        return self

    def unlock(self, unlocked_by: str) -> AccrualEntry:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "accrual_id": str(self.accrual_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "accrual_id": str(self.accrual_id),
            "accrual_type": self.accrual_type.name,
            "amount": str(self.amount),
            "currency": self.currency,
            "recognition_date": self.recognition_date.isoformat(),
            "reversal_date": self.reversal_date.isoformat() if self.reversal_date else None,
            "journal_entry_id": str(self.journal_entry_id) if self.journal_entry_id else None,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "approved_by": self.approved_by,
            "reversed": self.reversed,
            "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
            "reversed_by": self.reversed_by,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccrualEntry:
        return cls(
            accrual_id=UUID(data["accrual_id"]),
            accrual_type=AccrualType[data["accrual_type"]],
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            recognition_date=datetime.fromisoformat(data["recognition_date"]),
            reversal_date=datetime.fromisoformat(data["reversal_date"])
            if data.get("reversal_date")
            else None,
            journal_entry_id=UUID(data["journal_entry_id"])
            if data.get("journal_entry_id")
            else None,
            description=data["description"],
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            approved_by=data["approved_by"],
            reversed=data["reversed"],
            reversed_at=datetime.fromisoformat(data["reversed_at"])
            if data.get("reversed_at")
            else None,
            reversed_by=data.get("reversed_by"),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> AccrualEntry:
        new_id = uuid4()
        cloned = self._copy()
        object.__setattr__(cloned, "accrual_id", new_id)
        cloned.version = 1
        cloned.created_at = datetime.now(UTC)
        cloned.reversed = False
        cloned.reversed_at = None
        cloned.reversed_by = None
        cloned.deleted_at = None
        cloned.deleted_by = None
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.accrual_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "accrual_id": str(self.accrual_id),
            "amount": str(self.amount),
            "reversed": self.reversed,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AccrualEntry:
        new_entry = self._copy()
        new_entry.version = self.version + 1
        new_entry._record_audit("TOUCH", touched_by, {})
        return new_entry

    def get_version(self) -> int:
        return self.version

    def _copy(self) -> AccrualEntry:
        return AccrualEntry(
            accrual_id=self.accrual_id,
            accrual_type=self.accrual_type,
            amount=self.amount,
            currency=self.currency,
            recognition_date=self.recognition_date,
            reversal_date=self.reversal_date,
            journal_entry_id=self.journal_entry_id,
            description=self.description,
            created_by=self.created_by,
            created_at=self.created_at,
            approved_by=self.approved_by.copy(),
            reversed=self.reversed,
            reversed_at=self.reversed_at,
            reversed_by=self.reversed_by,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )

    def mark_reversed(self, reversed_by: str, journal_entry_id: UUID | None = None) -> AccrualEntry:
        if self.reversed:
            raise ValueError("Accrual already reversed")
        new_entry = self._copy()
        new_entry.reversed = True
        new_entry.reversed_at = datetime.now(UTC)
        new_entry.reversed_by = reversed_by
        if journal_entry_id:
            new_entry.journal_entry_id = journal_entry_id
        new_entry.version = self.version + 1
        new_entry._record_audit("REVERSE", reversed_by, {"journal_entry_id": str(journal_entry_id)})
        return new_entry

    def is_active(self, as_of: datetime | None = None) -> bool:
        check = as_of or datetime.now(UTC)
        if self.reversed:
            return False
        if self.reversal_date and check > self.reversal_date:
            return False
        if self.deleted_at:
            return False
        return True


# ==================== ENTITY: ACCRUAL BASIS VIOLATION ====================


@dataclass(kw_only=True)
class AccrualBasisViolation:
    violation_id: UUID
    transaction_id: UUID
    transaction_type: str
    cash_flow_date: datetime
    recognition_date: datetime
    difference_days: int
    amount: Decimal
    severity: AccrualBasisSeverity
    message: str
    detected_at: datetime
    detected_by: str
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    correction_journal_id: UUID | None
    is_auto_corrected: bool
    auto_correction_applied: str | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.detected_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.violation_id}|{self.transaction_id}|{self.difference_days}|{self.severity.value}|{self.is_auto_corrected}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "violation_id": str(self.violation_id),
                "severity": self.severity.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "violation_id": str(self.violation_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> AccrualBasisViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> AccrualBasisViolation:
        raise AttributeError("AccrualBasisViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> AccrualBasisViolation:
        raise AttributeError("AccrualBasisViolation cannot be deleted")

    def restore(self, restored_by: str) -> AccrualBasisViolation:
        raise AttributeError("AccrualBasisViolation cannot be restored")

    def activate(self, activated_by: str) -> AccrualBasisViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AccrualBasisViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> AccrualBasisViolation:
        return self

    def unlock(self, unlocked_by: str) -> AccrualBasisViolation:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "violation_id": str(self.violation_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "transaction_id": str(self.transaction_id),
            "transaction_type": self.transaction_type,
            "cash_flow_date": self.cash_flow_date.isoformat(),
            "recognition_date": self.recognition_date.isoformat(),
            "difference_days": self.difference_days,
            "amount": str(self.amount),
            "severity": self.severity.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "detected_by": self.detected_by,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "correction_journal_id": str(self.correction_journal_id)
            if self.correction_journal_id
            else None,
            "is_auto_corrected": self.is_auto_corrected,
            "auto_correction_applied": self.auto_correction_applied,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccrualBasisViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            transaction_id=UUID(data["transaction_id"]),
            transaction_type=data["transaction_type"],
            cash_flow_date=datetime.fromisoformat(data["cash_flow_date"]),
            recognition_date=datetime.fromisoformat(data["recognition_date"]),
            difference_days=data["difference_days"],
            amount=Decimal(data["amount"]),
            severity=AccrualBasisSeverity[data["severity"]],
            message=data["message"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            detected_by=data["detected_by"],
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            correction_journal_id=UUID(data["correction_journal_id"])
            if data.get("correction_journal_id")
            else None,
            is_auto_corrected=data["is_auto_corrected"],
            auto_correction_applied=data.get("auto_correction_applied"),
            version=data.get("version", 1),
        )

    def clone(self) -> AccrualBasisViolation:
        new_id = uuid4()
        return AccrualBasisViolation(
            violation_id=new_id,
            transaction_id=self.transaction_id,
            transaction_type=self.transaction_type,
            cash_flow_date=self.cash_flow_date,
            recognition_date=self.recognition_date,
            difference_days=self.difference_days,
            amount=self.amount,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=self.is_auto_corrected,
            auto_correction_applied=self.auto_correction_applied,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AccrualBasisViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def get_version(self) -> int:
        return self.version

    def resolve(self, by: str, correction_journal_id: UUID) -> AccrualBasisViolation:
        if self.resolved:
            raise ValueError("Violation already resolved")
        new_violation = self._copy()
        new_violation.resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.correction_journal_id = correction_journal_id
        new_violation.version = self.version + 1
        new_violation._record_audit(
            "RESOLVE", by, {"correction_journal_id": str(correction_journal_id)}
        )
        return new_violation

    def _copy(self) -> AccrualBasisViolation:
        return AccrualBasisViolation(
            violation_id=self.violation_id,
            transaction_id=self.transaction_id,
            transaction_type=self.transaction_type,
            cash_flow_date=self.cash_flow_date,
            recognition_date=self.recognition_date,
            difference_days=self.difference_days,
            amount=self.amount,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            correction_journal_id=self.correction_journal_id,
            is_auto_corrected=self.is_auto_corrected,
            auto_correction_applied=self.auto_correction_applied,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# ==================== VALIDATOR ====================


class AccrualBasisValidator:
    DEFAULT_TOLERANCE_DAYS = 7
    ESTIMATION_TOLERANCE_DAYS = 15

    @classmethod
    def validate_revenue_recognition(
        cls,
        transaction_id: UUID,
        cash_receipt_date: datetime,
        service_delivery_date: datetime,
        contract_criteria: RevenueRecognitionCriteria,
        amount: Decimal,
        tolerance_days: int | None = None,
    ) -> tuple[bool, AccrualBasisViolation | None, str | None]:
        tolerance = tolerance_days or cls.DEFAULT_TOLERANCE_DAYS

        if not contract_criteria.is_ready_for_recognition():
            violation = cls._create_violation(
                transaction_id=transaction_id,
                transaction_type="REVENUE",
                cash_flow_date=cash_receipt_date,
                recognition_date=contract_criteria.satisfaction_date or service_delivery_date,
                amount=amount,
                severity=AccrualBasisSeverity.HIGH,
                message="Revenue recognition criteria not met: performance not satisfied or evidence missing",
                is_auto_corrected=False,
                detected_by="system",
            )
            return False, violation, "Complete performance obligations"

        satisfaction = contract_criteria.satisfaction_date or service_delivery_date
        days_diff = (satisfaction - cash_receipt_date).days
        abs_days = abs(days_diff)

        if abs_days > tolerance:
            severity = cls._determine_severity_by_days(abs_days)
            violation = cls._create_violation(
                transaction_id=transaction_id,
                transaction_type="REVENUE",
                cash_flow_date=cash_receipt_date,
                recognition_date=satisfaction,
                amount=amount,
                severity=severity,
                message=f"Revenue recognition timing mismatch: {abs_days} days difference (tolerance {tolerance})",
                is_auto_corrected=False,
                detected_by="system",
            )
            return False, violation, None

        return True, None, None

    @classmethod
    def validate_expense_recognition(
        cls,
        transaction_id: UUID,
        cash_payment_date: datetime,
        expense_incurred_date: datetime,
        expense_criteria: ExpenseRecognitionCriteria,
        amount: Decimal,
        tolerance_days: int | None = None,
    ) -> tuple[bool, AccrualBasisViolation | None, str | None]:
        tolerance = tolerance_days or cls.DEFAULT_TOLERANCE_DAYS

        if not expense_criteria.is_ready_for_recognition():
            violation = cls._create_violation(
                transaction_id=transaction_id,
                transaction_type="EXPENSE",
                cash_flow_date=cash_payment_date,
                recognition_date=expense_incurred_date,
                amount=amount,
                severity=AccrualBasisSeverity.HIGH,
                message="Expense recognition criteria not met: no economic benefit consumed or liability incurred",
                is_auto_corrected=False,
                detected_by="system",
            )
            return False, violation, "Expense not yet recognized"

        days_diff = (expense_incurred_date - cash_payment_date).days
        abs_days = abs(days_diff)

        if abs_days > tolerance:
            severity = cls._determine_severity_by_days(abs_days)
            violation = cls._create_violation(
                transaction_id=transaction_id,
                transaction_type="EXPENSE",
                cash_flow_date=cash_payment_date,
                recognition_date=expense_incurred_date,
                amount=amount,
                severity=severity,
                message=f"Expense recognition timing mismatch: {abs_days} days difference (tolerance {tolerance})",
                is_auto_corrected=False,
                detected_by="system",
            )
            return False, violation, None

        return True, None, None

    @classmethod
    def _determine_severity_by_days(cls, abs_days: int) -> AccrualBasisSeverity:
        if abs_days > 90:
            return AccrualBasisSeverity.CATASTROPHIC
        elif abs_days > 30:
            return AccrualBasisSeverity.CRITICAL
        elif abs_days > 14:
            return AccrualBasisSeverity.HIGH
        elif abs_days > 7:
            return AccrualBasisSeverity.MEDIUM
        elif abs_days > 1:
            return AccrualBasisSeverity.LOW
        return AccrualBasisSeverity.INFO

    @classmethod
    def _create_violation(
        cls,
        transaction_id: UUID,
        transaction_type: str,
        cash_flow_date: datetime,
        recognition_date: datetime,
        amount: Decimal,
        severity: AccrualBasisSeverity,
        message: str,
        is_auto_corrected: bool,
        detected_by: str,
    ) -> AccrualBasisViolation:
        difference_days = abs((recognition_date - cash_flow_date).days)
        return AccrualBasisViolation(
            violation_id=uuid4(),
            transaction_id=transaction_id,
            transaction_type=transaction_type,
            cash_flow_date=cash_flow_date,
            recognition_date=recognition_date,
            difference_days=difference_days,
            amount=amount,
            severity=severity,
            message=message,
            detected_at=datetime.now(UTC),
            detected_by=detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
            is_auto_corrected=is_auto_corrected,
            auto_correction_applied=None,
            version=1,
        )


# ==================== AXIOM SERVICE (with repository methods) ====================


class AccrualBasisAxiom:
    _instance: AccrualBasisAxiom | None = None
    _validator = AccrualBasisValidator
    _accruals: dict[UUID, AccrualEntry] = {}
    _violations: list[AccrualBasisViolation] = []
    _revenue_criteria_cache: dict[UUID, RevenueRecognitionCriteria] = {}
    _expense_criteria_cache: dict[UUID, ExpenseRecognitionCriteria] = {}
    _lock = threading.Lock()

    def __new__(cls) -> AccrualBasisAxiom:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._accruals = {}
        self._violations = []
        self._revenue_criteria_cache = {}
        self._expense_criteria_cache = {}

    # ==================== REPOSITORY METHODS ====================
    def save_accrual(self, accrual: AccrualEntry) -> None:
        with self._lock:
            self._accruals[accrual.accrual_id] = accrual
            logger.debug(f"Accrual saved: {accrual.accrual_id}")

    def get_accrual(self, accrual_id: UUID) -> AccrualEntry | None:
        return self._accruals.get(accrual_id)

    def get_all_accruals(self) -> list[AccrualEntry]:
        return list(self._accruals.values())

    def delete_accrual(self, accrual_id: UUID) -> bool:
        with self._lock:
            if accrual_id in self._accruals:
                del self._accruals[accrual_id]
                logger.info(f"Accrual deleted: {accrual_id}")
                return True
            return False

    def save_violation(self, violation: AccrualBasisViolation) -> None:
        with self._lock:
            self._violations.append(violation)
            logger.warning(f"Violation saved: {violation.violation_id} - {violation.message}")

    def get_violations(
        self,
        limit: int = 100,
        min_severity: AccrualBasisSeverity | None = None,
        unresolved_only: bool = False,
    ) -> list[AccrualBasisViolation]:
        result = self._violations[-limit:]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, correction_journal_id: UUID
    ) -> AccrualBasisViolation | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.resolved:
                    resolved = v.resolve(resolved_by, correction_journal_id)
                    self._violations[i] = resolved
                    logger.info(f"Violation resolved: {violation_id} by {resolved_by}")
                    return resolved
        return None

    # ==================== BUSINESS METHODS ====================
    def enforce_revenue_recognition(
        self,
        transaction_id: UUID,
        cash_receipt_date: datetime,
        service_delivery_date: datetime,
        contract_criteria: RevenueRecognitionCriteria,
        amount: Decimal,
        tolerance_days: int | None = None,
    ) -> tuple[bool, AccrualBasisViolation | None, str | None]:
        """
        Enforce accrual basis for revenue: revenue recognized when earned, not when cash received.
        Returns (is_compliant, violation_if_any, message)
        """
        logger.debug(f"Enforcing revenue recognition for tx {transaction_id}")
        return self._validator.validate_revenue_recognition(
            transaction_id,
            cash_receipt_date,
            service_delivery_date,
            contract_criteria,
            amount,
            tolerance_days,
        )

    def enforce_expense_recognition(
        self,
        transaction_id: UUID,
        cash_payment_date: datetime,
        expense_incurred_date: datetime,
        expense_criteria: ExpenseRecognitionCriteria,
        amount: Decimal,
        tolerance_days: int | None = None,
    ) -> tuple[bool, AccrualBasisViolation | None, str | None]:
        """
        Enforce accrual basis for expense: expense recognized when incurred, not when paid.
        """
        logger.debug(f"Enforcing expense recognition for tx {transaction_id}")
        return self._validator.validate_expense_recognition(
            transaction_id,
            cash_payment_date,
            expense_incurred_date,
            expense_criteria,
            amount,
            tolerance_days,
        )

    def create_accrual(
        self,
        accrual_type: AccrualType,
        amount: Decimal,
        currency: str,
        recognition_date: datetime,
        reversal_date: datetime | None,
        description: str,
        created_by: str,
        approved_by: list[str],
        journal_entry_id: UUID | None = None,
    ) -> AccrualEntry:
        """Create a new accrual entry."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if not approved_by:
            raise ValueError("At least one approver required")

        accrual = AccrualEntry(
            accrual_id=uuid4(),
            accrual_type=accrual_type,
            amount=amount,
            currency=currency,
            recognition_date=recognition_date,
            reversal_date=reversal_date,
            journal_entry_id=journal_entry_id,
            description=description,
            created_by=created_by,
            created_at=datetime.now(UTC),
            approved_by=approved_by,
            version=1,
        )
        self.save_accrual(accrual)
        logger.info(
            f"Accrual created: {accrual.accrual_id} type={accrual_type.name} amount={amount}"
        )
        return accrual

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about accruals and violations."""
        with self._lock:
            total_accruals = len(self._accruals)
            active_accruals = sum(1 for a in self._accruals.values() if a.is_active())
            total_violations = len(self._violations)
            unresolved_violations = sum(1 for v in self._violations if not v.resolved)
            return {
                "total_accruals": total_accruals,
                "active_accruals": active_accruals,
                "total_violations": total_violations,
                "unresolved_violations": unresolved_violations,
                "severity_breakdown": {
                    severity.name: sum(1 for v in self._violations if v.severity == severity)
                    for severity in AccrualBasisSeverity
                },
            }

    def reset(self) -> None:
        """Reset all in-memory state (for testing only)."""
        with self._lock:
            self._accruals.clear()
            self._violations.clear()
            self._revenue_criteria_cache.clear()
            self._expense_criteria_cache.clear()
            logger.warning("AccrualBasisAxiom reset")


# ==================== SINGLETON ACCESS ====================

_accrual_basis_axiom_instance: AccrualBasisAxiom | None = None


def get_accrual_basis_axiom() -> AccrualBasisAxiom:
    global _accrual_basis_axiom_instance
    if _accrual_basis_axiom_instance is None:
        _accrual_basis_axiom_instance = AccrualBasisAxiom()
    return _accrual_basis_axiom_instance


# ==================== CONVENIENCE FUNCTIONS (for backwards compatibility) ====================


def create_revenue_criteria(
    contract_identified: bool,
    performance_obligations: list[str],
    transaction_price: Decimal,
    allocated_price: dict[str, Decimal],
    performance_satisfied: bool,
    satisfaction_date: datetime | None,
    evidence_of_satisfaction: list[str],
    recognition_model: RevenueRecognitionModel = RevenueRecognitionModel.AT_A_POINT_IN_TIME,
    progress_percentage: Decimal = Decimal(0),
) -> RevenueRecognitionCriteria:
    """Factory function to create a RevenueRecognitionCriteria instance."""
    return RevenueRecognitionCriteria(
        contract_identified=contract_identified,
        performance_obligations=performance_obligations,
        transaction_price=transaction_price,
        allocated_price=allocated_price,
        performance_satisfied=performance_satisfied,
        satisfaction_date=satisfaction_date,
        evidence_of_satisfaction=evidence_of_satisfaction,
        recognition_model=recognition_model,
        progress_percentage=progress_percentage,
    )


def create_expense_criteria(
    economic_benefit_consumed: bool,
    liability_incurred: bool,
    recognition_date: datetime,
    supporting_document: str,
    matching_revenue_id: UUID | None = None,
    matching_method: ExpenseMatchingMethod = ExpenseMatchingMethod.IMMEDIATE_RECOGNITION,
    is_allocated: bool = False,
    allocation_method: str | None = None,
    allocation_periods: int = 1,
) -> ExpenseRecognitionCriteria:
    """Factory function to create an ExpenseRecognitionCriteria instance."""
    return ExpenseRecognitionCriteria(
        economic_benefit_consumed=economic_benefit_consumed,
        liability_incurred=liability_incurred,
        recognition_date=recognition_date,
        supporting_document=supporting_document,
        matching_revenue_id=matching_revenue_id,
        matching_method=matching_method,
        is_allocated=is_allocated,
        allocation_method=allocation_method,
        allocation_periods=allocation_periods,
    )


def enforce_revenue_recognition(
    transaction_id: UUID,
    cash_receipt_date: datetime,
    service_delivery_date: datetime,
    contract_criteria: RevenueRecognitionCriteria,
    amount: Decimal,
    tolerance_days: int | None = None,
) -> tuple[bool, AccrualBasisViolation | None, str | None]:
    """Convenience function to enforce revenue recognition using the axiom singleton."""
    return get_accrual_basis_axiom().enforce_revenue_recognition(
        transaction_id,
        cash_receipt_date,
        service_delivery_date,
        contract_criteria,
        amount,
        tolerance_days,
    )


def enforce_expense_recognition(
    transaction_id: UUID,
    cash_payment_date: datetime,
    expense_incurred_date: datetime,
    expense_criteria: ExpenseRecognitionCriteria,
    amount: Decimal,
    tolerance_days: int | None = None,
) -> tuple[bool, AccrualBasisViolation | None, str | None]:
    """Convenience function to enforce expense recognition using the axiom singleton."""
    return get_accrual_basis_axiom().enforce_expense_recognition(
        transaction_id,
        cash_payment_date,
        expense_incurred_date,
        expense_criteria,
        amount,
        tolerance_days,
    )


def create_accrual(
    accrual_type: AccrualType,
    amount: Decimal,
    currency: str,
    recognition_date: datetime,
    reversal_date: datetime | None,
    description: str,
    created_by: str,
    approved_by: list[str],
    journal_entry_id: UUID | None = None,
) -> AccrualEntry:
    """Convenience function to create an accrual using the axiom singleton."""
    return get_accrual_basis_axiom().create_accrual(
        accrual_type,
        amount,
        currency,
        recognition_date,
        reversal_date,
        description,
        created_by,
        approved_by,
        journal_entry_id,
    )


def get_statistics() -> dict[str, Any]:
    """Get statistics from the axiom singleton."""
    return get_accrual_basis_axiom().get_statistics()


def reset() -> None:
    """Reset the axiom singleton state (for testing)."""
    get_accrual_basis_axiom().reset()


__all__ = [
    "AccrualBasisAxiom",
    "AccrualBasisSeverity",
    "AccrualBasisValidator",
    "AccrualBasisViolation",
    "AccrualBasisViolationError",
    "AccrualEntry",
    "AccrualType",
    "ExpenseRecognitionCriteria",
    "InvalidExpenseCriteriaError",
    "InvalidRevenueCriteriaError",
    "RevenueRecognitionCriteria",
    "create_accrual",
    "create_expense_criteria",
    "create_revenue_criteria",
    "enforce_expense_recognition",
    "enforce_revenue_recognition",
    "get_accrual_basis_axiom",
    "get_statistics",
    "reset",
]