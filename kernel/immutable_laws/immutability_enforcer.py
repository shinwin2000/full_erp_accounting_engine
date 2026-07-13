#!/usr/bin/env python3
"""
Module: immutability_enforcer.py
Layer: Kernel / Immutable Laws
Responsibility: Enforce immutability of posted journals.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    ImmutabilityLawViolation,
    LawViolationSeverity,
)

logger = logging.getLogger(__name__)


class JournalStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    POSTED = "posted"
    REVERSED = "reversed"
    ARCHIVED = "archived"
    VOID = "void"


class Journal:
    def __init__(
        self,
        journal_id: UUID,
        journal_number: str,
        status: JournalStatus,
        total_debit: Decimal,
        total_credit: Decimal,
        created_at: datetime,
        is_reversed: bool = False,
        reversal_journal_id: UUID | None = None,
    ):
        self.journal_id = journal_id
        self.journal_number = journal_number
        self.status = status
        self.total_debit = total_debit
        self.total_credit = total_credit
        self.created_at = created_at
        self.is_reversed = is_reversed
        self.reversal_journal_id = reversal_journal_id

    def is_balanced(self) -> bool:
        return abs(self.total_debit - self.total_credit) <= Decimal("0.0001")


class _FallbackJournalRepository:
    def __init__(self):
        self._journals: dict[UUID, Journal] = {}
        self._journal_by_number: dict[str, UUID] = {}

    async def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> Journal | None:
        return self._journals.get(journal_id)

    async def get_by_number(self, journal_number: str, legal_entity_id: UUID) -> Journal | None:
        jid = self._journal_by_number.get(journal_number)
        if jid:
            return self._journals.get(jid)
        return None

    async def update_status(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        new_status: JournalStatus,
        updated_by: str,
    ) -> bool:
        journal = self._journals.get(journal_id)
        if journal:
            updated = Journal(
                journal_id=journal.journal_id,
                journal_number=journal.journal_number,
                status=new_status,
                total_debit=journal.total_debit,
                total_credit=journal.total_credit,
                created_at=journal.created_at,
                is_reversed=journal.is_reversed,
                reversal_journal_id=journal.reversal_journal_id,
            )
            self._journals[journal_id] = updated
            return True
        return False

    async def mark_as_reversed(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        reversal_journal_id: UUID,
        reversed_by: str,
        reversed_at: datetime,
    ) -> bool:
        journal = self._journals.get(journal_id)
        if journal:
            updated = Journal(
                journal_id=journal.journal_id,
                journal_number=journal.journal_number,
                status=JournalStatus.REVERSED,
                total_debit=journal.total_debit,
                total_credit=journal.total_credit,
                created_at=journal.created_at,
                is_reversed=True,
                reversal_journal_id=reversal_journal_id,
            )
            self._journals[journal_id] = updated
            return True
        return False

    def add_journal(self, journal: Journal) -> None:
        self._journals[journal.journal_id] = journal
        self._journal_by_number[journal.journal_number] = journal.journal_id

    def clear(self) -> None:
        self._journals.clear()
        self._journal_by_number.clear()


class ImmutabilityViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


@dataclass
class ImmutabilityViolationRecord:
    violation_id: UUID
    journal_id: UUID
    journal_number: str
    attempted_operation: str
    current_status: str
    user_id: str
    timestamp: datetime
    message: str
    severity: ImmutabilityViolationSeverity
    is_correction: bool
    resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.violation_id}|{self.journal_id}|{self.attempted_operation}|"
            f"{self.current_status}|{self.user_id}|{self.severity.value}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def resolve(self, resolved_by: str) -> ImmutabilityViolationRecord:
        return ImmutabilityViolationRecord(
            violation_id=self.violation_id,
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            attempted_operation=self.attempted_operation,
            current_status=self.current_status,
            user_id=self.user_id,
            timestamp=self.timestamp,
            message=self.message,
            severity=self.severity,
            is_correction=self.is_correction,
            resolved=True,
            resolved_at=datetime.now(UTC),
            resolved_by=resolved_by,
            cryptographic_hash=self.cryptographic_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "attempted_operation": self.attempted_operation,
            "current_status": self.current_status,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "severity": self.severity.name,
            "is_correction": self.is_correction,
            "resolved": self.resolved,
        }


# ============================================================================
# BASE IMMUTABILITY ENFORCER (ABSTRACT)
# ============================================================================

class BaseImmutabilityEnforcer(ABC):
    """Base contract untuk Immutability Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    async def enforce_immutability(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        operation: str = "UPDATE",
        user_id: str | None = None,
        is_correction: bool = False,
        correction_reference: UUID | None = None,
        bypass_authorization: list[str] | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ImmutabilityViolationRecord | None]:
        """Enforce immutability for a journal operation."""
        pass

    @abstractmethod
    async def enforce_before_posting(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ImmutabilityViolationRecord | None]:
        """Validate journal before posting."""
        pass

    @abstractmethod
    async def record_posted_state(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        posted_by: str,
    ) -> bool:
        """Record that a journal has been posted."""
        pass

    @abstractmethod
    async def record_reversed_state(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        reversal_journal_id: UUID,
        reversed_by: str,
    ) -> bool:
        """Record that a journal has been reversed."""
        pass

    @abstractmethod
    def get_allowed_states_for_operation(self, operation: str) -> list[JournalStatus]:
        """Get allowed states for a given operation."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        journal_id: UUID | None = None,
        user_id: str | None = None,
        min_severity: ImmutabilityViolationSeverity | None = None,
        unresolved_only: bool = False,
    ) -> list[ImmutabilityViolationRecord]:
        """Get violation history."""
        pass

    @abstractmethod
    def resolve_violation(
        self,
        violation_id: UUID,
        resolved_by: str,
    ) -> ImmutabilityViolationRecord | None:
        """Resolve a violation."""
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
    def from_dict(cls, data: dict[str, Any]) -> BaseImmutabilityEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseImmutabilityEnforcer:
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
    def touch(self, touched_by: str) -> BaseImmutabilityEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# IMMUTABILITY ENFORCER (CONCRETE)
# ============================================================================

class ImmutabilityEnforcer(BaseImmutabilityEnforcer):
    IMMUTABLE_STATUSES = {JournalStatus.POSTED, JournalStatus.REVERSED, JournalStatus.ARCHIVED}
    MUTABLE_STATUSES = {JournalStatus.DRAFT, JournalStatus.SUBMITTED, JournalStatus.APPROVED}
    ALLOWED_OPERATIONS_ON_IMMUTABLE = {"READ", "SELECT", "GET", "VIEW", "EXPORT"}
    CORRECTION_OPERATIONS = {"REVERSE", "CORRECT", "ADJUST", "AMEND"}

    def __init__(self, journal_repository: Any | None = None):
        self._journal_repo = journal_repository or _FallbackJournalRepository()
        self._violations: list[ImmutabilityViolationRecord] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._emergency_override_roles = {"super_admin", "audit_committee", "ceo"}
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
        journal_id = context.get("journal_id")
        legal_entity_id = context.get("legal_entity_id")
        operation = context.get("operation", "UPDATE")

        if not journal_id:
            errors.append("journal_id is required")
        else:
            try:
                UUID(str(journal_id))
            except Exception:
                errors.append("journal_id must be a valid UUID")
        if not legal_entity_id:
            errors.append("legal_entity_id is required")
        else:
            try:
                UUID(str(legal_entity_id))
            except Exception:
                errors.append("legal_entity_id must be a valid UUID")
        if operation and not isinstance(operation, str):
            errors.append("operation must be a string")
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
                "max_history": self._max_history,
                "violations_count": len(self._violations),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImmutabilityEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ImmutabilityEnforcer:
        """Clone instance."""
        new_instance = ImmutabilityEnforcer()
        new_instance._enabled = self._enabled
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "violations_count": len(self._violations),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ImmutabilityEnforcer:
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
        logger.info(f"Immutability enforcer status: {enabled}")

    async def enforce_immutability(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        operation: str = "UPDATE",
        user_id: str | None = None,
        is_correction: bool = False,
        correction_reference: UUID | None = None,
        bypass_authorization: list[str] | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ImmutabilityViolationRecord | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        journal = await self._journal_repo.get_by_id(journal_id, legal_entity_id)
        if not journal:
            return True, None

        operation_upper = operation.upper()

        if journal.status in self.IMMUTABLE_STATUSES:
            if operation_upper in self.ALLOWED_OPERATIONS_ON_IMMUTABLE:
                return True, None

            if is_correction and operation_upper in self.CORRECTION_OPERATIONS:
                if correction_reference and correction_reference == journal_id:
                    if self._is_authorized_for_correction(user_id, bypass_authorization):
                        logger.info(f"Immutability override applied to journal {journal_id}")
                        self._record_audit("IMMUTABILITY_OVERRIDE", user_id, {"journal_id": str(journal_id)})
                        return True, None
                    else:
                        violation = self._create_violation(
                            journal_id=journal_id,
                            journal_number=journal.journal_number,
                            attempted_operation=operation,
                            current_status=journal.status.value,
                            user_id=user_id,
                            severity=ImmutabilityViolationSeverity.CRITICAL,
                            message=f"Unauthorized correction attempt on journal {journal_id}",
                            is_correction=True,
                        )
                        self._record_violation(violation)
                        if raise_on_violation:
                            raise ImmutabilityLawViolation(
                                message=violation.message,
                                attempted_operation=operation,
                                target_id=str(journal_id),
                                severity=LawViolationSeverity.CRITICAL,
                                details=violation.to_dict(),
                            )
                        return False, violation
                else:
                    violation = self._create_violation(
                        journal_id=journal_id,
                        journal_number=journal.journal_number,
                        attempted_operation=operation,
                        current_status=journal.status.value,
                        user_id=user_id,
                        severity=ImmutabilityViolationSeverity.HIGH,
                        message=f"Correction missing reference to original journal {journal_id}",
                        is_correction=True,
                    )
                    self._record_violation(violation)
                    if raise_on_violation:
                        raise ImmutabilityLawViolation(
                            message=violation.message,
                            attempted_operation=operation,
                            target_id=str(journal_id),
                            severity=LawViolationSeverity.HIGH,
                            details=violation.to_dict(),
                        )
                    return False, violation

            if bypass_authorization and any(
                role in self._emergency_override_roles for role in bypass_authorization
            ):
                logger.warning(f"Immutability override invoked for journal {journal_id}")
                self._record_audit("EMERGENCY_OVERRIDE", user_id, {"journal_id": str(journal_id)})
                return True, None

            violation = self._create_violation(
                journal_id=journal_id,
                journal_number=journal.journal_number,
                attempted_operation=operation,
                current_status=journal.status.value,
                user_id=user_id,
                severity=ImmutabilityViolationSeverity.CRITICAL,
                message=f"Cannot perform {operation} on journal {journal.journal_number} in {journal.status.value} state (immutable)",
                is_correction=False,
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise ImmutabilityLawViolation(
                    message=violation.message,
                    attempted_operation=operation,
                    target_id=str(journal_id),
                    severity=LawViolationSeverity.CRITICAL,
                    details=violation.to_dict(),
                )
            return False, violation

        if operation_upper in ("UPDATE", "EDIT", "MODIFY"):
            if journal.status == JournalStatus.DRAFT:
                return True, None
            elif journal.status in (JournalStatus.SUBMITTED, JournalStatus.APPROVED):
                if bypass_authorization:
                    logger.info(f"State override applied to journal {journal.journal_number}")
                    self._record_audit("STATE_OVERRIDE", user_id, {"journal_id": str(journal_id)})
                    return True, None
                else:
                    violation = self._create_violation(
                        journal_id=journal_id,
                        journal_number=journal.journal_number,
                        attempted_operation=operation,
                        current_status=journal.status.value,
                        user_id=user_id,
                        severity=ImmutabilityViolationSeverity.MEDIUM,
                        message=f"Modification of {journal.status.value} journal {journal.journal_number} requires authorization",
                        is_correction=False,
                    )
                    self._record_violation(violation)
                    if raise_on_violation:
                        raise ImmutabilityLawViolation(
                            message=violation.message,
                            attempted_operation=operation,
                            target_id=str(journal_id),
                            severity=LawViolationSeverity.MEDIUM,
                            details=violation.to_dict(),
                        )
                    return False, violation

        if operation_upper == "DELETE":
            if journal.status == JournalStatus.DRAFT:
                return True, None
            else:
                violation = self._create_violation(
                    journal_id=journal_id,
                    journal_number=journal.journal_number,
                    attempted_operation=operation,
                    current_status=journal.status.value,
                    user_id=user_id,
                    severity=ImmutabilityViolationSeverity.HIGH,
                    message=f"Cannot delete journal in {journal.status.value} state. Only DRAFT journals can be deleted.",
                    is_correction=False,
                )
                self._record_violation(violation)
                if raise_on_violation:
                    raise ImmutabilityLawViolation(
                        message=violation.message,
                        attempted_operation=operation,
                        target_id=str(journal_id),
                        severity=LawViolationSeverity.HIGH,
                        details=violation.to_dict(),
                    )
                return False, violation

        return True, None

    async def enforce_before_posting(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ImmutabilityViolationRecord | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        journal = await self._journal_repo.get_by_id(journal_id, legal_entity_id)
        if not journal:
            violation = self._create_violation(
                journal_id=journal_id,
                journal_number="UNKNOWN",
                attempted_operation="POST",
                current_status="NOT_FOUND",
                user_id=user_id,
                severity=ImmutabilityViolationSeverity.CRITICAL,
                message=f"Journal {journal_id} not found for posting",
                is_correction=False,
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise ImmutabilityLawViolation(
                    message=violation.message,
                    attempted_operation="POST",
                    target_id=str(journal_id),
                    severity=LawViolationSeverity.CRITICAL,
                    details=violation.to_dict(),
                )
            return False, violation

        if journal.status not in (JournalStatus.APPROVED, JournalStatus.SUBMITTED):
            violation = self._create_violation(
                journal_id=journal_id,
                journal_number=journal.journal_number,
                attempted_operation="POST",
                current_status=journal.status.value,
                user_id=user_id,
                severity=ImmutabilityViolationSeverity.HIGH,
                message=f"Cannot post journal in {journal.status.value} state. Journal must be APPROVED or SUBMITTED.",
                is_correction=False,
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise ImmutabilityLawViolation(
                    message=violation.message,
                    attempted_operation="POST",
                    target_id=str(journal_id),
                    severity=LawViolationSeverity.HIGH,
                    details=violation.to_dict(),
                )
            return False, violation

        if not journal.is_balanced():
            violation = self._create_violation(
                journal_id=journal_id,
                journal_number=journal.journal_number,
                attempted_operation="POST",
                current_status=journal.status.value,
                user_id=user_id,
                severity=ImmutabilityViolationSeverity.CRITICAL,
                message=f"Journal {journal.journal_number} is not balanced (debit={journal.total_debit}, credit={journal.total_credit})",
                is_correction=False,
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise ImmutabilityLawViolation(
                    message=violation.message,
                    attempted_operation="POST",
                    target_id=str(journal_id),
                    severity=LawViolationSeverity.CRITICAL,
                    details=violation.to_dict(),
                )
            return False, violation

        return True, None

    async def record_posted_state(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        posted_by: str,
    ) -> bool:
        success = await self._journal_repo.update_status(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            new_status=JournalStatus.POSTED,
            updated_by=posted_by,
        )
        if success:
            self._record_audit("POST_JOURNAL", posted_by, {"journal_id": str(journal_id)})
            logger.info(f"Journal {journal_id} state changed to posted")
        return success

    async def record_reversed_state(
        self,
        journal_id: UUID,
        legal_entity_id: UUID,
        reversal_journal_id: UUID,
        reversed_by: str,
    ) -> bool:
        success = await self._journal_repo.mark_as_reversed(
            journal_id=journal_id,
            legal_entity_id=legal_entity_id,
            reversal_journal_id=reversal_journal_id,
            reversed_by=reversed_by,
            reversed_at=datetime.now(UTC),
        )
        if success:
            self._record_audit("REVERSE_JOURNAL", reversed_by, {"journal_id": str(journal_id)})
            logger.info(f"Journal {journal_id} marked as reversed")
        return success

    def _create_violation(
        self,
        journal_id: UUID,
        journal_number: str,
        attempted_operation: str,
        current_status: str,
        user_id: str,
        severity: ImmutabilityViolationSeverity,
        message: str,
        is_correction: bool,
    ) -> ImmutabilityViolationRecord:
        violation = ImmutabilityViolationRecord(
            violation_id=uuid4(),
            journal_id=journal_id,
            journal_number=journal_number,
            attempted_operation=attempted_operation,
            current_status=current_status,
            user_id=user_id,
            timestamp=datetime.now(UTC),
            message=message,
            severity=severity,
            is_correction=is_correction,
            resolved=False,
            cryptographic_hash="",
        )
        violation.cryptographic_hash = violation.compute_hash()
        return violation

    def _record_violation(self, violation: ImmutabilityViolationRecord) -> None:
        with self._lock:
            self._violations.append(violation)
            if len(self._violations) > self._max_history:
                self._violations = self._violations[-self._max_history :]
            self._record_audit("VIOLATION", violation.user_id, {
                "violation_id": str(violation.violation_id),
                "journal_id": str(violation.journal_id),
                "severity": violation.severity.name,
            })

    def _is_authorized_for_correction(
        self,
        user_id: str,
        bypass_authorization: list[str] | None,
    ) -> bool:
        if bypass_authorization:
            return any(role in self._emergency_override_roles for role in bypass_authorization)
        return user_id == "super_admin" or user_id == "emergency_admin"

    def get_allowed_states_for_operation(self, operation: str) -> list[JournalStatus]:
        op = operation.upper()
        if op in ("READ", "SELECT", "GET", "VIEW"):
            return list(JournalStatus)
        elif op in ("UPDATE", "EDIT", "MODIFY"):
            return [JournalStatus.DRAFT, JournalStatus.SUBMITTED, JournalStatus.APPROVED]
        elif op == "DELETE":
            return [JournalStatus.DRAFT]
        elif op in ("REVERSE", "CORRECT", "ADJUST", "AMEND"):
            return [JournalStatus.POSTED, JournalStatus.REVERSED, JournalStatus.ARCHIVED]
        else:
            return []

    def get_violations(
        self,
        limit: int = 100,
        journal_id: UUID | None = None,
        user_id: str | None = None,
        min_severity: ImmutabilityViolationSeverity | None = None,
        unresolved_only: bool = False,
    ) -> list[ImmutabilityViolationRecord]:
        with self._lock:
            result = self._violations[-limit:]
        if journal_id:
            result = [v for v in result if v.journal_id == journal_id]
        if user_id:
            result = [v for v in result if v.user_id == user_id]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def resolve_violation(
        self,
        violation_id: UUID,
        resolved_by: str,
    ) -> ImmutabilityViolationRecord | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.resolved:
                    resolved = v.resolve(resolved_by)
                    self._violations[i] = resolved
                    self._record_audit("RESOLVE_VIOLATION", resolved_by, {"violation_id": str(violation_id)})
                    logger.info(f"Violation {violation_id} resolved")
                    return resolved
        return None

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._violations)
            if total == 0:
                return {"total_violations": 0, "enabled": self._enabled, "version": self._version}

            unresolved = len([v for v in self._violations if not v.resolved])
            by_severity = {}
            for sev in ImmutabilityViolationSeverity:
                count = len([v for v in self._violations if v.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count

            by_operation = {}
            for v in self._violations:
                op = v.attempted_operation
                by_operation[op] = by_operation.get(op, 0) + 1

            correction_count = len([v for v in self._violations if v.is_correction])

            return {
                "total_violations": total,
                "unresolved_violations": unresolved,
                "by_severity": by_severity,
                "by_operation": by_operation,
                "correction_attempts": correction_count,
                "enabled": self._enabled,
                "version": self._version,
                "latest_violation": self._violations[-1].timestamp.isoformat()
                if self._violations
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._violations = []
            self._enabled = True
            self._version += 1
            self._audit_trail = []
            if hasattr(self._journal_repo, "clear"):
                self._journal_repo.clear()


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_immutability_enforcer_instance: ImmutabilityEnforcer | None = None
_lock_instance = threading.Lock()


def get_immutability_enforcer() -> ImmutabilityEnforcer:
    global _immutability_enforcer_instance
    if _immutability_enforcer_instance is None:
        with _lock_instance:
            if _immutability_enforcer_instance is None:
                _immutability_enforcer_instance = ImmutabilityEnforcer()
    return _immutability_enforcer_instance


__all__ = [
    "BaseImmutabilityEnforcer",
    "ImmutabilityEnforcer",
    "ImmutabilityViolationRecord",
    "ImmutabilityViolationSeverity",
    "get_immutability_enforcer",
]
