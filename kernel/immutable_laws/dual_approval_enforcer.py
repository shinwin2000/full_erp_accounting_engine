#!/usr/bin/env python3
"""
Module: dual_approval_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: transaksi di atas threshold harus dua persetujuan.
               Memastikan bahwa transaksi dengan jumlah melebihi batas tertentu
               (materiality threshold) harus mendapatkan persetujuan dari
               minimal dua orang yang berwenang (dual control/approval).

Dependencies:
- standard library (logging, decimal, datetime, typing, hashlib, copy)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, DualApprovalViolation)

Audit: Setiap transaksi yang memerlukan dual approval dictat status approval-nya.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    DualApprovalViolation,
    LawViolationSeverity,
)

logger = logging.getLogger(__name__)

VERSION = "1.0.0"  # version of this enforcer implementation


# === 1. FALLBACK REPOSITORIES (internal, synchronous) ===


class _FallbackApprovalRepository:
    """Fallback approval repository (synchronous)."""

    def __init__(self):
        self._approvals: dict[UUID, list[dict[str, Any]]] = {}  # transaction_id -> approvals

    def get_by_transaction(self, transaction_id: UUID, legal_entity_id: UUID) -> list[Any]:
        approvals = self._approvals.get(transaction_id, [])
        return [_ApprovalProxy(a) for a in approvals]

    def get_by_transaction_and_approver(
        self,
        transaction_id: UUID,
        approver_id: str,
        legal_entity_id: UUID,
    ) -> Any | None:
        approvals = self._approvals.get(transaction_id, [])
        for a in approvals:
            if a.get("approver_id") == approver_id:
                return _ApprovalProxy(a)
        return None

    def add_approval(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        approver_id: str,
        approval_level: int,
        notes: str | None,
        approved_at: datetime,
    ) -> bool:
        if transaction_id not in self._approvals:
            self._approvals[transaction_id] = []
        self._approvals[transaction_id].append(
            {
                "transaction_id": transaction_id,
                "legal_entity_id": legal_entity_id,
                "approver_id": approver_id,
                "approval_level": approval_level,
                "notes": notes,
                "approved_at": approved_at,
                "status": "APPROVED",
            }
        )
        return True

    def clear(self):
        self._approvals.clear()


class _ApprovalProxy:
    def __init__(self, data: dict[str, Any]):
        self.transaction_id = data.get("transaction_id")
        self.legal_entity_id = data.get("legal_entity_id")
        self.approver_id = data.get("approver_id")
        self.approval_level = data.get("approval_level")
        self.notes = data.get("notes")
        self.approved_at = data.get("approved_at")
        self.status = data.get("status")


class _FallbackJournalRepository:
    """Fallback journal repository (synchronous)."""

    def __init__(self):
        self._journals: dict[UUID, dict[str, Any]] = {}

    def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        journal = self._journals.get(journal_id)
        if journal and journal.get("legal_entity_id") == legal_entity_id:
            return journal
        return None

    def add_journal(
        self, journal_id: UUID, legal_entity_id: UUID, journal_type: str, amount: Decimal
    ) -> None:
        self._journals[journal_id] = {
            "journal_id": journal_id,
            "legal_entity_id": legal_entity_id,
            "journal_type": journal_type,
            "total_debit": amount,
            "status": "DRAFT",
        }


# === 2. CONSTANTS & ENUMS ===


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalLevel(Enum):
    FIRST = 1
    SECOND = 2
    THIRD = 3


@dataclass
class ApprovalRecord:
    """Rekaman approval."""

    approval_id: UUID
    transaction_id: UUID
    legal_entity_id: UUID
    approver_id: str
    approval_level: int
    status: ApprovalStatus
    notes: str | None
    approved_at: datetime
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.approval_id}|{self.transaction_id}|{self.approver_id}|"
            f"{self.approval_level}|{self.status.value}|{self.approved_at.isoformat()}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": str(self.approval_id),
            "transaction_id": str(self.transaction_id),
            "approver_id": self.approver_id,
            "approval_level": self.approval_level,
            "status": self.status.value,
            "notes": self.notes[:100] if self.notes else None,
            "approved_at": self.approved_at.isoformat(),
        }


# === 3. DUAL APPROVAL ENFORCER (synchronous) ===


class DualApprovalEnforcer:
    """
    Enforcer untuk hukum dual approval.

    Business context: Transaksi material harus mendapatkan persetujuan
    minimal dua orang untuk mencegah fraud dan error signifikan.
    """

    DEFAULT_THRESHOLDS: ClassVar[dict[str, Decimal]] = {
        "JOURNAL": Decimal("500000000"),
        "PAYMENT": Decimal("250000000"),
        "INVOICE": Decimal("500000000"),
        "ASSET_DISPOSAL": Decimal("100000000"),
        "PERIOD_CLOSE": Decimal("0"),
        "YEAR_END_CLOSE": Decimal("0"),
        "CONSOLIDATION": Decimal("0"),
    }

    ALWAYS_REQUIRE_DUAL: ClassVar[list[str]] = [
        "PERIOD_CLOSE",
        "YEAR_END_CLOSE",
        "CONSOLIDATION",
        "SYSTEM_CONFIG_CHANGE",
    ]

    def __init__(
        self,
        approval_repository: Any | None = None,
        journal_repository: Any | None = None,
    ):
        self._approval_repo = approval_repository or _FallbackApprovalRepository()
        self._journal_repo = journal_repository or _FallbackJournalRepository()
        self._thresholds = self.DEFAULT_THRESHOLDS.copy()
        self._approval_history: list[ApprovalRecord] = []
        self._violation_history: list[DualApprovalViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._last_touched: datetime | None = None

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        logger.info(f"Dual approval enforcer enabled: {enabled}")

    def set_threshold(self, transaction_type: str, threshold: Decimal) -> None:
        self._thresholds[transaction_type] = threshold
        logger.info(f"Dual approval threshold for {transaction_type} set to {threshold}")

    def requires_dual_approval(self, transaction_type: str, amount: Decimal) -> bool:
        if transaction_type in self.ALWAYS_REQUIRE_DUAL:
            return True
        threshold = self._thresholds.get(transaction_type, Decimal("1000000000"))
        return amount >= threshold

    def check_approval_status(
        self,
        transaction_id: UUID,
        transaction_type: str,
        legal_entity_id: UUID,
    ) -> tuple[bool, int, list[str]]:
        approvals = self._approval_repo.get_by_transaction(transaction_id, legal_entity_id)
        approved = [a for a in approvals if getattr(a, "status", "") == "APPROVED"]
        approvers = [getattr(a, "approver_id", "") for a in approved]
        is_approved = len(approvers) >= 2
        return is_approved, len(approvers), approvers

    def enforce_dual_approval(
        self,
        transaction_id: UUID,
        transaction_type: str,
        amount: Decimal,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, DualApprovalViolation | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        requires = self.requires_dual_approval(transaction_type, amount)
        if not requires:
            return True, None

        is_approved, approval_count, approvers = self.check_approval_status(
            transaction_id, transaction_type, legal_entity_id
        )

        if not is_approved:
            violation = DualApprovalViolation(
                message=(
                    f"Transaction {transaction_type} of amount {amount} requires dual approval. "
                    f"Current approvals: {approval_count}/2"
                ),
                transaction_id=str(transaction_id),
                amount=str(amount),
                required_approvals=2,
                severity=LawViolationSeverity.CRITICAL,
                details={
                    "transaction_id": str(transaction_id),
                    "transaction_type": transaction_type,
                    "amount": str(amount),
                    "approvals_received": approval_count,
                    "approvers": approvers,
                    "required_approvals": 2,
                },
            )
            self._record_violation(violation)
            if raise_on_violation:
                raise violation
            return False, violation

        return True, None

    def add_approval(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        approver_id: str,
        approval_level: int = 1,
        notes: str | None = None,
    ) -> ApprovalRecord | None:
        existing = self._approval_repo.get_by_transaction_and_approver(
            transaction_id, approver_id, legal_entity_id
        )
        if existing:
            logger.warning(f"Approver {approver_id} already approved transaction {transaction_id}")
            return None

        success = self._approval_repo.add_approval(
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            approver_id=approver_id,
            approval_level=approval_level,
            notes=notes,
            approved_at=datetime.now(UTC),
        )

        if success:
            record = ApprovalRecord(
                approval_id=uuid4(),
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                approver_id=approver_id,
                approval_level=approval_level,
                status=ApprovalStatus.APPROVED,
                notes=notes,
                approved_at=datetime.now(UTC),
                cryptographic_hash="",
            )
            record.cryptographic_hash = record.compute_hash()
            with self._lock:
                self._approval_history.append(record)
                if len(self._approval_history) > self._max_history:
                    self._approval_history = self._approval_history[-self._max_history :]
            logger.info(f"Approval added for transaction {transaction_id} by {approver_id}")
            return record

        return None

    def get_approval_status_summary(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        approvals = self._approval_repo.get_by_transaction(transaction_id, legal_entity_id)
        return {
            "transaction_id": str(transaction_id),
            "total_approvals": len(approvals),
            "approvals": [
                {
                    "approver_id": getattr(a, "approver_id", ""),
                    "approval_level": getattr(a, "approval_level", 0),
                    "status": getattr(a, "status", ""),
                    "approved_at": getattr(a, "approved_at", None).isoformat()
                    if getattr(a, "approved_at", None)
                    else None,
                    "notes": getattr(a, "notes", "")[:100],
                }
                for a in approvals
            ],
        }

    def _record_violation(self, violation: DualApprovalViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]

    def get_violations(
        self,
        limit: int = 100,
        transaction_id: UUID | None = None,
    ) -> list[DualApprovalViolation]:
        with self._lock:
            result = self._violation_history[-limit:]
        if transaction_id:
            result = [v for v in result if v.transaction_id == str(transaction_id)]
        return result

    def get_approval_history(
        self,
        limit: int = 100,
        transaction_id: UUID | None = None,
    ) -> list[ApprovalRecord]:
        with self._lock:
            result = self._approval_history[-limit:]
        if transaction_id:
            result = [r for r in result if r.transaction_id == transaction_id]
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_approvals = len(self._approval_history)
            total_violations = len(self._violation_history)
            if total_approvals == 0 and total_violations == 0:
                return {"total_approvals": 0, "total_violations": 0, "enabled": self._enabled}

            by_level = {}
            for a in self._approval_history:
                by_level[a.approval_level] = by_level.get(a.approval_level, 0) + 1

            return {
                "total_approvals": total_approvals,
                "total_violations": total_violations,
                "by_approval_level": by_level,
                "thresholds": {k: str(v) for k, v in self._thresholds.items()},
                "enabled": self._enabled,
                "latest_approval": self._approval_history[-1].approved_at.isoformat()
                if self._approval_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._approval_history = []
            self._violation_history = []
            self._thresholds = self.DEFAULT_THRESHOLDS.copy()
            self._enabled = True

    # ----------------------------------------------------------------------
    # Required compliance methods (synchronous)
    # ----------------------------------------------------------------------

    def enforce(
        self,
        transaction_id: UUID,
        transaction_type: str,
        amount: Decimal,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, DualApprovalViolation | None]:
        """
        Enforce dual approval for a transaction. Alias for enforce_dual_approval.
        """
        return self.enforce_dual_approval(
            transaction_id, transaction_type, amount, legal_entity_id,
            user_id, raise_on_violation
        )

    def check(
        self,
        transaction_id: UUID,
        transaction_type: str,
        amount: Decimal,
        legal_entity_id: UUID,
        user_id: str | None = None,
    ) -> bool:
        """
        Check if the transaction complies with dual approval requirements.
        Returns True if approved or not required, False otherwise.
        """
        ok, _ = self.enforce_dual_approval(
            transaction_id, transaction_type, amount, legal_entity_id,
            user_id, raise_on_violation=False
        )
        return ok

    def validate(self) -> list[str]:
        """
        Validate the cryptographic integrity of all stored approval records.
        Returns a list of error messages (empty if all valid).
        """
        errors = []
        with self._lock:
            for record in self._approval_history:
                computed = record.compute_hash()
                if record.cryptographic_hash != computed:
                    errors.append(
                        f"Hash mismatch for approval {record.approval_id} "
                        f"(tx {record.transaction_id})"
                    )
        return errors

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the enforcer's configuration and basic state.
        """
        with self._lock:
            return {
                "version": VERSION,
                "enabled": self._enabled,
                "thresholds": {k: str(v) for k, v in self._thresholds.items()},
                "max_history": self._max_history,
                "total_approvals": len(self._approval_history),
                "total_violations": len(self._violation_history),
                "last_touched": self._last_touched.isoformat() if self._last_touched else None,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DualApprovalEnforcer:
        """
        Create an enforcer instance from a dictionary (restores configuration).
        Note: History is not restored; only configuration.
        """
        instance = cls()
        instance._enabled = data.get("enabled", True)
        if "thresholds" in data:
            instance._thresholds = {
                k: Decimal(v) for k, v in data["thresholds"].items()
            }
        if "max_history" in data:
            instance._max_history = data["max_history"]
        # last_touched is not restored; it is updated on usage.
        return instance

    def clone(self) -> DualApprovalEnforcer:
        """
        Create a shallow clone of this enforcer.
        Repositories are not cloned; the new instance gets fresh fallback repos.
        """
        new_instance = DualApprovalEnforcer()
        # Copy configuration
        new_instance._enabled = self._enabled
        new_instance._thresholds = self._thresholds.copy()
        new_instance._max_history = self._max_history
        # Do NOT copy history or violations to keep clones isolated.
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """
        Capture a snapshot of the current state (same as to_dict for simplicity).
        """
        return self.to_dict()

    def version(self) -> str:
        """
        Return the version of this enforcer implementation.
        """
        return VERSION

    def audit_trail(self, limit: int = 100) -> dict[str, Any]:
        """
        Retrieve the audit trail: recent approvals and violations.
        """
        with self._lock:
            approvals = self._approval_history[-limit:]
            violations = self._violation_history[-limit:]
        return {
            "approvals": [a.to_dict() for a in approvals],
            "violations": [
                {
                    "transaction_id": v.transaction_id,
                    "amount": v.amount,
                    "message": v.message,
                    "severity": v.severity.value if hasattr(v, "severity") else None,
                }
                for v in violations
            ],
        }

    def touch(self) -> None:
        """
        Mark the enforcer as used (update last_touched timestamp).
        """
        self._last_touched = datetime.now(UTC)


# === 4. SINGLETON ACCESSOR ===

_dual_approval_enforcer_instance: DualApprovalEnforcer | None = None
_lock_instance = threading.Lock()


def get_dual_approval_enforcer() -> DualApprovalEnforcer:
    global _dual_approval_enforcer_instance
    if _dual_approval_enforcer_instance is None:
        with _lock_instance:
            if _dual_approval_enforcer_instance is None:
                _dual_approval_enforcer_instance = DualApprovalEnforcer()
    return _dual_approval_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "VERSION",
    "ApprovalLevel",
    "ApprovalRecord",
    "ApprovalStatus",
    "DualApprovalEnforcer",
    "get_dual_approval_enforcer",
]
