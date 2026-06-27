#!/usr/bin/env python3
"""
Module: axiom_violation.py
Layer: 2 - Foundation / Axioms
Responsibility: Exception dan mekanisme pelaporan untuk semua pelanggaran aksioma.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

# Import enums dari axioms lain (dengan fallback jika belum import)
try:
    from axioms.accrual_basis import AccrualBasisSeverity
except ImportError:
    AccrualBasisSeverity = None
try:
    from axioms.causality_chain import CausalityViolationSeverity
except ImportError:
    CausalityViolationSeverity = None
try:
    from axioms.conservation_of_value import ConservationViolationSeverity
except ImportError:
    ConservationViolationSeverity = None
try:
    from axioms.double_entry import DoubleEntryViolationSeverity
except ImportError:
    DoubleEntryViolationSeverity = None
try:
    from axioms.entity_isolation import EntityIsolationViolationSeverity
except ImportError:
    EntityIsolationViolationSeverity = None
try:
    from axioms.going_concern import GoingConcernSeverity
except ImportError:
    GoingConcernSeverity = None
try:
    from axioms.immutability import ImmutabilityViolationSeverity
except ImportError:
    ImmutabilityViolationSeverity = None
try:
    from axioms.materiality import MaterialitySeverity
except ImportError:
    MaterialitySeverity = None
try:
    from axioms.monetary_unit import MonetaryUnitViolationSeverity
except ImportError:
    MonetaryUnitViolationSeverity = None
try:
    from axioms.period_bound import PeriodBoundViolationSeverity
except ImportError:
    PeriodBoundViolationSeverity = None
try:
    from axioms.substance_over_form import SubstanceAssessmentSeverity
except ImportError:
    SubstanceAssessmentSeverity = None
try:
    from axioms.time_irreversibility import TimeIrreversibilityViolationSeverity
except ImportError:
    TimeIrreversibilityViolationSeverity = None

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class AxiomType(Enum):
    CONSERVATION_OF_VALUE = auto()
    DOUBLE_ENTRY = auto()
    TIME_IRREVERSIBILITY = auto()
    IMMUTABILITY = auto()
    CAUSALITY_CHAIN = auto()
    MONETARY_UNIT = auto()
    ENTITY_ISOLATION = auto()
    PERIOD_BOUND = auto()
    GOING_CONCERN = auto()
    ACCRUAL_BASIS = auto()
    MATERIALITY = auto()
    SUBSTANCE_OVER_FORM = auto()


class AxiomViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0

    @classmethod
    def from_axiom_severity(
        cls, axiom_type: AxiomType, severity_value: int
    ) -> AxiomViolationSeverity:
        if severity_value >= 80:
            return cls.CATASTROPHIC if severity_value >= 100 else cls.CRITICAL
        elif severity_value >= 60:
            return cls.HIGH
        elif severity_value >= 40:
            return cls.MEDIUM
        elif severity_value >= 20:
            return cls.LOW
        return cls.INFO


# === 2. VALUE OBJECT: AXIOM VIOLATION RECORD ===


@dataclass(kw_only=True)
class AxiomViolationRecord:
    record_id: UUID
    axiom_type: AxiomType
    axiom_name: str
    transaction_id: UUID | None
    legal_entity_id: UUID | None
    user_id: str | None
    module: str
    severity: AxiomViolationSeverity
    original_severity_value: int
    message: str
    context: dict[str, Any]
    stack_trace: str
    detected_at: datetime
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.user_id or "system", {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.record_id}|{self.axiom_type.value}|{self.transaction_id}|{self.severity.value}|{self.message[:100]}|{self.detected_at.isoformat()}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "record_id": str(self.record_id),
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
                "record_id": str(self.record_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> AxiomViolationRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> AxiomViolationRecord:
        raise AttributeError("AxiomViolationRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> AxiomViolationRecord:
        raise AttributeError("AxiomViolationRecord cannot be deleted")

    def restore(self, restored_by: str) -> AxiomViolationRecord:
        raise AttributeError("AxiomViolationRecord cannot be restored")

    def activate(self, activated_by: str) -> AxiomViolationRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AxiomViolationRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> AxiomViolationRecord:
        return self

    def unlock(self, unlocked_by: str) -> AxiomViolationRecord:
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
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "axiom_type": self.axiom_type.name,
            "axiom_name": self.axiom_name,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "user_id": self.user_id,
            "module": self.module,
            "severity": self.severity.name,
            "original_severity_value": self.original_severity_value,
            "message": self.message[:200],
            "context": self.context,
            "stack_trace": self.stack_trace[:500] if self.stack_trace else None,
            "detected_at": self.detected_at.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_note": self.resolution_note,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AxiomViolationRecord:
        return cls(
            record_id=UUID(data["record_id"]),
            axiom_type=AxiomType[data["axiom_type"]],
            axiom_name=data["axiom_name"],
            transaction_id=UUID(data["transaction_id"]) if data.get("transaction_id") else None,
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            user_id=data.get("user_id"),
            module=data["module"],
            severity=AxiomViolationSeverity[data["severity"]],
            original_severity_value=data["original_severity_value"],
            message=data["message"],
            context=data.get("context", {}),
            stack_trace=data.get("stack_trace", ""),
            detected_at=datetime.fromisoformat(data["detected_at"]),
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            resolution_note=data.get("resolution_note"),
            version=data.get("version", 1),
        )

    def clone(self) -> AxiomViolationRecord:
        new_id = uuid4()
        return AxiomViolationRecord(
            record_id=new_id,
            axiom_type=self.axiom_type,
            axiom_name=self.axiom_name,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            user_id=self.user_id,
            module=self.module,
            severity=self.severity,
            original_severity_value=self.original_severity_value,
            message=self.message,
            context=self.context.copy(),
            stack_trace=self.stack_trace,
            detected_at=self.detected_at,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            resolution_note=self.resolution_note,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "record_id": str(self.record_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AxiomViolationRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str, note: str) -> AxiomViolationRecord:
        if self.resolved:
            raise ValueError("Already resolved")
        new_record = AxiomViolationRecord(
            record_id=self.record_id,
            axiom_type=self.axiom_type,
            axiom_name=self.axiom_name,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            user_id=self.user_id,
            module=self.module,
            severity=self.severity,
            original_severity_value=self.original_severity_value,
            message=self.message,
            context=self.context,
            stack_trace=self.stack_trace,
            detected_at=self.detected_at,
            resolved=True,
            resolved_at=datetime.now(UTC),
            resolved_by=by,
            resolution_note=note,
            version=self.version + 1,
        )
        new_record._record_audit("RESOLVE", by, {"note": note})
        return new_record


# === 3. BASE EXCEPTION ===


class AxiomViolationError(Exception):
    def __init__(
        self,
        message: str,
        axiom_type: AxiomType,
        severity: AxiomViolationSeverity,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
        module: str = "unknown",
        context: dict[str, Any] | None = None,
        original_severity_value: int = 0,
    ):
        self.axiom_type = axiom_type
        self.severity = severity
        self.transaction_id = transaction_id
        self.legal_entity_id = legal_entity_id
        self.user_id = user_id
        self.module = module
        self.context = context or {}
        self.original_severity_value = original_severity_value
        self.timestamp = datetime.now(UTC)
        full_message = f"[{axiom_type.name}][{severity.name}] {message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_record(self) -> AxiomViolationRecord:
        import traceback as tb

        return AxiomViolationRecord(
            record_id=uuid4(),
            axiom_type=self.axiom_type,
            axiom_name=self.axiom_type.name,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            user_id=self.user_id,
            module=self.module,
            severity=self.severity,
            original_severity_value=self.original_severity_value,
            message=self._original_message,
            context=self.context,
            stack_trace=tb.format_exc(),
            detected_at=self.timestamp,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            resolution_note=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_type": self.__class__.__name__,
            "axiom_type": self.axiom_type.name,
            "severity": self.severity.name,
            "severity_value": self.severity.value,
            "message": self._original_message,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "user_id": self.user_id,
            "module": self.module,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
        }


# === 4. CONCRETE EXCEPTIONS PER AXIOM ===


class ConservationOfValueViolation(AxiomViolationError):
    def __init__(
        self,
        message: str,
        source_value: Decimal,
        destination_value: Decimal,
        difference: Decimal,
        transaction_id: UUID | None = None,
        severity: AxiomViolationSeverity = AxiomViolationSeverity.CRITICAL,
        **kwargs,
    ):
        self.source_value = source_value
        self.destination_value = destination_value
        self.difference = difference
        super().__init__(
            message=message,
            axiom_type=AxiomType.CONSERVATION_OF_VALUE,
            severity=severity,
            transaction_id=transaction_id,
            **kwargs,
        )


class DoubleEntryViolation(AxiomViolationError):
    def __init__(
        self,
        message: str,
        total_debit: Decimal,
        total_credit: Decimal,
        difference: Decimal,
        journal_id: UUID | None = None,
        **kwargs,
    ):
        self.total_debit = total_debit
        self.total_credit = total_credit
        self.difference = difference
        self.journal_id = journal_id
        super().__init__(
            message=message, axiom_type=AxiomType.DOUBLE_ENTRY, transaction_id=journal_id, **kwargs
        )


class TimeIrreversibilityViolation(AxiomViolationError):
    def __init__(
        self,
        message: str,
        attempted_date: datetime,
        current_period_start: datetime,
        backdate_days: int,
        **kwargs,
    ):
        self.attempted_date = attempted_date
        self.current_period_start = current_period_start
        self.backdate_days = backdate_days
        super().__init__(message=message, axiom_type=AxiomType.TIME_IRREVERSIBILITY, **kwargs)


class ImmutabilityViolation(AxiomViolationError):
    def __init__(self, message: str, target_record_id: UUID, attempted_operation: str, **kwargs):
        self.target_record_id = target_record_id
        self.attempted_operation = attempted_operation
        super().__init__(
            message=message,
            axiom_type=AxiomType.IMMUTABILITY,
            transaction_id=target_record_id,
            **kwargs,
        )


class CausalityChainViolation(AxiomViolationError):
    def __init__(self, message: str, missing_evidence: list[str], incomplete_chain: bool, **kwargs):
        self.missing_evidence = missing_evidence
        self.incomplete_chain = incomplete_chain
        super().__init__(message=message, axiom_type=AxiomType.CAUSALITY_CHAIN, **kwargs)


class MonetaryUnitViolation(AxiomViolationError):
    def __init__(self, message: str, currency_used: str, functional_currency: str, **kwargs):
        self.currency_used = currency_used
        self.functional_currency = functional_currency
        super().__init__(message=message, axiom_type=AxiomType.MONETARY_UNIT, **kwargs)


class EntityIsolationViolation(AxiomViolationError):
    def __init__(
        self,
        message: str,
        source_entity_id: UUID,
        target_entity_id: UUID,
        attempted_operation: str,
        **kwargs,
    ):
        self.source_entity_id = source_entity_id
        self.target_entity_id = target_entity_id
        self.attempted_operation = attempted_operation
        super().__init__(
            message=message,
            axiom_type=AxiomType.ENTITY_ISOLATION,
            legal_entity_id=source_entity_id,
            **kwargs,
        )


class PeriodBoundViolation(AxiomViolationError):
    def __init__(self, message: str, transaction_date: datetime, period_status: str, **kwargs):
        self.transaction_date = transaction_date
        self.period_status = period_status
        super().__init__(message=message, axiom_type=AxiomType.PERIOD_BOUND, **kwargs)


class GoingConcernViolation(AxiomViolationError):
    def __init__(self, message: str, assessment_status: str | None = None, **kwargs):
        self.assessment_status = assessment_status
        super().__init__(message=message, axiom_type=AxiomType.GOING_CONCERN, **kwargs)


class AccrualBasisViolation(AxiomViolationError):
    def __init__(
        self,
        message: str,
        recognition_date: datetime,
        cash_flow_date: datetime,
        difference_days: int,
        **kwargs,
    ):
        self.recognition_date = recognition_date
        self.cash_flow_date = cash_flow_date
        self.difference_days = difference_days
        super().__init__(message=message, axiom_type=AxiomType.ACCRUAL_BASIS, **kwargs)


class MaterialityViolation(AxiomViolationError):
    def __init__(
        self, message: str, item_amount: Decimal, threshold: Decimal, failure_type: str, **kwargs
    ):
        self.item_amount = item_amount
        self.threshold = threshold
        self.failure_type = failure_type
        super().__init__(message=message, axiom_type=AxiomType.MATERIALITY, **kwargs)


class SubstanceOverFormViolation(AxiomViolationError):
    def __init__(self, message: str, legal_form_summary: str, proper_treatment: str, **kwargs):
        self.legal_form_summary = legal_form_summary
        self.proper_treatment = proper_treatment
        super().__init__(message=message, axiom_type=AxiomType.SUBSTANCE_OVER_FORM, **kwargs)


# === 5. AXIOM VIOLATION HANDLER (dengan repository methods) ===


class AxiomViolationHandler:
    _instance: AxiomViolationHandler | None = None
    _violations: list[AxiomViolationRecord] = []
    _lock = threading.Lock()

    def __new__(cls) -> AxiomViolationHandler:
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
        self._violations = []

    def handle(
        self, exception: AxiomViolationError, record: bool = True, notify: bool = True
    ) -> AxiomViolationRecord:
        record_obj = exception.to_record()
        if record:
            with self._lock:
                self._violations.append(record_obj)
        log_msg = f"Axiom violation: {exception.axiom_type.name} - {exception.original_message}"
        if exception.severity.value >= AxiomViolationSeverity.HIGH.value:
            logger.error(log_msg, exc_info=True)
        else:
            logger.warning(log_msg)
        if notify and exception.severity.value >= AxiomViolationSeverity.HIGH.value:
            self._send_notification(record_obj)
        return record_obj

    def _send_notification(self, record: AxiomViolationRecord) -> None:
        logger.info(f"NOTIFICATION: {record.axiom_name} violation - {record.message[:100]}")

    # ==================== REPOSITORY METHODS ====================
    def save_violation(self, record: AxiomViolationRecord) -> None:
        with self._lock:
            self._violations.append(record)

    def get_violations(
        self,
        axiom_type: AxiomType | None = None,
        min_severity: AxiomViolationSeverity | None = None,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        unresolved_only: bool = False,
        limit: int = 100,
    ) -> list[AxiomViolationRecord]:
        result = self._violations[-limit:] if limit else self._violations
        if axiom_type:
            result = [v for v in result if v.axiom_type == axiom_type]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if transaction_id:
            result = [v for v in result if v.transaction_id == transaction_id]
        if legal_entity_id:
            result = [v for v in result if v.legal_entity_id == legal_entity_id]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def get_violation(self, record_id: UUID) -> AxiomViolationRecord | None:
        with self._lock:
            for v in self._violations:
                if v.record_id == record_id:
                    return v
            return None

    def resolve_violation(
        self, record_id: UUID, resolved_by: str, resolution_note: str
    ) -> AxiomViolationRecord | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.record_id == record_id and not v.resolved:
                    resolved = v.resolve(resolved_by, resolution_note)
                    self._violations[i] = resolved
                    logger.info(f"Violation {record_id} resolved by {resolved_by}")
                    return resolved
            return None

    def delete_violation(self, record_id: UUID) -> bool:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.record_id == record_id:
                    del self._violations[i]
                    return True
            return False

    def count_violations(self) -> int:
        with self._lock:
            return len(self._violations)

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._violations)
            unresolved = len([v for v in self._violations if not v.resolved])
            by_axiom = {}
            for v in self._violations:
                by_axiom[v.axiom_name] = by_axiom.get(v.axiom_name, 0) + 1
            by_severity = {}
            for sev in AxiomViolationSeverity:
                count = len([v for v in self._violations if v.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count
            return {
                "total_violations": total,
                "unresolved_count": unresolved,
                "by_axiom": by_axiom,
                "by_severity": by_severity,
                "latest_violation": self._violations[-1].detected_at.isoformat()
                if self._violations
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._violations = []


# === 6. SINGLETON ACCESSOR ===

_handler_instance: AxiomViolationHandler | None = None


def get_axiom_violation_handler() -> AxiomViolationHandler:
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = AxiomViolationHandler()
    return _handler_instance


# === 7. CONVENIENCE FUNCTIONS ===


def raise_conservation_violation(
    message: str,
    source_value: Decimal,
    destination_value: Decimal,
    difference: Decimal,
    transaction_id: UUID | None = None,
    **kwargs,
) -> None:
    exc = ConservationOfValueViolation(
        message=message,
        source_value=source_value,
        destination_value=destination_value,
        difference=difference,
        transaction_id=transaction_id,
        **kwargs,
    )
    handler = get_axiom_violation_handler()
    handler.handle(exc, record=True, notify=True)
    raise exc


def raise_double_entry_violation(
    message: str,
    total_debit: Decimal,
    total_credit: Decimal,
    difference: Decimal,
    journal_id: UUID | None = None,
    **kwargs,
) -> None:
    exc = DoubleEntryViolation(
        message=message,
        total_debit=total_debit,
        total_credit=total_credit,
        difference=difference,
        journal_id=journal_id,
        **kwargs,
    )
    handler = get_axiom_violation_handler()
    handler.handle(exc)
    raise exc


def handle_axiom_violation(exc: Exception) -> AxiomViolationRecord | None:
    if isinstance(exc, AxiomViolationError):
        return get_axiom_violation_handler().handle(exc)
    else:
        wrapped = AxiomViolationError(
            message=str(exc),
            axiom_type=AxiomType.CONSERVATION_OF_VALUE,
            severity=AxiomViolationSeverity.MEDIUM,
            module="unknown",
        )
        return get_axiom_violation_handler().handle(wrapped)


# === 8. EXPORTS ===

__all__ = [
    # Enums
    "AxiomType",
    "AxiomViolationSeverity",
    # Record
    "AxiomViolationRecord",
    # Base exception
    "AxiomViolationError",
    # Concrete exceptions
    "ConservationOfValueViolation",
    "DoubleEntryViolation",
    "TimeIrreversibilityViolation",
    "ImmutabilityViolation",
    "CausalityChainViolation",
    "MonetaryUnitViolation",
    "EntityIsolationViolation",
    "PeriodBoundViolation",
    "GoingConcernViolation",
    "AccrualBasisViolation",
    "MaterialityViolation",
    "SubstanceOverFormViolation",
    # Handler
    "AxiomViolationHandler",
    "get_axiom_violation_handler",
    # Convenience
    "raise_conservation_violation",
    "raise_double_entry_violation",
    "handle_axiom_violation",
]
