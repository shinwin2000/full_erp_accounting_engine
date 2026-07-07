#!/usr/bin/env python3
"""
Module: journal_entity.py
Layer: Domain / Journal
Responsibility: Entitas header jurnal dan state machine (circular import fixed).

Perbaikan:
- Validasi Double-Entry eksplisit di __post_init__.
- Immutability guard untuk journal yang sudah diposting.
- Method update_metadata dan update_totals dengan validasi.
- Helper _ensure_editable dan _ensure_not_posted.
- Docstring lengkap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class JournalStatus(Enum):
    """Status lifecycle of a journal entry."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    REVERSED = "reversed"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> JournalStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT

    def can_transition_to(self, to_status: JournalStatus) -> bool:
        """Check if transition to given status is allowed."""
        return globals()["JournalStateMachine"].can_transition(self, to_status)


class JournalType(Enum):
    """Type of journal entry."""
    GENERAL = "general"
    ADJUSTING = "adjusting"
    CLOSING = "closing"
    REVERSAL = "reversal"
    CORRECTION = "correction"
    INTERCOMPANY = "intercompany"
    CONSOLIDATION = "consolidation"
    ACCRUAL = "accrual"
    DEFERRAL = "deferral"
    BANK_TRANSFER = "bank_transfer"
    BANK_DEPOSIT = "bank_deposit"
    BANK_WITHDRAWAL = "bank_withdrawal"
    SALES_INVOICE = "sales_invoice"
    PURCHASE_INVOICE = "purchase_invoice"
    PAYMENT = "payment"
    RECEIPT = "receipt"
    DEPRECIATION = "depreciation"
    AMORTIZATION = "amortization"
    PAYROLL = "payroll"
    TAX = "tax"

    @classmethod
    def from_string(cls, value: str) -> JournalType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.GENERAL


@dataclass
class JournalLine:
    """A single line in a journal entry."""

    id: UUID = field(default_factory=uuid4)
    journal_id: UUID | None = None
    account_code: str = ""
    account_name: str = ""
    debit_amount: Decimal = Decimal(0)
    credit_amount: Decimal = Decimal(0)
    currency: str = "IDR"
    cost_center: str | None = None
    department: str | None = None
    description: str | None = None
    project_id: UUID | None = None
    customer_id: UUID | None = None
    supplier_id: UUID | None = None
    employee_id: UUID | None = None
    tax_rate: Decimal = Decimal(0)
    tax_amount: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        """Validate line invariants."""
        if self.debit_amount < 0 or self.credit_amount < 0:
            raise ValueError("Debit and credit amounts must be non-negative")
        if self.debit_amount == 0 and self.credit_amount == 0:
            raise ValueError("Either debit or credit must be > 0")
        if self.debit_amount > 0 and self.credit_amount > 0:
            raise ValueError("A line cannot have both debit and credit")

    @property
    def net_amount(self) -> Decimal:
        """Net amount (debit - credit)."""
        return self.debit_amount - self.credit_amount

    @property
    def side(self) -> str:
        """Return 'debit' or 'credit' based on the line."""
        return "debit" if self.debit_amount > 0 else "credit"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "journal_id": str(self.journal_id) if self.journal_id else None,
            "account_code": self.account_code,
            "account_name": self.account_name,
            "debit_amount": str(self.debit_amount),
            "credit_amount": str(self.credit_amount),
            "currency": self.currency,
            "cost_center": self.cost_center,
            "department": self.department,
            "description": self.description,
            "project_id": str(self.project_id) if self.project_id else None,
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "employee_id": str(self.employee_id) if self.employee_id else None,
            "tax_rate": str(self.tax_rate),
            "tax_amount": str(self.tax_amount),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalLine:
        """Reconstruct from dictionary."""
        return cls(
            id=UUID(data["id"]) if data.get("id") else uuid4(),
            journal_id=UUID(data["journal_id"]) if data.get("journal_id") else None,
            account_code=data.get("account_code", ""),
            account_name=data.get("account_name", ""),
            debit_amount=Decimal(data.get("debit_amount", "0")),
            credit_amount=Decimal(data.get("credit_amount", "0")),
            currency=data.get("currency", "IDR"),
            cost_center=data.get("cost_center"),
            department=data.get("department"),
            description=data.get("description"),
            project_id=UUID(data["project_id"]) if data.get("project_id") else None,
            customer_id=UUID(data["customer_id"]) if data.get("customer_id") else None,
            supplier_id=UUID(data["supplier_id"]) if data.get("supplier_id") else None,
            employee_id=UUID(data["employee_id"]) if data.get("employee_id") else None,
            tax_rate=Decimal(data.get("tax_rate", "0")),
            tax_amount=Decimal(data.get("tax_amount", "0")),
        )


# ============================================================================
# STATE MACHINE DEFINITIONS
# ============================================================================

_ALLOWED_TRANSITIONS: dict[JournalStatus, set[JournalStatus]] = {
    JournalStatus.DRAFT: {
        JournalStatus.SUBMITTED,
        JournalStatus.ARCHIVED,
        JournalStatus.CANCELLED,
    },
    JournalStatus.SUBMITTED: {
        JournalStatus.APPROVED,
        JournalStatus.REJECTED,
        JournalStatus.DRAFT,
        JournalStatus.CANCELLED,
    },
    JournalStatus.APPROVED: {
        JournalStatus.POSTED,
        JournalStatus.REJECTED,
        JournalStatus.DRAFT,
    },
    JournalStatus.REJECTED: {
        JournalStatus.DRAFT,
        JournalStatus.ARCHIVED,
    },
    JournalStatus.POSTED: {
        JournalStatus.REVERSED,
        JournalStatus.ARCHIVED,
    },
    JournalStatus.REVERSED: {
        JournalStatus.ARCHIVED,
    },
    JournalStatus.ARCHIVED: {
        JournalStatus.POSTED,
        JournalStatus.REJECTED,
    },
    JournalStatus.CANCELLED: set(),
}


@dataclass
class StateTransitionRule:
    """Rule for a state transition."""
    from_status: JournalStatus
    to_status: JournalStatus
    requires_approval: bool = False
    requires_dual_control: bool = False
    required_role: str | None = None
    check_balance: bool = False
    check_period_open: bool = False
    requires_reason: bool = False
    allowed_user_roles: list[str] | None = None


_TRANSITION_RULES: list[StateTransitionRule] = [
    StateTransitionRule(
        from_status=JournalStatus.DRAFT,
        to_status=JournalStatus.SUBMITTED,
        check_balance=True,
        requires_reason=False,
    ),
    StateTransitionRule(
        from_status=JournalStatus.SUBMITTED,
        to_status=JournalStatus.APPROVED,
        requires_approval=True,
        required_role="approver",
        allowed_user_roles=["approver", "manager"],
    ),
    StateTransitionRule(
        from_status=JournalStatus.SUBMITTED,
        to_status=JournalStatus.REJECTED,
        requires_approval=True,
        required_role="approver",
        requires_reason=True,
    ),
    StateTransitionRule(
        from_status=JournalStatus.APPROVED,
        to_status=JournalStatus.POSTED,
        requires_dual_control=False,
        check_period_open=True,
        required_role="poster",
    ),
    StateTransitionRule(
        from_status=JournalStatus.POSTED,
        to_status=JournalStatus.REVERSED,
        requires_approval=True,
        required_role="manager",
        check_period_open=True,
        requires_reason=True,
    ),
    StateTransitionRule(
        from_status=JournalStatus.DRAFT,
        to_status=JournalStatus.CANCELLED,
        requires_approval=True,
        required_role="manager",
        requires_reason=True,
    ),
    StateTransitionRule(
        from_status=JournalStatus.SUBMITTED,
        to_status=JournalStatus.CANCELLED,
        requires_approval=True,
        required_role="manager",
        requires_reason=True,
    ),
]


class JournalStateMachine:
    """State machine for journal status transitions."""

    @staticmethod
    def can_transition(from_status: JournalStatus, to_status: JournalStatus) -> bool:
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        return to_status in allowed

    @staticmethod
    def get_allowed_transitions(current_status: JournalStatus) -> list[JournalStatus]:
        return list(_ALLOWED_TRANSITIONS.get(current_status, set()))

    @staticmethod
    def get_transition_rule(
        from_status: JournalStatus,
        to_status: JournalStatus,
    ) -> StateTransitionRule | None:
        for rule in _TRANSITION_RULES:
            if rule.from_status == from_status and rule.to_status == to_status:
                return rule
        return None

    @staticmethod
    def validate_transition(
        from_status: JournalStatus,
        to_status: JournalStatus,
        user_role: str,
        is_balanced: bool = True,
        period_is_open: bool = True,
        amount: Decimal = Decimal(0),
        reason: str | None = None,
    ) -> tuple[bool, str | None]:
        if not JournalStateMachine.can_transition(from_status, to_status):
            return False, f"Cannot transition from {from_status.value} to {to_status.value}"

        rule = JournalStateMachine.get_transition_rule(from_status, to_status)
        if rule:
            if rule.check_balance and not is_balanced:
                return False, "Journal must be balanced before this transition"

            if rule.check_period_open and not period_is_open:
                return False, "Accounting period is closed. Cannot perform this transition."

            if rule.requires_approval and user_role not in (
                rule.allowed_user_roles or [rule.required_role]
            ):
                return (
                    False,
                    f"Approval required. User must have role '{rule.required_role or rule.allowed_user_roles}'",
                )

            if rule.requires_reason and not reason:
                return False, "Reason is required for this transition"

            if rule.requires_dual_control:
                threshold = Decimal("1000000000")
                if amount > threshold:
                    return False, f"Dual control required for amount exceeding {threshold}"

        return True, None

    @staticmethod
    def get_status_flow() -> dict[str, list[str]]:
        return {
            status.value: [s.value for s in _ALLOWED_TRANSITIONS.get(status, set())]
            for status in JournalStatus
        }

    @staticmethod
    def is_terminal(status: JournalStatus) -> bool:
        return len(_ALLOWED_TRANSITIONS.get(status, set())) == 0

    @staticmethod
    def can_edit(status: JournalStatus) -> bool:
        return status in [JournalStatus.DRAFT, JournalStatus.REJECTED]

    @staticmethod
    def can_delete(status: JournalStatus) -> bool:
        return status == JournalStatus.DRAFT

    @staticmethod
    def needs_approval(status: JournalStatus) -> bool:
        return status == JournalStatus.SUBMITTED

    @staticmethod
    def can_be_posted(status: JournalStatus) -> bool:
        return status == JournalStatus.APPROVED

    @staticmethod
    def get_next_statuses(current: JournalStatus) -> list[JournalStatus]:
        return JournalStateMachine.get_allowed_transitions(current)

    @staticmethod
    def get_previous_statuses(current: JournalStatus) -> list[JournalStatus]:
        previous = []
        for status, transitions in _ALLOWED_TRANSITIONS.items():
            if current in transitions:
                previous.append(status)
        return previous

    @staticmethod
    def get_status_description(status: JournalStatus) -> str:
        descriptions = {
            JournalStatus.DRAFT: "Draft - Initial state, can be edited",
            JournalStatus.SUBMITTED: "Submitted - Waiting for approval",
            JournalStatus.APPROVED: "Approved - Ready for posting",
            JournalStatus.REJECTED: "Rejected - Needs revision",
            JournalStatus.POSTED: "Posted - Finalized in General Ledger",
            JournalStatus.REVERSED: "Reversed - Original journal has been reversed",
            JournalStatus.ARCHIVED: "Archived - Historical record",
            JournalStatus.CANCELLED: "Cancelled - Voided before posting",
        }
        return descriptions.get(status, "Unknown status")

    @staticmethod
    def visualize() -> str:
        lines = ["Journal State Machine Flow:"]
        lines.append("DRAFT -> SUBMITTED -> APPROVED -> POSTED -> REVERSED -> ARCHIVED")
        lines.append("          |            |          |")
        lines.append("          v            v          v")
        lines.append("      REJECTED <- DRAFT     CANCELLED")
        lines.append("          |")
        lines.append("          v")
        lines.append("      ARCHIVED")
        return "\n".join(lines)


# ============================================================================
# JOURNAL ENTITY
# ============================================================================


@dataclass
class JournalEntity:
    """
    Journal header entity.

    This entity represents the header of a journal entry. It does not contain
    line items; lines are managed separately. The total_debit and total_credit
    fields must be maintained by the caller and validated for balance.

    Invariants:
    - total_debit == total_credit (within tolerance)
    - journal_number is at least 3 characters
    - description is at least 2 characters
    - total_debit and total_credit are non-negative
    """

    journal_id: UUID
    journal_number: str
    journal_type: JournalType
    transaction_date: datetime
    description: str
    legal_entity_id: UUID
    status: JournalStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    reference: str | None = None
    source_system: str = "ERP"
    version: int = 1
    bank_account_id: UUID | None = None
    total_debit: Decimal = Decimal(0)
    total_credit: Decimal = Decimal(0)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _is_locked: bool = False

    def __post_init__(self) -> None:
        """
        Validate all invariants after initialization.

        Raises:
            ValueError: If any invariant is violated.
        """
        # Validate journal number
        if not self.journal_number or len(self.journal_number.strip()) < 3:
            raise ValueError("Journal number must be at least 3 characters")

        # Validate description
        if not self.description or len(self.description.strip()) < 2:
            raise ValueError("Description must be at least 2 characters")

        # Validate non-negative totals
        if self.total_debit < 0 or self.total_credit < 0:
            raise ValueError("Total debit and credit cannot be negative")

        # ========== DOUBLE-ENTRY VALIDATION (ACC-016) ==========
        # Ensure total debit equals total credit within tolerance.
        # This is the core double-entry axiom check.
        if abs(self.total_debit - self.total_credit) > Decimal("0.01"):
            raise ValueError(
                f"Journal not balanced: debit={self.total_debit}, credit={self.total_credit}"
            )

    # ==================== PROPERTIES ====================

    @property
    def id(self) -> UUID:
        """Get journal ID."""
        return self.journal_id

    @property
    def is_balanced(self) -> bool:
        """Check if the journal is balanced within tolerance."""
        return abs(self.total_debit - self.total_credit) <= Decimal("0.01")

    @property
    def difference(self) -> Decimal:
        """Difference between total debit and total credit."""
        return self.total_debit - self.total_credit

    @property
    def is_posted(self) -> bool:
        """Check if the journal has been posted."""
        return self.status == JournalStatus.POSTED

    @property
    def is_draft(self) -> bool:
        """Check if the journal is in DRAFT status."""
        return self.status == JournalStatus.DRAFT

    @property
    def is_locked(self) -> bool:
        """Check if the journal is locked."""
        return self._is_locked

    @property
    def is_editable(self) -> bool:
        """Check if the journal can be edited."""
        return JournalStateMachine.can_edit(self.status) and not self._is_locked

    # ==================== BUSINESS RULES HELPERS ====================

    def _ensure_editable(self, operation: str) -> None:
        """
        Ensure the journal is in an editable state.

        Args:
            operation: Name of the operation for error messages.

        Raises:
            ValueError: If the journal is locked or not editable.
        """
        if self._is_locked:
            raise ValueError(f"Cannot {operation}: journal is locked")
        if not JournalStateMachine.can_edit(self.status):
            raise ValueError(f"Cannot {operation}: journal is in status {self.status.value}")

    def _ensure_not_posted(self, operation: str) -> None:
        """
        Ensure the journal is not posted (immutability guard).

        Args:
            operation: Name of the operation for error messages.

        Raises:
            ValueError: If the journal is POSTED.
        """
        if self.status == JournalStatus.POSTED:
            raise ValueError(
                f"Cannot {operation}: journal has been posted and is immutable. "
                "Use reverse() to create a reversal instead."
            )

    def can_edit(self) -> bool:
        """Check if the journal can be edited."""
        return self.is_editable

    def can_submit(self) -> bool:
        """Check if the journal can be submitted."""
        return self.status == JournalStatus.DRAFT and not self._is_locked

    def can_approve(self) -> bool:
        """Check if the journal can be approved."""
        return self.status == JournalStatus.SUBMITTED and not self._is_locked

    def can_post(self) -> bool:
        """Check if the journal can be posted."""
        return self.status == JournalStatus.APPROVED and not self._is_locked

    def can_reverse(self) -> bool:
        """Check if the journal can be reversed."""
        return self.status == JournalStatus.POSTED and not self._is_locked

    def can_cancel(self) -> bool:
        """Check if the journal can be cancelled."""
        return self.status in [JournalStatus.DRAFT, JournalStatus.SUBMITTED] and not self._is_locked

    def can_archive(self) -> bool:
        """Check if the journal can be archived."""
        return (
            self.status in [JournalStatus.POSTED, JournalStatus.REVERSED, JournalStatus.REJECTED]
            and not self._is_locked
        )

    # ==================== AUDIT TRAIL ====================

    def record_audit(self, action: str, user_id: str, details: dict[str, Any] | None = None) -> None:
        """
        Record an audit trail entry.

        Args:
            action: Name of the action.
            user_id: ID of the user performing the action.
            details: Additional details about the action.
        """
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "user_id": user_id,
                "details": details or {},
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict[str, Any]]:
        """Get a copy of the full audit trail."""
        return self._audit_trail.copy()

    # ==================== METADATA UPDATE ====================

    def update_metadata(
        self,
        updated_by: str,
        description: str | None = None,
        reference: str | None = None,
        transaction_date: datetime | None = None,
    ) -> JournalEntity:
        """
        Update metadata fields of the journal.

        Args:
            updated_by: User performing the update.
            description: New description (optional).
            reference: New reference (optional).
            transaction_date: New transaction date (optional).

        Returns:
            A new JournalEntity instance with updated metadata.

        Raises:
            ValueError: If the journal is locked, not editable, or posted.
        """
        # ========== IMMUTABILITY GUARD (ACC-026) ==========
        if self.status == JournalStatus.POSTED:
            raise ValueError(
                f"Cannot update metadata: journal has been posted and is immutable. "
                f"Use reverse() to create a reversal instead."
            )

        self._ensure_editable("update metadata")
        self._ensure_not_posted("update metadata")

        changes = {}
        new_description = self.description
        new_reference = self.reference
        new_transaction_date = self.transaction_date

        if description is not None and description != self.description:
            if not description or len(description.strip()) < 2:
                raise ValueError("Description must be at least 2 characters")
            changes["description"] = {"old": self.description, "new": description}
            new_description = description

        if reference is not None and reference != self.reference:
            changes["reference"] = {"old": self.reference, "new": reference}
            new_reference = reference

        if transaction_date is not None and transaction_date != self.transaction_date:
            changes["transaction_date"] = {
                "old": self.transaction_date.isoformat(),
                "new": transaction_date.isoformat(),
            }
            new_transaction_date = transaction_date

        if not changes:
            return self

        new_journal = JournalEntity(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=new_transaction_date,
            description=new_description,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            reference=new_reference,
            source_system=self.source_system,
            version=self.version + 1,
            bank_account_id=self.bank_account_id,
            total_debit=self.total_debit,
            total_credit=self.total_credit,
            _is_locked=self._is_locked,
        )
        new_journal.record_audit("metadata_updated", updated_by, {"changes": changes})
        logger.info("Journal %s metadata updated by %s", self.journal_id, updated_by)
        return new_journal

    # ==================== TOTALS UPDATE ====================

    def update_totals(
        self,
        updated_by: str,
        new_total_debit: Decimal,
        new_total_credit: Decimal,
    ) -> JournalEntity:
        """
        Update the total debit and credit amounts.

        Args:
            updated_by: User performing the update.
            new_total_debit: New total debit amount.
            new_total_credit: New total credit amount.

        Returns:
            A new JournalEntity instance with updated totals.

        Raises:
            ValueError: If the journal is locked, not editable, posted, or unbalanced.
        """
        # ========== IMMUTABILITY GUARD (ACC-026) ==========
        if self.status == JournalStatus.POSTED:
            raise ValueError(
                f"Cannot update totals: journal has been posted and is immutable. "
                f"Use reverse() to create a reversal instead."
            )

        self._ensure_editable("update totals")
        self._ensure_not_posted("update totals")

        if new_total_debit < 0 or new_total_credit < 0:
            raise ValueError("Total debit and credit cannot be negative")

        # Validate double-entry balance
        if abs(new_total_debit - new_total_credit) > Decimal("0.01"):
            raise ValueError(
                f"Journal would be unbalanced: debit={new_total_debit}, credit={new_total_credit}"
            )

        new_journal = JournalEntity(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            journal_type=self.journal_type,
            transaction_date=self.transaction_date,
            description=self.description,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            reference=self.reference,
            source_system=self.source_system,
            version=self.version + 1,
            bank_account_id=self.bank_account_id,
            total_debit=new_total_debit,
            total_credit=new_total_credit,
            _is_locked=self._is_locked,
        )
        new_journal.record_audit(
            "totals_updated",
            updated_by,
            {
                "old_debit": str(self.total_debit),
                "new_debit": str(new_total_debit),
                "old_credit": str(self.total_credit),
                "new_credit": str(new_total_credit),
            },
        )
        logger.info("Journal %s totals updated by %s", self.journal_id, updated_by)
        return new_journal

    # ==================== SERIALIZATION ====================

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "journal_type": self.journal_type.value,
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "legal_entity_id": str(self.legal_entity_id),
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "reference": self.reference,
            "source_system": self.source_system,
            "version": self.version,
            "bank_account_id": str(self.bank_account_id) if self.bank_account_id else None,
            "total_debit": str(self.total_debit),
            "total_credit": str(self.total_credit),
            "is_balanced": self.is_balanced,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalEntity:
        """Reconstruct from dictionary."""
        return cls(
            journal_id=UUID(data["journal_id"]),
            journal_number=data["journal_number"],
            journal_type=JournalType.from_string(data["journal_type"]),
            transaction_date=datetime.fromisoformat(data["transaction_date"]),
            description=data["description"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            status=JournalStatus.from_string(data["status"]),
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            reference=data.get("reference"),
            source_system=data.get("source_system", "ERP"),
            version=data.get("version", 1),
            bank_account_id=UUID(data["bank_account_id"]) if data.get("bank_account_id") else None,
            total_debit=Decimal(data.get("total_debit", "0")),
            total_credit=Decimal(data.get("total_credit", "0")),
        )


# ============================================================================
# REPOSITORY PROTOCOL
# ============================================================================


class JournalEntityRepository:
    """Repository protocol for JournalEntity."""

    async def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> JournalEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, journal_number: str, legal_entity_id: UUID
    ) -> JournalEntity | None:
        raise NotImplementedError

    async def save(self, journal: JournalEntity) -> None:
        raise NotImplementedError

    async def delete(self, journal_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def exists(self, journal_number: str, legal_entity_id: UUID) -> bool:
        raise NotImplementedError


# ============================================================================
# ALIAS
# ============================================================================

JournalEntry = JournalEntity

__all__ = [
    "JournalEntity",
    "JournalEntityRepository",
    "JournalEntry",
    "JournalLine",
    "JournalStateMachine",
    "JournalStatus",
    "JournalType",
    "StateTransitionRule",
]