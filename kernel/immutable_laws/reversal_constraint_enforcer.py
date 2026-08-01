#!/usr/bin/env python3
"""
Module: reversal_constraint_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: reversal harus menggunakan jurnal koreksi, bukan hapus.
               Memastikan bahwa koreksi atas jurnal yang sudah diposting
               harus dilakukan melalui jurnal reversal atau amendment entry,
               bukan dengan menghapus atau memodifikasi jurnal asli.
               Setiap reversal wajib memiliki referensi ke jurnal asli.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, ReversalConstraintViolation)

Audit: Setiap reversal dictat dengan referensi ke jurnal asli.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    LawViolationSeverity,
    ReversalConstraintViolation,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORY (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackJournalRepository:
    """Fallback journal repository dengan in-memory storage."""

    def __init__(self):
        self._journals: dict[UUID, dict[str, Any]] = {}
        self._by_number: dict[str, UUID] = {}
        self._by_reversal_of: dict[UUID, list[UUID]] = {}

    async def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        journal = self._journals.get(journal_id)
        if journal and journal.get("legal_entity_id") == legal_entity_id:
            return journal
        return None

    async def get_by_number(
        self, journal_number: str, legal_entity_id: UUID
    ) -> dict[str, Any] | None:
        jid = self._by_number.get(journal_number)
        if jid:
            return await self.get_by_id(jid, legal_entity_id)
        return None

    async def get_reversals_of(
        self, original_journal_id: UUID, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        reversal_ids = self._by_reversal_of.get(original_journal_id, [])
        result = []
        for rid in reversal_ids:
            journal = self._journals.get(rid)
            if journal and journal.get("legal_entity_id") == legal_entity_id:
                result.append(journal)
        return result

    async def mark_as_reversed(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        reversal_journal_id: UUID,
        reversed_by: str,
        reversed_at: datetime,
    ) -> bool:
        journal = self._journals.get(journal_id)
        if not journal or journal.get("legal_entity_id") != legal_entity_id:
            return False
        journal["is_reversed"] = True
        journal["reversal_journal_id"] = reversal_journal_id
        journal["reversed_by"] = reversed_by
        journal["reversed_at"] = reversed_at
        journal["status"] = "REVERSED"
        return True

    async def set_reversal_of(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        original_journal_id: UUID,
    ) -> bool:
        journal = self._journals.get(journal_id)
        if not journal or journal.get("legal_entity_id") != legal_entity_id:
            return False
        journal["is_reversal"] = True
        journal["reversal_of"] = original_journal_id
        self._by_reversal_of.setdefault(original_journal_id, []).append(journal_id)
        return True

    async def get_reversal_chain(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        chain = []
        current_id = journal_id
        visited = set()
        for _ in range(max_depth):
            if current_id in visited:
                break
            visited.add(current_id)
            journal = await self.get_by_id(current_id, legal_entity_id)
            if not journal:
                break
            chain.append(
                {
                    "journal_id": str(journal.get("journal_id")),
                    "journal_number": journal.get("journal_number"),
                    "is_reversal": journal.get("is_reversal", False),
                    "reversal_of": str(journal.get("reversal_of"))
                    if journal.get("reversal_of")
                    else None,
                    "is_reversed": journal.get("is_reversed", False),
                    "reversal_journal_id": str(journal.get("reversal_journal_id"))
                    if journal.get("reversal_journal_id")
                    else None,
                    "status": journal.get("status"),
                    "total_debit": str(journal.get("total_debit", 0)),
                    "total_credit": str(journal.get("total_credit", 0)),
                    "created_at": journal.get("created_at").isoformat()
                    if journal.get("created_at")
                    else None,
                }
            )
            if journal.get("is_reversed") and journal.get("reversal_journal_id"):
                current_id = journal["reversal_journal_id"]
            else:
                break
        return chain

    async def is_already_reversed(self, journal_id: UUID, legal_entity_id: UUID) -> bool:
        journal = await self.get_by_id(journal_id, legal_entity_id)
        return journal.get("is_reversed", False) if journal else False

    async def get_reversal_count(self, original_journal_id: UUID, legal_entity_id: UUID) -> int:
        reversals = await self.get_reversals_of(original_journal_id, legal_entity_id)
        return len(reversals)

    def add_journal(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        journal_number: str,
        status: str,
        total_debit: Decimal,
        total_credit: Decimal,
        created_at: datetime | None = None,
        is_reversal: bool = False,
        reversal_of: UUID | None = None,
        is_reversed: bool = False,
        reversal_journal_id: UUID | None = None,
    ) -> None:
        journal = {
            "journal_id": journal_id,
            "legal_entity_id": legal_entity_id,
            "journal_number": journal_number,
            "status": status,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "created_at": created_at or datetime.now(UTC),
            "is_reversal": is_reversal,
            "reversal_of": reversal_of,
            "is_reversed": is_reversed,
            "reversal_journal_id": reversal_journal_id,
        }
        self._journals[journal_id] = journal
        self._by_number[journal_number] = journal_id
        if reversal_of:
            self._by_reversal_of.setdefault(reversal_of, []).append(journal_id)

    def clear(self) -> None:
        self._journals.clear()
        self._by_number.clear()
        self._by_reversal_of.clear()


# === 2. CONSTANTS & ENUMS ===


class ReversalReason(Enum):
    ERROR_CORRECTION = "error_correction"
    ADJUSTMENT = "adjustment"
    CANCELLATION = "cancellation"
    AMENDMENT = "amendment"
    REGULATORY = "regulatory"


class ReversalSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


@dataclass
class ReversalRecord:
    reversal_id: UUID
    original_journal_id: UUID
    reversal_journal_id: UUID
    legal_entity_id: UUID
    reason: ReversalReason
    reason_description: str
    approved_by: list[str]
    created_by: str
    created_at: datetime
    amount: Decimal
    currency: str = "IDR"
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.reversal_id}|{self.original_journal_id}|{self.reversal_journal_id}|"
            f"{self.legal_entity_id}|{self.reason.value}|{self.created_at.isoformat()}|"
            f"{self.amount}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "reversal_id": str(self.reversal_id),
            "original_journal_id": str(self.original_journal_id),
            "reversal_journal_id": str(self.reversal_journal_id),
            "legal_entity_id": str(self.legal_entity_id),
            "reason": self.reason.value,
            "reason_description": self.reason_description[:100],
            "approved_by": self.approved_by,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
        }


@dataclass
class ReversalCheckResult:
    check_id: UUID
    original_journal_id: UUID
    reversal_journal_id: UUID
    legal_entity_id: UUID
    is_allowed: bool
    severity: ReversalSeverity
    message: str
    requires_approval: bool = False
    requires_reason: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.check_id}|{self.original_journal_id}|{self.reversal_journal_id}|"
            f"{self.is_allowed}|{self.severity.value}|{self.message[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": str(self.check_id),
            "original_journal_id": str(self.original_journal_id),
            "reversal_journal_id": str(self.reversal_journal_id),
            "legal_entity_id": str(self.legal_entity_id),
            "is_allowed": self.is_allowed,
            "severity": self.severity.name,
            "message": self.message,
            "requires_approval": self.requires_approval,
            "requires_reason": self.requires_reason,
            "timestamp": self.timestamp.isoformat(),
        }


# ============================================================================
# BASE REVERSAL CONSTRAINT ENFORCER (ABSTRACT)
# ============================================================================

class BaseReversalConstraintEnforcer(ABC):
    """Base contract untuk Reversal Constraint Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode."""
        pass

    @abstractmethod
    def set_thresholds(self, material: Decimal, dual_approval: Decimal) -> None:
        """Set reversal thresholds."""
        pass

    @abstractmethod
    async def enforce_reversal_constraint(
        self,
        reversal_journal_id: UUID,
        original_journal_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        reason: ReversalReason | None = None,
        reason_description: str | None = None,
        approved_by: list[str] | None = None,
        raise_on_violation: bool = True,
    ) -> ReversalCheckResult:
        """Enforce reversal constraint for a journal reversal."""
        pass

    @abstractmethod
    async def validate_reversal_amounts(
        self,
        original_journal: dict[str, Any],
        reversal_journal: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Validate reversal amounts match original."""
        pass

    @abstractmethod
    async def record_reversal(
        self,
        reversal_journal_id: UUID,
        original_journal_id: UUID,
        legal_entity_id: UUID,
        reversed_by: str,
    ) -> None:
        """Record a reversal relationship."""
        pass

    @abstractmethod
    async def get_reversal_chain(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        """Get reversal chain for a journal."""
        pass

    @abstractmethod
    async def get_reversal_history(
        self,
        original_journal_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ReversalRecord]:
        """Get reversal history."""
        pass

    @abstractmethod
    async def is_already_reversed(self, journal_id: UUID, legal_entity_id: UUID) -> bool:
        """Check if a journal is already reversed."""
        pass

    @abstractmethod
    async def get_reversal_count(self, original_journal_id: UUID, legal_entity_id: UUID) -> int:
        """Get number of reversals for a journal."""
        pass

    @abstractmethod
    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
    ) -> list[ReversalCheckResult]:
        """Get check history."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
    ) -> list[ReversalConstraintViolation]:
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
    def from_dict(cls, data: dict[str, Any]) -> BaseReversalConstraintEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseReversalConstraintEnforcer:
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
    def touch(self, touched_by: str) -> BaseReversalConstraintEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# REVERSAL CONSTRAINT ENFORCER (CONCRETE)
# ============================================================================

class ReversalConstraintEnforcer(BaseReversalConstraintEnforcer):
    """
    Enforcer untuk hukum reversal constraint.

    Business context: Koreksi data akuntansi harus dilakukan dengan
    cara membalik (reversal) atau jurnal koreksi, bukan menghapus
    data asli. Ini menjaga integritas audit trail.
    """

    MATERIAL_THRESHOLD = Decimal("10000000")  # 10 juta
    DUAL_APPROVAL_THRESHOLD = Decimal("100000000")  # 100 juta

    def __init__(self, journal_repository: Any | None = None):
        self._journal_repo = journal_repository or _FallbackJournalRepository()
        self._reversal_records: list[ReversalRecord] = []
        self._check_history: list[ReversalCheckResult] = []
        self._violation_history: list[ReversalConstraintViolation] = []
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
        reversal_journal_id = context.get("reversal_journal_id")
        original_journal_id = context.get("original_journal_id")
        legal_entity_id = context.get("legal_entity_id")

        if not reversal_journal_id:
            errors.append("reversal_journal_id is required")
        else:
            try:
                UUID(str(reversal_journal_id))
            except Exception:
                errors.append("reversal_journal_id must be a valid UUID")
        if not original_journal_id:
            errors.append("original_journal_id is required")
        else:
            try:
                UUID(str(original_journal_id))
            except Exception:
                errors.append("original_journal_id must be a valid UUID")
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
        if self.MATERIAL_THRESHOLD < 0:
            errors.append("MATERIAL_THRESHOLD must be non-negative")
        if self.DUAL_APPROVAL_THRESHOLD < 0:
            errors.append("DUAL_APPROVAL_THRESHOLD must be non-negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "max_history": self._max_history,
                "material_threshold": str(self.MATERIAL_THRESHOLD),
                "dual_approval_threshold": str(self.DUAL_APPROVAL_THRESHOLD),
                "reversal_records_count": len(self._reversal_records),
                "checks_count": len(self._check_history),
                "violations_count": len(self._violation_history),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReversalConstraintEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._strict_mode = data.get("strict_mode", True)
        instance._max_history = data.get("max_history", 10000)
        instance.MATERIAL_THRESHOLD = Decimal(str(data.get("material_threshold", 10000000)))
        instance.DUAL_APPROVAL_THRESHOLD = Decimal(str(data.get("dual_approval_threshold", 100000000)))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ReversalConstraintEnforcer:
        """Clone instance."""
        new_instance = ReversalConstraintEnforcer()
        new_instance._enabled = self._enabled
        new_instance._strict_mode = self._strict_mode
        new_instance._max_history = self._max_history
        new_instance.MATERIAL_THRESHOLD = self.MATERIAL_THRESHOLD
        new_instance.DUAL_APPROVAL_THRESHOLD = self.DUAL_APPROVAL_THRESHOLD
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "reversal_records_count": len(self._reversal_records),
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

    def touch(self, touched_by: str) -> ReversalConstraintEnforcer:
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
        logger.info(f"Reversal constraint enforcer enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        self._strict_mode = strict
        self._record_audit("SET_STRICT_MODE", "system", {"strict": strict})
        logger.info(f"Reversal constraint enforcer strict mode: {strict}")

    def set_thresholds(self, material: Decimal, dual_approval: Decimal) -> None:
        self.MATERIAL_THRESHOLD = material
        self.DUAL_APPROVAL_THRESHOLD = dual_approval
        self._record_audit("SET_THRESHOLDS", "system", {
            "material": str(material),
            "dual_approval": str(dual_approval),
        })
        logger.info(f"Reversal thresholds set: material={material}, dual_approval={dual_approval}")

    async def enforce_reversal_constraint(
        self,
        reversal_journal_id: UUID,
        original_journal_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        reason: ReversalReason | None = None,
        reason_description: str | None = None,
        approved_by: list[str] | None = None,
        raise_on_violation: bool = True,
    ) -> ReversalCheckResult:
        if not self._enabled:
            return ReversalCheckResult(
                check_id=uuid4(),
                original_journal_id=original_journal_id,
                reversal_journal_id=reversal_journal_id,
                legal_entity_id=legal_entity_id,
                is_allowed=True,
                severity=ReversalSeverity.LOW,
                message="Reversal constraint enforcer disabled",
            )

        if user_id is None:
            user_id = get_current_user() or "unknown"

        original_data = await self._journal_repo.get_by_id(original_journal_id, legal_entity_id)
        if not original_data:
            result = ReversalCheckResult(
                check_id=uuid4(),
                original_journal_id=original_journal_id,
                reversal_journal_id=reversal_journal_id,
                legal_entity_id=legal_entity_id,
                is_allowed=False,
                severity=ReversalSeverity.HIGH,
                message=f"Original journal {original_journal_id} not found",
            )
            self._record_check(result)
            if raise_on_violation:
                violation = ReversalConstraintViolation(
                    message=result.message,
                    original_journal_id=str(original_journal_id),
                    severity=LawViolationSeverity.HIGH,
                    details=result.to_dict(),
                )
                self._record_violation(violation)
                raise violation
            return result

        original_status = original_data.get("status", "UNKNOWN")
        original_total = Decimal(str(original_data.get("total_debit", 0)))
        is_reversed = original_data.get("is_reversed", False)
        original_number = original_data.get("journal_number", str(original_journal_id))

        reversible_statuses = ["POSTED", "APPROVED"]
        if original_status not in reversible_statuses:
            result = ReversalCheckResult(
                check_id=uuid4(),
                original_journal_id=original_journal_id,
                reversal_journal_id=reversal_journal_id,
                legal_entity_id=legal_entity_id,
                is_allowed=False,
                severity=ReversalSeverity.HIGH,
                message=f"Cannot reverse journal in {original_status} state. Only POSTED or APPROVED journals can be reversed.",
            )
            self._record_check(result)
            if raise_on_violation:
                violation = ReversalConstraintViolation(
                    message=result.message,
                    original_journal_id=str(original_journal_id),
                    severity=LawViolationSeverity.HIGH,
                    details=result.to_dict(),
                )
                self._record_violation(violation)
                raise violation
            return result

        if is_reversed:
            existing_reversal = original_data.get("reversal_journal_id")
            result = ReversalCheckResult(
                check_id=uuid4(),
                original_journal_id=original_journal_id,
                reversal_journal_id=reversal_journal_id,
                legal_entity_id=legal_entity_id,
                is_allowed=False,
                severity=ReversalSeverity.CRITICAL,
                message=f"Journal {original_number} has already been reversed (reversal ID: {existing_reversal}). Cannot reverse again.",
                requires_approval=False,
            )
            self._record_check(result)
            if raise_on_violation:
                violation = ReversalConstraintViolation(
                    message=result.message,
                    original_journal_id=str(original_journal_id),
                    severity=LawViolationSeverity.CRITICAL,
                    details=result.to_dict(),
                )
                self._record_violation(violation)
                raise violation
            return result

        requires_reason = original_total >= self.MATERIAL_THRESHOLD
        if requires_reason and not reason:
            result = ReversalCheckResult(
                check_id=uuid4(),
                original_journal_id=original_journal_id,
                reversal_journal_id=reversal_journal_id,
                legal_entity_id=legal_entity_id,
                is_allowed=False,
                severity=ReversalSeverity.MEDIUM,
                message=f"Reversal of material journal (amount {original_total}) requires a reason.",
                requires_reason=True,
            )
            self._record_check(result)
            if raise_on_violation:
                violation = ReversalConstraintViolation(
                    message=result.message,
                    original_journal_id=str(original_journal_id),
                    severity=LawViolationSeverity.MEDIUM,
                    details=result.to_dict(),
                )
                self._record_violation(violation)
                raise violation
            return result

        requires_approval = original_total >= self.DUAL_APPROVAL_THRESHOLD
        if requires_approval:
            if not approved_by or len(approved_by) < 2:
                result = ReversalCheckResult(
                    check_id=uuid4(),
                    original_journal_id=original_journal_id,
                    reversal_journal_id=reversal_journal_id,
                    legal_entity_id=legal_entity_id,
                    is_allowed=False,
                    severity=ReversalSeverity.HIGH,
                    message=f"Reversal of very large journal (amount {original_total}) requires dual approval (minimum 2 approvers).",
                    requires_approval=True,
                )
                self._record_check(result)
                if raise_on_violation:
                    violation = ReversalConstraintViolation(
                        message=result.message,
                        original_journal_id=str(original_journal_id),
                        severity=LawViolationSeverity.HIGH,
                        details=result.to_dict(),
                    )
                    self._record_violation(violation)
                    raise violation
                return result
        elif requires_reason and not requires_approval:
            # FIX: SIM212 - gunakan approved_by if approved_by else [user_id]
            approved_by = approved_by if approved_by else [user_id]

        if reason is None:
            reason = ReversalReason.ADJUSTMENT

        result = ReversalCheckResult(
            check_id=uuid4(),
            original_journal_id=original_journal_id,
            reversal_journal_id=reversal_journal_id,
            legal_entity_id=legal_entity_id,
            is_allowed=True,
            severity=ReversalSeverity.LOW,
            message=f"Reversal constraint passed for journal {original_number}",
        )
        self._record_check(result)

        # Record the reversal
        reversal_record = ReversalRecord(
            reversal_id=uuid4(),
            original_journal_id=original_journal_id,
            reversal_journal_id=reversal_journal_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
            reason_description=reason_description or "",
            approved_by=approved_by or [user_id],
            created_by=user_id,
            created_at=datetime.now(UTC),
            amount=original_total,
            cryptographic_hash="",
        )
        reversal_record.cryptographic_hash = reversal_record.compute_hash()

        with self._lock:
            self._reversal_records.append(reversal_record)
            if len(self._reversal_records) > self._max_history:
                self._reversal_records = self._reversal_records[-self._max_history :]

        self._record_audit("REVERSAL_ALLOWED", user_id, {
            "original_journal_id": str(original_journal_id),
            "reversal_journal_id": str(reversal_journal_id),
            "reason": reason.value,
        })
        logger.info(f"Reversal constraint passed for journal {original_journal_id} by {user_id}")
        return result

    async def validate_reversal_amounts(
        self,
        original_journal: dict[str, Any],
        reversal_journal: dict[str, Any],
    ) -> tuple[bool, str | None]:
        original_debit = Decimal(str(original_journal.get("total_debit", 0)))
        original_credit = Decimal(str(original_journal.get("total_credit", 0)))
        reversal_debit = Decimal(str(reversal_journal.get("total_debit", 0)))
        reversal_credit = Decimal(str(reversal_journal.get("total_credit", 0)))

        if reversal_debit != original_credit:
            return (
                False,
                f"Reversal debit {reversal_debit} does not match original credit {original_credit}",
            )
        if reversal_credit != original_debit:
            return (
                False,
                f"Reversal credit {reversal_credit} does not match original debit {original_debit}",
            )
        return True, None

    async def record_reversal(
        self,
        reversal_journal_id: UUID,
        original_journal_id: UUID,
        legal_entity_id: UUID,
        reversed_by: str,
    ) -> None:
        success1 = await self._journal_repo.mark_as_reversed(
            journal_id=original_journal_id,
            legal_entity_id=legal_entity_id,
            reversal_journal_id=reversal_journal_id,
            reversed_by=reversed_by,
            reversed_at=datetime.now(UTC),
        )
        success2 = await self._journal_repo.set_reversal_of(
            journal_id=reversal_journal_id,
            legal_entity_id=legal_entity_id,
            original_journal_id=original_journal_id,
        )
        if success1 and success2:
            self._record_audit("RECORD_REVERSAL", reversed_by, {
                "original_journal_id": str(original_journal_id),
                "reversal_journal_id": str(reversal_journal_id),
            })
            logger.info(f"Reversal recorded: {reversal_journal_id} reverses {original_journal_id}")
        else:
            logger.error(
                f"Failed to record reversal relationship between {reversal_journal_id} and {original_journal_id}"
            )

    async def get_reversal_chain(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        return await self._journal_repo.get_reversal_chain(journal_id, legal_entity_id, max_depth)

    async def get_reversal_history(
        self,
        original_journal_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ReversalRecord]:
        with self._lock:
            result = self._reversal_records[-limit:]
        if original_journal_id:
            result = [r for r in result if r.original_journal_id == original_journal_id]
        if legal_entity_id:
            result = [r for r in result if r.legal_entity_id == legal_entity_id]
        return result

    async def is_already_reversed(self, journal_id: UUID, legal_entity_id: UUID) -> bool:
        return await self._journal_repo.is_already_reversed(journal_id, legal_entity_id)

    async def get_reversal_count(self, original_journal_id: UUID, legal_entity_id: UUID) -> int:
        return await self._journal_repo.get_reversal_count(original_journal_id, legal_entity_id)

    def _record_check(self, result: ReversalCheckResult) -> None:
        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

    def _record_violation(self, violation: ReversalConstraintViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]
            self._record_audit("VIOLATION", violation.user_id or "system", {
                "message": violation.message,
                "severity": violation.severity.name,
            })

    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
    ) -> list[ReversalCheckResult]:
        with self._lock:
            result = self._check_history[-limit:]
        if only_violations:
            result = [r for r in result if not r.is_allowed]
        return result

    def get_violations(
        self,
        limit: int = 100,
    ) -> list[ReversalConstraintViolation]:
        with self._lock:
            return self._violation_history[-limit:]

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_checks = len(self._check_history)
            total_violations = len(self._violation_history)
            total_reversals = len(self._reversal_records)

            if total_checks == 0:
                return {
                    "total_checks": 0,
                    "total_violations": 0,
                    "total_reversals": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                    "version": self._version,
                }

            allowed = len([r for r in self._check_history if r.is_allowed])
            blocked = total_checks - allowed

            by_reason = {}
            for r in self._reversal_records:
                reason = r.reason.value
                by_reason[reason] = by_reason.get(reason, 0) + 1

            return {
                "total_checks": total_checks,
                "total_violations": total_violations,
                "total_reversals": total_reversals,
                "allowed_count": allowed,
                "blocked_count": blocked,
                "allow_rate": allowed / total_checks if total_checks > 0 else 0,
                "by_reason": by_reason,
                "material_threshold": str(self.MATERIAL_THRESHOLD),
                "dual_approval_threshold": str(self.DUAL_APPROVAL_THRESHOLD),
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "version": self._version,
                "latest_check": self._check_history[-1].timestamp.isoformat()
                if self._check_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._reversal_records = []
            self._check_history = []
            self._violation_history = []
            self._enabled = True
            self._strict_mode = True
            self._version += 1
            self._audit_trail = []
            if hasattr(self._journal_repo, "clear"):
                self._journal_repo.clear()


# === 4. SINGLETON ACCESSOR ===

_reversal_constraint_enforcer_instance: ReversalConstraintEnforcer | None = None
_lock_instance = threading.Lock()


def get_reversal_constraint_enforcer() -> ReversalConstraintEnforcer:
    global _reversal_constraint_enforcer_instance
    if _reversal_constraint_enforcer_instance is None:
        with _lock_instance:
            if _reversal_constraint_enforcer_instance is None:
                _reversal_constraint_enforcer_instance = ReversalConstraintEnforcer()
    return _reversal_constraint_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "ReversalCheckResult",
    "ReversalConstraintEnforcer",
    "ReversalReason",
    "ReversalRecord",
    "ReversalSeverity",
    "get_reversal_constraint_enforcer",
]
