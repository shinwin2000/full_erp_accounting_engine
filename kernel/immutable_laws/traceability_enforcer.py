#!/usr/bin/env python3
"""
Module: traceability_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: setiap perubahan harus bisa dilacak hingga ke sumber.
               Memastikan bahwa setiap transaksi atau perubahan data dalam sistem
               dapat dilacak kembali ke sumber asalnya (source document, user action,
               atau sistem trigger). Melengkapi rantai kausalitas untuk audit.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, TraceabilityViolation)

Audit: Setiap transaksi tanpa traceability dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    LawViolationSeverity,
    TraceabilityViolation,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackAuditTrailRepository:
    """Fallback audit trail repository dengan in-memory storage."""

    def __init__(self):
        self._trace_records: dict[UUID, dict[str, Any]] = {}  # transaction_id -> record
        self._by_correlation: dict[str, list[UUID]] = {}
        self._by_source: dict[str, list[UUID]] = {}
        self._chain: list[dict[str, Any]] = []

    async def get_by_transaction(
        self, transaction_id: UUID, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        record = self._trace_records.get(transaction_id)
        if record and record.get("legal_entity_id") == legal_entity_id:
            return [record]
        return []

    async def get_root_cause(
        self, transaction_id: UUID, legal_entity_id: UUID
    ) -> dict[str, Any] | None:
        record = self._trace_records.get(transaction_id)
        if record and record.get("legal_entity_id") == legal_entity_id:
            current = record
            visited = set()
            while current.get("causation_id") and current["causation_id"] not in visited:
                visited.add(current["causation_id"])
                parent = self._trace_records.get(current["causation_id"])
                if not parent or parent.get("legal_entity_id") != legal_entity_id:
                    break
                current = parent
            return current
        return None

    async def get_traceability(
        self, transaction_id: UUID, legal_entity_id: UUID
    ) -> dict[str, Any] | None:
        record = self._trace_records.get(transaction_id)
        if record and record.get("legal_entity_id") == legal_entity_id:
            return record
        return None

    async def get_by_correlation(
        self, correlation_id: str, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        tx_ids = self._by_correlation.get(correlation_id, [])
        result = []
        for tid in tx_ids:
            record = self._trace_records.get(tid)
            if record and record.get("legal_entity_id") == legal_entity_id:
                result.append(record)
        return result

    async def get_by_source(
        self, source_type: str, source_id: str, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        key = f"{source_type}:{source_id}"
        tx_ids = self._by_source.get(key, [])
        result = []
        for tid in tx_ids:
            record = self._trace_records.get(tid)
            if record and record.get("legal_entity_id") == legal_entity_id:
                result.append(record)
        return result

    async def create_traceability_record(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        source_type: str,
        source_id: str,
        source_description: str,
        user_id: str,
        correlation_id: str | None,
        causation_id: UUID | None,
        timestamp: datetime,
    ) -> UUID:
        record_id = uuid4()
        record = {
            "record_id": record_id,
            "transaction_id": transaction_id,
            "legal_entity_id": legal_entity_id,
            "source_type": source_type,
            "source_id": source_id,
            "source_description": source_description,
            "user_id": user_id,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "timestamp": timestamp,
            "created_at": datetime.now(UTC),
        }
        self._trace_records[transaction_id] = record
        if correlation_id:
            self._by_correlation.setdefault(correlation_id, []).append(transaction_id)
        key = f"{source_type}:{source_id}"
        self._by_source.setdefault(key, []).append(transaction_id)
        self._chain.append(record)
        return record_id

    async def get_chain(self, legal_entity_id: UUID, limit: int = 1000) -> list[dict[str, Any]]:
        return [r for r in self._chain if r.get("legal_entity_id") == legal_entity_id][-limit:]

    def clear(self) -> None:
        self._trace_records.clear()
        self._by_correlation.clear()
        self._by_source.clear()
        self._chain.clear()


class _FallbackTransactionRepository:
    """Fallback transaction repository jika infrastructure belum tersedia."""

    def __init__(self):
        self._transactions: dict[UUID, dict[str, Any]] = {}

    async def get_by_id(self, transaction_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        tx = self._transactions.get(transaction_id)
        if tx and tx.get("legal_entity_id") == legal_entity_id:
            return tx
        return None

    def add_transaction(
        self, transaction_id: UUID, legal_entity_id: UUID, transaction_type: str
    ) -> None:
        self._transactions[transaction_id] = {
            "transaction_id": transaction_id,
            "legal_entity_id": legal_entity_id,
            "transaction_type": transaction_type,
            "created_at": datetime.now(UTC),
        }

    def clear(self) -> None:
        self._transactions.clear()


# === 2. CONSTANTS & ENUMS ===


class SourceType(Enum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    API = "API"
    FILE = "FILE"
    BATCH = "BATCH"
    SCHEDULER = "SCHEDULER"
    WEBHOOK = "WEBHOOK"
    WORKFLOW = "WORKFLOW"
    SAGA = "SAGA"


class TraceabilitySeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


@dataclass
class TraceabilityRecord:
    record_id: UUID
    transaction_id: UUID
    legal_entity_id: UUID
    source_type: SourceType
    source_id: str
    source_description: str
    user_id: str
    correlation_id: str | None
    causation_id: UUID | None
    timestamp: datetime
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.record_id}|{self.transaction_id}|{self.legal_entity_id}|"
            f"{self.source_type.value}|{self.source_id}|{self.source_description[:100]}|"
            f"{self.user_id}|{self.correlation_id}|{self.causation_id}|{self.timestamp.isoformat()}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "transaction_id": str(self.transaction_id),
            "legal_entity_id": str(self.legal_entity_id),
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "source_description": self.source_description[:100],
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TraceabilityCheckResult:
    check_id: UUID
    transaction_id: UUID
    legal_entity_id: UUID
    is_valid: bool
    severity: TraceabilitySeverity
    message: str
    missing_fields: list[str]
    chain_length: int
    has_root_cause: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.check_id}|{self.transaction_id}|{self.is_valid}|"
            f"{self.severity.value}|{self.message[:100]}|{self.chain_length}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": str(self.check_id),
            "transaction_id": str(self.transaction_id),
            "legal_entity_id": str(self.legal_entity_id),
            "is_valid": self.is_valid,
            "severity": self.severity.name,
            "message": self.message,
            "missing_fields": self.missing_fields,
            "chain_length": self.chain_length,
            "has_root_cause": self.has_root_cause,
            "timestamp": self.timestamp.isoformat(),
        }


# ============================================================================
# BASE TRACEABILITY ENFORCER (ABSTRACT)
# ============================================================================

class BaseTraceabilityEnforcer(ABC):
    """Base contract untuk Traceability Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode."""
        pass

    @abstractmethod
    async def enforce_traceability(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        source_type: SourceType | None = None,
        source_id: str | None = None,
        source_description: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
        raise_on_violation: bool = True,
    ) -> TraceabilityCheckResult:
        """Enforce traceability for a transaction."""
        pass

    @abstractmethod
    async def create_traceability_record(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        source_type: SourceType,
        source_id: str | None = None,
        source_description: str = "",
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
    ) -> TraceabilityRecord:
        """Create a traceability record for a transaction."""
        pass

    @abstractmethod
    async def get_traceability_chain(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        """Get traceability chain for a transaction."""
        pass

    @abstractmethod
    async def verify_chain_integrity(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
    ) -> tuple[bool, str | None, list[str]]:
        """Verify integrity of traceability chain."""
        pass

    @abstractmethod
    async def get_transaction_source_summary(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        """Get source summary for a transaction."""
        pass

    @abstractmethod
    async def ensure_root_cause(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        root_source_type: SourceType,
        root_source_id: str,
        root_description: str,
        user_id: str | None = None,
    ) -> TraceabilityRecord:
        """Ensure root cause exists for a transaction."""
        pass

    @abstractmethod
    async def get_by_correlation(
        self, correlation_id: str, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        """Get traceability records by correlation ID."""
        pass

    @abstractmethod
    async def get_by_source(
        self, source_type: SourceType, source_id: str, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        """Get traceability records by source."""
        pass

    @abstractmethod
    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
    ) -> list[TraceabilityCheckResult]:
        """Get check history."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
    ) -> list[TraceabilityViolation]:
        """Get violation history."""
        pass

    @abstractmethod
    def get_traceability_records(
        self,
        transaction_id: UUID | None = None,
        limit: int = 100,
    ) -> list[TraceabilityRecord]:
        """Get traceability records."""
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
    def from_dict(cls, data: dict[str, Any]) -> BaseTraceabilityEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseTraceabilityEnforcer:
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
    def touch(self, touched_by: str) -> BaseTraceabilityEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# TRACEABILITY ENFORCER (CONCRETE)
# ============================================================================

class TraceabilityEnforcer(BaseTraceabilityEnforcer):
    """
    Enforcer untuk hukum traceability.

    Business context: Setiap perubahan data harus dapat dilacak ke sumbernya.
    Ini memungkinkan audit forensik dan investigasi.
    """

    def __init__(
        self,
        audit_trail_repository: Any | None = None,
        transaction_repository: Any | None = None,
    ):
        self._audit_repo = audit_trail_repository or _FallbackAuditTrailRepository()
        self._tx_repo = transaction_repository or _FallbackTransactionRepository()
        self._trace_records: list[TraceabilityRecord] = []
        self._check_history: list[TraceabilityCheckResult] = []
        self._violation_history: list[TraceabilityViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._strict_mode = True
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
        source_type = context.get("source_type")

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
        if source_type:
            try:
                SourceType(source_type.upper())
            except ValueError:
                errors.append(f"source_type '{source_type}' is not a valid SourceType")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "max_history": self._max_history,
                "trace_records_count": len(self._trace_records),
                "checks_count": len(self._check_history),
                "violations_count": len(self._violation_history),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraceabilityEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._strict_mode = data.get("strict_mode", True)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TraceabilityEnforcer:
        """Clone instance."""
        new_instance = TraceabilityEnforcer()
        new_instance._enabled = self._enabled
        new_instance._strict_mode = self._strict_mode
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "trace_records_count": len(self._trace_records),
                "checks_count": len(self._check_history),
                "violations_count": len(self._violation_history),
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TraceabilityEnforcer:
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
        logger.info(f"Traceability enforcer enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        self._strict_mode = strict
        self._record_audit("SET_STRICT_MODE", "system", {"strict": strict})
        logger.info(f"Traceability enforcer strict mode: {strict}")

    async def enforce_traceability(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        source_type: SourceType | None = None,
        source_id: str | None = None,
        source_description: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
        raise_on_violation: bool = True,
    ) -> TraceabilityCheckResult:
        if not self._enabled:
            return TraceabilityCheckResult(
                check_id=uuid4(),
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                is_valid=True,
                severity=TraceabilitySeverity.LOW,
                message="Traceability enforcer disabled",
                missing_fields=[],
                chain_length=0,
                has_root_cause=False,
            )

        if user_id is None:
            user_id = get_current_user() or "unknown"

        missing_fields = []

        if source_type is None:
            missing_fields.append("source_type")
        else:
            valid_types = [st.value for st in SourceType]
            if source_type.value not in valid_types:
                missing_fields.append(f"invalid_source_type:{source_type.value}")

        if source_type == SourceType.USER and not source_id and not user_id:
            missing_fields.append("source_id_or_user_id")

        existing_records = await self._audit_repo.get_by_transaction(
            transaction_id, legal_entity_id
        )

        if not existing_records and not source_type:
            result = TraceabilityCheckResult(
                check_id=uuid4(),
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                is_valid=False,
                severity=TraceabilitySeverity.CRITICAL,
                message=f"Transaction {transaction_id} has no traceability record",
                missing_fields=["no_traceability_record"],
                chain_length=0,
                has_root_cause=False,
            )
            self._record_check(result)
            if raise_on_violation:
                violation = TraceabilityViolation(
                    message=result.message,
                    transaction_id=str(transaction_id),
                    severity=LawViolationSeverity.CRITICAL,
                    details=result.to_dict(),
                )
                self._record_violation(violation)
                raise violation
            return result

        root_cause = await self._audit_repo.get_root_cause(transaction_id, legal_entity_id)
        chain_length = len(existing_records)

        severity = TraceabilitySeverity.LOW
        if missing_fields:
            if "source_type" in missing_fields:
                severity = TraceabilitySeverity.HIGH
            elif "source_id_or_user_id" in missing_fields:
                severity = TraceabilitySeverity.MEDIUM
            else:
                severity = TraceabilitySeverity.LOW

        is_valid = len(missing_fields) == 0 and root_cause is not None

        result = TraceabilityCheckResult(
            check_id=uuid4(),
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            is_valid=is_valid,
            severity=severity,
            message="Traceability OK" if is_valid else f"Missing fields: {missing_fields}",
            missing_fields=missing_fields,
            chain_length=chain_length,
            has_root_cause=root_cause is not None,
        )
        result.cryptographic_hash = result.compute_hash()
        self._record_check(result)

        if not is_valid and raise_on_violation:
            violation = TraceabilityViolation(
                message=result.message,
                transaction_id=str(transaction_id),
                severity=LawViolationSeverity.HIGH,
                details=result.to_dict(),
            )
            self._record_violation(violation)
            raise violation

        return result

    async def create_traceability_record(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        source_type: SourceType,
        source_id: str | None = None,
        source_description: str = "",
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
    ) -> TraceabilityRecord:
        if not self._enabled:
            raise TraceabilityViolation(
                message="Traceability enforcer disabled, cannot create record",
                transaction_id=str(transaction_id),
                severity=LawViolationSeverity.MEDIUM,
            )

        if user_id is None:
            user_id = get_current_user() or "system"

        effective_source_id = source_id or user_id

        record_id = await self._audit_repo.create_traceability_record(
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            source_type=source_type.value,
            source_id=effective_source_id,
            source_description=source_description,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            timestamp=datetime.now(UTC),
        )

        trace_record = TraceabilityRecord(
            record_id=record_id,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            source_type=source_type,
            source_id=effective_source_id,
            source_description=source_description,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            timestamp=datetime.now(UTC),
            cryptographic_hash="",
        )
        trace_record.cryptographic_hash = trace_record.compute_hash()

        with self._lock:
            self._trace_records.append(trace_record)
            if len(self._trace_records) > self._max_history:
                self._trace_records = self._trace_records[-self._max_history :]

        self._record_audit("CREATE_TRACEABILITY_RECORD", user_id, {
            "transaction_id": str(transaction_id),
            "source_type": source_type.value,
        })
        logger.info(f"Traceability record {record_id} created for transaction {transaction_id}")
        return trace_record

    async def get_traceability_chain(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        chain = []
        current_id = transaction_id
        visited = set()

        for _ in range(max_depth):
            if current_id in visited:
                break
            visited.add(current_id)

            trace_data = await self._audit_repo.get_traceability(current_id, legal_entity_id)
            if not trace_data:
                break

            # Safe timestamp extraction
            timestamp_val = trace_data.get("timestamp")
            timestamp_str = timestamp_val.isoformat() if timestamp_val else None

            chain.append(
                {
                    "transaction_id": str(trace_data.get("transaction_id")),
                    "source_type": trace_data.get("source_type"),
                    "source_id": trace_data.get("source_id"),
                    "source_description": trace_data.get("source_description", "")[:100],
                    "user_id": trace_data.get("user_id"),
                    "timestamp": timestamp_str,
                    "correlation_id": trace_data.get("correlation_id"),
                    "causation_id": str(trace_data.get("causation_id"))
                    if trace_data.get("causation_id")
                    else None,
                }
            )

            causation = trace_data.get("causation_id")
            if causation:
                current_id = causation
            else:
                break

        return chain

    async def verify_chain_integrity(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
    ) -> tuple[bool, str | None, list[str]]:
        chain = await self.get_traceability_chain(transaction_id, legal_entity_id)
        if not chain:
            return False, "No traceability chain found", ["empty_chain"]

        issues = []
        for i in range(1, len(chain)):
            prev = chain[i - 1]
            curr = chain[i]
            if curr.get("causation_id") and curr["causation_id"] != prev["transaction_id"]:
                issues.append(
                    f"Chain break at {curr['transaction_id']}: causation {curr['causation_id']} "
                    f"does not match previous {prev['transaction_id']}"
                )

        for item in chain:
            if not item.get("source_type"):
                issues.append(f"Missing source_type for {item['transaction_id']}")
            if not item.get("source_id"):
                issues.append(f"Missing source_id for {item['transaction_id']}")

        is_valid = len(issues) == 0
        message = None if is_valid else f"Chain integrity issues: {len(issues)}"
        return is_valid, message, issues

    async def get_transaction_source_summary(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        trace_data = await self._audit_repo.get_traceability(transaction_id, legal_entity_id)
        if not trace_data:
            return {
                "transaction_id": str(transaction_id),
                "has_traceability": False,
                "message": "No traceability record found",
            }

        chain = await self.get_traceability_chain(transaction_id, legal_entity_id)
        is_valid, _, issues = await self.verify_chain_integrity(transaction_id, legal_entity_id)

        timestamp_val = trace_data.get("timestamp")
        timestamp_str = timestamp_val.isoformat() if timestamp_val else None

        return {
            "transaction_id": str(transaction_id),
            "has_traceability": True,
            "source_type": trace_data.get("source_type"),
            "source_id": trace_data.get("source_id"),
            "source_description": trace_data.get("source_description", "")[:200],
            "user_id": trace_data.get("user_id"),
            "timestamp": timestamp_str,
            "correlation_id": trace_data.get("correlation_id"),
            "causation_id": str(trace_data.get("causation_id"))
            if trace_data.get("causation_id")
            else None,
            "chain_length": len(chain),
            "chain_integrity_valid": is_valid,
            "integrity_issues": issues[:10],
        }

    async def ensure_root_cause(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        root_source_type: SourceType,
        root_source_id: str,
        root_description: str,
        user_id: str | None = None,
    ) -> TraceabilityRecord:
        existing = await self._audit_repo.get_root_cause(transaction_id, legal_entity_id)
        if existing:
            return TraceabilityRecord(
                record_id=existing.get("record_id", uuid4()),
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                source_type=SourceType(existing.get("source_type")),
                source_id=existing.get("source_id", ""),
                source_description=existing.get("source_description", ""),
                user_id=existing.get("user_id", ""),
                correlation_id=existing.get("correlation_id"),
                causation_id=existing.get("causation_id"),
                timestamp=existing.get("timestamp", datetime.now(UTC)),
            )
        return await self.create_traceability_record(
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            source_type=root_source_type,
            source_id=root_source_id,
            source_description=root_description,
            user_id=user_id,
            correlation_id=None,
            causation_id=None,
        )

    async def get_by_correlation(
        self, correlation_id: str, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        return await self._audit_repo.get_by_correlation(correlation_id, legal_entity_id)

    async def get_by_source(
        self, source_type: SourceType, source_id: str, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        return await self._audit_repo.get_by_source(source_type.value, source_id, legal_entity_id)

    def _record_check(self, result: TraceabilityCheckResult) -> None:
        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

    def _record_violation(self, violation: TraceabilityViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]
            # Use getattr to safely access attributes that may not exist
            user_id = getattr(violation, "user_id", None) or "system"
            message = getattr(violation, "message", str(violation))
            severity = getattr(violation, "severity", LawViolationSeverity.MEDIUM)
            self._record_audit(
                "VIOLATION",
                user_id,
                {
                    "message": message,
                    "severity": severity.name if hasattr(severity, "name") else str(severity),
                }
            )

    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
    ) -> list[TraceabilityCheckResult]:
        with self._lock:
            result = self._check_history[-limit:]
        if only_violations:
            result = [r for r in result if not r.is_valid]
        return result

    def get_violations(
        self,
        limit: int = 100,
    ) -> list[TraceabilityViolation]:
        with self._lock:
            return self._violation_history[-limit:]

    def get_traceability_records(
        self,
        transaction_id: UUID | None = None,
        limit: int = 100,
    ) -> list[TraceabilityRecord]:
        with self._lock:
            result = self._trace_records[-limit:]
        if transaction_id:
            result = [r for r in result if r.transaction_id == transaction_id]
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_checks = len(self._check_history)
            total_violations = len(self._violation_history)
            total_records = len(self._trace_records)

            if total_checks == 0:
                return {
                    "total_checks": 0,
                    "total_violations": 0,
                    "total_records": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                    "version": self._version,
                }

            valid = len([r for r in self._check_history if r.is_valid])
            invalid = total_checks - valid

            by_severity: dict[str, int] = {}
            for r in self._check_history:
                if not r.is_valid:
                    sev = r.severity.name
                    by_severity[sev] = by_severity.get(sev, 0) + 1

            by_source_type: dict[str, int] = {}
            for record in self._trace_records:  # changed variable name to avoid conflict
                st = record.source_type.value
                by_source_type[st] = by_source_type.get(st, 0) + 1

            return {
                "total_checks": total_checks,
                "total_violations": total_violations,
                "total_records": total_records,
                "valid_count": valid,
                "invalid_count": invalid,
                "validity_rate": valid / total_checks if total_checks > 0 else 0,
                "by_severity": by_severity,
                "by_source_type": by_source_type,
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "version": self._version,
                "latest_check": self._check_history[-1].timestamp.isoformat()
                if self._check_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._trace_records = []
            self._check_history = []
            self._violation_history = []
            self._enabled = True
            self._strict_mode = True
            self._version += 1
            self._audit_trail = []
            if hasattr(self._audit_repo, "clear"):
                self._audit_repo.clear()
            if hasattr(self._tx_repo, "clear"):
                self._tx_repo.clear()


# === 4. SINGLETON ACCESSOR ===

_traceability_enforcer_instance: TraceabilityEnforcer | None = None
_lock_instance = threading.Lock()


def get_traceability_enforcer() -> TraceabilityEnforcer:
    global _traceability_enforcer_instance
    if _traceability_enforcer_instance is None:
        with _lock_instance:
            if _traceability_enforcer_instance is None:
                _traceability_enforcer_instance = TraceabilityEnforcer()
    return _traceability_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "SourceType",
    "TraceabilityCheckResult",
    "TraceabilityEnforcer",
    "TraceabilityRecord",
    "TraceabilitySeverity",
    "get_traceability_enforcer",
]
