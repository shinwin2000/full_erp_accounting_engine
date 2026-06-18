#!/usr/bin/env python3
"""
Module: constitutional_invariants.py
Layer: 1 - Foundation / Constitution
Responsibility: Mendefinisikan invariant konstitusi yang harus selalu benar
               dalam sistem akuntansi. Invariant adalah kebenaran fundamental
               yang tidak boleh dilanggar dalam keadaan apapun.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, getcontext
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)

getcontext().prec = 28


# === 1. ENUMS ===


class InvariantType(Enum):
    ACCOUNTING_EQUATION = auto()
    DOUBLE_ENTRY_BALANCE = auto()
    CONSERVATION_OF_VALUE = auto()
    TIME_MONOTONICITY = auto()
    PERIOD_INTEGRITY = auto()
    SEQUENCE_INTEGRITY = auto()
    LEGAL_ENTITY_ISOLATION = auto()
    CURRENCY_CONSISTENCY = auto()
    HASH_CHAIN_CONSISTENCY = auto()
    AUDIT_TRAIL_COMPLETENESS = auto()
    IDEMPOTENCY_STRICT = auto()
    NON_NEGATIVE_CASH = auto()
    NON_NEGATIVE_INVENTORY = auto()
    NON_NEGATIVE_RECEIVABLE = auto()
    TAX_CONSISTENCY = auto()
    PERIOD_CLOSURE_FINALITY = auto()
    CURRENCY_EXPOSURE_CONSISTENCY = auto()


class InvariantSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


class InvariantScope(Enum):
    GLOBAL = auto()
    PER_LEGAL_ENTITY = auto()
    PER_PERIOD = auto()
    PER_TRANSACTION = auto()


class InvariantValidationStage(Enum):
    PRE_EXECUTION = auto()
    POST_EXECUTION = auto()
    RECONCILIATION = auto()
    PERIODIC_SCAN = auto()


# === 2. EXCEPTIONS ===


class InvariantViolationError(Exception):
    def __init__(
        self,
        invariant_type: InvariantType,
        message: str,
        severity: InvariantSeverity,
        context: dict[str, Any],
    ):
        self.invariant_type = invariant_type
        self.severity = severity
        self.context = context
        super().__init__(f"[{invariant_type.name}:{severity.name}] {message}")


# === 3. VALUE OBJECTS ===


@dataclass(kw_only=True)
class InvariantDefinition:
    # Required fields (no defaults)
    invariant_id: UUID
    invariant_type: InvariantType
    name: str
    description: str
    scope: InvariantScope
    severity: InvariantSeverity
    validation_function_name: str
    validation_stage: InvariantValidationStage
    is_active: bool
    created_at: datetime
    created_by: str
    approved_by: list[str]
    version: str
    # Optional fields (with defaults)
    cryptographic_hash: str = ""
    auto_correct: bool = False
    correction_action: str | None = None
    version_number: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version must be >= 1")
        if self.scope == InvariantScope.GLOBAL and len(self.approved_by) < 2:
            raise ValueError("Global scope invariant requires at least 2 approvers")

    def compute_hash(self) -> str:
        content = (
            f"{self.invariant_id}|{self.invariant_type.value}|{self.name}|{self.description}|"
            f"{self.scope.value}|{self.severity.value}|{self.validation_function_name}|"
            f"{self.validation_stage.value}|{self.is_active}|{self.created_at.isoformat()}|"
            f"{self.created_by}|{','.join(self.approved_by)}|{self.version}|"
            f"{self.auto_correct}|{self.correction_action or ''}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "invariant_id": str(self.invariant_id),
                "name": self.name,
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
                "version": self.version_number,
                "invariant_id": str(self.invariant_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> InvariantDefinition:
        return self

    def update(self, updated_by: str, **kwargs) -> InvariantDefinition:
        new_def = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_def, key) and key not in (
                "invariant_id",
                "created_at",
                "created_by",
                "version_number",
            ):
                setattr(new_def, key, value)
        new_def.version_number = self.version_number + 1
        new_def._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_def

    def delete(self, deleted_by: str, reason: str | None = None) -> InvariantDefinition:
        new_def = self._copy()
        new_def.deleted_at = datetime.now(UTC)
        new_def.deleted_by = deleted_by
        new_def.is_active = False
        new_def.version_number = self.version_number + 1
        new_def._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_def

    def restore(self, restored_by: str) -> InvariantDefinition:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_def = self._copy()
        new_def.deleted_at = None
        new_def.deleted_by = None
        new_def.is_active = True
        new_def.version_number = self.version_number + 1
        new_def._record_audit("RESTORE", restored_by, {})
        return new_def

    def activate(self, activated_by: str) -> InvariantDefinition:
        if self.is_active:
            return self
        new_def = self._copy()
        new_def.is_active = True
        new_def.version_number = self.version_number + 1
        new_def._record_audit("ACTIVATE", activated_by, {})
        return new_def

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> InvariantDefinition:
        if not self.is_active:
            return self
        new_def = self._copy()
        new_def.is_active = False
        new_def.version_number = self.version_number + 1
        new_def._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_def

    def lock(self, locked_by: str, reason: str) -> InvariantDefinition:
        new_def = self._copy()
        new_def.version_number = self.version_number + 1
        new_def._record_audit("LOCK", locked_by, {"reason": reason})
        return new_def

    def unlock(self, unlocked_by: str) -> InvariantDefinition:
        new_def = self._copy()
        new_def.version_number = self.version_number + 1
        new_def._record_audit("UNLOCK", unlocked_by, {})
        return new_def

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
            "invariant_id": str(self.invariant_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_id": str(self.invariant_id),
            "invariant_type": self.invariant_type.name,
            "name": self.name,
            "description": self.description,
            "scope": self.scope.name,
            "severity": self.severity.name,
            "validation_function_name": self.validation_function_name,
            "validation_stage": self.validation_stage.name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "version": self.version,
            "auto_correct": self.auto_correct,
            "correction_action": self.correction_action,
            "version_number": self.version_number,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvariantDefinition:
        return cls(
            invariant_id=UUID(data["invariant_id"]),
            invariant_type=InvariantType[data["invariant_type"]],
            name=data["name"],
            description=data["description"],
            scope=InvariantScope[data["scope"]],
            severity=InvariantSeverity[data["severity"]],
            validation_function_name=data["validation_function_name"],
            validation_stage=InvariantValidationStage[data["validation_stage"]],
            is_active=data["is_active"],
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data["created_by"],
            approved_by=data["approved_by"],
            version=data["version"],
            cryptographic_hash=data.get("cryptographic_hash", ""),
            auto_correct=data.get("auto_correct", False),
            correction_action=data.get("correction_action"),
            version_number=data.get("version_number", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> InvariantDefinition:
        new_id = uuid4()
        return InvariantDefinition(
            invariant_id=new_id,
            invariant_type=self.invariant_type,
            name=self.name,
            description=self.description,
            scope=self.scope,
            severity=self.severity,
            validation_function_name=self.validation_function_name,
            validation_stage=self.validation_stage,
            is_active=False,
            created_at=datetime.now(UTC),
            created_by=self.created_by,
            approved_by=self.approved_by.copy(),
            version=self.version,
            cryptographic_hash="",
            auto_correct=self.auto_correct,
            correction_action=self.correction_action,
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "invariant_id": str(self.invariant_id),
            "name": self.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InvariantDefinition:
        new_def = self._copy()
        new_def.version_number = self.version_number + 1
        new_def._record_audit("TOUCH", touched_by, {})
        return new_def

    def is_active_rule(self, at_date: datetime | None = None) -> bool:
        check = at_date or datetime.now(UTC)
        if self.deleted_at:
            return False
        return self.is_active

    def _copy(self) -> InvariantDefinition:
        return InvariantDefinition(
            invariant_id=self.invariant_id,
            invariant_type=self.invariant_type,
            name=self.name,
            description=self.description,
            scope=self.scope,
            severity=self.severity,
            validation_function_name=self.validation_function_name,
            validation_stage=self.validation_stage,
            is_active=self.is_active,
            created_at=self.created_at,
            created_by=self.created_by,
            approved_by=self.approved_by.copy(),
            version=self.version,
            cryptographic_hash=self.cryptographic_hash,
            auto_correct=self.auto_correct,
            correction_action=self.correction_action,
            version_number=self.version_number,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class InvariantViolation:
    # Required fields (no defaults)
    violation_id: UUID
    invariant_id: UUID
    invariant_type: InvariantType
    severity: InvariantSeverity
    violated_at: datetime
    actual_value: dict[str, Any]
    expected_value: dict[str, Any]
    difference: dict[str, Any]
    message: str
    offending_module: str
    is_resolved: bool
    # Optional fields (with defaults)
    forensic_evidence_hash: str = ""
    transaction_id: UUID | None = None
    legal_entity_id: UUID | None = None
    period_id: UUID | None = None
    offending_user: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_action: str | None = None
    auto_corrected: bool = False
    auto_correction_applied: str | None = None
    version_number: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.forensic_evidence_hash:
            object.__setattr__(self, "forensic_evidence_hash", self.compute_evidence_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.offending_module, {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version must be >= 1")

    def compute_evidence_hash(self) -> str:
        content = (
            f"{self.violation_id}|{self.invariant_id}|{self.violated_at.isoformat()}|"
            f"{self.transaction_id!s}|{self.legal_entity_id!s}|"
            f"{json.dumps(self.actual_value, sort_keys=True, default=str)[:500]}|"
            f"{json.dumps(self.expected_value, sort_keys=True, default=str)[:500]}|{self.message}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "violation_id": str(self.violation_id),
                "invariant_type": self.invariant_type.name,
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
                "version": self.version_number,
                "violation_id": str(self.violation_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> InvariantViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> InvariantViolation:
        raise AttributeError("InvariantViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> InvariantViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> InvariantViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> InvariantViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> InvariantViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> InvariantViolation:
        return self

    def unlock(self, unlocked_by: str) -> InvariantViolation:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.forensic_evidence_hash != self.compute_evidence_hash():
                errors.append("Forensic hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "violation_id": str(self.violation_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "invariant_id": str(self.invariant_id),
            "invariant_type": self.invariant_type.name,
            "severity": self.severity.name,
            "violated_at": self.violated_at.isoformat(),
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "period_id": str(self.period_id) if self.period_id else None,
            "actual_value": self.actual_value,
            "expected_value": self.expected_value,
            "difference": self.difference,
            "message": self.message,
            "offending_module": self.offending_module,
            "offending_user": self.offending_user,
            "is_resolved": self.is_resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_action": self.resolution_action,
            "forensic_evidence_hash": self.forensic_evidence_hash[:16] + "...",
            "auto_corrected": self.auto_corrected,
            "auto_correction_applied": self.auto_correction_applied,
            "version_number": self.version_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvariantViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            invariant_id=UUID(data["invariant_id"]),
            invariant_type=InvariantType[data["invariant_type"]],
            severity=InvariantSeverity[data["severity"]],
            violated_at=datetime.fromisoformat(data["violated_at"]),
            transaction_id=UUID(data["transaction_id"]) if data.get("transaction_id") else None,
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            period_id=UUID(data["period_id"]) if data.get("period_id") else None,
            actual_value=data["actual_value"],
            expected_value=data["expected_value"],
            difference=data["difference"],
            message=data["message"],
            offending_module=data["offending_module"],
            offending_user=data.get("offending_user"),
            is_resolved=data["is_resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            resolution_action=data.get("resolution_action"),
            forensic_evidence_hash=data.get("forensic_evidence_hash", ""),
            auto_corrected=data.get("auto_corrected", False),
            auto_correction_applied=data.get("auto_correction_applied"),
            version_number=data.get("version_number", 1),
        )

    def clone(self) -> InvariantViolation:
        new_id = uuid4()
        return InvariantViolation(
            violation_id=new_id,
            invariant_id=self.invariant_id,
            invariant_type=self.invariant_type,
            severity=self.severity,
            violated_at=self.violated_at,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            period_id=self.period_id,
            actual_value=self.actual_value.copy(),
            expected_value=self.expected_value.copy(),
            difference=self.difference.copy(),
            message=self.message,
            offending_module=self.offending_module,
            offending_user=self.offending_user,
            is_resolved=False,
            resolved_at=None,
            resolved_by=None,
            resolution_action=None,
            forensic_evidence_hash="",
            auto_corrected=self.auto_corrected,
            auto_correction_applied=self.auto_correction_applied,
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "violation_id": str(self.violation_id),
            "invariant_type": self.invariant_type.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InvariantViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    def resolve(self, by: str, action: str) -> InvariantViolation:
        if self.is_resolved:
            raise ValueError("Already resolved")
        new_violation = self._copy()
        new_violation.is_resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.resolution_action = action
        new_violation.version_number = self.version_number + 1
        new_violation._record_audit("RESOLVE", by, {"action": action})
        return new_violation

    def _copy(self) -> InvariantViolation:
        return InvariantViolation(
            violation_id=self.violation_id,
            invariant_id=self.invariant_id,
            invariant_type=self.invariant_type,
            severity=self.severity,
            violated_at=self.violated_at,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            period_id=self.period_id,
            actual_value=self.actual_value.copy(),
            expected_value=self.expected_value.copy(),
            difference=self.difference.copy(),
            message=self.message,
            offending_module=self.offending_module,
            offending_user=self.offending_user,
            is_resolved=self.is_resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            resolution_action=self.resolution_action,
            forensic_evidence_hash=self.forensic_evidence_hash,
            auto_corrected=self.auto_corrected,
            auto_correction_applied=self.auto_correction_applied,
            version_number=self.version_number,
        )


# === 4. VALIDATION FUNCTIONS (dipertahankan dari kode asli) ===


class InvariantValidator:
    @staticmethod
    def validate_accounting_equation(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        assets = context.get("total_assets", Decimal(0))
        liabilities = context.get("total_liabilities", Decimal(0))
        equity = context.get("total_equity", Decimal(0))
        expected = liabilities + equity
        difference = assets - expected
        tolerance = Decimal("0.01")
        is_valid = abs(difference) <= tolerance
        diff_dict = {
            "assets": str(assets),
            "liabilities": str(liabilities),
            "equity": str(equity),
            "expected": str(expected),
            "difference": str(difference),
            "tolerance": str(tolerance),
        }
        auto_correction = (
            f"Adjust equity by {difference}"
            if not is_valid and abs(difference) > tolerance
            else None
        )
        return is_valid, diff_dict, auto_correction

    @staticmethod
    def validate_double_entry_balance(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        debit = context.get("total_debit", Decimal(0))
        credit = context.get("total_credit", Decimal(0))
        difference = debit - credit
        tolerance = Decimal("0.0001")
        is_valid = abs(difference) <= tolerance
        diff_dict = {
            "total_debit": str(debit),
            "total_credit": str(credit),
            "difference": str(difference),
            "tolerance": str(tolerance),
        }
        auto_correction = (
            "Manual correction required: journal entry must be balanced" if not is_valid else None
        )
        return is_valid, diff_dict, auto_correction

    @staticmethod
    def validate_conservation_of_value(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        source = context.get("source_value", Decimal(0))
        destination = context.get("destination_value", Decimal(0))
        fee = context.get("transaction_fee", Decimal(0))
        expected = source - fee
        difference = destination - expected
        tolerance = Decimal("0.01")
        is_valid = abs(difference) <= tolerance
        diff_dict = {
            "source_value": str(source),
            "destination_value": str(destination),
            "transaction_fee": str(fee),
            "expected": str(expected),
            "difference": str(difference),
        }
        auto_correction = (
            "Review transaction for missing fees or incorrect amounts" if not is_valid else None
        )
        return is_valid, diff_dict, auto_correction

    @staticmethod
    def validate_time_monotonicity(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        tx_time = context.get("transaction_time")
        if tx_time is None:
            return True, {}, None
        if tx_time.tzinfo is None:
            tx_time = tx_time.replace(tzinfo=UTC)
        last_tx = context.get("last_transaction_time")
        if last_tx:
            if last_tx.tzinfo is None:
                last_tx = last_tx.replace(tzinfo=UTC)
            if tx_time < last_tx:
                return (
                    False,
                    {
                        "transaction_time": tx_time.isoformat(),
                        "last_transaction_time": last_tx.isoformat(),
                        "difference_seconds": (last_tx - tx_time).total_seconds(),
                    },
                    "Transaction time cannot be earlier than last transaction",
                )
        period_start = context.get("period_start")
        period_end = context.get("period_end")
        if period_start and period_end:
            if period_start.tzinfo is None:
                period_start = period_start.replace(tzinfo=UTC)
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=UTC)
            if tx_time < period_start or tx_time > period_end:
                return (
                    False,
                    {
                        "transaction_time": tx_time.isoformat(),
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                    },
                    "Transaction time outside period",
                )
        return True, {}, None

    @staticmethod
    def validate_legal_entity_isolation(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        tx_entity = context.get("transaction_legal_entity_id")
        accessed = context.get("accessed_legal_entity_ids", [])
        user_entities = context.get("user_legal_entity_ids", [])
        if tx_entity:
            accessed.append(tx_entity)
        for entity in accessed:
            if entity not in user_entities:
                return (
                    False,
                    {
                        "offending_entity": str(entity),
                        "user_entities": [str(e) for e in user_entities],
                        "accessed_entities": [str(e) for e in accessed],
                    },
                    f"User does not have access to legal entity {entity}",
                )
        return True, {}, None

    @staticmethod
    def validate_currency_consistency(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        currencies = context.get("currencies", set())
        if len(currencies) > 1:
            exchange_rates = context.get("exchange_rates", {})
            for curr in currencies:
                if curr != context.get("base_currency") and curr not in exchange_rates:
                    return (
                        False,
                        {"currencies": list(currencies), "missing_exchange_rate": curr},
                        f"Missing exchange rate for currency {curr}",
                    )
        return True, {}, None

    @staticmethod
    def validate_hash_chain_consistency(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        prev_hash = context.get("previous_hash")
        expected_prev = context.get("expected_previous_hash")
        if prev_hash and expected_prev and prev_hash != expected_prev:
            return (
                False,
                {
                    "previous_hash": prev_hash[:16] + "...",
                    "expected_previous_hash": expected_prev[:16] + "...",
                },
                "Hash chain broken",
            )
        curr_hash = context.get("current_hash")
        if curr_hash:
            content = context.get("content_to_hash", "")
            computed = hashlib.sha3_256(content.encode()).hexdigest()
            if computed != curr_hash:
                return (
                    False,
                    {
                        "computed_hash": computed[:16] + "...",
                        "provided_hash": curr_hash[:16] + "...",
                    },
                    "Hash mismatch: content tampering detected",
                )
        return True, {}, None

    @staticmethod
    def validate_audit_trail_completeness(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        expected = context.get("expected_event_count", 0)
        actual = context.get("actual_event_count", 0)
        missing = context.get("missing_sequence_numbers", [])
        if actual < expected:
            return (
                False,
                {
                    "expected_event_count": expected,
                    "actual_event_count": actual,
                    "missing_count": expected - actual,
                },
                f"Missing {expected - actual} audit events",
            )
        if missing:
            return (
                False,
                {"missing_sequence_numbers": missing[:10], "missing_count": len(missing)},
                f"Missing sequence numbers: {missing[:5]}...",
            )
        return True, {}, None

    @staticmethod
    def validate_idempotency_strict(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        key = context.get("idempotency_key")
        if not key:
            return True, {}, None
        previous = context.get("previous_result")
        current = context.get("current_result")
        if previous is not None and current is not None and previous != current:
            return (
                False,
                {
                    "idempotency_key": key,
                    "previous_result_hash": hashlib.sha3_256(str(previous).encode()).hexdigest()[
                        :16
                    ],
                    "current_result_hash": hashlib.sha3_256(str(current).encode()).hexdigest()[:16],
                },
                "Non-idempotent result for same key",
            )
        return True, {}, None

    @staticmethod
    def validate_non_negative_cash(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        balance = context.get("cash_balance", Decimal(0))
        proposed = context.get("proposed_change", Decimal(0))
        new_balance = balance + proposed
        if new_balance < 0:
            return (
                False,
                {
                    "current_balance": str(balance),
                    "proposed_change": str(proposed),
                    "new_balance": str(new_balance),
                    "deficit": str(abs(new_balance)),
                    "account_id": str(context.get("account_id", "unknown")),
                },
                "Transaction would cause negative cash balance",
            )
        return True, {}, None

    @staticmethod
    def validate_non_negative_inventory(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        qty = context.get("quantity", Decimal(0))
        proposed = context.get("proposed_change", Decimal(0))
        new_qty = qty + proposed
        if new_qty < 0:
            return (
                False,
                {
                    "current_quantity": str(qty),
                    "proposed_change": str(proposed),
                    "new_quantity": str(new_qty),
                    "shortage": str(abs(new_qty)),
                    "item_id": str(context.get("item_id", "unknown")),
                    "warehouse_id": str(context.get("warehouse_id", "unknown")),
                },
                "Insufficient inventory for this transaction",
            )
        return True, {}, None

    @staticmethod
    def validate_non_negative_receivable(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        balance = context.get("receivable_balance", Decimal(0))
        payment = context.get("proposed_payment", Decimal(0))
        new_balance = balance - payment
        if new_balance < 0:
            return (
                False,
                {
                    "current_receivable": str(balance),
                    "proposed_payment": str(payment),
                    "overpayment": str(abs(new_balance)),
                    "customer_id": str(context.get("customer_id", "unknown")),
                },
                "Payment exceeds receivable balance",
            )
        return True, {}, None

    @staticmethod
    def validate_tax_consistency(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        collected = context.get("tax_collected", Decimal(0))
        submitted = context.get("tax_submitted", Decimal(0))
        difference = collected - submitted
        tolerance = Decimal("0.01")
        is_valid = abs(difference) <= tolerance
        diff_dict = {
            "tax_collected": str(collected),
            "tax_submitted": str(submitted),
            "difference": str(difference),
            "tax_period": str(context.get("tax_period", "unknown")),
        }
        return is_valid, diff_dict, None

    @staticmethod
    def validate_period_closure_finality(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        is_closed = context.get("is_closed", False)
        is_reopening = context.get("is_reopening", False)
        if is_closed and is_reopening:
            auth = context.get("reopening_authorization", {})
            if not auth.get("approved_by"):
                return (
                    False,
                    {
                        "period_id": str(context.get("period_id", "unknown")),
                        "reason": "Reopening requires dual approval",
                    },
                    "Reopening requires dual approval from finance and audit",
                )
            if not auth.get("audit_trail_id"):
                return (
                    False,
                    {
                        "period_id": str(context.get("period_id", "unknown")),
                        "reason": "Reopening requires audit trail entry",
                    },
                    "Reopening requires audit trail reference",
                )
        return True, {}, None

    @staticmethod
    def validate_period_integrity(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        tx_date = context.get("transaction_date")
        if not tx_date:
            return True, {}, None
        period_status = context.get("period_status", "OPEN")
        if period_status == "CLOSED":
            return (
                False,
                {"transaction_date": tx_date.isoformat(), "period_status": period_status},
                "Cannot post to closed period",
            )
        if period_status == "LOCKED":
            return (
                False,
                {"transaction_date": tx_date.isoformat(), "period_status": period_status},
                "Period is locked for adjustments",
            )
        period_start = context.get("period_start")
        period_end = context.get("period_end")
        if period_start and period_end:
            if tx_date < period_start or tx_date > period_end:
                return (
                    False,
                    {
                        "transaction_date": tx_date.isoformat(),
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                    },
                    "Transaction date outside period",
                )
        return True, {}, None

    @staticmethod
    def validate_sequence_integrity(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        current = context.get("current_number", 0)
        last = context.get("last_number", 0)
        expected = context.get("expected_next", last + 1)
        allow_gap = context.get("allow_gap", False)
        if not allow_gap and current != expected:
            gap = current - expected if current > expected else expected - current
            return (
                False,
                {
                    "document_type": context.get("document_type", "unknown"),
                    "current_number": current,
                    "expected_number": expected,
                    "last_number": last,
                    "gap": gap,
                },
                f"Sequence gap detected: expected {expected}, got {current}",
            )
        return True, {}, None

    @staticmethod
    def validate_currency_exposure_consistency(
        context: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str | None]:
        foreign = context.get("foreign_currency_amounts", {})
        functional = context.get("functional_currency_amounts", {})
        rates = context.get("exchange_rates", {})
        for currency, amount in foreign.items():
            expected = amount * rates.get(currency, Decimal(1))
            actual = functional.get(currency, Decimal(0))
            if abs(expected - actual) > Decimal("0.01"):
                return (
                    False,
                    {
                        "currency": currency,
                        "foreign_amount": str(amount),
                        "expected_functional": str(expected),
                        "actual_functional": str(actual),
                        "exchange_rate": str(rates.get(currency, 1)),
                    },
                    f"Currency exposure mismatch for {currency}",
                )
        return True, {}, None


# === 5. MAPPING INVARIANT TYPE TO VALIDATOR ===

_INVARIANT_VALIDATOR_MAP: dict[InvariantType, Callable] = {
    InvariantType.ACCOUNTING_EQUATION: InvariantValidator.validate_accounting_equation,
    InvariantType.DOUBLE_ENTRY_BALANCE: InvariantValidator.validate_double_entry_balance,
    InvariantType.CONSERVATION_OF_VALUE: InvariantValidator.validate_conservation_of_value,
    InvariantType.TIME_MONOTONICITY: InvariantValidator.validate_time_monotonicity,
    InvariantType.LEGAL_ENTITY_ISOLATION: InvariantValidator.validate_legal_entity_isolation,
    InvariantType.CURRENCY_CONSISTENCY: InvariantValidator.validate_currency_consistency,
    InvariantType.HASH_CHAIN_CONSISTENCY: InvariantValidator.validate_hash_chain_consistency,
    InvariantType.AUDIT_TRAIL_COMPLETENESS: InvariantValidator.validate_audit_trail_completeness,
    InvariantType.IDEMPOTENCY_STRICT: InvariantValidator.validate_idempotency_strict,
    InvariantType.NON_NEGATIVE_CASH: InvariantValidator.validate_non_negative_cash,
    InvariantType.NON_NEGATIVE_INVENTORY: InvariantValidator.validate_non_negative_inventory,
    InvariantType.NON_NEGATIVE_RECEIVABLE: InvariantValidator.validate_non_negative_receivable,
    InvariantType.TAX_CONSISTENCY: InvariantValidator.validate_tax_consistency,
    InvariantType.PERIOD_CLOSURE_FINALITY: InvariantValidator.validate_period_closure_finality,
    InvariantType.PERIOD_INTEGRITY: InvariantValidator.validate_period_integrity,
    InvariantType.SEQUENCE_INTEGRITY: InvariantValidator.validate_sequence_integrity,
    InvariantType.CURRENCY_EXPOSURE_CONSISTENCY: InvariantValidator.validate_currency_exposure_consistency,
}


def get_validator_for_invariant(invariant_type: InvariantType) -> Callable | None:
    return _INVARIANT_VALIDATOR_MAP.get(invariant_type)


# === 6. CONSTITUTIONAL INVARIANTS AGGREGATE ===


@dataclass(kw_only=True)
class ConstitutionalInvariants:
    invariants: dict[UUID, InvariantDefinition] = field(default_factory=dict)
    violations: list[InvariantViolation] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.invariants:
            self._load_default_invariants()

    def _load_default_invariants(self) -> None:
        now = datetime.now(UTC)
        default_invariants = [
            InvariantDefinition(
                invariant_id=uuid4(),
                invariant_type=InvariantType.ACCOUNTING_EQUATION,
                name="Accounting Equation",
                description="Total assets must equal total liabilities plus equity at all times",
                scope=InvariantScope.GLOBAL,
                severity=InvariantSeverity.CATASTROPHIC,
                validation_function_name="validate_accounting_equation",
                validation_stage=InvariantValidationStage.RECONCILIATION,
                is_active=True,
                created_at=now,
                created_by="system_bootstrap",
                approved_by=["audit_committee_founder", "ceo_founder"],
                version="1.0.0",
                cryptographic_hash="",
                auto_correct=False,
            ),
            InvariantDefinition(
                invariant_id=uuid4(),
                invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
                name="Double Entry Balance",
                description="Every journal entry must have equal debit and credit totals",
                scope=InvariantScope.PER_TRANSACTION,
                severity=InvariantSeverity.CRITICAL,
                validation_function_name="validate_double_entry_balance",
                validation_stage=InvariantValidationStage.PRE_EXECUTION,
                is_active=True,
                created_at=now,
                created_by="system_bootstrap",
                approved_by=["audit_committee_founder", "ceo_founder"],
                version="1.0.0",
                cryptographic_hash="",
                auto_correct=False,
            ),
            InvariantDefinition(
                invariant_id=uuid4(),
                invariant_type=InvariantType.CONSERVATION_OF_VALUE,
                name="Conservation of Value",
                description="Value cannot be created or destroyed, only transferred",
                scope=InvariantScope.PER_TRANSACTION,
                severity=InvariantSeverity.CRITICAL,
                validation_function_name="validate_conservation_of_value",
                validation_stage=InvariantValidationStage.POST_EXECUTION,
                is_active=True,
                created_at=now,
                created_by="system_bootstrap",
                approved_by=["audit_committee_founder", "ceo_founder"],
                version="1.0.0",
                cryptographic_hash="",
                auto_correct=False,
            ),
            # Additional invariants can be added here as needed
        ]
        for inv in default_invariants:
            self.invariants[inv.invariant_id] = inv

    # ==================== REPOSITORY METHODS ====================
    def save_invariant(self, invariant: InvariantDefinition) -> None:
        with self._lock:
            self.invariants[invariant.invariant_id] = invariant

    def get_invariant(self, invariant_id: UUID) -> InvariantDefinition | None:
        return self.invariants.get(invariant_id)

    def get_all_invariants(self) -> list[InvariantDefinition]:
        return list(self.invariants.values())

    def delete_invariant(self, invariant_id: UUID) -> bool:
        with self._lock:
            if invariant_id in self.invariants:
                del self.invariants[invariant_id]
                return True
            return False

    def save_violation(self, violation: InvariantViolation) -> None:
        with self._lock:
            self.violations.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        invariant_type: InvariantType | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        resolved_only: bool = False,
        unresolved_only: bool = False,
    ) -> list[InvariantViolation]:
        result = self.violations[-limit:]
        if invariant_type:
            result = [v for v in result if v.invariant_type == invariant_type]
        if from_date:
            result = [v for v in result if v.violated_at >= from_date]
        if to_date:
            result = [v for v in result if v.violated_at <= to_date]
        if resolved_only:
            result = [v for v in result if v.is_resolved]
        if unresolved_only:
            result = [v for v in result if not v.is_resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, resolution_action: str
    ) -> InvariantViolation | None:
        with self._lock:
            for i, v in enumerate(self.violations):
                if v.violation_id == violation_id and not v.is_resolved:
                    resolved = v.resolve(resolved_by, resolution_action)
                    self.violations[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS ====================
    def validate(
        self,
        invariant_type: InvariantType,
        context: dict[str, Any],
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        period_id: UUID | None = None,
        offending_module: str = "unknown",
        offending_user: str | None = None,
        auto_correct: bool = False,
    ) -> tuple[bool, InvariantViolation | None]:
        inv_def = None
        for inv in self.invariants.values():
            if inv.invariant_type == invariant_type and inv.is_active:
                inv_def = inv
                break
        if not inv_def:
            return True, None
        validator = get_validator_for_invariant(invariant_type)
        if not validator:
            logger.error(f"No validator found for invariant {invariant_type}")
            return True, None
        is_valid, difference, hint = validator(context)
        if is_valid:
            return True, None
        auto_corrected = False
        auto_correction_applied = None
        if auto_correct and inv_def.auto_correct and hint:
            auto_corrected = True
            auto_correction_applied = hint
        violation = InvariantViolation(
            violation_id=uuid4(),
            invariant_id=inv_def.invariant_id,
            invariant_type=invariant_type,
            severity=inv_def.severity,
            violated_at=datetime.now(UTC),
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            actual_value=context,
            expected_value=difference,
            difference=difference,
            message=f"Invariant {inv_def.name} violated: {difference}",
            offending_module=offending_module,
            offending_user=offending_user,
            is_resolved=False,
            resolved_at=None,
            resolved_by=None,
            resolution_action=None,
            forensic_evidence_hash="",
            auto_corrected=auto_corrected,
            auto_correction_applied=auto_correction_applied,
        )
        self.violations.append(violation)
        self._notify_supreme_law(violation)
        if inv_def.severity == InvariantSeverity.CATASTROPHIC:
            self._handle_catastrophic_violation(violation)
        return False, violation

    def _notify_supreme_law(self, violation: InvariantViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            severity_map = {
                InvariantSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                InvariantSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                InvariantSeverity.HIGH: ConstitutionalSeverity.HIGH,
                InvariantSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                InvariantSeverity.LOW: ConstitutionalSeverity.LOW,
            }
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
                offending_module=violation.offending_module,
                message=violation.message,
                offending_user=violation.offending_user,
                offending_command_id=violation.transaction_id,
            )
        except Exception as e:
            logger.critical(f"Failed to notify supreme law of violation: {e}")

    def _handle_catastrophic_violation(self, violation: InvariantViolation) -> None:
        logger.critical(
            f"CATASTROPHIC INVARIANT VIOLATION: {violation.message}. System may need to freeze."
        )

    def validate_all_active(
        self,
        context: dict[str, Any],
        scope_filter: InvariantScope | None = None,
        stage_filter: InvariantValidationStage | None = None,
        **kwargs,
    ) -> list[InvariantViolation]:
        violations = []
        for inv_def in self.invariants.values():
            if not inv_def.is_active:
                continue
            if scope_filter and inv_def.scope != scope_filter:
                continue
            if stage_filter and inv_def.validation_stage != stage_filter:
                continue
            is_valid, violation = self.validate(
                invariant_type=inv_def.invariant_type,
                context=context,
                **kwargs,
            )
            if not is_valid and violation:
                violations.append(violation)
        return violations

    def get_unresolved_violations(self) -> list[InvariantViolation]:
        return [v for v in self.violations if not v.is_resolved]

    def add_invariant(self, definition: InvariantDefinition) -> None:
        with self._lock:
            if definition.cryptographic_hash != definition.compute_hash():
                raise ValueError("Hash mismatch")
            self.invariants[definition.invariant_id] = definition

    def deactivate_invariant(self, invariant_id: UUID, deactivated_by: str) -> None:
        with self._lock:
            if invariant_id in self.invariants:
                inv = self.invariants[invariant_id]
                self.invariants[invariant_id] = inv.deactivate(deactivated_by)

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_invariants = len(self.invariants)
            active_invariants = len([i for i in self.invariants.values() if i.is_active])
            total_violations = len(self.violations)
            unresolved = len([v for v in self.violations if not v.is_resolved])
            by_severity = {}
            for sev in InvariantSeverity:
                count = len([v for v in self.violations if v.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count
            by_type = {}
            for it in InvariantType:
                count = len([v for v in self.violations if v.invariant_type == it])
                if count > 0:
                    by_type[it.name] = count
            auto_corrected = len([v for v in self.violations if v.auto_corrected])
            return {
                "total_invariants": total_invariants,
                "active_invariants": active_invariants,
                "total_violations": total_violations,
                "unresolved_violations": unresolved,
                "by_severity": by_severity,
                "by_type": by_type,
                "auto_corrected_violations": auto_corrected,
                "latest_violation": self.violations[-1].violated_at.isoformat()
                if self.violations
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self.invariants = {}
            self.violations = []
            self._load_default_invariants()


# === 7. CONSTITUTIONAL INVARIANTS SERVICE ===


class ConstitutionalInvariantsService:
    _instance: ConstitutionalInvariantsService | None = None
    _invariants: ConstitutionalInvariants | None = None

    def __new__(cls) -> ConstitutionalInvariantsService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._invariants = ConstitutionalInvariants()

    # ==================== REPOSITORY METHODS ====================
    def save_invariant(self, invariant: InvariantDefinition) -> None:
        self._invariants.save_invariant(invariant)

    def get_invariant(self, invariant_id: UUID) -> InvariantDefinition | None:
        return self._invariants.get_invariant(invariant_id)

    def get_all_invariants(self) -> list[InvariantDefinition]:
        return self._invariants.get_all_invariants()

    def delete_invariant(self, invariant_id: UUID) -> bool:
        return self._invariants.delete_invariant(invariant_id)

    def save_violation(self, violation: InvariantViolation) -> None:
        self._invariants.save_violation(violation)

    def get_violations(self, limit: int = 100, **filters) -> list[InvariantViolation]:
        return self._invariants.get_violations(limit, **filters)

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, resolution_action: str
    ) -> InvariantViolation | None:
        return self._invariants.resolve_violation(violation_id, resolved_by, resolution_action)

    # ==================== BUSINESS METHODS ====================
    def validate(
        self,
        invariant_type: InvariantType,
        context: dict[str, Any],
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        period_id: UUID | None = None,
        offending_module: str = "unknown",
        offending_user: str | None = None,
        auto_correct: bool = False,
    ) -> tuple[bool, InvariantViolation | None]:
        is_valid, violation = self._invariants.validate(
            invariant_type=invariant_type,
            context=context,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            offending_module=offending_module,
            offending_user=offending_user,
            auto_correct=auto_correct,
        )
        if violation and violation.severity == InvariantSeverity.CATASTROPHIC:
            raise InvariantViolationError(
                invariant_type=invariant_type,
                message=violation.message,
                severity=violation.severity,
                context=context,
            )
        return is_valid, violation

    def validate_all(
        self, context: dict[str, Any], stage: InvariantValidationStage | None = None, **kwargs
    ) -> list[InvariantViolation]:
        return self._invariants.validate_all_active(context, stage_filter=stage, **kwargs)

    def validate_accounting_equation(
        self, total_assets: Decimal, total_liabilities: Decimal, total_equity: Decimal, **kwargs
    ) -> tuple[bool, InvariantViolation | None]:
        context = {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
        }
        return self.validate(InvariantType.ACCOUNTING_EQUATION, context, **kwargs)

    def validate_double_entry(
        self, total_debit: Decimal, total_credit: Decimal, **kwargs
    ) -> tuple[bool, InvariantViolation | None]:
        context = {"total_debit": total_debit, "total_credit": total_credit}
        return self.validate(InvariantType.DOUBLE_ENTRY_BALANCE, context, **kwargs)

    def validate_period_integrity(
        self,
        transaction_date: datetime,
        period_start: datetime,
        period_end: datetime,
        period_status: str = "OPEN",
        **kwargs,
    ) -> tuple[bool, InvariantViolation | None]:
        context = {
            "transaction_date": transaction_date,
            "period_start": period_start,
            "period_end": period_end,
            "period_status": period_status,
        }
        return self.validate(InvariantType.PERIOD_INTEGRITY, context, **kwargs)

    def validate_legal_entity_isolation(
        self,
        transaction_legal_entity_id: UUID,
        accessed_legal_entity_ids: list[UUID],
        user_legal_entity_ids: list[UUID],
        **kwargs,
    ) -> tuple[bool, InvariantViolation | None]:
        context = {
            "transaction_legal_entity_id": transaction_legal_entity_id,
            "accessed_legal_entity_ids": accessed_legal_entity_ids,
            "user_legal_entity_ids": user_legal_entity_ids,
        }
        return self.validate(InvariantType.LEGAL_ENTITY_ISOLATION, context, **kwargs)

    def validate_non_negative_cash(
        self, current_balance: Decimal, proposed_change: Decimal, **kwargs
    ) -> tuple[bool, InvariantViolation | None]:
        context = {"cash_balance": current_balance, "proposed_change": proposed_change}
        return self.validate(InvariantType.NON_NEGATIVE_CASH, context, **kwargs)

    def get_active_invariants(self) -> list[InvariantDefinition]:
        return [inv for inv in self._invariants.invariants.values() if inv.is_active]

    def get_violation_report(self) -> dict[str, Any]:
        return self._invariants.get_statistics()

    def get_violation_history(self, limit: int = 100, **filters) -> list[InvariantViolation]:
        return self._invariants.get_violations(limit, **filters)


def get_constitutional_invariants_service() -> ConstitutionalInvariantsService:
    global _constitutional_invariants_service_instance
    if _constitutional_invariants_service_instance is None:
        _constitutional_invariants_service_instance = ConstitutionalInvariantsService()
    return _constitutional_invariants_service_instance


_constitutional_invariants_service_instance: ConstitutionalInvariantsService | None = None

__all__ = [
    "ConstitutionalInvariants",
    "ConstitutionalInvariantsService",
    "InvariantDefinition",
    "InvariantScope",
    "InvariantSeverity",
    "InvariantType",
    "InvariantValidationStage",
    "InvariantValidator",
    "InvariantViolation",
    "InvariantViolationError",
    "get_constitutional_invariants_service",
    "get_validator_for_invariant",
]
