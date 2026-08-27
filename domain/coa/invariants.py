#!/usr/bin/env python3
"""
Module: invariants.py
Layer: Domain / COA
Responsibility: Mendefinisikan exceptions dan fungsi validasi invariant untuk COA.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# ============================================================================
# Base Exception
# ============================================================================


class COAInvariantError(Exception):
    """
    Base exception untuk semua invariant COA.

    Attributes:
        message: Pesan error
        code: Kode error (opsional)
        details: Detail tambahan (dictionary)
        timestamp: Waktu terjadinya error
    """

    def __init__(
        self,
        message: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}
        self.timestamp = datetime.now(UTC)
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format pesan error dengan timestamp dan detail."""
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        if self.details:
            return f"[{ts}] {self.message} | Details: {self.details}"
        return f"[{ts}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Konversi exception ke dictionary untuk serialisasi."""
        return {
            "type": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_json(self) -> str:
        """Konversi ke JSON string."""
        return json.dumps(self.to_dict(), default=str, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> COAInvariantError:
        """Rekonstruksi exception dari dictionary."""
        return cls(
            message=data["message"],
            code=data.get("code"),
            details=data.get("details", {}),
        )


# ============================================================================
# Code & Name Validation Errors
# ============================================================================


class InvalidAccountCodeError(COAInvariantError):
    """Exception raised when account code format is invalid."""

    def __init__(
        self,
        account_code: str,
        reason: str,
        pattern: str | None = None,
        **kwargs,
    ):
        self.account_code = account_code
        self.reason = reason
        self.pattern = pattern
        super().__init__(
            message=f"Invalid account code '{account_code}': {reason}",
            code="INVALID_ACCOUNT_CODE",
            details={
                "account_code": account_code,
                "reason": reason,
                "pattern": pattern,
                **kwargs,
            },
        )


class AccountCodeDuplicateError(COAInvariantError):
    """Exception raised when trying to create account with duplicate code."""

    def __init__(self, account_code: str, existing_account_id: UUID | None = None, **kwargs):
        self.account_code = account_code
        self.existing_account_id = existing_account_id
        super().__init__(
            message=f"Account code '{account_code}' already exists",
            code="DUPLICATE_ACCOUNT_CODE",
            details={
                "account_code": account_code,
                "existing_account_id": str(existing_account_id) if existing_account_id else None,
                **kwargs,
            },
        )


class AccountNameTooLongError(COAInvariantError):
    """Exception raised when account name exceeds maximum length."""

    def __init__(self, account_name: str, max_length: int = 200, **kwargs):
        self.account_name = account_name
        self.max_length = max_length
        super().__init__(
            message=f"Account name '{account_name[:50]}...' exceeds maximum length of {max_length} characters",
            code="ACCOUNT_NAME_TOO_LONG",
            details={
                "account_name": account_name[:100],
                "length": len(account_name),
                "max_length": max_length,
                **kwargs,
            },
        )


class AccountNameEmptyError(COAInvariantError):
    """Exception raised when account name is empty."""

    def __init__(self, **kwargs):
        super().__init__(
            message="Account name cannot be empty",
            code="ACCOUNT_NAME_EMPTY",
            details=kwargs,
        )


# ============================================================================
# Parent-Child Hierarchy Errors
# ============================================================================


class ParentAccountNotFoundError(COAInvariantError):
    """Exception raised when parent account does not exist."""

    def __init__(self, parent_id: UUID, **kwargs):
        self.parent_id = parent_id
        super().__init__(
            message=f"Parent account with ID {parent_id} not found",
            code="PARENT_NOT_FOUND",
            details={"parent_id": str(parent_id), **kwargs},
        )


class CircularParentReferenceError(COAInvariantError):
    """Exception raised when parent reference would create a cycle."""

    def __init__(self, account_id: UUID, parent_id: UUID, **kwargs):
        self.account_id = account_id
        self.parent_id = parent_id
        super().__init__(
            message=f"Moving account {account_id} under {parent_id} would create a cycle in hierarchy",
            code="CIRCULAR_REFERENCE",
            details={
                "account_id": str(account_id),
                "parent_id": str(parent_id),
                **kwargs,
            },
        )


class AccountHasChildrenError(COAInvariantError):
    """Exception raised when trying to deactivate/delete account that has children."""

    def __init__(self, account_id: UUID, child_count: int, **kwargs):
        self.account_id = account_id
        self.child_count = child_count
        super().__init__(
            message=f"Cannot deactivate/delete account with {child_count} child account(s)",
            code="ACCOUNT_HAS_CHILDREN",
            details={
                "account_id": str(account_id),
                "child_count": child_count,
                **kwargs,
            },
        )


class InvalidParentTypeError(COAInvariantError):
    """Exception raised when child account type is not compatible with parent type."""

    def __init__(
        self,
        child_type: str,
        parent_type: str,
        allowed_parent_types: list[str] | None = None,
        **kwargs,
    ):
        self.child_type = child_type
        self.parent_type = parent_type
        self.allowed_parent_types = allowed_parent_types
        msg = f"Account type '{child_type}' cannot have parent of type '{parent_type}'"
        if allowed_parent_types:
            msg += f". Allowed parent types: {', '.join(allowed_parent_types)}"
        super().__init__(
            message=msg,
            code="INVALID_PARENT_TYPE",
            details={
                "child_type": child_type,
                "parent_type": parent_type,
                "allowed_parent_types": allowed_parent_types,
                **kwargs,
            },
        )


class MaxHierarchyDepthExceededError(COAInvariantError):
    """Exception raised when adding account would exceed maximum hierarchy depth."""

    def __init__(self, current_depth: int, max_depth: int, **kwargs):
        self.current_depth = current_depth
        self.max_depth = max_depth
        super().__init__(
            message=f"Cannot add account: hierarchy depth would exceed maximum of {max_depth} (current depth: {current_depth})",
            code="MAX_HIERARCHY_DEPTH_EXCEEDED",
            details={
                "current_depth": current_depth,
                "max_depth": max_depth,
                **kwargs,
            },
        )


class SelfParentError(COAInvariantError):
    """Exception raised when account tries to be its own parent."""

    def __init__(self, account_id: UUID, **kwargs):
        self.account_id = account_id
        super().__init__(
            message=f"Account cannot be its own parent (account_id: {account_id})",
            code="SELF_PARENT",
            details={"account_id": str(account_id), **kwargs},
        )


class ParentNotActiveError(COAInvariantError):
    """Exception raised when parent account is not active."""

    def __init__(self, parent_id: UUID, parent_status: str, **kwargs):
        self.parent_id = parent_id
        self.parent_status = parent_status
        super().__init__(
            message=f"Parent account {parent_id} is not active (status: {parent_status})",
            code="PARENT_NOT_ACTIVE",
            details={
                "parent_id": str(parent_id),
                "parent_status": parent_status,
                **kwargs,
            },
        )


# ============================================================================
# Account Status & Operation Errors
# ============================================================================


class CannotDeleteAccountWithTransactionsError(COAInvariantError):
    """Exception raised when trying to delete account that has transactions."""

    def __init__(self, account_id: UUID, transaction_count: int, **kwargs):
        self.account_id = account_id
        self.transaction_count = transaction_count
        super().__init__(
            message=f"Cannot delete account with {transaction_count} transaction(s)",
            code="ACCOUNT_HAS_TRANSACTIONS",
            details={
                "account_id": str(account_id),
                "transaction_count": transaction_count,
                **kwargs,
            },
        )


class CannotDeactivateControlAccountError(COAInvariantError):
    """Exception raised when trying to deactivate a control account that has children."""

    def __init__(self, account_id: UUID, child_count: int, **kwargs):
        self.account_id = account_id
        self.child_count = child_count
        super().__init__(
            message=f"Cannot deactivate control account with {child_count} child account(s)",
            code="CONTROL_ACCOUNT_HAS_CHILDREN",
            details={"account_id": str(account_id), "child_count": child_count, **kwargs},
        )


class AccountLockedError(COAInvariantError):
    """Exception raised when trying to modify a locked account."""

    def __init__(self, account_id: UUID, reason: str | None = None, **kwargs):
        self.account_id = account_id
        self.reason = reason
        super().__init__(
            message=f"Account {account_id} is locked" + (f": {reason}" if reason else ""),
            code="ACCOUNT_LOCKED",
            details={"account_id": str(account_id), "reason": reason, **kwargs},
        )


class AccountArchivedError(COAInvariantError):
    """Exception raised when trying to modify an archived account."""

    def __init__(self, account_id: UUID, **kwargs):
        self.account_id = account_id
        super().__init__(
            message=f"Account {account_id} is archived and cannot be modified",
            code="ACCOUNT_ARCHIVED",
            details={"account_id": str(account_id), **kwargs},
        )


class AccountAlreadyExistsError(COAInvariantError):
    """Exception raised when trying to create an account that already exists."""

    def __init__(self, account_id: UUID, account_code: str | None = None, **kwargs):
        self.account_id = account_id
        self.account_code = account_code
        super().__init__(
            message=f"Account already exists: ID={account_id}"
            + (f", code='{account_code}'" if account_code else ""),
            code="ACCOUNT_ALREADY_EXISTS",
            details={
                "account_id": str(account_id),
                "account_code": account_code,
                **kwargs,
            },
        )


class AccountNotFoundError(COAInvariantError):
    """Exception raised when account not found."""

    def __init__(self, account_id: UUID | str, **kwargs):
        self.account_id = account_id
        super().__init__(
            message=f"Account not found: {account_id}",
            code="ACCOUNT_NOT_FOUND",
            details={"account_id": str(account_id), **kwargs},
        )


class AccountNotActiveError(COAInvariantError):
    """Exception raised when trying to post to inactive account."""

    def __init__(self, account_id: UUID, current_status: str, **kwargs):
        self.account_id = account_id
        self.current_status = current_status
        super().__init__(
            message=f"Cannot post to account {account_id}: status is {current_status} (required: ACTIVE)",
            code="ACCOUNT_NOT_ACTIVE",
            details={
                "account_id": str(account_id),
                "current_status": current_status,
                **kwargs,
            },
        )


# ============================================================================
# COA Level Errors
# ============================================================================


class COALockedError(COAInvariantError):
    """Exception raised when trying to modify a locked COA."""

    def __init__(self, coa_id: UUID, reason: str | None = None, **kwargs):
        self.coa_id = coa_id
        self.reason = reason
        super().__init__(
            message=f"Chart of Accounts {coa_id} is locked" + (f": {reason}" if reason else ""),
            code="COA_LOCKED",
            details={"coa_id": str(coa_id), "reason": reason, **kwargs},
        )


class COAArchivedError(COAInvariantError):
    """Exception raised when trying to modify an archived COA."""

    def __init__(self, coa_id: UUID, **kwargs):
        self.coa_id = coa_id
        super().__init__(
            message=f"Chart of Accounts {coa_id} is archived and cannot be modified",
            code="COA_ARCHIVED",
            details={"coa_id": str(coa_id), **kwargs},
        )


class COANotFoundError(COAInvariantError):
    """Exception raised when COA not found."""

    def __init__(self, coa_id: UUID, **kwargs):
        self.coa_id = coa_id
        super().__init__(
            message=f"Chart of Accounts not found: {coa_id}",
            code="COA_NOT_FOUND",
            details={"coa_id": str(coa_id), **kwargs},
        )


class COAAlreadyExistsError(COAInvariantError):
    """Exception raised when trying to create COA that already exists for legal entity."""

    def __init__(self, legal_entity_id: UUID, coa_name: str | None = None, **kwargs):
        self.legal_entity_id = legal_entity_id
        self.coa_name = coa_name
        super().__init__(
            message=f"Chart of Accounts already exists for legal entity {legal_entity_id}"
            + (f" (name: {coa_name})" if coa_name else ""),
            code="COA_ALREADY_EXISTS",
            details={
                "legal_entity_id": str(legal_entity_id),
                "coa_name": coa_name,
                **kwargs,
            },
        )


class COANotActiveError(COAInvariantError):
    """Exception raised when COA is not active for operation."""

    def __init__(
        self, coa_id: UUID, current_status: str, required_status: str = "ACTIVE", **kwargs
    ):
        self.coa_id = coa_id
        self.current_status = current_status
        self.required_status = required_status
        super().__init__(
            message=f"Chart of Accounts {coa_id} is not {required_status} (current: {current_status})",
            code="COA_NOT_ACTIVE",
            details={
                "coa_id": str(coa_id),
                "current_status": current_status,
                "required_status": required_status,
                **kwargs,
            },
        )


# ============================================================================
# Currency & Balance Errors
# ============================================================================


class CurrencyMismatchError(COAInvariantError):
    """Exception raised when currency mismatch occurs."""

    def __init__(self, expected_currency: str, actual_currency: str, **kwargs):
        self.expected_currency = expected_currency
        self.actual_currency = actual_currency
        super().__init__(
            message=f"Currency mismatch: expected '{expected_currency}', got '{actual_currency}'",
            code="CURRENCY_MISMATCH",
            details={
                "expected_currency": expected_currency,
                "actual_currency": actual_currency,
                **kwargs,
            },
        )


class OpeningBalanceSignError(COAInvariantError):
    """Exception raised when opening balance sign does not match normal balance."""

    def __init__(self, account_code: str, opening_balance: str, normal_balance: str, **kwargs):
        self.account_code = account_code
        self.opening_balance = opening_balance
        self.normal_balance = normal_balance
        super().__init__(
            message=f"Opening balance sign mismatch for account {account_code}: balance={opening_balance}, normal={normal_balance}",
            code="OPENING_BALANCE_SIGN_ERROR",
            details={
                "account_code": account_code,
                "opening_balance": opening_balance,
                "normal_balance": normal_balance,
                **kwargs,
            },
        )


class InvalidNormalBalanceError(COAInvariantError):
    """Exception raised when normal balance value is invalid."""

    def __init__(self, value: str, valid_values: list[str], **kwargs):
        self.value = value
        self.valid_values = valid_values
        super().__init__(
            message=f"Invalid normal balance '{value}'. Must be one of: {', '.join(valid_values)}",
            code="INVALID_NORMAL_BALANCE",
            details={
                "value": value,
                "valid_values": valid_values,
                **kwargs,
            },
        )


# ============================================================================
# Legal Entity & Cross-Entity Errors
# ============================================================================


class CrossLegalEntityError(COAInvariantError):
    """Exception raised when trying to associate account from different legal entity."""

    def __init__(self, account_legal_entity_id: UUID, coa_legal_entity_id: UUID, **kwargs):
        self.account_legal_entity_id = account_legal_entity_id
        self.coa_legal_entity_id = coa_legal_entity_id
        super().__init__(
            message=f"Account legal entity {account_legal_entity_id} does not match COA legal entity {coa_legal_entity_id}",
            code="CROSS_LEGAL_ENTITY",
            details={
                "account_legal_entity_id": str(account_legal_entity_id),
                "coa_legal_entity_id": str(coa_legal_entity_id),
                **kwargs,
            },
        )


# ============================================================================
# Transition & Approval Errors
# ============================================================================


class InvalidStatusTransitionError(COAInvariantError):
    """Exception raised when account status transition is not allowed."""

    def __init__(
        self, from_status: str, to_status: str, required_roles: list[str] | None = None, **kwargs
    ):
        self.from_status = from_status
        self.to_status = to_status
        self.required_roles = required_roles
        msg = f"Status transition from {from_status} to {to_status} is not allowed"
        if required_roles:
            msg += f". Required roles: {', '.join(required_roles)}"
        super().__init__(
            message=msg,
            code="INVALID_STATUS_TRANSITION",
            details={
                "from_status": from_status,
                "to_status": to_status,
                "required_roles": required_roles,
                **kwargs,
            },
        )


class InsufficientRoleError(COAInvariantError):
    """Exception raised when user role does not have permission for operation."""

    def __init__(self, user_role: str, required_roles: list[str], operation: str, **kwargs):
        self.user_role = user_role
        self.required_roles = required_roles
        self.operation = operation
        super().__init__(
            message=f"User role '{user_role}' insufficient for {operation}. Required roles: {', '.join(required_roles)}",
            code="INSUFFICIENT_ROLE",
            details={
                "user_role": user_role,
                "required_roles": required_roles,
                "operation": operation,
                **kwargs,
            },
        )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AccountAlreadyExistsError",
    "AccountArchivedError",
    "AccountCodeDuplicateError",
    "AccountHasChildrenError",
    "AccountLockedError",
    "AccountNameEmptyError",
    "AccountNameTooLongError",
    "AccountNotActiveError",
    "AccountNotFoundError",
    "COAAlreadyExistsError",
    "COAArchivedError",
    # Base
    "COAInvariantError",
    # COA Level
    "COALockedError",
    "COANotActiveError",
    "COANotFoundError",
    "CannotDeactivateControlAccountError",
    # Account Status & Operation
    "CannotDeleteAccountWithTransactionsError",
    "CircularParentReferenceError",
    # Legal Entity
    "CrossLegalEntityError",
    # Currency & Balance
    "CurrencyMismatchError",
    "InsufficientRoleError",
    # Code & Name
    "InvalidAccountCodeError",
    "InvalidNormalBalanceError",
    "InvalidParentTypeError",
    # Transition & Approval
    "InvalidStatusTransitionError",
    "MaxHierarchyDepthExceededError",
    "OpeningBalanceSignError",
    # Hierarchy
    "ParentAccountNotFoundError",
    "ParentNotActiveError",
    "SelfParentError",
]
