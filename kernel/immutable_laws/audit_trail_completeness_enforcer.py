#!/usr/bin/env python3
"""
Module: audit_trail_completeness_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: audit trail harus lengkap tanpa celah.
               Memastikan bahwa setiap perubahan data dalam sistem memiliki
               audit trail yang lengkap, berkesinambungan, dan tidak dapat
               diubah. Setiap transaksi harus tercatat dalam event store
               dengan hash chain yang terhubung.

Dependencies:
- standard library (hashlib, logging, dataclass, datetime, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, AuditTrailCompletenessViolation)

Audit: Setiap celah dalam audit trail dictat sebagai pelanggaran berat.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    AuditTrailCompletenessViolation,
    LawViolationSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackAuditRepository:
    """Fallback audit repository dengan in-memory storage dan hash chain."""

    def __init__(self):
        self._events: list[dict[str, Any]] = []
        self._by_transaction: dict[UUID, list[int]] = {}
        self._last_sequence: dict[UUID, int] = {}
        self._last_hash: dict[UUID, str] = {}

    async def get_by_transaction(self, transaction_id: UUID, legal_entity_id: UUID) -> list[Any]:
        indices = self._by_transaction.get(transaction_id, [])
        return [self._events[i] for i in indices if i < len(self._events)]

    async def get_by_time_range(
        self,
        legal_entity_id: UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Any]:
        result = []
        for e in self._events:
            ts = e.get("timestamp")
            if ts and from_date <= ts <= to_date:
                if e.get("legal_entity_id") == legal_entity_id:
                    result.append(_AuditEventProxy(e))
        return result

    async def get_last_event(self, legal_entity_id: UUID) -> Any | None:
        for e in reversed(self._events):
            if e.get("legal_entity_id") == legal_entity_id:
                return _AuditEventProxy(e)
        return None

    async def create_event(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        event_type: str,
        event_data: dict[str, Any],
        user_id: str,
        sequence_number: int,
        previous_hash: str | None,
        timestamp: datetime,
    ) -> UUID:
        event_id = uuid4()
        content = (
            f"{event_id}|{transaction_id}|{sequence_number}|"
            f"{json.dumps(event_data, sort_keys=True)}|"
            f"{previous_hash or ''}|{timestamp.isoformat()}"
        )
        current_hash = hashlib.sha3_256(content.encode()).hexdigest()

        event = {
            "event_id": event_id,
            "transaction_id": transaction_id,
            "legal_entity_id": legal_entity_id,
            "event_type": event_type,
            "event_data": event_data,
            "user_id": user_id,
            "sequence_number": sequence_number,
            "previous_hash": previous_hash,
            "current_hash": current_hash,
            "timestamp": timestamp,
        }
        self._events.append(event)
        idx = len(self._events) - 1
        self._by_transaction.setdefault(transaction_id, []).append(idx)
        self._last_sequence[legal_entity_id] = sequence_number
        self._last_hash[legal_entity_id] = current_hash
        return event_id

    def clear(self) -> None:
        self._events.clear()
        self._by_transaction.clear()
        self._last_sequence.clear()
        self._last_hash.clear()


class _AuditEventProxy:
    """Proxy untuk audit event dari fallback repository."""

    def __init__(self, data: dict[str, Any]):
        self.event_id = data.get("event_id")
        self.transaction_id = data.get("transaction_id")
        self.legal_entity_id = data.get("legal_entity_id")
        self.event_type = data.get("event_type")
        self.event_data = data.get("event_data")
        self.user_id = data.get("user_id")
        self.sequence_number = data.get("sequence_number")
        self.previous_hash = data.get("previous_hash")
        self.current_hash = data.get("current_hash")
        self.timestamp = data.get("timestamp")


class _FallbackEventStore:
    """Fallback event store (simulasi append-only)."""

    def __init__(self):
        self._events: list[dict[str, Any]] = []

    async def append(self, event: Any) -> None:
        self._events.append({"event": event})

    def clear(self) -> None:
        self._events.clear()


# === 2. CONSTANTS & ENUMS ===


class AuditEventType(Enum):
    """Jenis event audit."""

    TRANSACTION_START = "transaction_start"
    TRANSACTION_COMMIT = "transaction_commit"
    TRANSACTION_ROLLBACK = "transaction_rollback"
    DATA_CREATE = "data_create"
    DATA_UPDATE = "data_update"
    DATA_DELETE = "data_delete"
    STATE_CHANGE = "state_change"
    APPROVAL = "approval"
    REJECTION = "rejection"
    SYSTEM_EVENT = "system_event"


class AuditTrailSeverity(Enum):
    """Severity untuk masalah audit trail."""

    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


@dataclass
class AuditEvent:
    """Event audit individual."""

    event_id: UUID
    transaction_id: UUID
    legal_entity_id: UUID
    event_type: AuditEventType
    event_data: dict[str, Any]
    user_id: str
    sequence_number: int
    previous_hash: str | None
    current_hash: str
    timestamp: datetime
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.event_id}|{self.transaction_id}|{self.sequence_number}|"
            f"{json.dumps(self.event_data, sort_keys=True)[:500]}|{self.previous_hash or ''}|"
            f"{self.timestamp.isoformat()}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "transaction_id": str(self.transaction_id),
            "legal_entity_id": str(self.legal_entity_id),
            "event_type": self.event_type.value,
            "user_id": self.user_id,
            "sequence_number": self.sequence_number,
            "previous_hash": self.previous_hash[:16] + "..." if self.previous_hash else None,
            "current_hash": self.current_hash[:16] + "...",
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AuditTrailReport:
    """Laporan kelengkapan audit trail."""

    legal_entity_id: UUID
    from_date: datetime | None
    to_date: datetime | None
    total_events: int
    has_gaps: bool
    first_sequence: int | None
    last_sequence: int | None
    missing_sequences: list[int]
    broken_hash_chain: bool
    broken_at_sequence: int | None
    severity: AuditTrailSeverity
    message: str
    generated_at: datetime


# ============================================================================
# BASE AUDIT TRAIL COMPLETENESS ENFORCER (ABSTRACT)
# ============================================================================

class BaseAuditTrailCompletenessEnforcer(ABC):
    """Base contract untuk Audit Trail Completeness Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    async def enforce_completeness(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, AuditTrailCompletenessViolation | None]:
        """Enforce audit trail completeness for a transaction."""
        pass

    @abstractmethod
    async def enforce_no_gap_between_transactions(
        self,
        legal_entity_id: UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> AuditTrailReport:
        """Check for time gaps between transactions."""
        pass

    @abstractmethod
    async def record_audit_event(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        event_type: AuditEventType,
        event_data: dict[str, Any],
        user_id: str,
        sequence_number: int | None = None,
    ) -> UUID:
        """Record an audit event with hash chain."""
        pass

    @abstractmethod
    async def get_audit_trail_summary(
        self,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> AuditTrailReport:
        """Get audit trail summary."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        min_severity: LawViolationSeverity = LawViolationSeverity.LOW,
    ) -> list[AuditTrailCompletenessViolation]:
        """Get violation history."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset state."""
        pass

    # ==================== CHECKER METHODS ====================

    @abstractmethod
    def check(self, context: dict) -> list[str]:
        """Sync check method untuk compliance checker."""
        pass

    @abstractmethod
    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseAuditTrailCompletenessEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseAuditTrailCompletenessEnforcer:
        """Clone instance."""
        pass

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        pass

    @abstractmethod
    def version(self) -> int:
        """Dapatkan versi."""
        pass

    @abstractmethod
    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        pass

    @abstractmethod
    def touch(self, touched_by: str) -> BaseAuditTrailCompletenessEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# AUDIT TRAIL COMPLETENESS ENFORCER (CONCRETE)
# ============================================================================

class AuditTrailCompletenessEnforcer(BaseAuditTrailCompletenessEnforcer):
    """
    Enforcer untuk kelengkapan audit trail.

    Business context: Audit trail harus lengkap, berkesinambungan,
    dan tidak boleh ada celah. Setiap transaksi harus tercatat.
    """

    MAX_TIME_GAP_SECONDS = 3600

    def __init__(self, audit_repo: Any | None = None, event_store: Any | None = None):
        self._audit_repo = audit_repo or _FallbackAuditRepository()
        self._event_store = event_store or _FallbackEventStore()
        self._violation_history: list[AuditTrailCompletenessViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        # Entity fields
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        transaction_id = context.get("transaction_id")
        legal_entity_id = context.get("legal_entity_id")

        if not transaction_id:
            errors.append("transaction_id is required")
        else:
            try:
                UUID(str(transaction_id))
            except Exception:
                errors.append("transaction_id must be a valid UUID")
        if not legal_entity_id:
            errors.append("legal_entity_id is required")
        else:
            try:
                UUID(str(legal_entity_id))
            except Exception:
                errors.append("legal_entity_id must be a valid UUID")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if self.MAX_TIME_GAP_SECONDS <= 0:
            errors.append("MAX_TIME_GAP_SECONDS must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "max_history": self._max_history,
                "max_time_gap_seconds": self.MAX_TIME_GAP_SECONDS,
                "violations_count": len(self._violation_history),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditTrailCompletenessEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> AuditTrailCompletenessEnforcer:
        """Clone instance."""
        new_instance = AuditTrailCompletenessEnforcer()
        new_instance._enabled = self._enabled
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "violations_count": len(self._violation_history),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AuditTrailCompletenessEnforcer:
        """Touch instance (increment version)."""
        self._version += 1
        self._audit_trail.append({
            "action": "TOUCH",
            "performed_by": touched_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
        })
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "details": details,
        })

    # ==================== ORIGINAL BUSINESS METHODS ====================

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"Audit trail completeness enforcer enabled: {enabled}")

    async def enforce_completeness(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, AuditTrailCompletenessViolation | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        events = await self._audit_repo.get_by_transaction(transaction_id, legal_entity_id)
        if not events:
            violation = AuditTrailCompletenessViolation(
                message=f"Transaction {transaction_id} has no audit trail events",
                transaction_id=str(transaction_id),
                gap_sequence=None,
                severity=LawViolationSeverity.CRITICAL,
                details={"transaction_id": str(transaction_id)},
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise violation
            return False, violation

        seq_numbers = sorted([getattr(e, "sequence_number", 0) for e in events])
        missing = []
        for i in range(1, len(seq_numbers)):
            expected = seq_numbers[i - 1] + 1
            if seq_numbers[i] != expected:
                missing.extend(range(expected, seq_numbers[i]))

        if missing:
            violation = AuditTrailCompletenessViolation(
                message=(
                    f"Audit trail gap detected in transaction {transaction_id}: "
                    f"missing sequences {missing[:10]}"
                ),
                transaction_id=str(transaction_id),
                gap_sequence=missing[0] if missing else None,
                severity=LawViolationSeverity.CATASTROPHIC,
                details={
                    "transaction_id": str(transaction_id),
                    "missing_sequences": missing[:20],
                    "found_sequences": seq_numbers,
                },
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise violation
            return False, violation

        # Verify hash chain continuity
        prev_hash = None
        broken_at = None
        for event in sorted(events, key=lambda e: getattr(e, "sequence_number", 0)):
            event_prev = getattr(event, "previous_hash", None)
            if prev_hash and event_prev != prev_hash:
                broken_at = getattr(event, "sequence_number", 0)
                violation = AuditTrailCompletenessViolation(
                    message=(
                        f"Hash chain broken in transaction {transaction_id} at sequence {broken_at}: "
                        f"expected {prev_hash[:16]}, got {event_prev[:16] if event_prev else 'None'}"
                    ),
                    transaction_id=str(transaction_id),
                    gap_sequence=broken_at,
                    severity=LawViolationSeverity.CATASTROPHIC,
                    details={
                        "transaction_id": str(transaction_id),
                        "broken_at_sequence": broken_at,
                        "expected_hash": prev_hash[:16] + "...",
                        "actual_hash": (event_prev[:16] + "...") if event_prev else None,
                    },
                )
                self._record_violation(violation)
                if raise_on_violation:
                    raise violation
                return False, violation
            prev_hash = getattr(event, "current_hash", None)

        return True, None

    async def enforce_no_gap_between_transactions(
        self,
        legal_entity_id: UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> AuditTrailReport:
        events = await self._audit_repo.get_by_time_range(legal_entity_id, from_date, to_date)
        if not events:
            return AuditTrailReport(
                legal_entity_id=legal_entity_id,
                from_date=from_date,
                to_date=to_date,
                total_events=0,
                has_gaps=False,
                first_sequence=None,
                last_sequence=None,
                missing_sequences=[],
                broken_hash_chain=False,
                broken_at_sequence=None,
                severity=AuditTrailSeverity.INFO,
                message="No events in range",
                generated_at=datetime.now(UTC),
            )

        sorted_events = sorted(events, key=lambda e: getattr(e, "timestamp", datetime.min))
        time_gaps = []
        prev_ts = None
        for e in sorted_events:
            ts = getattr(e, "timestamp", None)
            if prev_ts and ts:
                gap = (ts - prev_ts).total_seconds()
                if gap > self.MAX_TIME_GAP_SECONDS:
                    time_gaps.append((prev_ts, ts, gap))
            prev_ts = ts

        has_gaps = len(time_gaps) > 0
        severity = AuditTrailSeverity.MEDIUM if has_gaps else AuditTrailSeverity.INFO
        message = f"Found {len(time_gaps)} time gaps" if has_gaps else "No time gaps"

        if time_gaps:
            logger.warning(
                f"Time gaps in audit trail for entity {legal_entity_id}: {time_gaps[:3]}"
            )

        return AuditTrailReport(
            legal_entity_id=legal_entity_id,
            from_date=from_date,
            to_date=to_date,
            total_events=len(events),
            has_gaps=has_gaps,
            first_sequence=getattr(sorted_events[0], "sequence_number", None)
            if sorted_events
            else None,
            last_sequence=getattr(sorted_events[-1], "sequence_number", None)
            if sorted_events
            else None,
            missing_sequences=[],
            broken_hash_chain=False,
            broken_at_sequence=None,
            severity=severity,
            message=message,
            generated_at=datetime.now(UTC),
        )

    async def record_audit_event(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        event_type: AuditEventType,
        event_data: dict[str, Any],
        user_id: str,
        sequence_number: int | None = None,
    ) -> UUID:
        if not self._enabled:
            raise AuditTrailCompletenessViolation(
                message="Audit trail enforcer disabled, cannot record event",
                transaction_id=str(transaction_id),
                gap_sequence=None,
                severity=LawViolationSeverity.MEDIUM,
            )

        if sequence_number is None:
            last = await self._audit_repo.get_last_event(legal_entity_id)
            sequence_number = (getattr(last, "sequence_number", 0) + 1) if last else 1

        prev_hash = await self._get_previous_hash(legal_entity_id)

        event_id = await self._audit_repo.create_event(
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            event_type=event_type.value,
            event_data=event_data,
            user_id=user_id,
            sequence_number=sequence_number,
            previous_hash=prev_hash,
            timestamp=datetime.now(UTC),
        )

        self._record_audit("RECORD_EVENT", user_id, {
            "transaction_id": str(transaction_id),
            "event_type": event_type.value,
            "sequence": sequence_number,
        })
        logger.debug(
            f"Audit event recorded for transaction {transaction_id} (seq {sequence_number})"
        )
        return event_id

    async def _get_previous_hash(self, legal_entity_id: UUID) -> str | None:
        last = await self._audit_repo.get_last_event(legal_entity_id)
        return getattr(last, "current_hash", None) if last else None

    async def get_audit_trail_summary(
        self,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> AuditTrailReport:
        if from_date is None:
            from_date = datetime.min.replace(tzinfo=UTC)
        if to_date is None:
            to_date = datetime.max.replace(tzinfo=UTC)
        return await self.enforce_no_gap_between_transactions(legal_entity_id, from_date, to_date)

    def _record_violation(self, violation: AuditTrailCompletenessViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]
            self._record_audit("VIOLATION", violation.user_id or "system", {
                "message": violation.message,
                "severity": violation.severity.name,
            })

    def get_violations(
        self,
        limit: int = 100,
        min_severity: LawViolationSeverity = LawViolationSeverity.LOW,
    ) -> list[AuditTrailCompletenessViolation]:
        with self._lock:
            result = [v for v in self._violation_history if v.severity.value >= min_severity.value]
            return result[-limit:]

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._violation_history)
            if total == 0:
                return {
                    "total_violations": 0,
                    "enabled": self._enabled,
                    "version": self._version,
                }

            by_severity = {}
            for v in self._violation_history:
                by_severity[v.severity.name] = by_severity.get(v.severity.name, 0) + 1

            return {
                "total_violations": total,
                "by_severity": by_severity,
                "max_time_gap_seconds": self.MAX_TIME_GAP_SECONDS,
                "enabled": self._enabled,
                "version": self._version,
                "latest_violation": self._violation_history[-1].timestamp.isoformat()
                if self._violation_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._violation_history = []
            self._enabled = True
            self._version += 1
            self._audit_trail = []
            if hasattr(self._audit_repo, "clear"):
                self._audit_repo.clear()
            if hasattr(self._event_store, "clear"):
                self._event_store.clear()


# === 4. SINGLETON ACCESSOR ===

_audit_trail_completeness_enforcer_instance: AuditTrailCompletenessEnforcer | None = None
_lock_instance = threading.Lock()


def get_audit_trail_completeness_enforcer() -> AuditTrailCompletenessEnforcer:
    global _audit_trail_completeness_enforcer_instance
    if _audit_trail_completeness_enforcer_instance is None:
        with _lock_instance:
            if _audit_trail_completeness_enforcer_instance is None:
                _audit_trail_completeness_enforcer_instance = AuditTrailCompletenessEnforcer()
    return _audit_trail_completeness_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "AuditEvent",
    "AuditEventType",
    "AuditTrailCompletenessEnforcer",
    "AuditTrailReport",
    "AuditTrailSeverity",
    "get_audit_trail_completeness_enforcer",
]