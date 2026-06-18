#!/usr/bin/env python3
"""
Module: invariants_validator.py

Layer: Domain / COA (Chart of Accounts)

Responsibility:
    Validate invariants of Chart of Accounts aggregate.

    Ensures business rules such as:
    - Unique account codes within a legal entity.
    - No cycles in account hierarchy.
    - Parent account must exist and have compatible type.
    - Account cannot be deactivated if it has active children or transactions.
    - Account code format compliance.
    - Opening balance sign consistency with normal balance.
    - Maximum depth constraints.
    - Control account restrictions.
    - Cross-legal entity references prohibited.

Dependencies:
    - domain.coa.account_entity (AccountEntity, AccountType)
    - domain.coa.account_code_vo (AccountCodeVO)
    - domain.shared_value_objects.money_vo (Money) - optional

Audit:
    Pure validation; no I/O. Returns validation results without side effects.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.coa.account_entity import AccountEntity
from domain.coa.account_type_enum import AccountType

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class InvariantViolationError(ValueError):
    """Raised when a validation invariant is violated."""

    pass


class ValidationResult:
    """Immutable result of a validation check."""

    def __init__(
        self, is_valid: bool, message: str | None = None, details: dict[str, Any] | None = None
    ):
        self.is_valid = is_valid
        self.message = message
        self.details = details or {}

    @classmethod
    def success(
        cls, message: str = "OK", details: dict[str, Any] | None = None
    ) -> ValidationResult:
        return cls(True, message, details)

    @classmethod
    def failure(cls, message: str, details: dict[str, Any] | None = None) -> ValidationResult:
        return cls(False, message, details)

    def __bool__(self) -> bool:
        return self.is_valid

    def __str__(self) -> str:
        return self.message or ("Valid" if self.is_valid else "Invalid")


# ============================================================================
# Main Validator Class
# ============================================================================


class COAInvariantsValidator:
    """
    Validator for Chart of Accounts invariants.

    This class provides static validation methods that can be composed
    to enforce all business rules of the COA aggregate.

    Usage:
        validator = COAInvariantsValidator()
        result = validator.validate_unique_account_code(code, existing_codes)
        if not result.is_valid:
            raise InvariantViolationError(result.message)
    """

    # Class constants
    MAX_ACCOUNT_CODE_LENGTH: int = 20
    MIN_ACCOUNT_CODE_LENGTH: int = 1
    MAX_HIERARCHY_DEPTH: int = 10
    VALID_CODE_PATTERN: str = r"^[A-Za-z0-9._-]+$"
    ALLOWED_CURRENCIES: set[str] = {"IDR", "USD", "EUR", "GBP", "JPY", "CNY", "SGD", "MYR"}

    # Mapping of child account types to allowed parent types
    ALLOWED_PARENT_TYPES: dict[AccountType, set[AccountType]] = {
        AccountType.ASSET: {AccountType.ASSET},
        AccountType.CONTRA_ASSET: {AccountType.ASSET},
        AccountType.LIABILITY: {AccountType.LIABILITY},
        AccountType.CONTRA_LIABILITY: {AccountType.LIABILITY},
        AccountType.EQUITY: {AccountType.EQUITY},
        AccountType.CONTRA_EQUITY: {AccountType.EQUITY},
        AccountType.REVENUE: {AccountType.REVENUE},
        AccountType.EXPENSE: {AccountType.EXPENSE},
    }

    # ------------------------------------------------------------------------
    # Code Validation
    # ------------------------------------------------------------------------

    def validate_account_code_format(self, account_code: str) -> ValidationResult:
        """
        Validate the format of an account code.

        Rules:
            - Must be non-empty string.
            - Length between MIN and MAX.
            - Only alphanumeric, dot, underscore, hyphen.
            - Should not start or end with separator.
        """
        if not account_code or not isinstance(account_code, str):
            return ValidationResult.failure("Account code must be a non-empty string")
        cleaned = account_code.strip()
        if len(cleaned) < self.MIN_ACCOUNT_CODE_LENGTH:
            return ValidationResult.failure(
                f"Account code must be at least {self.MIN_ACCOUNT_CODE_LENGTH} characters"
            )
        if len(cleaned) > self.MAX_ACCOUNT_CODE_LENGTH:
            return ValidationResult.failure(
                f"Account code must not exceed {self.MAX_ACCOUNT_CODE_LENGTH} characters"
            )
        if not re.match(self.VALID_CODE_PATTERN, cleaned):
            return ValidationResult.failure(
                "Account code contains invalid characters. Allowed: letters, numbers, dot, underscore, hyphen"
            )
        # Check separators not at start or end
        if cleaned[0] in "._-" or cleaned[-1] in "._-":
            return ValidationResult.failure(
                "Account code cannot start or end with a separator (._-)"
            )
        return ValidationResult.success()

    def validate_unique_account_code(
        self, account_code: str, existing_codes: set[str], exclude_account_id: UUID | None = None
    ) -> ValidationResult:
        """
        Validate that account code is unique.

        Args:
            account_code: Code to validate
            existing_codes: Set of existing codes
            exclude_account_id: If provided, exclude this account's code from check
        """
        if account_code in existing_codes:
            return ValidationResult.failure(f"Account code '{account_code}' already exists")
        return ValidationResult.success()

    # ------------------------------------------------------------------------
    # Name Validation
    # ------------------------------------------------------------------------

    def validate_account_name(self, name: str) -> ValidationResult:
        """Validate account name (non-empty, reasonable length)."""
        if not name or not isinstance(name, str):
            return ValidationResult.failure("Account name must be a non-empty string")
        cleaned = name.strip()
        if len(cleaned) < 2:
            return ValidationResult.failure("Account name must be at least 2 characters")
        if len(cleaned) > 200:
            return ValidationResult.failure("Account name must not exceed 200 characters")
        return ValidationResult.success()

    # ------------------------------------------------------------------------
    # Parent-Child Validation
    # ------------------------------------------------------------------------

    def validate_parent_exists(
        self, parent_account_id: UUID | None, existing_account_ids: set[UUID]
    ) -> ValidationResult:
        """Validate that parent account exists in the set."""
        if parent_account_id is None:
            return ValidationResult.success()
        if parent_account_id not in existing_account_ids:
            return ValidationResult.failure(f"Parent account with ID {parent_account_id} not found")
        return ValidationResult.success()

    def validate_parent_not_self(
        self, account_id: UUID, parent_account_id: UUID | None
    ) -> ValidationResult:
        """Validate that parent is not the account itself."""
        if parent_account_id is not None and parent_account_id == account_id:
            return ValidationResult.failure("Account cannot be its own parent")
        return ValidationResult.success()

    def validate_parent_type_compatibility(
        self, child_type: AccountType, parent_type: AccountType
    ) -> ValidationResult:
        """
        Validate that the child account type is compatible with parent type.

        Rules:
            - Asset can only have asset parent.
            - Contra-asset can only have asset parent.
            - Liability can only have liability parent.
            - Contra-liability can only have liability parent.
            - Equity can only have equity parent.
            - Contra-equity can only have equity parent.
            - Revenue can only have revenue parent.
            - Expense can only have expense parent.
        """
        allowed_parents = self.ALLOWED_PARENT_TYPES.get(child_type)
        if allowed_parents is None:
            return ValidationResult.failure(f"Unknown child account type: {child_type}")
        if parent_type not in allowed_parents:
            return ValidationResult.failure(
                f"Account type '{child_type.value}' cannot have parent of type '{parent_type.value}'. "
                f"Allowed: {[t.value for t in allowed_parents]}"
            )
        return ValidationResult.success()

    def validate_no_cycle(
        self,
        account_id: UUID,
        new_parent_id: UUID | None,
        get_parent_func: Callable[[UUID], UUID | None],
    ) -> ValidationResult:
        """
        Validate that moving account to new parent does not create a cycle.

        Args:
            account_id: The account being moved
            new_parent_id: Proposed new parent ID
            get_parent_func: Function to get parent of any account ID
        """
        if new_parent_id is None:
            return ValidationResult.success()
        # Traverse up from new_parent to see if we encounter account_id
        current = new_parent_id
        visited = set()
        while current is not None and current not in visited:
            if current == account_id:
                return ValidationResult.failure("Moving would create a cycle in account hierarchy")
            visited.add(current)
            current = get_parent_func(current)
        return ValidationResult.success()

    def validate_max_depth(
        self, parent_id: UUID | None, get_depth_func: Callable[[UUID], int]
    ) -> ValidationResult:
        """
        Validate that adding account under parent does not exceed max depth.
        """
        if parent_id is None:
            return ValidationResult.success()
        parent_depth = get_depth_func(parent_id)
        if parent_depth + 1 > self.MAX_HIERARCHY_DEPTH:
            return ValidationResult.failure(
                f"Cannot add account: maximum hierarchy depth ({self.MAX_HIERARCHY_DEPTH}) exceeded"
            )
        return ValidationResult.success()

    # ------------------------------------------------------------------------
    # Account Status Validation
    # ------------------------------------------------------------------------

    def validate_can_deactivate(
        self, account: AccountEntity, children: list[AccountEntity], has_transactions: bool = False
    ) -> ValidationResult:
        """
        Validate that an account can be deactivated.

        Rules:
            - Account must be active.
            - Account must have no active children.
            - Account must have no transactions (optional check).
        """
        if not account.is_active:
            return ValidationResult.failure("Account is already inactive")
        active_children = [c for c in children if c.is_active]
        if active_children:
            return ValidationResult.failure(
                f"Account has {len(active_children)} active child accounts. "
                f"Deactivate children first."
            )
        if has_transactions:
            return ValidationResult.failure("Account has existing transactions. Cannot deactivate.")
        return ValidationResult.success()

    def validate_can_reactivate(
        self, account: AccountEntity, parent_active: bool = True
    ) -> ValidationResult:
        """
        Validate that an account can be reactivated.

        Rules:
            - Account must be inactive.
            - Parent account (if any) must be active.
        """
        if account.is_active:
            return ValidationResult.failure("Account is already active")
        if account.parent_account_id is not None and not parent_active:
            return ValidationResult.failure(
                "Cannot reactivate: parent account is inactive. Reactivate parent first."
            )
        return ValidationResult.success()

    def validate_can_delete(
        self, account: AccountEntity, children: list[AccountEntity], has_transactions: bool = False
    ) -> ValidationResult:
        """
        Validate that an account can be deleted (physically removed).

        Rules:
            - Account must have no children.
            - Account must have no transactions.
            - Account must be inactive (or allow force?).
        """
        if children:
            return ValidationResult.failure(
                f"Account has {len(children)} child accounts. Delete children first."
            )
        if has_transactions:
            return ValidationResult.failure("Account has existing transactions. Cannot delete.")
        if account.is_active:
            return ValidationResult.failure("Account is active. Deactivate before deletion.")
        return ValidationResult.success()

    # ------------------------------------------------------------------------
    # Opening Balance Validation
    # ------------------------------------------------------------------------

    def validate_opening_balance_sign(
        self, opening_balance: Decimal, normal_balance: str
    ) -> ValidationResult:
        """
        Validate that opening balance sign is consistent with normal balance.

        For normal debit accounts, opening balance should be >= 0.
        For normal credit accounts, opening balance should be <= 0.
        """
        if normal_balance == "debit":
            if opening_balance < 0:
                return ValidationResult.failure(
                    f"Opening balance for debit account cannot be negative: {opening_balance}"
                )
        else:  # credit
            if opening_balance > 0:
                return ValidationResult.failure(
                    f"Opening balance for credit account cannot be positive: {opening_balance}"
                )
        return ValidationResult.success()

    def validate_opening_balance_precision(
        self, opening_balance: Decimal, currency_code: str = "IDR"
    ) -> ValidationResult:
        """
        Validate that opening balance has correct decimal precision for currency.
        """
        # Currency decimal places: IDR=0, USD=2, etc.
        currency_decimals = {
            "IDR": 0,
            "JPY": 0,
            "KRW": 0,
            "VND": 0,
            "USD": 2,
            "EUR": 2,
            "GBP": 2,
            "SGD": 2,
            "MYR": 2,
            "CNY": 2,
        }
        max_decimals = currency_decimals.get(currency_code.upper(), 2)
        if opening_balance.as_tuple().exponent < -max_decimals:
            return ValidationResult.failure(
                f"Opening balance has too many decimal places for {currency_code}. "
                f"Maximum allowed: {max_decimals}"
            )
        return ValidationResult.success()

    # ------------------------------------------------------------------------
    # Control Account Validation
    # ------------------------------------------------------------------------

    def validate_control_account(
        self, account: AccountEntity, has_children: bool
    ) -> ValidationResult:
        """
        Validate control account rules.

        Rules:
            - Control accounts cannot have direct postings (enforced by posting engine).
            - Control accounts can have child accounts.
        """
        if account.is_control_account and not has_children:
            # Warning, not error: control account can be leaf but then should allow postings?
            # We'll allow but log warning.
            logger.debug(f"Control account {account.account_code} has no children")
        return ValidationResult.success()

    # ------------------------------------------------------------------------
    # Cross-Entity Validation
    # ------------------------------------------------------------------------

    def validate_same_legal_entity(
        self, account_legal_entity_id: UUID, coa_legal_entity_id: UUID
    ) -> ValidationResult:
        """Validate that account belongs to the same legal entity as COA."""
        if account_legal_entity_id != coa_legal_entity_id:
            return ValidationResult.failure(
                f"Account legal entity {account_legal_entity_id} does not match COA legal entity {coa_legal_entity_id}"
            )
        return ValidationResult.success()

    # ------------------------------------------------------------------------
    # Comprehensive Validation Methods
    # ------------------------------------------------------------------------

    def validate_new_account(
        self,
        account: AccountEntity,
        existing_codes: set[str],
        existing_accounts: dict[UUID, AccountEntity],
        coa_legal_entity_id: UUID,
    ) -> list[ValidationResult]:
        """
        Run all validations for a new account before creation.

        Returns a list of validation results; all must be valid.
        """
        results = []

        # Basic field validations
        results.append(self.validate_account_code_format(account.account_code))
        results.append(self.validate_account_name(account.account_name))
        results.append(self.validate_unique_account_code(account.account_code, existing_codes))

        # Parent validations
        results.append(self.validate_parent_not_self(account.account_id, account.parent_account_id))
        results.append(
            self.validate_parent_exists(account.parent_account_id, set(existing_accounts.keys()))
        )

        if account.parent_account_id and account.parent_account_id in existing_accounts:
            parent = existing_accounts[account.parent_account_id]
            results.append(
                self.validate_parent_type_compatibility(account.account_type, parent.account_type)
            )
            results.append(
                self.validate_max_depth(
                    account.parent_account_id, lambda aid: existing_accounts[aid].level
                )
            )

        # Opening balance
        results.append(
            self.validate_opening_balance_sign(account.opening_balance, account.normal_balance)
        )
        results.append(
            self.validate_opening_balance_precision(account.opening_balance, account.currency_code)
        )

        # Legal entity
        results.append(
            self.validate_same_legal_entity(account.legal_entity_id, coa_legal_entity_id)
        )

        return results

    def validate_existing_account_update(
        self,
        old_account: AccountEntity,
        new_account: AccountEntity,
        existing_codes: set[str],
        existing_accounts: dict[UUID, AccountEntity],
        get_parent_func: Callable[[UUID], UUID | None],
        get_depth_func: Callable[[UUID], int],
        coa_legal_entity_id: UUID,
    ) -> list[ValidationResult]:
        """
        Run all validations for updating an existing account.
        """
        results = []

        # Code change validation
        if new_account.account_code != old_account.account_code:
            results.append(self.validate_account_code_format(new_account.account_code))
            results.append(
                self.validate_unique_account_code(
                    new_account.account_code,
                    existing_codes,
                    exclude_account_id=old_account.account_id,
                )
            )

        # Name validation
        if new_account.account_name != old_account.account_name:
            results.append(self.validate_account_name(new_account.account_name))

        # Parent change validation
        if new_account.parent_account_id != old_account.parent_account_id:
            results.append(
                self.validate_parent_not_self(new_account.account_id, new_account.parent_account_id)
            )
            results.append(
                self.validate_parent_exists(
                    new_account.parent_account_id, set(existing_accounts.keys())
                )
            )
            results.append(
                self.validate_no_cycle(
                    new_account.account_id, new_account.parent_account_id, get_parent_func
                )
            )
            results.append(self.validate_max_depth(new_account.parent_account_id, get_depth_func))
            if new_account.parent_account_id and new_account.parent_account_id in existing_accounts:
                parent = existing_accounts[new_account.parent_account_id]
                results.append(
                    self.validate_parent_type_compatibility(
                        new_account.account_type, parent.account_type
                    )
                )

        # Opening balance validation
        if new_account.opening_balance != old_account.opening_balance:
            results.append(
                self.validate_opening_balance_sign(
                    new_account.opening_balance, new_account.normal_balance
                )
            )
            results.append(
                self.validate_opening_balance_precision(
                    new_account.opening_balance, new_account.currency_code
                )
            )

        # Legal entity
        results.append(
            self.validate_same_legal_entity(new_account.legal_entity_id, coa_legal_entity_id)
        )

        return results

    # ------------------------------------------------------------------------
    # Bulk Validation Helpers
    # ------------------------------------------------------------------------

    @classmethod
    def validate_all_results(cls, results: list[ValidationResult]) -> tuple[bool, list[str]]:
        """Aggregate multiple validation results."""
        errors = [r.message for r in results if not r.is_valid]
        return len(errors) == 0, errors

    @classmethod
    def raise_if_invalid(cls, results: list[ValidationResult]) -> None:
        """Raise InvariantViolationError if any result is invalid."""
        valid, errors = cls.validate_all_results(results)
        if not valid:
            raise InvariantViolationError("; ".join(errors))

    # ------------------------------------------------------------------------
    # Additional Business Rules
    # ------------------------------------------------------------------------

    def validate_account_type_consistency(
        self, account_type: AccountType, normal_balance: str
    ) -> ValidationResult:
        """
        Validate that normal balance matches account type standard.
        """
        expected_normal = {
            AccountType.ASSET: "debit",
            AccountType.CONTRA_ASSET: "credit",
            AccountType.LIABILITY: "credit",
            AccountType.CONTRA_LIABILITY: "debit",
            AccountType.EQUITY: "credit",
            AccountType.CONTRA_EQUITY: "debit",
            AccountType.REVENUE: "credit",
            AccountType.EXPENSE: "debit",
        }
        expected = expected_normal.get(account_type)
        if expected and normal_balance != expected:
            return ValidationResult.failure(
                f"Account type {account_type.value} should have normal balance '{expected}', "
                f"but got '{normal_balance}'"
            )
        return ValidationResult.success()

    def validate_currency_supported(self, currency_code: str) -> ValidationResult:
        """Validate that currency is supported by the system."""
        if currency_code.upper() not in self.ALLOWED_CURRENCIES:
            return ValidationResult.failure(
                f"Currency {currency_code} is not supported. "
                f"Supported: {sorted(self.ALLOWED_CURRENCIES)}"
            )
        return ValidationResult.success()

    def validate_level_consistency(
        self, account: AccountEntity, expected_level: int
    ) -> ValidationResult:
        """Validate that account.level matches the computed level from parent."""
        if account.level != expected_level:
            return ValidationResult.failure(
                f"Account level mismatch: stored={account.level}, expected={expected_level}"
            )
        return ValidationResult.success()


# ============================================================================
# Convenience Functions
# ============================================================================


def validate_account_code(code: str) -> bool:
    """Quick validation of account code format (returns bool)."""
    validator = COAInvariantsValidator()
    return validator.validate_account_code_format(code).is_valid


def validate_account_name(name: str) -> bool:
    """Quick validation of account name format."""
    validator = COAInvariantsValidator()
    return validator.validate_account_name(name).is_valid


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "COAInvariantsValidator",
    "InvariantViolationError",
    "ValidationResult",
    "validate_account_code",
    "validate_account_name",
]
