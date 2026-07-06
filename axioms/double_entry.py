#!/usr/bin/env python3
"""
Module: double_entry.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: setiap transaksi harus seimbang (debit = kredit).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, getcontext
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

getcontext().prec = 28


# === 1. ENUMS ===


class Side(Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalType(Enum):
    GENERAL = auto()
    ADJUSTING = auto()
    CLOSING = auto()
    REVERSAL = auto()
    CORRECTION = auto()
    INTERCOMPANY = auto()
    CONSOLIDATION = auto()
    BUDGET = auto()
    STATISTICAL = auto()


class JournalStatus(Enum):
    DRAFT = auto()
    SUBMITTED = auto()
    APPROVED = auto()
    POSTED = auto()
    REVERSED = auto()
    VOID = auto()
    REJECTED = auto()


class DoubleEntryViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


# === 2. EXCEPTIONS ===


class DoubleEntryViolationError(Exception):
    def __init__(
        self,
        message: str,
        total_debit: Decimal,
        total_credit: Decimal,
        difference: Decimal,
        journal_id: UUID | None = None,
        severity: DoubleEntryViolationSeverity = DoubleEntryViolationSeverity.CRITICAL,
    ):
        self.total_debit = total_debit
        self.total_credit = total_credit
        self.difference = difference
        self.journal_id = journal_id
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | Debit: {total_debit}, Credit: {total_credit}, Diff: {difference}"
        )


class InvalidJournalEntryError(Exception):
    pass


# === 3. VALUE OBJECTS ===


@dataclass(kw_only=True)
class JournalLine:
    line_id: UUID
    journal_id: UUID
    account_code: str
    side: Side
    amount: Decimal
    currency: str
    description: str
    legal_entity_id: UUID
    cost_center: str | None = None
    department: str | None = None
    project_id: UUID | None = None
    reference: str | None = None
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
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if self.amount <= 0:
            raise InvalidJournalEntryError(f"Amount must be positive: {self.amount}")
        if not self.account_code:
            raise InvalidJournalEntryError("Account code required")
        if len(self.currency) != 3:
            raise InvalidJournalEntryError(f"Invalid currency: {self.currency}")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.line_id}|{self.journal_id}|{self.account_code}|{self.side.value}|{self.amount}|{self.currency}|{self.legal_entity_id}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "line_id": str(self.line_id),
                "amount": str(self.amount),
                "side": self.side.value,
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
                "line_id": str(self.line_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> JournalLine:
        return self

    def update(self, updated_by: str, **kwargs) -> JournalLine:
        new_line = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_line, key) and key not in ("line_id", "journal_id", "version"):
                setattr(new_line, key, value)
        new_line.version = self.version + 1
        new_line._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_line

    def delete(self, deleted_by: str, reason: str | None = None) -> JournalLine:
        new_line = self._copy()
        new_line.deleted_at = datetime.now(UTC)
        new_line.deleted_by = deleted_by
        new_line.version = self.version + 1
        new_line._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_line

    def restore(self, restored_by: str) -> JournalLine:
        if self.deleted_at is None:
            raise ValueError("Line not deleted")
        new_line = self._copy()
        new_line.deleted_at = None
        new_line.deleted_by = None
        new_line.version = self.version + 1
        new_line._record_audit("RESTORE", restored_by, {})
        return new_line

    def activate(self, activated_by: str) -> JournalLine:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> JournalLine:
        return self

    def lock(self, locked_by: str, reason: str) -> JournalLine:
        return self

    def unlock(self, unlocked_by: str) -> JournalLine:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except (ValueError, InvalidJournalEntryError) as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "line_id": str(self.line_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": str(self.line_id),
            "journal_id": str(self.journal_id),
            "account_code": self.account_code,
            "side": self.side.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "description": self.description,
            "legal_entity_id": str(self.legal_entity_id),
            "cost_center": self.cost_center,
            "department": self.department,
            "project_id": str(self.project_id) if self.project_id else None,
            "reference": self.reference,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalLine:
        return cls(
            line_id=UUID(data["line_id"]),
            journal_id=UUID(data["journal_id"]),
            account_code=data["account_code"],
            side=Side(data["side"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            description=data["description"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            cost_center=data.get("cost_center"),
            department=data.get("department"),
            project_id=UUID(data["project_id"]) if data.get("project_id") else None,
            reference=data.get("reference"),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> JournalLine:
        new_id = uuid4()
        return JournalLine(
            line_id=new_id,
            journal_id=self.journal_id,
            account_code=self.account_code,
            side=self.side,
            amount=self.amount,
            currency=self.currency,
            description=self.description,
            legal_entity_id=self.legal_entity_id,
            cost_center=self.cost_center,
            department=self.department,
            project_id=self.project_id,
            reference=self.reference,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "line_id": str(self.line_id),
            "amount": str(self.amount),
            "side": self.side.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> JournalLine:
        new_line = self._copy()
        new_line.version = self.version + 1
        new_line._record_audit("TOUCH", touched_by, {})
        return new_line

    def _copy(self) -> JournalLine:
        return JournalLine(
            line_id=self.line_id,
            journal_id=self.journal_id,
            account_code=self.account_code,
            side=self.side,
            amount=self.amount,
            currency=self.currency,
            description=self.description,
            legal_entity_id=self.legal_entity_id,
            cost_center=self.cost_center,
            department=self.department,
            project_id=self.project_id,
            reference=self.reference,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class JournalEntry:
    journal_id: UUID
    journal_number: str
    journal_type: JournalType
    transaction_date: datetime
    posting_date: datetime | None
    description: str
    lines: list[JournalLine]
    created_by: str
    created_at: datetime
    approved_by: list[str]
    status: JournalStatus
    reference_id: UUID | None = None
    reversal_of: UUID | None = None
    reversal_journal_id: UUID | None = None
    version: int = 1
    cryptographic_hash: str = ""
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
        if not self.lines:
            raise InvalidJournalEntryError("Journal must have at least one line")
        for line in self.lines:
            if line.journal_id != self.journal_id:
                raise InvalidJournalEntryError(f"Line {line.line_id} has mismatched journal_id")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        lines_hash = hashlib.sha3_256(
            "".join(str(l.line_id) for l in self.lines).encode()
        ).hexdigest()
        content = f"{self.journal_id}|{self.journal_number}|{self.journal_type.value}|{self.transaction_date.isoformat()}|{self.total_debit}|{self.total_credit}|{self.difference}|{self.status.value}|{self.version}|{lines_hash}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "journal_id": str(self.journal_id),
                "journal_number": self.journal_number,
                "status": self.status.name,
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
                "journal_id": str(self.journal_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> JournalEntry:
        return self

    def update(self, updated_by: str, **kwargs) -> JournalEntry:
        if not self.is_mutable():
            raise ValueError(f"Cannot update journal with status {self.status.name}")
        new_journal = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_journal, key) and key not in (
                "journal_id",
                "created_at",
                "created_by",
                "version",
            ):
                setattr(new_journal, key, value)
        new_journal.version = self.version + 1
        new_journal._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_journal

    def delete(self, deleted_by: str, reason: str | None = None) -> JournalEntry:
        if not self.is_mutable():
            raise ValueError(f"Cannot delete journal with status {self.status.name}")
        new_journal = self._copy()
        new_journal.deleted_at = datetime.now(UTC)
        new_journal.deleted_by = deleted_by
        new_journal.version = self.version + 1
        new_journal._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_journal

    def restore(self, restored_by: str) -> JournalEntry:
        if self.deleted_at is None:
            raise ValueError("Journal not deleted")
        new_journal = self._copy()
        new_journal.deleted_at = None
        new_journal.deleted_by = None
        new_journal.version = self.version + 1
        new_journal._record_audit("RESTORE", restored_by, {})
        return new_journal

    def activate(self, activated_by: str) -> JournalEntry:
        if self.status != JournalStatus.DRAFT:
            raise ValueError(f"Cannot activate journal with status {self.status.name}")
        new_journal = self._copy()
        new_journal.status = JournalStatus.SUBMITTED
        new_journal.version = self.version + 1
        new_journal._record_audit("ACTIVATE", activated_by, {})
        return new_journal

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> JournalEntry:
        if self.status != JournalStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate journal with status {self.status.name}")
        new_journal = self._copy()
        new_journal.status = JournalStatus.DRAFT
        new_journal.version = self.version + 1
        new_journal._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_journal

    def lock(self, locked_by: str, reason: str) -> JournalEntry:
        # No lock state for journal, just add to metadata
        return self

    def unlock(self, unlocked_by: str) -> JournalEntry:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
            if abs(self.difference) > Decimal("0.0001"):
                errors.append(f"Journal not balanced: diff={self.difference}")
        except (ValueError, InvalidJournalEntryError) as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "journal_id": str(self.journal_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "journal_type": self.journal_type.name,
            "transaction_date": self.transaction_date.isoformat(),
            "posting_date": self.posting_date.isoformat() if self.posting_date else None,
            "description": self.description,
            "lines": [l.to_dict() for l in self.lines],
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "approved_by": self.approved_by,
            "status": self.status.name,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "reversal_of": str(self.reversal_of) if self.reversal_of else None,
            "reversal_journal_id": str(self.reversal_journal_id)
            if self.reversal_journal_id
            else None,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalEntry:
        return cls(
            journal_id=UUID(data["journal_id"]),
            journal_number=data["journal_number"],
            journal_type=JournalType[data["journal_type"]],
            transaction_date=datetime.fromisoformat(data["transaction_date"]),
            posting_date=datetime.fromisoformat(data["posting_date"])
            if data.get("posting_date")
            else None,
            description=data["description"],
            lines=[JournalLine.from_dict(l) for l in data.get("lines", [])],
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            approved_by=data.get("approved_by", []),
            status=JournalStatus[data["status"]],
            reference_id=UUID(data["reference_id"]) if data.get("reference_id") else None,
            reversal_of=UUID(data["reversal_of"]) if data.get("reversal_of") else None,
            reversal_journal_id=UUID(data["reversal_journal_id"])
            if data.get("reversal_journal_id")
            else None,
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> JournalEntry:
        new_id = uuid4()
        return JournalEntry(
            journal_id=new_id,
            journal_number=f"{self.journal_number}_COPY",
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=None,
            description=f"Copy of {self.journal_number}: {self.description}",
            lines=[l.clone() for l in self.lines],
            created_by=self.created_by,
            created_at=datetime.now(UTC),
            approved_by=[],
            status=JournalStatus.DRAFT,
            reference_id=self.reference_id,
            reversal_of=self.reversal_of,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> JournalEntry:
        new_journal = self._copy()
        new_journal.version = self.version + 1
        new_journal._record_audit("TOUCH", touched_by, {})
        return new_journal

    @property
    def total_debit(self) -> Decimal:
        return sum(line.amount for line in self.lines if line.side == Side.DEBIT)

    @property
    def total_credit(self) -> Decimal:
        return sum(line.amount for line in self.lines if line.side == Side.CREDIT)

    @property
    def difference(self) -> Decimal:
        return self.total_debit - self.total_credit

    def is_balanced(self, tolerance: Decimal = Decimal("0.0001")) -> bool:
        return abs(self.difference) <= tolerance

    def is_posted(self) -> bool:
        return self.status == JournalStatus.POSTED

    def is_mutable(self) -> bool:
        return self.status in (JournalStatus.DRAFT, JournalStatus.SUBMITTED)

    def _copy(self) -> JournalEntry:
        return JournalEntry(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines.copy(),
            created_by=self.created_by,
            created_at=self.created_at,
            approved_by=self.approved_by.copy(),
            status=self.status,
            reference_id=self.reference_id,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class DoubleEntryVerificationRecord:
    record_id: UUID
    journal_id: UUID
    verified_at: datetime
    verified_by: str
    is_balanced: bool
    total_debit: Decimal
    total_credit: Decimal
    difference: Decimal
    tolerance: Decimal
    severity: DoubleEntryViolationSeverity
    violation_message: str | None
    journal_type: str
    auto_corrected: bool
    auto_correction_applied: str | None
    cryptographic_hash: str
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.verified_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        # Skip hash validation during initial construction (hash="" means not yet computed)
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Hash mismatch")

    def compute_hash(self) -> str:
        content = f"{self.record_id}|{self.journal_id}|{self.verified_at.isoformat()}|{self.is_balanced}|{self.total_debit}|{self.total_credit}|{self.difference}|{self.tolerance}|{self.journal_type}|{self.auto_corrected}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "record_id": str(self.record_id),
                "is_balanced": self.is_balanced,
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
                "record_id": str(self.record_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> DoubleEntryVerificationRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> DoubleEntryVerificationRecord:
        raise AttributeError("DoubleEntryVerificationRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> DoubleEntryVerificationRecord:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> DoubleEntryVerificationRecord:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> DoubleEntryVerificationRecord:
        return self

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> DoubleEntryVerificationRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> DoubleEntryVerificationRecord:
        return self

    def unlock(self, unlocked_by: str) -> DoubleEntryVerificationRecord:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "record_id": str(self.record_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "journal_id": str(self.journal_id),
            "verified_at": self.verified_at.isoformat(),
            "verified_by": self.verified_by,
            "is_balanced": self.is_balanced,
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
            "difference": str(self.difference),
            "tolerance": str(self.tolerance),
            "severity": self.severity.name,
            "violation_message": self.violation_message,
            "journal_type": self.journal_type,
            "auto_corrected": self.auto_corrected,
            "auto_correction_applied": self.auto_correction_applied,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DoubleEntryVerificationRecord:
        return cls(
            record_id=UUID(data["record_id"]),
            journal_id=UUID(data["journal_id"]),
            verified_at=datetime.fromisoformat(data["verified_at"]),
            verified_by=data["verified_by"],
            is_balanced=data["is_balanced"],
            total_debit=Decimal(data["total_debit"]),
            total_credit=Decimal(data["total_credit"]),
            difference=Decimal(data["difference"]),
            tolerance=Decimal(data["tolerance"]),
            severity=DoubleEntryViolationSeverity[data["severity"]],
            violation_message=data.get("violation_message"),
            journal_type=data["journal_type"],
            auto_corrected=data["auto_corrected"],
            auto_correction_applied=data.get("auto_correction_applied"),
            cryptographic_hash=data["cryptographic_hash"],
            version=data.get("version", 1),
        )

    def clone(self) -> DoubleEntryVerificationRecord:
        new_id = uuid4()
        return DoubleEntryVerificationRecord(
            record_id=new_id,
            journal_id=self.journal_id,
            verified_at=self.verified_at,
            verified_by=self.verified_by,
            is_balanced=self.is_balanced,
            total_debit=self.total_debit,
            total_credit=self.total_credit,
            difference=self.difference,
            tolerance=self.tolerance,
            severity=self.severity,
            violation_message=self.violation_message,
            journal_type=self.journal_type,
            auto_corrected=self.auto_corrected,
            auto_correction_applied=self.auto_correction_applied,
            cryptographic_hash="",
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "record_id": str(self.record_id),
            "is_balanced": self.is_balanced,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DoubleEntryVerificationRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. DOUBLE ENTRY AXIOM SERVICE (dengan repository methods) ===


class DoubleEntryAxiom:
    _instance: DoubleEntryAxiom | None = None
    _journals: dict[UUID, JournalEntry] = {}
    _verification_history: list[DoubleEntryVerificationRecord] = []
    _violation_history: list[DoubleEntryVerificationRecord] = []
    _journal_sequence: dict[str, int] = {}
    _lock = threading.Lock()

    def __new__(cls) -> DoubleEntryAxiom:
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
        self._journals = {}
        self._verification_history = []
        self._violation_history = []
        self._journal_sequence = {}

    # ==================== REPOSITORY METHODS ====================
    def save_journal(self, journal: JournalEntry) -> None:
        with self._lock:
            self._journals[journal.journal_id] = journal

    def get_journal(self, journal_id: UUID) -> JournalEntry | None:
        return self._journals.get(journal_id)

    def get_all_journals(self) -> list[JournalEntry]:
        return list(self._journals.values())

    def delete_journal(self, journal_id: UUID) -> bool:
        with self._lock:
            if journal_id in self._journals:
                del self._journals[journal_id]
                return True
            return False

    def save_verification(self, record: DoubleEntryVerificationRecord) -> None:
        with self._lock:
            self._verification_history.append(record)
            if not record.is_balanced:
                self._violation_history.append(record)

    def get_verifications(
        self, journal_id: UUID | None = None, limit: int = 100
    ) -> list[DoubleEntryVerificationRecord]:
        result = self._verification_history[-limit:]
        if journal_id:
            result = [r for r in result if r.journal_id == journal_id]
        return result

    def get_violations(
        self,
        limit: int = 100,
        min_severity: DoubleEntryViolationSeverity | None = None,
        journal_id: UUID | None = None,
    ) -> list[DoubleEntryVerificationRecord]:
        result = self._violation_history[-limit:]
        if min_severity:
            result = [r for r in result if r.severity.value >= min_severity.value]
        if journal_id:
            result = [r for r in result if r.journal_id == journal_id]
        return result

    # ==================== BUSINESS METHODS ====================
    def generate_journal_number(self, prefix: str = "JRN") -> str:
        with self._lock:
            if prefix not in self._journal_sequence:
                self._journal_sequence[prefix] = 0
            self._journal_sequence[prefix] += 1
            seq = self._journal_sequence[prefix]
            year = datetime.now(UTC).year
            month = datetime.now(UTC).month
            return f"{prefix}-{year}{month:02d}-{seq:06d}"

    def create_journal(
        self,
        journal_type: JournalType,
        transaction_date: datetime,
        description: str,
        lines: list[JournalLine],
        created_by: str,
        approved_by: list[str] | None = None,
        journal_number: str | None = None,
        reference_id: UUID | None = None,
        reversal_of: UUID | None = None,
    ) -> JournalEntry:
        if not lines:
            raise InvalidJournalEntryError("Journal must have at least one line")
        journal_number = journal_number or self.generate_journal_number()
        journal_id = uuid4()
        lines_with_id = []
        for line in lines:
            line_with_id = JournalLine(
                line_id=line.line_id,
                journal_id=journal_id,
                account_code=line.account_code,
                side=line.side,
                amount=line.amount,
                currency=line.currency,
                description=line.description,
                legal_entity_id=line.legal_entity_id,
                cost_center=line.cost_center,
                department=line.department,
                project_id=line.project_id,
                reference=line.reference,
            )
            lines_with_id.append(line_with_id)
        journal = JournalEntry(
            journal_id=journal_id,
            journal_number=journal_number,
            journal_type=journal_type,
            transaction_date=transaction_date,
            posting_date=None,
            description=description,
            lines=lines_with_id,
            created_by=created_by,
            created_at=datetime.now(UTC),
            approved_by=approved_by or [],
            status=JournalStatus.DRAFT,
            reference_id=reference_id,
            reversal_of=reversal_of,
        )
        with self._lock:
            self._journals[journal.journal_id] = journal
        return journal

    def submit_journal(self, journal_id: UUID, submitted_by: str) -> JournalEntry | None:
        with self._lock:
            journal = self._journals.get(journal_id)
            if not journal or journal.status != JournalStatus.DRAFT:
                return None
            updated = journal.update(submitted_by, status=JournalStatus.SUBMITTED)
            self._journals[journal_id] = updated
            return updated

    def approve_journal(self, journal_id: UUID, approved_by: str) -> JournalEntry | None:
        with self._lock:
            journal = self._journals.get(journal_id)
            if not journal or journal.status != JournalStatus.SUBMITTED:
                return None
            new_approvers = journal.approved_by + [approved_by]
            updated = journal.update(
                approved_by, status=JournalStatus.APPROVED, approved_by=new_approvers
            )
            self._journals[journal_id] = updated
            return updated

    def enforce(
        self,
        journal: JournalEntry,
        tolerance: Decimal | None = None,
        auto_correct: bool = True,
        raise_on_violation: bool = True,
    ) -> tuple[bool, DoubleEntryVerificationRecord | None]:
        tolerance = tolerance or Decimal("0.0001")
        is_balanced = journal.is_balanced(tolerance)
        diff = journal.difference
        severity = (
            DoubleEntryViolationSeverity.INFO
            if is_balanced
            else self._determine_severity(
                diff, journal.total_debit, journal.total_credit, tolerance
            )
        )
        record = DoubleEntryVerificationRecord(
            record_id=uuid4(),
            journal_id=journal.journal_id,
            verified_at=datetime.now(UTC),
            verified_by="double_entry_axiom",
            is_balanced=is_balanced,
            total_debit=journal.total_debit,
            total_credit=journal.total_credit,
            difference=diff,
            tolerance=tolerance,
            severity=severity,
            violation_message=None if is_balanced else f"Journal not balanced: diff={diff}",
            journal_type=journal.journal_type.name,
            auto_corrected=False,
            auto_correction_applied=None,
            cryptographic_hash="",
        )
        record = DoubleEntryVerificationRecord(
            record_id=record.record_id,
            journal_id=record.journal_id,
            verified_at=record.verified_at,
            verified_by=record.verified_by,
            is_balanced=record.is_balanced,
            total_debit=record.total_debit,
            total_credit=record.total_credit,
            difference=record.difference,
            tolerance=record.tolerance,
            severity=record.severity,
            violation_message=record.violation_message,
            journal_type=record.journal_type,
            auto_corrected=record.auto_corrected,
            auto_correction_applied=record.auto_correction_applied,
            cryptographic_hash=record.compute_hash(),
        )
        with self._lock:
            self._verification_history.append(record)
            if not is_balanced:
                self._violation_history.append(record)
        if (
            not is_balanced
            and raise_on_violation
            and severity.value >= DoubleEntryViolationSeverity.HIGH.value
        ):
            raise DoubleEntryViolationError(
                message=record.violation_message or "Double entry violation",
                total_debit=record.total_debit,
                total_credit=record.total_credit,
                difference=record.difference,
                journal_id=journal.journal_id,
                severity=severity,
            )
        return is_balanced, record

    def _determine_severity(
        self, difference: Decimal, total_debit: Decimal, total_credit: Decimal, tolerance: Decimal
    ) -> DoubleEntryViolationSeverity:
        abs_diff = abs(difference)
        max_total = max(total_debit, total_credit)
        if max_total > 0:
            ratio = abs_diff / max_total
        else:
            ratio = Decimal("0")
        if ratio > Decimal("0.01"):
            return DoubleEntryViolationSeverity.CATASTROPHIC
        elif ratio > Decimal("0.001"):
            return DoubleEntryViolationSeverity.CRITICAL
        elif ratio > Decimal("0.0001"):
            return DoubleEntryViolationSeverity.HIGH
        elif ratio > tolerance * 10:
            return DoubleEntryViolationSeverity.MEDIUM
        elif ratio > tolerance:
            return DoubleEntryViolationSeverity.LOW
        return DoubleEntryViolationSeverity.INFO

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_journals = len(self._journals)
            total_verifications = len(self._verification_history)
            total_violations = len(self._violation_history)
            return {
                "total_journals": total_journals,
                "total_verifications": total_verifications,
                "total_violations": total_violations,
                "by_status": {
                    s.name: len([j for j in self._journals.values() if j.status == s])
                    for s in JournalStatus
                },
                "unresolved_violations": 0,
            }

    def reset(self) -> None:
        with self._lock:
            self._journals = {}
            self._verification_history = []
            self._violation_history = []
            self._journal_sequence = {}


# === 5. DOUBLE ENTRY VALIDATOR (for compatibility with __init__.py) ===


class DoubleEntryValidator:
    """
    Validator for double entry axiom.
    Provides static methods to validate journals and lines.
    """

    @staticmethod
    def validate_journal(
        journal: JournalEntry, tolerance: Decimal = Decimal("0.0001")
    ) -> tuple[bool, str | None]:
        """
        Validate that a journal is balanced.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if abs(journal.difference) <= tolerance:
            return True, None
        return (
            False,
            f"Journal not balanced: debit={journal.total_debit}, credit={journal.total_credit}, diff={journal.difference}",
        )

    @staticmethod
    def validate_lines(lines: list[JournalLine]) -> tuple[bool, str | None]:
        """
        Validate that journal lines have positive amounts and valid accounts.

        Returns:
            Tuple of (is_valid, error_message)
        """
        for line in lines:
            if line.amount <= 0:
                return False, f"Line {line.line_id} has non-positive amount: {line.amount}"
            if not line.account_code:
                return False, f"Line {line.line_id} has empty account code"
        return True, None

    @staticmethod
    def validate_balance(
        debit: Decimal, credit: Decimal, tolerance: Decimal = Decimal("0.0001")
    ) -> tuple[bool, Decimal]:
        """
        Validate that debit equals credit within tolerance.

        Returns:
            Tuple of (is_valid, difference)
        """
        diff = debit - credit
        return abs(diff) <= tolerance, diff


# === 6. SINGLETON ACCESSOR ===

_double_entry_axiom_instance: DoubleEntryAxiom | None = None


def get_double_entry_axiom() -> DoubleEntryAxiom:
    global _double_entry_axiom_instance
    if _double_entry_axiom_instance is None:
        _double_entry_axiom_instance = DoubleEntryAxiom()
    return _double_entry_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_journal_line(
    account_code: str,
    side: Side | str,
    amount: Decimal,
    currency: str = "IDR",
    description: str = "",
    legal_entity_id: UUID | None = None,
    cost_center: str | None = None,
    department: str | None = None,
    project_id: UUID | None = None,
    reference: str | None = None,
) -> JournalLine:
    if isinstance(side, str):
        side = Side.DEBIT if side.lower() == "debit" else Side.CREDIT
    return JournalLine(
        line_id=uuid4(),
        journal_id=UUID(int=0),
        account_code=account_code,
        side=side,
        amount=amount,
        currency=currency.upper(),
        description=description,
        legal_entity_id=legal_entity_id or UUID(int=0),
        cost_center=cost_center,
        department=department,
        project_id=project_id,
        reference=reference,
    )


def create_debit_line(
    account_code: str,
    amount: Decimal,
    currency: str = "IDR",
    description: str = "",
    legal_entity_id: UUID | None = None,
    **kwargs,
) -> JournalLine:
    return create_journal_line(
        account_code, Side.DEBIT, amount, currency, description, legal_entity_id, **kwargs
    )


def create_credit_line(
    account_code: str,
    amount: Decimal,
    currency: str = "IDR",
    description: str = "",
    legal_entity_id: UUID | None = None,
    **kwargs,
) -> JournalLine:
    return create_journal_line(
        account_code, Side.CREDIT, amount, currency, description, legal_entity_id, **kwargs
    )


def create_journal_line_dict(
    account_code: str,
    side: str,
    amount: Decimal,
    currency: str = "IDR",
    description: str = "",
    legal_entity_id: UUID | None = None,
    **kwargs,
) -> dict[str, Any]:
    return {
        "account_code": account_code,
        "side": side,
        "amount": amount,
        "currency": currency,
        "description": description,
        "legal_entity_id": legal_entity_id,
        **kwargs,
    }


# === 8. SINGLETON INSTANCE ALIAS (untuk import langsung) ===
# Ini adalah perbaikan utama: menyediakan instance singleton dengan nama 'double_entry'
double_entry = get_double_entry_axiom()


# === 9. EXPORTS ===

__all__ = [
    "DoubleEntryAxiom",
    "DoubleEntryValidator",
    "DoubleEntryVerificationRecord",
    "DoubleEntryViolationError",
    "DoubleEntryViolationSeverity",
    "InvalidJournalEntryError",
    "JournalEntry",
    "JournalLine",
    "JournalStatus",
    "JournalType",
    "Side",
    "create_credit_line",
    "create_debit_line",
    "create_journal_line",
    "create_journal_line_dict",
    "double_entry",
    "get_double_entry_axiom",
]