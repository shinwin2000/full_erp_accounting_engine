#!/usr/bin/env python3
"""
Module: state_machine.py

Layer: Domain / COA (Chart of Accounts)

Responsibility:
    State machine for account lifecycle status.

    Manages account status transitions with business rules, role-based
    permissions, and pre-condition validation.

    Statuses:
        DRAFT     -> Initial state when account is created but not yet active.
        ACTIVE    -> Normal operational state (can be used in transactions).
        SUSPENDED -> Temporarily disabled (can be reactivated).
        LOCKED    -> Permanently locked (requires special override to unlock).
        CLOSED    -> End-of-life, no transactions allowed.
        ARCHIVED  -> Read-only historical data.

Business rules:
    - Only ACTIVE accounts can be used in journal entries.
    - DRAFT accounts cannot be used in transactions.
    - CLOSED accounts cannot be reopened (terminal state).
    - ARCHIVED accounts cannot be modified.
    - Certain transitions require specific user roles (admin, auditor).
    - Transitions may be disallowed if account has children or balances.

Dependencies:
    - domain.coa.account_entity (AccountEntity)
    - standard library (enum, dataclass, typing, datetime)

Audit:
    Every state transition should be logged and recorded as a domain event.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Account Status Enum
# ============================================================================


class AccountStatus(Enum):
    """
    Account lifecycle states.

    The progression follows a typical DRAFT -> ACTIVE -> ... -> CLOSED/ARCHIVED,
    with optional SUSPENDED and LOCKED states for special cases.

    Terminal states: CLOSED, ARCHIVED (no outgoing transitions).
    """

    DRAFT = "draft"  # Newly created, not yet activated
    ACTIVE = "active"  # Normal operational state
    SUSPENDED = "suspended"  # Temporarily disabled (e.g., pending review)
    LOCKED = "locked"  # Permanently locked (e.g., due to audit hold)
    CLOSED = "closed"  # End-of-life, no further changes
    ARCHIVED = "archived"  # Read-only historical record

    # ------------------------------------------------------------------------
    # Helper properties
    # ------------------------------------------------------------------------

    def is_active(self) -> bool:
        """Can this account be used in journal entries?"""
        return self == AccountStatus.ACTIVE

    def is_draft(self) -> bool:
        return self == AccountStatus.DRAFT

    def is_suspended(self) -> bool:
        return self == AccountStatus.SUSPENDED

    def is_locked(self) -> bool:
        return self == AccountStatus.LOCKED

    def is_closed(self) -> bool:
        return self == AccountStatus.CLOSED

    def is_archived(self) -> bool:
        return self == AccountStatus.ARCHIVED

    def can_modify(self) -> bool:
        """Can the account's attributes be changed?"""
        return self in (AccountStatus.DRAFT, AccountStatus.ACTIVE, AccountStatus.SUSPENDED)

    def can_post(self) -> bool:
        """Can journal entries be posted to this account?"""
        return self == AccountStatus.ACTIVE

    def can_delete(self) -> bool:
        """Can the account be physically deleted?"""
        return self in (AccountStatus.DRAFT, AccountStatus.CLOSED, AccountStatus.ARCHIVED)

    def is_terminal(self) -> bool:
        """Is this a terminal state with no outgoing transitions?"""
        return self in (AccountStatus.CLOSED, AccountStatus.ARCHIVED)

    def display_name(self) -> str:
        """User-friendly name in Indonesian."""
        names = {
            AccountStatus.DRAFT: "Draft",
            AccountStatus.ACTIVE: "Aktif",
            AccountStatus.SUSPENDED: "Ditangguhkan",
            AccountStatus.LOCKED: "Terkunci",
            AccountStatus.CLOSED: "Ditutup",
            AccountStatus.ARCHIVED: "Diarsipkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> AccountStatus | None:
        """Parse from string (case-insensitive)."""
        for status in cls:
            if status.value == value.lower():
                return status
        return None


# ============================================================================
# Transition Definitions
# ============================================================================

# Allowed transitions: (from_state, to_state) -> tuple of (required_roles, condition_description)
# Roles: admin, finance_manager, auditor, system, user (default)
TransitionRule = tuple[set[str], str]

ALLOWED_TRANSITIONS: dict[tuple[AccountStatus, AccountStatus], TransitionRule] = {
    # From DRAFT
    (AccountStatus.DRAFT, AccountStatus.ACTIVE): (
        {"finance_manager", "admin"},
        "Activate draft account",
    ),
    (AccountStatus.DRAFT, AccountStatus.CLOSED): (
        {"finance_manager", "admin"},
        "Close draft without activating",
    ),
    (AccountStatus.DRAFT, AccountStatus.ARCHIVED): ({"admin"}, "Archive draft"),
    # From ACTIVE
    (AccountStatus.ACTIVE, AccountStatus.SUSPENDED): (
        {"finance_manager", "admin"},
        "Temporarily suspend",
    ),
    (AccountStatus.ACTIVE, AccountStatus.LOCKED): ({"auditor", "admin"}, "Lock for audit"),
    (AccountStatus.ACTIVE, AccountStatus.CLOSED): ({"finance_manager", "admin"}, "Close account"),
    (AccountStatus.ACTIVE, AccountStatus.ARCHIVED): ({"admin"}, "Archive active account"),
    # From SUSPENDED
    (AccountStatus.SUSPENDED, AccountStatus.ACTIVE): (
        {"finance_manager", "admin"},
        "Reactivate suspended account",
    ),
    (AccountStatus.SUSPENDED, AccountStatus.LOCKED): (
        {"auditor", "admin"},
        "Lock suspended account",
    ),
    (AccountStatus.SUSPENDED, AccountStatus.CLOSED): (
        {"finance_manager", "admin"},
        "Close suspended account",
    ),
    # From LOCKED
    (AccountStatus.LOCKED, AccountStatus.ACTIVE): ({"admin"}, "Unlock account (admin override)"),
    (AccountStatus.LOCKED, AccountStatus.CLOSED): ({"admin"}, "Close locked account"),
    (AccountStatus.LOCKED, AccountStatus.ARCHIVED): ({"admin"}, "Archive locked account"),
    # From CLOSED (terminal: no outgoing except to ARCHIVED)
    (AccountStatus.CLOSED, AccountStatus.ARCHIVED): ({"admin"}, "Archive closed account"),
    # No transitions from ARCHIVED
}


def get_allowed_transitions(from_status: AccountStatus) -> list[AccountStatus]:
    """Return list of destination states allowed from given status."""
    return [to for (frm, to) in ALLOWED_TRANSITIONS if frm == from_status]


def is_transition_allowed(from_status: AccountStatus, to_status: AccountStatus) -> bool:
    """Check if a transition is defined in the allowed transitions map."""
    return (from_status, to_status) in ALLOWED_TRANSITIONS


def get_required_roles(from_status: AccountStatus, to_status: AccountStatus) -> set[str]:
    """Get required user roles for a transition, or empty set if not allowed."""
    rule = ALLOWED_TRANSITIONS.get((from_status, to_status))
    return rule[0] if rule else set()


# ============================================================================
# State Machine Class
# ============================================================================


class AccountStateMachine:
    """
    State machine for account status.

    Provides methods to validate transitions, execute state changes,
    and enforce business rules.

    Examples:
        >>> sm = AccountStateMachine()
        >>> sm.can_transition(AccountStatus.DRAFT, AccountStatus.ACTIVE)
        True
        >>> sm.validate_transition(account, AccountStatus.ACTIVE, user_role="finance_manager")
        (True, None)
    """

    # ------------------------------------------------------------------------
    # Core transition validation
    # ------------------------------------------------------------------------

    @staticmethod
    def can_transition(from_status: AccountStatus, to_status: AccountStatus) -> bool:
        """Check if a transition is defined (ignoring business conditions)."""
        return is_transition_allowed(from_status, to_status)

    @staticmethod
    def validate_transition(
        account: Any,
        new_status: AccountStatus,
        user_role: str = "user",
        has_children: bool = False,
        has_balance: bool = False,
        has_transactions: bool = False,
        override_reason: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Validate whether the account can transition to a new status.

        Args:
            account: Account entity (must have status or is_active flag)
            new_status: Desired new status
            user_role: Role of the user performing the transition
            has_children: Whether account has child accounts
            has_balance: Whether account has non-zero balance
            has_transactions: Whether account has any posted transactions
            override_reason: Optional override reason (for admin bypass)

        Returns:
            (is_valid, error_message)
        """
        # Determine current status from account
        if hasattr(account, "status"):
            current_status = account.status
        elif hasattr(account, "is_active"):
            # Legacy mapping: is_active -> ACTIVE else DRAFT (simplified)
            current_status = AccountStatus.ACTIVE if account.is_active else AccountStatus.DRAFT
        else:
            return False, "Account object has no status or is_active field"

        # Terminal state check
        if current_status.is_terminal() and current_status != new_status:
            return False, f"Cannot transition from terminal state {current_status.display_name()}"

        # Check if transition is defined
        if not is_transition_allowed(current_status, new_status):
            return False, (
                f"Transition from {current_status.display_name()} "
                f"to {new_status.display_name()} is not allowed"
            )

        # Role-based authorization
        required_roles = get_required_roles(current_status, new_status)
        if required_roles and user_role not in required_roles and user_role != "super_admin":
            return False, (
                f"Transition requires one of roles: {', '.join(required_roles)}. "
                f"User has role: {user_role}"
            )

        # Business rule: cannot close account with children
        if new_status == AccountStatus.CLOSED and has_children:
            return (
                False,
                "Cannot close account that has child accounts. Delete or reassign children first.",
            )

        # Business rule: cannot close account with non-zero balance
        if new_status == AccountStatus.CLOSED and has_balance and not override_reason:
            return False, "Cannot close account with non-zero balance. Zero out balance first."

        # Business rule: cannot close account with transactions (unless forced)
        if new_status == AccountStatus.CLOSED and has_transactions and not override_reason:
            return False, "Cannot close account that has transaction history. Use archive instead."

        # Business rule: cannot activate draft if it has invalid parent
        if new_status == AccountStatus.ACTIVE and current_status == AccountStatus.DRAFT:
            if hasattr(account, "parent_account_id") and account.parent_account_id:
                # Parent should be active (check would require service call)
                pass  # In real validation, we'd need to check parent status

        # Business rule: locking requires audit trail
        if new_status == AccountStatus.LOCKED and not override_reason:
            if not hasattr(account, "audit_trail_id"):
                # We'll still allow but log warning
                logger.warning(f"Locking account {account} without explicit override reason")

        # Override bypass for admin
        if override_reason and user_role in ("admin", "super_admin"):
            logger.info(f"Transition overridden by {user_role}: {override_reason}")
            return True, None

        return True, None

    @staticmethod
    def transition(
        account: Any,
        new_status: AccountStatus,
        user_role: str = "user",
        changed_by: str | None = None,
        has_children: bool = False,
        has_balance: bool = False,
        has_transactions: bool = False,
        override_reason: str | None = None,
    ) -> Any:
        """
        Execute a state transition on an account.

        Returns a new account object with updated status and version incremented.
        """
        is_valid, error = AccountStateMachine.validate_transition(
            account=account,
            new_status=new_status,
            user_role=user_role,
            has_children=has_children,
            has_balance=has_balance,
            has_transactions=has_transactions,
            override_reason=override_reason,
        )
        if not is_valid:
            raise ValueError(f"Invalid state transition: {error}")

        # Determine current status
        if hasattr(account, "status"):
            current_status = account.status
        else:
            current_status = AccountStatus.ACTIVE if account.is_active else AccountStatus.DRAFT

        # Create updated account (immutable copy)
        if hasattr(account, "__dataclass_fields__"):
            from dataclasses import replace

            # Map status to is_active flag if needed
            is_active = new_status == AccountStatus.ACTIVE
            updated = replace(
                account,
                is_active=is_active,
                status=new_status,
                updated_at=datetime.now(UTC),
                updated_by=changed_by or user_role,
                version=account.version + 1,
            )
            return updated
        else:
            # Fallback: try to set attributes (mutable, not ideal)
            account.status = new_status
            account.is_active = new_status == AccountStatus.ACTIVE
            account.updated_at = datetime.now(UTC)
            if changed_by:
                account.updated_by = changed_by
            account.version += 1
            return account

    # ------------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------------

    @staticmethod
    def get_allowed_next_states(status: AccountStatus) -> list[AccountStatus]:
        """Return list of allowed next states from given status."""
        return get_allowed_transitions(status)

    @staticmethod
    def get_allowed_transitions_with_roles(status: AccountStatus) -> list[dict[str, Any]]:
        """Return detailed list of allowed transitions with required roles."""
        result = []
        for frm, to in ALLOWED_TRANSITIONS:
            if frm == status:
                roles, desc = ALLOWED_TRANSITIONS[(frm, to)]
                result.append(
                    {
                        "from": frm.value,
                        "to": to.value,
                        "required_roles": list(roles),
                        "description": desc,
                    }
                )
        return result

    @staticmethod
    def can_activate(account: Any, user_role: str = "user") -> bool:
        """Shortcut: can the account be activated?"""
        valid, _ = AccountStateMachine.validate_transition(account, AccountStatus.ACTIVE, user_role)
        return valid

    @staticmethod
    def can_suspend(account: Any, user_role: str = "user") -> bool:
        """Shortcut: can the account be suspended?"""
        valid, _ = AccountStateMachine.validate_transition(
            account, AccountStatus.SUSPENDED, user_role
        )
        return valid

    @staticmethod
    def can_lock(account: Any, user_role: str = "user") -> bool:
        """Shortcut: can the account be locked?"""
        valid, _ = AccountStateMachine.validate_transition(account, AccountStatus.LOCKED, user_role)
        return valid

    @staticmethod
    def can_close(account: Any, user_role: str = "user", has_balance: bool = False) -> bool:
        """Shortcut: can the account be closed?"""
        valid, _ = AccountStateMachine.validate_transition(
            account, AccountStatus.CLOSED, user_role, has_balance=has_balance
        )
        return valid

    @staticmethod
    def can_archive(account: Any, user_role: str = "user") -> bool:
        """Shortcut: can the account be archived?"""
        valid, _ = AccountStateMachine.validate_transition(
            account, AccountStatus.ARCHIVED, user_role
        )
        return valid


# ============================================================================
# Transition History (Optional)
# ============================================================================


@dataclass
class StatusTransitionRecord:
    """Record of a single status transition."""

    from_status: AccountStatus
    to_status: AccountStatus
    transitioned_at: datetime
    transitioned_by: str
    reason: str | None = None
    user_role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "transitioned_at": self.transitioned_at.isoformat(),
            "transitioned_by": self.transitioned_by,
            "reason": self.reason,
            "user_role": self.user_role,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatusTransitionRecord:
        return cls(
            from_status=AccountStatus.from_string(data["from_status"]),
            to_status=AccountStatus.from_string(data["to_status"]),
            transitioned_at=datetime.fromisoformat(data["transitioned_at"]),
            transitioned_by=data["transitioned_by"],
            reason=data.get("reason"),
            user_role=data.get("user_role"),
        )


class TransitionHistory:
    """
    Manages history of status transitions for an account.
    """

    def __init__(self, account_id: Any):
        self.account_id = account_id
        self._history: list[StatusTransitionRecord] = []

    def add_transition(
        self,
        from_status: AccountStatus,
        to_status: AccountStatus,
        transitioned_by: str,
        reason: str | None = None,
        user_role: str | None = None,
    ) -> None:
        """Add a new transition record."""
        record = StatusTransitionRecord(
            from_status=from_status,
            to_status=to_status,
            transitioned_at=datetime.now(UTC),
            transitioned_by=transitioned_by,
            reason=reason,
            user_role=user_role,
        )
        self._history.append(record)

    def get_history(self) -> list[StatusTransitionRecord]:
        """Return full history (oldest first)."""
        return self._history.copy()

    def get_last_transition(self) -> StatusTransitionRecord | None:
        """Return the most recent transition, or None."""
        return self._history[-1] if self._history else None

    def clear(self) -> None:
        """Clear history (for testing)."""
        self._history.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "history": [r.to_dict() for r in self._history],
        }


# ============================================================================
# COA Level State Machine (optional)
# ============================================================================


class COAStatus(Enum):
    """Status for the entire Chart of Accounts."""

    ACTIVE = "active"
    LOCKED = "locked"
    ARCHIVED = "archived"

    def can_modify(self) -> bool:
        return self == COAStatus.ACTIVE

    def can_read(self) -> bool:
        return self in (COAStatus.ACTIVE, COAStatus.LOCKED)


class COAStateMachine:
    """State machine for Chart of Accounts aggregate."""

    _allowed_transitions = {
        (COAStatus.ACTIVE, COAStatus.LOCKED): {"admin", "auditor"},
        (COAStatus.ACTIVE, COAStatus.ARCHIVED): {"admin"},
        (COAStatus.LOCKED, COAStatus.ACTIVE): {"admin"},
        (COAStatus.LOCKED, COAStatus.ARCHIVED): {"admin"},
    }

    @staticmethod
    def can_transition(from_status: COAStatus, to_status: COAStatus) -> bool:
        return (from_status, to_status) in COAStateMachine._allowed_transitions

    @staticmethod
    def validate_transition(
        from_status: COAStatus, to_status: COAStatus, user_role: str = "user"
    ) -> tuple[bool, str | None]:
        if not COAStateMachine.can_transition(from_status, to_status):
            return False, f"Transition {from_status.value} -> {to_status.value} not allowed"
        required_roles = COAStateMachine._allowed_transitions.get((from_status, to_status), set())
        if required_roles and user_role not in required_roles and user_role != "super_admin":
            return False, f"Required roles: {required_roles}"
        return True, None

    @staticmethod
    def transition(
        coa: Any, to_status: COAStatus, user_role: str = "user", changed_by: str | None = None
    ) -> Any:
        from_status = coa.status
        valid, err = COAStateMachine.validate_transition(from_status, to_status, user_role)
        if not valid:
            raise ValueError(err)
        # Create updated COA (immutable)
        from dataclasses import replace

        return replace(
            coa,
            status=to_status,
            updated_at=datetime.now(UTC),
            updated_by=changed_by or user_role,
            version=coa.version + 1,
        )


# ============================================================================
# Helper Functions
# ============================================================================


def status_from_is_active(is_active: bool) -> AccountStatus:
    """Convert old is_active flag to AccountStatus."""
    return AccountStatus.ACTIVE if is_active else AccountStatus.DRAFT


def is_active_to_status(is_active: bool, is_locked: bool = False) -> AccountStatus:
    """Convert multiple flags to AccountStatus."""
    if is_locked:
        return AccountStatus.LOCKED
    return AccountStatus.ACTIVE if is_active else AccountStatus.DRAFT


def get_status_display_name(status: AccountStatus | str) -> str:
    """Get user-friendly display name."""
    if isinstance(status, str):
        status = AccountStatus.from_string(status)
        if status is None:
            return status
    return status.display_name()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AccountStateMachine",
    "AccountStatus",
    "COAStateMachine",
    "COAStatus",
    "StatusTransitionRecord",
    "TransitionHistory",
    "get_allowed_transitions",
    "get_required_roles",
    "get_status_display_name",
    "is_active_to_status",
    "is_transition_allowed",
    "status_from_is_active",
]
