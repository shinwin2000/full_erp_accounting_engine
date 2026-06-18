#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: 6 - Domain / Journal
Responsibility: Root agregat jurnal (header + banyak baris).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.journal.journal_entity import JournalStatus, JournalType
from domain.journal.journal_line_vo import JournalLineVO, JournalSide
from domain.journal.optimistic_lock import VersionedJournalMixin
from domain.journal.state_machine import JournalStateMachine

logger = logging.getLogger(__name__)


@dataclass
class Journal(VersionedJournalMixin):
    """
    Root aggregate untuk journal entry.
    Mewakili jurnal akuntansi yang mencatat transaksi keuangan.
    Setiap jurnal harus balance (total debit = total kredit).
    """

    journal_id: UUID
    journal_number: str
    journal_type: JournalType
    transaction_date: datetime
    posting_date: datetime | None
    description: str
    lines: list[JournalLineVO]
    legal_entity_id: UUID
    status: JournalStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    approved_by: list[str] = field(default_factory=list)
    approved_at: datetime | None = None
    posted_by: str | None = None
    posted_at: datetime | None = None
    reversed_by: str | None = None
    reversed_at: datetime | None = None
    reversal_of: UUID | None = None
    reversal_journal_id: UUID | None = None
    reference: str | None = None
    source_system: str = "ERP"
    _version: int = 1
    _audit_trail: list[dict] = field(default_factory=list)
    _snapshots: list[dict] = field(default_factory=list)
    _is_locked: bool = False
    _locked_by: str | None = None
    _locked_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validasi jurnal setelah inisialisasi."""
        super().__init__(version=self._version)
        if not self.is_balanced():
            raise ValueError(
                f"Journal is not balanced: debit={self.total_debit}, credit={self.total_credit}"
            )
        for line in self.lines:
            if line.legal_entity_id != self.legal_entity_id:
                raise ValueError(f"Line {line.line_id} has different legal_entity_id")
        if not self.journal_number or len(self.journal_number.strip()) < 3:
            raise ValueError("Journal number must be at least 3 characters")
        if not self.description or len(self.description.strip()) < 2:
            raise ValueError("Description must be at least 2 characters")

    # ==================== PROPERTIES ====================

    @property
    def total_debit(self) -> Decimal:
        return sum(line.amount for line in self.lines if line.side == JournalSide.DEBIT)

    @property
    def total_credit(self) -> Decimal:
        return sum(line.amount for line in self.lines if line.side == JournalSide.CREDIT)

    @property
    def difference(self) -> Decimal:
        return self.total_debit - self.total_credit

    @property
    def version(self) -> int:
        return self._version

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @property
    def audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    # ==================== CORE BUSINESS METHODS ====================

    def is_balanced(self, tolerance: Decimal = Decimal("0.0001")) -> bool:
        return abs(self.difference) <= tolerance

    def is_posted(self) -> bool:
        return self.status == JournalStatus.POSTED

    def is_reversed(self) -> bool:
        return self.reversal_journal_id is not None

    def can_approve(self, user_id: str) -> bool:
        if self.status != JournalStatus.SUBMITTED:
            return False
        if user_id == self.created_by:
            return False
        return True

    def can_post(self, user_id: str) -> bool:
        return self.status == JournalStatus.APPROVED

    def can_reverse(self) -> bool:
        return self.status == JournalStatus.POSTED

    def can_edit(self) -> bool:
        return self.status in [JournalStatus.DRAFT, JournalStatus.REJECTED]

    def can_delete(self) -> bool:
        return self.status == JournalStatus.DRAFT

    # ==================== LOCK / UNLOCK ====================

    def lock(self, user_id: str, reason: str | None = None) -> Journal:
        if self._is_locked:
            raise ValueError(f"Journal is already locked by {self._locked_by}")
        self._record_audit_trail("locked", {"user_id": user_id, "reason": reason})
        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
            _is_locked=True,
            _locked_by=user_id,
            _locked_at=datetime.now(UTC),
        )

    def unlock(self, user_id: str) -> Journal:
        if not self._is_locked:
            raise ValueError("Journal is not locked")
        if self._locked_by != user_id:
            raise ValueError(f"Journal locked by {self._locked_by}, cannot unlock by {user_id}")
        self._record_audit_trail("unlocked", {"user_id": user_id})
        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
            _is_locked=False,
            _locked_by=None,
            _locked_at=None,
        )

    # ==================== STATE TRANSITIONS ====================

    def submit(self, submitted_by: str) -> Journal:
        if self._is_locked:
            raise ValueError("Cannot submit locked journal")
        if self.status != JournalStatus.DRAFT:
            raise ValueError(f"Cannot submit journal in status {self.status.value}")

        valid, message = JournalStateMachine.validate_transition(
            from_status=self.status,
            to_status=JournalStatus.SUBMITTED,
            user_role="maker",
            is_balanced=self.is_balanced(),
        )
        if not valid:
            raise ValueError(message)

        self._record_audit_trail("submitted", {"user_id": submitted_by})
        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=JournalStatus.SUBMITTED,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def approve(self, approved_by: str) -> Journal:
        if self._is_locked:
            raise ValueError("Cannot approve locked journal")
        if self.status != JournalStatus.SUBMITTED:
            raise ValueError(f"Cannot approve journal in status {self.status.value}")
        if approved_by == self.created_by:
            raise ValueError("Maker cannot approve own journal")

        valid, message = JournalStateMachine.validate_transition(
            from_status=self.status,
            to_status=JournalStatus.APPROVED,
            user_role="approver",
        )
        if not valid:
            raise ValueError(message)

        new_approved_by = self.approved_by + [approved_by]
        self._record_audit_trail("approved", {"user_id": approved_by})

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=JournalStatus.APPROVED,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=new_approved_by,
            approved_at=datetime.now(UTC),
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def reject(self, rejected_by: str, reason: str) -> Journal:
        if self._is_locked:
            raise ValueError("Cannot reject locked journal")
        if self.status != JournalStatus.SUBMITTED:
            raise ValueError(f"Cannot reject journal in status {self.status.value}")

        valid, message = JournalStateMachine.validate_transition(
            from_status=self.status,
            to_status=JournalStatus.REJECTED,
            user_role="approver",
        )
        if not valid:
            raise ValueError(message)

        self._record_audit_trail("rejected", {"user_id": rejected_by, "reason": reason})

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=f"{self.description}\nRejected: {reason}",
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=JournalStatus.REJECTED,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def post(self, posted_by: str) -> Journal:
        if self._is_locked:
            raise ValueError("Cannot post locked journal")
        if self.status != JournalStatus.APPROVED:
            raise ValueError(f"Cannot post journal in status {self.status.value}")

        valid, message = JournalStateMachine.validate_transition(
            from_status=self.status,
            to_status=JournalStatus.POSTED,
            user_role="poster",
        )
        if not valid:
            raise ValueError(message)

        self._record_audit_trail("posted", {"user_id": posted_by})

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=datetime.now(UTC),
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=JournalStatus.POSTED,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=posted_by,
            posted_at=datetime.now(UTC),
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def reverse(self, reversed_by: str, reversal_journal_id: UUID, reason: str) -> Journal:
        if self._is_locked:
            raise ValueError("Cannot reverse locked journal")
        if self.status != JournalStatus.POSTED:
            raise ValueError(f"Cannot reverse journal in status {self.status.value}")

        valid, message = JournalStateMachine.validate_transition(
            from_status=self.status,
            to_status=JournalStatus.REVERSED,
            user_role="manager",
        )
        if not valid:
            raise ValueError(message)

        self._record_audit_trail(
            "reversed",
            {
                "user_id": reversed_by,
                "reason": reason,
                "reversal_journal_id": str(reversal_journal_id),
            },
        )

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=JournalStatus.REVERSED,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=reversed_by,
            reversed_at=datetime.now(UTC),
            reversal_of=self.journal_id,
            reversal_journal_id=reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def void(self, voided_by: str, reason: str) -> Journal:
        """Membatalkan jurnal (void)."""
        if self._is_locked:
            raise ValueError("Cannot void locked journal")
        if self.status not in [JournalStatus.DRAFT, JournalStatus.SUBMITTED]:
            raise ValueError(f"Cannot void journal in status {self.status.value}")

        valid, message = JournalStateMachine.validate_transition(
            from_status=self.status,
            to_status=JournalStatus.CANCELLED,
            user_role="manager",
        )
        if not valid:
            raise ValueError(message or "Cannot void journal")

        self._record_audit_trail("voided", {"user_id": voided_by, "reason": reason})

        from domain.journal.journal_entity import JournalStatus as JS

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=f"{self.description}\nVoided: {reason}",
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=JS.CANCELLED,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def archive(self, archived_by: str) -> Journal:
        """Mengarsipkan jurnal."""
        if self.status not in [
            JournalStatus.POSTED,
            JournalStatus.REVERSED,
            JournalStatus.REJECTED,
        ]:
            raise ValueError(f"Cannot archive journal in status {self.status.value}")

        self._record_audit_trail("archived", {"user_id": archived_by})

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=JournalStatus.ARCHIVED,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def unarchive(self, unarchived_by: str) -> Journal:
        """Membatalkan arsip jurnal."""
        if self.status != JournalStatus.ARCHIVED:
            raise ValueError(f"Cannot unarchive journal in status {self.status.value}")

        previous_status = JournalStatus.POSTED if self.posted_by else JournalStatus.REJECTED
        self._record_audit_trail("unarchived", {"user_id": unarchived_by})

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=self.lines,
            legal_entity_id=self.legal_entity_id,
            status=previous_status,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    # ==================== LINE MANAGEMENT ====================

    def add_line(self, new_line: JournalLineVO) -> Journal:
        """Menambah baris jurnal."""
        if self._is_locked:
            raise ValueError("Cannot add line to locked journal")
        if not self.can_edit():
            raise ValueError(f"Cannot add line to journal in status {self.status.value}")

        new_lines = self.lines + [new_line]
        total_debit = sum(l.amount for l in new_lines if l.side == JournalSide.DEBIT)
        total_credit = sum(l.amount for l in new_lines if l.side == JournalSide.CREDIT)

        if abs(total_debit - total_credit) > Decimal("0.01"):
            raise ValueError(
                f"Journal would be unbalanced: debit={total_debit}, credit={total_credit}"
            )

        self._record_audit_trail("line_added", {"line_id": str(new_line.line_id)})

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=new_lines,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    def remove_line(self, line_id: UUID) -> Journal:
        """Menghapus baris jurnal."""
        if self._is_locked:
            raise ValueError("Cannot remove line from locked journal")
        if not self.can_edit():
            raise ValueError(f"Cannot remove line from journal in status {self.status.value}")

        line_to_remove = next((l for l in self.lines if l.line_id == line_id), None)
        if not line_to_remove:
            raise ValueError(f"Line {line_id} not found")

        new_lines = [l for l in self.lines if l.line_id != line_id]
        if not new_lines:
            raise ValueError("Journal must have at least one line")

        total_debit = sum(l.amount for l in new_lines if l.side == JournalSide.DEBIT)
        total_credit = sum(l.amount for l in new_lines if l.side == JournalSide.CREDIT)

        if abs(total_debit - total_credit) > Decimal("0.01"):
            raise ValueError(
                f"Journal would be unbalanced: debit={total_debit}, credit={total_credit}"
            )

        self._record_audit_trail("line_removed", {"line_id": str(line_id)})

        return Journal(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            posting_date=self.posting_date,
            description=self.description,
            lines=new_lines,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            posted_by=self.posted_by,
            posted_at=self.posted_at,
            reversed_by=self.reversed_by,
            reversed_at=self.reversed_at,
            reversal_of=self.reversal_of,
            reversal_journal_id=self.reversal_journal_id,
            reference=self.reference,
            source_system=self.source_system,
            _version=self._version + 1,
        )

    # ==================== VALIDATION ====================

    def validate(self) -> list[str]:
        """Validasi semua invariant jurnal."""
        errors = []
        if not self.is_balanced():
            errors.append(
                f"Journal not balanced: debit={self.total_debit}, credit={self.total_credit}"
            )
        if not self.lines:
            errors.append("Journal must have at least one line")
        for line in self.lines:
            if line.amount <= 0:
                errors.append(f"Line {line.line_id} has invalid amount: {line.amount}")
        if not self.journal_number or len(self.journal_number.strip()) < 3:
            errors.append("Journal number must be at least 3 characters")
        if not self.description or len(self.description.strip()) < 2:
            errors.append("Description must be at least 2 characters")
        return errors

    # ==================== AUDIT TRAIL ====================

    def _record_audit_trail(self, action: str, details: dict) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
                "version": self._version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def clear_audit_trail(self) -> None:
        self._audit_trail.clear()

    # ==================== SNAPSHOT ====================

    def snapshot(self) -> dict:
        """Membuat snapshot dari state saat ini."""
        snapshot_data = {
            "aggregate_id": str(self.journal_id),
            "aggregate_type": "Journal",
            "version": self._version,
            "timestamp": datetime.now(UTC).isoformat(),
            "state": {
                "journal_number": self.journal_number,
                "journal_type": self.journal_type.value,
                "transaction_date": self.transaction_date.isoformat(),
                "description": self.description,
                "status": self.status.value,
                "total_debit": str(self.total_debit),
                "total_credit": str(self.total_credit),
                "lines_count": len(self.lines),
            },
            "hash": self._compute_hash(),
        }
        self._snapshots.append(snapshot_data)
        self._record_audit_trail("snapshot_created", {"version": self._version})
        return snapshot_data

    def restore_from_snapshot(self, snapshot: dict) -> None:
        """Restore state dari snapshot."""
        if snapshot.get("aggregate_id") != str(self.journal_id):
            raise ValueError("Snapshot belongs to different aggregate")
        self._record_audit_trail(
            "restored_from_snapshot", {"snapshot_version": snapshot.get("version")}
        )

    def _compute_hash(self) -> str:
        """Compute hash untuk integrity."""
        state_str = json.dumps(
            {
                "id": str(self.journal_id),
                "version": self._version,
                "total_debit": str(self.total_debit),
                "total_credit": str(self.total_credit),
                "status": self.status.value,
            },
            sort_keys=True,
        )
        return hashlib.sha256(state_str.encode()).hexdigest()

    # ==================== CLONE ====================

    def clone(self) -> Journal:
        """Membuat copy dari journal."""
        new_lines = [
            JournalLineVO(
                line_id=uuid4(),
                journal_id=uuid4(),
                account_id=line.account_id,
                account_code=line.account_code,
                account_name=line.account_name,
                side=line.side,
                amount=line.amount,
                description=line.description,
                legal_entity_id=line.legal_entity_id,
                cost_center=line.cost_center,
                department=line.department,
                project_id=line.project_id,
                customer_id=line.customer_id,
                supplier_id=line.supplier_id,
                employee_id=line.employee_id,
            )
            for line in self.lines
        ]

        self._record_audit_trail("cloned", {"source_id": str(self.journal_id)})

        return Journal(
            journal_id=uuid4(),
            journal_number=f"COPY-{self.journal_number}",
            journal_type=self.journal_type,
            transaction_date=datetime.now(UTC),
            posting_date=None,
            description=f"Copy of: {self.description}",
            lines=new_lines,
            legal_entity_id=self.legal_entity_id,
            status=JournalStatus.DRAFT,
            created_by=self.created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            reference=self.reference,
            source_system=self.source_system,
            _version=1,
        )

    # ==================== DICTIONARY METHODS ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "journal_type": self.journal_type.value,
            "transaction_date": self.transaction_date.isoformat(),
            "posting_date": self.posting_date.isoformat() if self.posting_date else None,
            "description": self.description,
            "lines_count": len(self.lines),
            "lines": [line.to_dict() for line in self.lines],
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
            "legal_entity_id": str(self.legal_entity_id),
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "posted_by": self.posted_by,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "reversed_by": self.reversed_by,
            "reversed_at": self.reversed_at.isoformat() if self.reversed_at else None,
            "reversal_of": str(self.reversal_of) if self.reversal_of else None,
            "reversal_journal_id": str(self.reversal_journal_id)
            if self.reversal_journal_id
            else None,
            "reference": self.reference,
            "source_system": self.source_system,
            "version": self._version,
            "is_locked": self._is_locked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Journal:
        from domain.journal.journal_line_vo import JournalLineVO, JournalSide

        lines = []
        for line_data in data.get("lines", []):
            lines.append(
                JournalLineVO(
                    line_id=UUID(line_data["line_id"]),
                    journal_id=UUID(data["journal_id"]),
                    account_id=UUID(line_data["account_id"]),
                    account_code=line_data["account_code"],
                    account_name=line_data["account_name"],
                    side=JournalSide(line_data["side"]),
                    amount=Decimal(line_data["amount"]),
                    description=line_data["description"],
                    legal_entity_id=UUID(data["legal_entity_id"]),
                    cost_center=line_data.get("cost_center"),
                    department=line_data.get("department"),
                    project_id=UUID(line_data["project_id"])
                    if line_data.get("project_id")
                    else None,
                    customer_id=UUID(line_data["customer_id"])
                    if line_data.get("customer_id")
                    else None,
                    supplier_id=UUID(line_data["supplier_id"])
                    if line_data.get("supplier_id")
                    else None,
                    employee_id=UUID(line_data["employee_id"])
                    if line_data.get("employee_id")
                    else None,
                )
            )

        return cls(
            journal_id=UUID(data["journal_id"]),
            journal_number=data["journal_number"],
            journal_type=JournalType(data["journal_type"]),
            transaction_date=datetime.fromisoformat(data["transaction_date"]),
            posting_date=datetime.fromisoformat(data["posting_date"])
            if data.get("posting_date")
            else None,
            description=data["description"],
            lines=lines,
            legal_entity_id=UUID(data["legal_entity_id"]),
            status=JournalStatus(data["status"]),
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            approved_by=data.get("approved_by", []),
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            posted_by=data.get("posted_by"),
            posted_at=datetime.fromisoformat(data["posted_at"]) if data.get("posted_at") else None,
            reversed_by=data.get("reversed_by"),
            reversed_at=datetime.fromisoformat(data["reversed_at"])
            if data.get("reversed_at")
            else None,
            reversal_of=UUID(data["reversal_of"]) if data.get("reversal_of") else None,
            reversal_journal_id=UUID(data["reversal_journal_id"])
            if data.get("reversal_journal_id")
            else None,
            reference=data.get("reference"),
            source_system=data.get("source_system", "ERP"),
            _version=data.get("version", 1),
        )


# === REPOSITORY PROTOCOL ===


class JournalRepository:
    async def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> Journal | None:
        raise NotImplementedError

    async def get_by_number(self, journal_number: str, legal_entity_id: UUID) -> Journal | None:
        raise NotImplementedError

    async def get_by_date_range(
        self, legal_entity_id: UUID, from_date: datetime, to_date: datetime, limit: int = 100
    ) -> list[Journal]:
        raise NotImplementedError

    async def get_by_status(
        self, legal_entity_id: UUID, status: JournalStatus, limit: int = 100
    ) -> list[Journal]:
        raise NotImplementedError

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[Journal]:
        raise NotImplementedError

    async def save(self, journal: Journal) -> None:
        raise NotImplementedError

    async def delete(self, journal_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def exists(self, journal_number: str, legal_entity_id: UUID) -> bool:
        raise NotImplementedError

    async def count(self, legal_entity_id: UUID, status: JournalStatus | None = None) -> int:
        raise NotImplementedError


# === ALIAS ===
JournalAggregate = Journal

__all__ = [
    "Journal",
    "JournalAggregate",
    "JournalRepository",
]
