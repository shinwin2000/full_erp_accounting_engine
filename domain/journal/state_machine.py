#!/usr/bin/env python3
"""
Module: state_machine.py
Layer: 6 - Domain / Journal
Responsibility: Mendefinisikan state (status) jurnal, aturan transisi, dan mesin state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================


class JournalStatus(Enum):
    """Status dari sebuah jurnal."""

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
        """Cek apakah transisi dari status ini ke status lain diperbolehkan."""
        return JournalStateMachine.can_transition(self, to_status)


# ============================================================================
# STATE TRANSITION RULES
# ============================================================================


@dataclass
class StateTransitionRule:
    """Aturan untuk transisi antar status."""

    from_status: JournalStatus
    to_status: JournalStatus
    requires_approval: bool = False
    requires_dual_control: bool = False
    required_role: str | None = None
    check_balance: bool = False
    check_period_open: bool = False
    requires_reason: bool = False
    allowed_user_roles: list[str] | None = None


# ============================================================================
# ALLOWED TRANSITIONS (Graph)
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

# Public aliases untuk ekspor
ALLOWED_TRANSITIONS = _ALLOWED_TRANSITIONS

# ============================================================================
# TRANSITION RULES LIST (untuk validasi spesifik)
# ============================================================================

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

# Public aliases untuk ekspor
TRANSITION_RULES = _TRANSITION_RULES


# ============================================================================
# JOURNAL STATE MACHINE
# ============================================================================


class JournalStateMachine:
    """Mesin status untuk jurnal."""

    @staticmethod
    def can_transition(from_status: JournalStatus, to_status: JournalStatus) -> bool:
        """Apakah transisi diperbolehkan secara graf."""
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        return to_status in allowed

    @staticmethod
    def get_allowed_transitions(current_status: JournalStatus) -> list[JournalStatus]:
        """Daftar status yang dapat dicapai dari status saat ini."""
        return list(_ALLOWED_TRANSITIONS.get(current_status, set()))

    @staticmethod
    def get_transition_rule(
        from_status: JournalStatus,
        to_status: JournalStatus,
    ) -> StateTransitionRule | None:
        """Mendapatkan aturan transisi spesifik jika ada."""
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
        """
        Memvalidasi transisi dengan mempertimbangkan aturan tambahan.

        Returns:
            (is_valid, error_message)
        """
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
        """Diagram alur status dalam bentuk dictionary."""
        return {
            status.value: [s.value for s in _ALLOWED_TRANSITIONS.get(status, set())]
            for status in JournalStatus
        }

    @staticmethod
    def is_terminal(status: JournalStatus) -> bool:
        """Apakah status ini adalah terminal (tidak ada transisi keluar)."""
        return len(_ALLOWED_TRANSITIONS.get(status, set())) == 0

    @staticmethod
    def can_edit(status: JournalStatus) -> bool:
        """Apakah jurnal dengan status ini masih bisa diedit."""
        return status in [JournalStatus.DRAFT, JournalStatus.REJECTED]

    @staticmethod
    def can_delete(status: JournalStatus) -> bool:
        """Apakah jurnal dengan status ini bisa dihapus."""
        return status == JournalStatus.DRAFT

    @staticmethod
    def needs_approval(status: JournalStatus) -> bool:
        """Apakah jurnal dengan status ini sedang menunggu approval."""
        return status == JournalStatus.SUBMITTED

    @staticmethod
    def can_be_posted(status: JournalStatus) -> bool:
        """Apakah jurnal dengan status ini siap untuk diposting."""
        return status == JournalStatus.APPROVED

    @staticmethod
    def get_next_statuses(current: JournalStatus) -> list[JournalStatus]:
        """Alias untuk get_allowed_transitions."""
        return JournalStateMachine.get_allowed_transitions(current)

    @staticmethod
    def get_previous_statuses(current: JournalStatus) -> list[JournalStatus]:
        """Status apa saja yang dapat menuju ke status saat ini."""
        previous = []
        for status, transitions in _ALLOWED_TRANSITIONS.items():
            if current in transitions:
                previous.append(status)
        return previous

    @staticmethod
    def get_status_description(status: JournalStatus) -> str:
        """Deskripsi singkat status."""
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
        """Visualisasi alur status dalam teks."""
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
# EXPORTS
# ============================================================================

__all__ = [
    "ALLOWED_TRANSITIONS",
    "TRANSITION_RULES",
    "JournalStateMachine",
    "JournalStatus",
    "StateTransitionRule",
]
