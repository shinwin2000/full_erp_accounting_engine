#!/usr/bin/env python3
"""
Module: immutability.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: data yang sudah dicatat tidak bisa diubah (append-only).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class ImmutabilityViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class DataState(Enum):
    DRAFT = auto()
    SUBMITTED = auto()
    APPROVED = auto()
    POSTED = auto()
    REVERSED = auto()
    ARCHIVED = auto()
    DELETED = auto()


class CorrectionMethod(Enum):
    REVERSAL_JOURNAL = auto()
    AMENDMENT_ENTRY = auto()
    PRIOR_PERIOD_ADJUSTMENT = auto()
    ERROR_CORRECTION = auto()


class ImmutableRecordType(Enum):
    JOURNAL = auto()
    INVOICE = auto()
    PAYMENT = auto()
    ACCOUNT_BALANCE = auto()
    PERIOD_CLOSE = auto()
    AUDIT_EVENT = auto()


# === 2. EXCEPTIONS ===


class ImmutabilityViolationError(Exception):
    def __init__(
        self,
        message: str,
        target_record_id: UUID,
        attempted_operation: str,
        severity: ImmutabilityViolationSeverity,
    ):
        self.target_record_id = target_record_id
        self.attempted_operation = attempted_operation
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | Record: {target_record_id}, Op: {attempted_operation}"
        )


class ImmutabilityHashChainError(Exception):
    pass


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class ImmutableRecord:
    record_id: UUID
    record_type: ImmutableRecordType
    aggregate_id: UUID
    version: int
    data_hash: str
    previous_hash: str | None
    timestamp: datetime
    created_by: str
    signature: str
    is_active: bool = True
    cryptographic_hash: str = ""
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    _version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self._version < 1:
            raise ValueError("_version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_data_hash(self, data: dict[str, Any]) -> str:
        return hashlib.sha3_256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def compute_chain_hash(self) -> str:
        content = f"{self.record_id}|{self.record_type.value}|{self.aggregate_id}|{self.version}|{self.data_hash}|{self.previous_hash or ''}|{self.timestamp.isoformat()}|{self.is_active}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def compute_hash(self) -> str:
        content = f"{self.record_id}|{self.record_type.value}|{self.aggregate_id}|{self.version}|{self.data_hash}|{self.previous_hash or ''}|{self.timestamp.isoformat()}|{self.created_by}|{self.signature}|{self.is_active}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self._version,
                "record_id": str(self.record_id),
                "is_active": self.is_active,
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
                "version": self._version,
                "record_id": str(self.record_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ImmutableRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> ImmutableRecord:
        raise AttributeError("ImmutableRecord cannot be updated")

    def delete(self, deleted_by: str, reason: str | None = None) -> ImmutableRecord:
        new_record = self._copy()
        new_record.deleted_at = datetime.now(UTC)
        new_record.deleted_by = deleted_by
        new_record._version = self._version + 1
        new_record._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_record

    def restore(self, restored_by: str) -> ImmutableRecord:
        if self.deleted_at is None:
            raise ValueError("Record not deleted")
        new_record = self._copy()
        new_record.deleted_at = None
        new_record.deleted_by = None
        new_record._version = self._version + 1
        new_record._record_audit("RESTORE", restored_by, {})
        return new_record

    def activate(self, activated_by: str) -> ImmutableRecord:
        if self.is_active:
            return self
        new_record = self._copy()
        new_record.is_active = True
        new_record._version = self._version + 1
        new_record._record_audit("ACTIVATE", activated_by, {})
        return new_record

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ImmutableRecord:
        if not self.is_active:
            return self
        new_record = self._copy()
        new_record.is_active = False
        new_record._version = self._version + 1
        new_record._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_record

    def lock(self, locked_by: str, reason: str) -> ImmutableRecord:
        return self

    def unlock(self, unlocked_by: str) -> ImmutableRecord:
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
            "record_id": str(self.record_id),
            "version": self._version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "record_type": self.record_type.name,
            "aggregate_id": str(self.aggregate_id),
            "version": self.version,
            "data_hash": self.data_hash[:16] + "...",
            "previous_hash": self.previous_hash[:16] + "..." if self.previous_hash else None,
            "timestamp": self.timestamp.isoformat(),
            "created_by": self.created_by,
            "signature": self.signature[:16] + "...",
            "is_active": self.is_active,
            "_version": self._version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImmutableRecord:
        return cls(
            record_id=UUID(data["record_id"]),
            record_type=ImmutableRecordType[data["record_type"]],
            aggregate_id=UUID(data["aggregate_id"]),
            version=data["version"],
            data_hash=data["data_hash"],
            previous_hash=data.get("previous_hash"),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            created_by=data["created_by"],
            signature=data["signature"],
            is_active=data.get("is_active", True),
            cryptographic_hash=data.get("cryptographic_hash", ""),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
            _version=data.get("_version", 1),
        )

    def clone(self) -> ImmutableRecord:
        new_id = uuid4()
        return ImmutableRecord(
            record_id=new_id,
            record_type=self.record_type,
            aggregate_id=self.aggregate_id,
            version=self.version,
            data_hash=self.data_hash,
            previous_hash=self.previous_hash,
            timestamp=datetime.now(UTC),
            created_by=self.created_by,
            signature=self.signature,
            is_active=True,
            _version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "record_id": str(self.record_id),
            "is_active": self.is_active,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ImmutableRecord:
        new_record = self._copy()
        new_record._version = self._version + 1
        new_record._record_audit("TOUCH", touched_by, {})
        return new_record

    def _copy(self) -> ImmutableRecord:
        return ImmutableRecord(
            record_id=self.record_id,
            record_type=self.record_type,
            aggregate_id=self.aggregate_id,
            version=self.version,
            data_hash=self.data_hash,
            previous_hash=self.previous_hash,
            timestamp=self.timestamp,
            created_by=self.created_by,
            signature=self.signature,
            is_active=self.is_active,
            cryptographic_hash=self.cryptographic_hash,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
            _version=self._version,
        )

    def deactivate_default(self) -> ImmutableRecord:
        """Alias for deactivate() dengan nilai default. Diganti nama dari
        deactivate() -- nama itu bentrok dengan method utama
        deactivate(self, deactivated_by, reason=None) di atas (dipakai oleh
        service_coa.py, faktur_masukan_processor.py,
        constitutional_invariants.py) dan menyebabkan TypeError setiap kali
        method utama itu dipanggil dengan argumen."""
        return self.deactivate("system", "Deactivated")


@dataclass(kw_only=True)
class CorrectionRecord:
    correction_id: UUID
    original_record_id: UUID
    correction_method: CorrectionMethod
    correction_record_id: UUID
    reason: str
    authorized_by: str
    authorized_at: datetime
    approved_by: list[str]
    audit_reference: str
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
        self._record_audit("CREATE", self.authorized_by, {})

    def _validate(self) -> None:
        if not self.approved_by:
            raise ValueError("At least one approver required")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.correction_id}|{self.original_record_id}|{self.correction_method.value}|{self.correction_record_id}|{self.reason}|{self.authorized_by}|{','.join(self.approved_by)}|{self.audit_reference}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "correction_id": str(self.correction_id),
                "method": self.correction_method.name,
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
                "correction_id": str(self.correction_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> CorrectionRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> CorrectionRecord:
        raise AttributeError("CorrectionRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> CorrectionRecord:
        new_record = self._copy()
        new_record.deleted_at = datetime.now(UTC)
        new_record.deleted_by = deleted_by
        new_record.version = self.version + 1
        new_record._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_record

    def restore(self, restored_by: str) -> CorrectionRecord:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_record = self._copy()
        new_record.deleted_at = None
        new_record.deleted_by = None
        new_record.version = self.version + 1
        new_record._record_audit("RESTORE", restored_by, {})
        return new_record

    def activate(self, activated_by: str) -> CorrectionRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CorrectionRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> CorrectionRecord:
        return self

    def unlock(self, unlocked_by: str) -> CorrectionRecord:
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
            "correction_id": str(self.correction_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "correction_id": str(self.correction_id),
            "original_record_id": str(self.original_record_id),
            "correction_method": self.correction_method.name,
            "correction_record_id": str(self.correction_record_id),
            "reason": self.reason,
            "authorized_by": self.authorized_by,
            "authorized_at": self.authorized_at.isoformat(),
            "approved_by": self.approved_by,
            "audit_reference": self.audit_reference,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorrectionRecord:
        return cls(
            correction_id=UUID(data["correction_id"]),
            original_record_id=UUID(data["original_record_id"]),
            correction_method=CorrectionMethod[data["correction_method"]],
            correction_record_id=UUID(data["correction_record_id"]),
            reason=data["reason"],
            authorized_by=data["authorized_by"],
            authorized_at=datetime.fromisoformat(data["authorized_at"]),
            approved_by=data["approved_by"],
            audit_reference=data["audit_reference"],
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> CorrectionRecord:
        new_id = uuid4()
        return CorrectionRecord(
            correction_id=new_id,
            original_record_id=self.original_record_id,
            correction_method=self.correction_method,
            correction_record_id=self.correction_record_id,
            reason=self.reason,
            authorized_by=self.authorized_by,
            authorized_at=datetime.now(UTC),
            approved_by=self.approved_by.copy(),
            audit_reference=self.audit_reference,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "correction_id": str(self.correction_id),
            "method": self.correction_method.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CorrectionRecord:
        new_record = self._copy()
        new_record.version = self.version + 1
        new_record._record_audit("TOUCH", touched_by, {})
        return new_record

    def _copy(self) -> CorrectionRecord:
        return CorrectionRecord(
            correction_id=self.correction_id,
            original_record_id=self.original_record_id,
            correction_method=self.correction_method,
            correction_record_id=self.correction_record_id,
            reason=self.reason,
            authorized_by=self.authorized_by,
            authorized_at=self.authorized_at,
            approved_by=self.approved_by.copy(),
            audit_reference=self.audit_reference,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class ImmutabilityViolation:
    violation_id: UUID
    target_record_id: UUID
    target_aggregate_id: UUID
    attempted_operation: str
    attempted_by: str
    attempted_at: datetime
    source_module: str
    severity: ImmutabilityViolationSeverity
    message: str
    was_blocked: bool
    bypass_attempted: bool
    forensic_evidence_hash: str
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_forensic_hash()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.attempted_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_forensic_hash(self) -> None:
        if not self.forensic_evidence_hash:
            object.__setattr__(self, "forensic_evidence_hash", self.compute_forensic_hash())

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_forensic_hash(self) -> str:
        content = f"{self.violation_id}|{self.target_record_id}|{self.target_aggregate_id}|{self.attempted_operation}|{self.attempted_by}|{self.attempted_at.isoformat()}|{self.was_blocked}|{self.bypass_attempted}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def compute_hash(self) -> str:
        content = f"{self.violation_id}|{self.severity.value}|{self.message[:100]}|{self.attempted_operation}|{self.was_blocked}"
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
    def create(self, created_by: str) -> ImmutabilityViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> ImmutabilityViolation:
        raise AttributeError("ImmutabilityViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> ImmutabilityViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> ImmutabilityViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> ImmutabilityViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ImmutabilityViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> ImmutabilityViolation:
        return self

    def unlock(self, unlocked_by: str) -> ImmutabilityViolation:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
            if self.forensic_evidence_hash != self.compute_forensic_hash():
                errors.append("Forensic hash mismatch")
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
            "target_record_id": str(self.target_record_id),
            "target_aggregate_id": str(self.target_aggregate_id),
            "attempted_operation": self.attempted_operation,
            "attempted_by": self.attempted_by,
            "attempted_at": self.attempted_at.isoformat(),
            "source_module": self.source_module,
            "severity": self.severity.name,
            "message": self.message,
            "was_blocked": self.was_blocked,
            "bypass_attempted": self.bypass_attempted,
            "forensic_evidence_hash": self.forensic_evidence_hash[:16] + "...",
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImmutabilityViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            target_record_id=UUID(data["target_record_id"]),
            target_aggregate_id=UUID(data["target_aggregate_id"]),
            attempted_operation=data["attempted_operation"],
            attempted_by=data["attempted_by"],
            attempted_at=datetime.fromisoformat(data["attempted_at"]),
            source_module=data["source_module"],
            severity=ImmutabilityViolationSeverity[data["severity"]],
            message=data["message"],
            was_blocked=data["was_blocked"],
            bypass_attempted=data["bypass_attempted"],
            forensic_evidence_hash=data["forensic_evidence_hash"],
            version=data.get("version", 1),
        )

    def clone(self) -> ImmutabilityViolation:
        new_id = uuid4()
        return ImmutabilityViolation(
            violation_id=new_id,
            target_record_id=self.target_record_id,
            target_aggregate_id=self.target_aggregate_id,
            attempted_operation=self.attempted_operation,
            attempted_by=self.attempted_by,
            attempted_at=datetime.now(UTC),
            source_module=self.source_module,
            severity=self.severity,
            message=self.message,
            was_blocked=self.was_blocked,
            bypass_attempted=self.bypass_attempted,
            forensic_evidence_hash="",
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ImmutabilityViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. VALIDATOR ===


class ImmutabilityValidator:
    IMMUTABLE_STATES = {DataState.POSTED, DataState.REVERSED, DataState.ARCHIVED, DataState.DELETED}
    MUTABLE_STATES = {DataState.DRAFT, DataState.SUBMITTED, DataState.APPROVED}
    ALLOWED_OPERATIONS_ON_IMMUTABLE = {"READ", "SELECT", "GET", "VIEW", "EXPORT"}
    CORRECTION_OPERATIONS = {"REVERSE", "CORRECT", "ADJUST", "AMEND"}

    @classmethod
    def validate_operation(
        cls,
        current_state: DataState,
        operation: str,
        aggregate_id: UUID,
        record_id: UUID,
        user_id: str,
        module: str,
        is_correction: bool = False,
        correction_method: CorrectionMethod | None = None,
        bypass_authorization: list[str] | None = None,
    ) -> tuple[bool, ImmutabilityViolation | None]:
        if current_state in cls.IMMUTABLE_STATES:
            if operation.upper() in cls.ALLOWED_OPERATIONS_ON_IMMUTABLE:
                return True, None
            if is_correction and operation.upper() in cls.CORRECTION_OPERATIONS:
                if correction_method in (
                    CorrectionMethod.REVERSAL_JOURNAL,
                    CorrectionMethod.AMENDMENT_ENTRY,
                ):
                    if bypass_authorization and len(bypass_authorization) >= 1:
                        return True, None
            severity = ImmutabilityViolationSeverity.CRITICAL
            violation = cls._create_violation(
                record_id,
                aggregate_id,
                operation,
                user_id,
                module,
                severity,
                f"Cannot perform {operation} on record in {current_state.name} state",
                True,
                False,
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation
        if operation.upper() in ("UPDATE", "EDIT", "MODIFY"):
            if current_state == DataState.DRAFT:
                return True, None
            elif current_state in (DataState.SUBMITTED, DataState.APPROVED):
                if bypass_authorization and len(bypass_authorization) >= 1:
                    return True, None
                else:
                    violation = cls._create_violation(
                        record_id,
                        aggregate_id,
                        operation,
                        user_id,
                        module,
                        ImmutabilityViolationSeverity.MEDIUM,
                        f"Modification on {current_state.name} requires authorization",
                        True,
                        False,
                    )
                    cls._log_violation(violation)
                    return False, violation
        if operation.upper() == "DELETE":
            if current_state == DataState.DRAFT:
                return True, None
            else:
                violation = cls._create_violation(
                    record_id,
                    aggregate_id,
                    operation,
                    user_id,
                    module,
                    ImmutabilityViolationSeverity.CRITICAL,
                    f"Cannot delete record in {current_state.name} state",
                    True,
                    False,
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation
        return True, None

    @classmethod
    def validate_state_transition(
        cls,
        from_state: DataState,
        to_state: DataState,
        aggregate_id: UUID,
        record_id: UUID,
        user_id: str,
        module: str,
        require_approval: bool = True,
    ) -> tuple[bool, ImmutabilityViolation | None]:
        if to_state == DataState.POSTED:
            if from_state not in (DataState.APPROVED, DataState.SUBMITTED):
                violation = cls._create_violation(
                    record_id,
                    aggregate_id,
                    f"STATE_TRANSITION_{from_state.name}_TO_{to_state.name}",
                    user_id,
                    module,
                    ImmutabilityViolationSeverity.CRITICAL,
                    f"Cannot post from {from_state.name}",
                    True,
                    False,
                )
                cls._log_violation(violation)
                return False, violation
        if from_state == DataState.POSTED:
            if to_state not in (DataState.REVERSED, DataState.ARCHIVED):
                violation = cls._create_violation(
                    record_id,
                    aggregate_id,
                    f"STATE_TRANSITION_{from_state.name}_TO_{to_state.name}",
                    user_id,
                    module,
                    ImmutabilityViolationSeverity.CATASTROPHIC,
                    f"Cannot transition from POSTED to {to_state.name}",
                    True,
                    False,
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation
        if to_state == DataState.REVERSED and require_approval and not user_id:
            violation = cls._create_violation(
                record_id,
                aggregate_id,
                f"STATE_TRANSITION_{from_state.name}_TO_{to_state.name}",
                user_id,
                module,
                ImmutabilityViolationSeverity.HIGH,
                "Reversal requires authorization",
                True,
                False,
            )
            cls._log_violation(violation)
            return False, violation
        return True, None

    @classmethod
    def _create_violation(
        cls,
        target_record_id: UUID,
        target_aggregate_id: UUID,
        attempted_operation: str,
        attempted_by: str,
        module: str,
        severity: ImmutabilityViolationSeverity,
        message: str,
        was_blocked: bool,
        bypass_attempted: bool,
    ) -> ImmutabilityViolation:
        return ImmutabilityViolation(
            violation_id=uuid4(),
            target_record_id=target_record_id,
            target_aggregate_id=target_aggregate_id,
            attempted_operation=attempted_operation,
            attempted_by=attempted_by,
            attempted_at=datetime.now(UTC),
            source_module=module,
            severity=severity,
            message=message,
            was_blocked=was_blocked,
            bypass_attempted=bypass_attempted,
            forensic_evidence_hash="",
        )

    @classmethod
    def _log_violation(cls, violation: ImmutabilityViolation) -> None:
        log_msg = f"[{violation.severity.name}] Immutability violation: {violation.message}"
        if violation.severity.value >= ImmutabilityViolationSeverity.CRITICAL.value:
            logger.critical(log_msg)
        elif violation.severity.value >= ImmutabilityViolationSeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: ImmutabilityViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                ImmutabilityViolationSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                ImmutabilityViolationSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                ImmutabilityViolationSeverity.HIGH: ConstitutionalSeverity.HIGH,
                ImmutabilityViolationSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                ImmutabilityViolationSeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.IMMUTABILITY,
                offending_module=violation.source_module,
                message=violation.message,
                offending_user=violation.attempted_by,
                offending_command_id=violation.target_record_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 5. AXIOM SERVICE ===


class ImmutabilityAxiom:
    _instance: ImmutabilityAxiom | None = None
    _immutable_records: dict[UUID, ImmutableRecord] = {}
    _correction_history: list[CorrectionRecord] = []
    _violation_history: list[ImmutabilityViolation] = []
    _state_registry: dict[UUID, DataState] = {}
    _lock = threading.Lock()

    def __new__(cls) -> ImmutabilityAxiom:
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
        self._immutable_records = {}
        self._correction_history = []
        self._violation_history = []
        self._state_registry = {}

    # ==================== REPOSITORY METHODS ====================
    def save_immutable_record(self, record: ImmutableRecord) -> None:
        with self._lock:
            self._immutable_records[record.record_id] = record
            self._state_registry[record.aggregate_id] = (
                DataState.POSTED if record.is_active else DataState.REVERSED
            )

    def get_immutable_record(self, record_id: UUID) -> ImmutableRecord | None:
        return self._immutable_records.get(record_id)

    def get_immutable_records_for_aggregate(self, aggregate_id: UUID) -> list[ImmutableRecord]:
        return [r for r in self._immutable_records.values() if r.aggregate_id == aggregate_id]

    def delete_immutable_record(self, record_id: UUID) -> bool:
        with self._lock:
            if record_id in self._immutable_records:
                del self._immutable_records[record_id]
                return True
            return False

    def save_correction(self, correction: CorrectionRecord) -> None:
        with self._lock:
            self._correction_history.append(correction)

    def get_corrections(
        self, original_record_id: UUID | None = None, limit: int = 100
    ) -> list[CorrectionRecord]:
        result = self._correction_history[-limit:]
        if original_record_id:
            result = [c for c in result if c.original_record_id == original_record_id]
        return result

    def delete_correction(self, correction_id: UUID) -> bool:
        with self._lock:
            for i, c in enumerate(self._correction_history):
                if c.correction_id == correction_id:
                    self._correction_history.pop(i)
                    return True
            return False

    def save_violation(self, violation: ImmutabilityViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        min_severity: ImmutabilityViolationSeverity | None = None,
        aggregate_id: UUID | None = None,
    ) -> list[ImmutabilityViolation]:
        result = self._violation_history[-limit:]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if aggregate_id:
            result = [v for v in result if v.target_aggregate_id == aggregate_id]
        return result

    # ==================== BUSINESS METHODS ====================
    def register_immutable_record(
        self, record: ImmutableRecord, verify_hash_chain: bool = True
    ) -> None:
        with self._lock:
            if verify_hash_chain:
                previous = None
                if record.previous_hash:
                    for r in self._immutable_records.values():
                        if r.compute_chain_hash() == record.previous_hash:
                            previous = r
                            break
                if previous is None and record.previous_hash is not None:
                    raise ImmutabilityHashChainError("Previous record not found")
            self.save_immutable_record(record)

    def get_aggregate_state(self, aggregate_id: UUID) -> DataState:
        return self._state_registry.get(aggregate_id, DataState.DRAFT)

    def set_aggregate_state(self, aggregate_id: UUID, state: DataState) -> None:
        with self._lock:
            self._state_registry[aggregate_id] = state

    def enforce_operation(
        self,
        aggregate_id: UUID,
        operation: str,
        record_id: UUID,
        user_id: str,
        module: str = "unknown",
        is_correction: bool = False,
        correction_method: CorrectionMethod | None = None,
        bypass_authorization: list[str] | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ImmutabilityViolation | None]:
        current_state = self.get_aggregate_state(aggregate_id)
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state,
            operation,
            aggregate_id,
            record_id,
            user_id,
            module,
            is_correction,
            correction_method,
            bypass_authorization,
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= ImmutabilityViolationSeverity.CRITICAL.value
            ):
                raise ImmutabilityViolationError(
                    violation.message,
                    violation.target_record_id,
                    violation.attempted_operation,
                    violation.severity,
                )
        return is_allowed, violation

    def enforce_state_transition(
        self,
        aggregate_id: UUID,
        from_state: DataState,
        to_state: DataState,
        record_id: UUID,
        user_id: str,
        module: str = "unknown",
        require_approval: bool = True,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ImmutabilityViolation | None]:
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state, to_state, aggregate_id, record_id, user_id, module, require_approval
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= ImmutabilityViolationSeverity.HIGH.value
            ):
                raise ImmutabilityViolationError(
                    violation.message,
                    violation.target_record_id,
                    violation.attempted_operation,
                    violation.severity,
                )
            return False, violation
        if is_valid:
            self.set_aggregate_state(aggregate_id, to_state)
        return True, None

    def record_correction(
        self,
        original_record_id: UUID,
        correction_method: CorrectionMethod,
        correction_record_id: UUID,
        reason: str,
        authorized_by: str,
        approved_by: list[str],
        audit_reference: str,
    ) -> CorrectionRecord:
        if correction_method in (
            CorrectionMethod.PRIOR_PERIOD_ADJUSTMENT,
            CorrectionMethod.AMENDMENT_ENTRY,
        ):
            if len(approved_by) < 2:
                raise ValueError(f"{correction_method.name} requires at least 2 approvers")
        correction = CorrectionRecord(
            correction_id=uuid4(),
            original_record_id=original_record_id,
            correction_method=correction_method,
            correction_record_id=correction_record_id,
            reason=reason,
            authorized_by=authorized_by,
            authorized_at=datetime.now(UTC),
            approved_by=approved_by,
            audit_reference=audit_reference,
        )
        self.save_correction(correction)
        original = self.get_immutable_record(original_record_id)
        if original and original.is_active:
            deactivated = original.deactivate_default()
            self.save_immutable_record(deactivated)
        return correction

    def is_immutable(self, state: DataState) -> bool:
        return state in ImmutabilityValidator.IMMUTABLE_STATES

    def get_allowed_states_for_operation(self, operation: str) -> list[DataState]:
        op = operation.upper()
        if op in ("READ", "SELECT", "GET", "VIEW"):
            return list(DataState)
        elif op in ("UPDATE", "EDIT", "MODIFY"):
            return [DataState.DRAFT, DataState.SUBMITTED, DataState.APPROVED]
        elif op == "DELETE":
            return [DataState.DRAFT]
        elif op in ("REVERSE", "CORRECT", "ADJUST", "AMEND"):
            return [DataState.POSTED, DataState.REVERSED, DataState.ARCHIVED]
        return []

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_records = len(self._immutable_records)
            active_records = len([r for r in self._immutable_records.values() if r.is_active])
            total_corrections = len(self._correction_history)
            total_violations = len(self._violation_history)
            state_dist = {
                s.name: len([a for a in self._state_registry.values() if a == s]) for s in DataState
            }
            return {
                "total_immutable_records": total_records,
                "active_records": active_records,
                "total_corrections": total_corrections,
                "total_violations": total_violations,
                "state_distribution": state_dist,
                "unresolved_violations": 0,
            }

    def reset(self) -> None:
        with self._lock:
            self._immutable_records = {}
            self._correction_history = []
            self._violation_history = []
            self._state_registry = {}


# === 6. SINGLETON ACCESSOR ===

_immutability_axiom_instance: ImmutabilityAxiom | None = None


def get_immutability_axiom() -> ImmutabilityAxiom:
    global _immutability_axiom_instance
    if _immutability_axiom_instance is None:
        _immutability_axiom_instance = ImmutabilityAxiom()
    return _immutability_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_immutable_record(
    record_id: UUID,
    record_type: ImmutableRecordType,
    aggregate_id: UUID,
    version: int,
    data: dict[str, Any],
    previous_hash: str | None,
    created_by: str,
    signature: str,
) -> ImmutableRecord:
    data_hash = hashlib.sha3_256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return ImmutableRecord(
        record_id=record_id,
        record_type=record_type,
        aggregate_id=aggregate_id,
        version=version,
        data_hash=data_hash,
        previous_hash=previous_hash,
        timestamp=datetime.now(UTC),
        created_by=created_by,
        signature=signature,
        is_active=True,
    )


def state_from_string(state_str: str) -> DataState:
    mapping = {
        "DRAFT": DataState.DRAFT,
        "SUBMITTED": DataState.SUBMITTED,
        "APPROVED": DataState.APPROVED,
        "POSTED": DataState.POSTED,
        "REVERSED": DataState.REVERSED,
        "ARCHIVED": DataState.ARCHIVED,
        "DELETED": DataState.DELETED,
    }
    return mapping.get(state_str.upper(), DataState.DRAFT)


def record_type_from_string(record_type_str: str) -> ImmutableRecordType:
    mapping = {
        "JOURNAL": ImmutableRecordType.JOURNAL,
        "INVOICE": ImmutableRecordType.INVOICE,
        "PAYMENT": ImmutableRecordType.PAYMENT,
        "ACCOUNT_BALANCE": ImmutableRecordType.ACCOUNT_BALANCE,
        "PERIOD_CLOSE": ImmutableRecordType.PERIOD_CLOSE,
        "AUDIT_EVENT": ImmutableRecordType.AUDIT_EVENT,
    }
    return mapping.get(record_type_str.upper(), ImmutableRecordType.JOURNAL)


__all__ = [
    "CorrectionMethod",
    "CorrectionRecord",
    "DataState",
    "ImmutabilityAxiom",
    "ImmutabilityHashChainError",
    "ImmutabilityValidator",
    "ImmutabilityViolation",
    "ImmutabilityViolationError",
    "ImmutabilityViolationSeverity",
    "ImmutableRecord",
    "ImmutableRecordType",
    "create_immutable_record",
    "get_immutability_axiom",
    "record_type_from_string",
    "state_from_string",
]
