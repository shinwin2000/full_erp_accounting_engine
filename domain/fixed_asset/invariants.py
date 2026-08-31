#!/usr/bin/env python3
"""
Module: invariants.py

Layer: Domain / Fixed Asset

Responsibility:
    Invariants (business rules) validation for Fixed Asset aggregate.

    Defines all invariants that must be satisfied by fixed assets:
    - Unique asset code per legal entity
    - Positive acquisition cost and non-negative salvage value
    - Salvage value <= acquisition cost
    - Useful life positive (for depreciable assets)
    - Accumulated depreciation cannot exceed depreciable amount
    - Net book value cannot be negative
    - Valid depreciation method
    - Revaluation value positive
    - Disposal only allowed for active assets
    - Transfer only allowed for active assets
    - Impairment loss cannot exceed NBV
    - Status transitions must be valid

    Provides reusable validators and an enforcer with callbacks.

Dependencies:
    - Python standard library (decimal, datetime, logging, re)
    - domain.fixed_asset.asset_entity (FixedAsset, AssetStatus, AssetType)
    - domain.fixed_asset.depreciation_schedule_engine (DepreciationMethod)

Audit:
    Validation failures are logged; enforcer methods can be used in commands.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from domain.fixed_asset.asset_entity import (
    AssetStatus,
    AssetType,
    FixedAsset,
)
from domain.fixed_asset.depreciation_schedule_engine import DepreciationMethod

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Result
# ============================================================================


@dataclass
class InvariantResult:
    """
    Result of an invariant validation.

    Attributes:
        is_valid: True if all checks passed
        errors: List of error messages
        warnings: List of warning messages (non-critical)
    """

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error message and mark as invalid."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message (does not affect validity)."""
        self.warnings.append(warning)

    def merge(self, other: InvariantResult) -> InvariantResult:
        """Merge another result into this one."""
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def __bool__(self) -> bool:
        return self.is_valid

    @classmethod
    def success(cls, warnings: list[str] | None = None) -> InvariantResult:
        return cls(is_valid=True, warnings=warnings or [])

    @classmethod
    def failure(cls, error: str, warnings: list[str] | None = None) -> InvariantResult:
        result = cls(is_valid=False, warnings=warnings or [])
        result.add_error(error)
        return result


# ============================================================================
# Common Validators
# ============================================================================


def validate_positive_decimal(value: Decimal, field_name: str = "Value") -> InvariantResult:
    """Validate that a Decimal value is positive."""
    if value <= 0:
        return InvariantResult.failure(f"{field_name} must be positive: {value}")
    return InvariantResult.success()


def validate_non_negative_decimal(value: Decimal, field_name: str = "Value") -> InvariantResult:
    """Validate that a Decimal value is non-negative."""
    if value < 0:
        return InvariantResult.failure(f"{field_name} cannot be negative: {value}")
    return InvariantResult.success()


def validate_string_not_empty(
    value: str | None, field_name: str = "Value", min_len: int = 1
) -> InvariantResult:
    """Validate that a string is not empty and meets minimum length."""
    if value is None:
        return InvariantResult.failure(f"{field_name} cannot be None")
    if not isinstance(value, str):
        return InvariantResult.failure(f"{field_name} must be a string")
    cleaned = value.strip()
    if len(cleaned) < min_len:
        return InvariantResult.failure(f"{field_name} must be at least {min_len} character(s)")
    return InvariantResult.success()


def validate_date_not_future(date_val: date, field_name: str = "Date") -> InvariantResult:
    """Validate that a date is not in the future."""
    if date_val > date.today():
        return InvariantResult.failure(f"{field_name} cannot be in the future: {date_val}")
    return InvariantResult.success()


def validate_date_sequence(
    start_date: date, end_date: date, start_name: str = "Start", end_name: str = "End"
) -> InvariantResult:
    """Validate that start_date <= end_date."""
    if start_date > end_date:
        return InvariantResult.failure(
            f"{start_name} date {start_date} must be before or equal to {end_name} date {end_date}"
        )
    return InvariantResult.success()


def validate_version(version: int, expected_version: int | None = None) -> InvariantResult:
    """Validate version number and optimistic lock."""
    if version < 1:
        return InvariantResult.failure(f"Version must be >= 1, got {version}")
    if expected_version is not None and version != expected_version:
        return InvariantResult.failure(
            f"Version mismatch: expected {expected_version}, got {version}"
        )
    return InvariantResult.success()


# ============================================================================
# Fixed Asset Invariants (Static)
# ============================================================================


class FixedAssetInvariants:
    """
    Collection of static invariant validators for Fixed Asset entity.
    """

    @staticmethod
    def validate_asset_code(code: str) -> InvariantResult:
        """Validate asset code format."""
        result = validate_string_not_empty(code, "Asset code", min_len=2)
        if not result:
            return result
        cleaned = code.strip()
        if len(cleaned) > 30:
            return InvariantResult.failure("Asset code must not exceed 30 characters")
        if not re.match(r"^[A-Za-z0-9\-_/]+$", cleaned):
            return InvariantResult.failure(
                "Asset code can only contain letters, numbers, hyphens, underscores, and slashes"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_asset_name(name: str) -> InvariantResult:
        """Validate asset name."""
        result = validate_string_not_empty(name, "Asset name", min_len=2)
        if not result:
            return result
        cleaned = name.strip()
        if len(cleaned) > 200:
            return InvariantResult.failure("Asset name must not exceed 200 characters")
        return InvariantResult.success()

    @staticmethod
    def validate_asset_type(asset_type: AssetType) -> InvariantResult:
        """Validate asset type."""
        if not isinstance(asset_type, AssetType):
            return InvariantResult.failure(f"Invalid asset_type: {asset_type}")
        return InvariantResult.success()

    @staticmethod
    def validate_asset_status(status: AssetStatus) -> InvariantResult:
        """Validate asset status."""
        if not isinstance(status, AssetStatus):
            return InvariantResult.failure(f"Invalid status: {status}")
        return InvariantResult.success()

    @staticmethod
    def validate_acquisition_date(date_val: date) -> InvariantResult:
        """Validate acquisition date (cannot be in future)."""
        return validate_date_not_future(date_val, "Acquisition date")

    @staticmethod
    def validate_cost(cost: Decimal) -> InvariantResult:
        """Validate acquisition cost (positive)."""
        return validate_positive_decimal(cost, "Acquisition cost")

    @staticmethod
    def validate_salvage_value(salvage: Decimal, cost: Decimal) -> InvariantResult:
        """Validate salvage value (non-negative, <= cost)."""
        result = validate_non_negative_decimal(salvage, "Salvage value")
        if not result:
            return result
        if salvage > cost:
            return InvariantResult.failure(
                f"Salvage value {salvage} cannot exceed acquisition cost {cost}"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_useful_life(years: int, asset_type: AssetType) -> InvariantResult:
        """Validate useful life (positive for depreciable assets, zero for land)."""
        result = InvariantResult()
        if asset_type == AssetType.LAND:
            if years != 0:
                result.add_warning("Land typically has zero useful life (not depreciable)")
            return result
        if years <= 0:
            return InvariantResult.failure(
                f"Useful life must be positive for depreciable assets: {years}"
            )
        if years > 100:
            result.add_warning(f"Useful life {years} years is unusually long")
        return result

    @staticmethod
    def validate_depreciation_method(
        method: DepreciationMethod | str, asset_type: AssetType
    ) -> InvariantResult:
        """Validate depreciation method (land should not have a method)."""
        # Convert string to enum if needed
        if isinstance(method, str):
            try:
                method = DepreciationMethod(method)
            except ValueError:
                return InvariantResult.failure(f"Invalid depreciation method: {method}")

        if asset_type == AssetType.LAND:
            if method != DepreciationMethod.STRAIGHT_LINE:
                result = InvariantResult()
                result.add_warning("Land is not depreciable; method will be ignored")
                return result
            return InvariantResult.success()
        if not isinstance(method, DepreciationMethod):
            return InvariantResult.failure(f"Invalid depreciation method: {method}")
        return InvariantResult.success()

    @staticmethod
    def validate_accumulated_depreciation(
        acc_dep: Decimal, cost: Decimal, salvage: Decimal
    ) -> InvariantResult:
        """Validate accumulated depreciation (>=0, <= cost - salvage)."""
        result = validate_non_negative_decimal(acc_dep, "Accumulated depreciation")
        if not result:
            return result
        max_dep = cost - salvage
        if acc_dep > max_dep + Decimal("0.01"):  # tolerance
            return InvariantResult.failure(
                f"Accumulated depreciation {acc_dep} exceeds depreciable amount {max_dep}"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_net_book_value(
        nbv: Decimal, cost: Decimal, acc_dep: Decimal, impairment: Decimal
    ) -> InvariantResult:
        """Validate net book value equals cost - acc_dep - impairment."""
        expected = cost - acc_dep - impairment
        if abs(nbv - expected) > Decimal("0.01"):
            return InvariantResult.failure(
                f"Net book value mismatch: expected {expected}, got {nbv}"
            )
        if nbv < 0:
            return InvariantResult.failure(f"Net book value cannot be negative: {nbv}")
        return InvariantResult.success()

    @staticmethod
    def validate_accumulated_impairment(
        impairment: Decimal, nbv_before: Decimal
    ) -> InvariantResult:
        """Validate accumulated impairment (>=0, <= NBV)."""
        result = validate_non_negative_decimal(impairment, "Accumulated impairment")
        if not result:
            return result
        if impairment > nbv_before + Decimal("0.01"):
            return InvariantResult.failure(
                f"Accumulated impairment {impairment} exceeds NBV {nbv_before}"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_revaluation_surplus(surplus: Decimal) -> InvariantResult:
        """Validate revaluation surplus (>=0)."""
        return validate_non_negative_decimal(surplus, "Revaluation surplus")

    @staticmethod
    def validate_currency(currency: str) -> InvariantResult:
        """Validate ISO 4217 currency code."""
        result = validate_string_not_empty(currency, "Currency", min_len=3)
        if not result:
            return result
        cleaned = currency.strip().upper()
        if len(cleaned) != 3:
            return InvariantResult.failure(f"Currency code must be exactly 3 characters: {cleaned}")
        if not re.match(r"^[A-Z]{3}$", cleaned):
            return InvariantResult.failure(f"Currency code must contain only letters: {cleaned}")
        return InvariantResult.success()

    @staticmethod
    def validate_asset_unique_code(code: str, existing_codes: set[str]) -> InvariantResult:
        """Validate that asset code is unique."""
        if code in existing_codes:
            return InvariantResult.failure(f"Asset code '{code}' already exists")
        return InvariantResult.success()

    @staticmethod
    def validate_disposal_allowed(asset: FixedAsset) -> InvariantResult:
        """Check if asset can be disposed."""
        if asset.is_disposed:
            return InvariantResult.failure(f"Asset {asset.asset_code} is already disposed")
        if asset.status == AssetStatus.UNDER_CONSTRUCTION:
            return InvariantResult.failure("Assets under construction cannot be disposed")
        return InvariantResult.success()

    @staticmethod
    def validate_transfer_allowed(asset: FixedAsset) -> InvariantResult:
        """Check if asset can be transferred."""
        if asset.is_disposed:
            return InvariantResult.failure(
                f"Asset {asset.asset_code} is already disposed and cannot be transferred"
            )
        if not asset.status.can_transfer():
            return InvariantResult.failure(
                f"Asset in status {asset.status.display_name()} cannot be transferred"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_revaluation_allowed(asset: FixedAsset, new_value: Decimal) -> InvariantResult:
        """Check if asset can be revalued."""
        if not asset.status.can_revalue():
            return InvariantResult.failure(
                f"Asset in status {asset.status.display_name()} cannot be revalued"
            )
        if new_value <= 0:
            return InvariantResult.failure(f"Revaluation value must be positive: {new_value}")
        # Optional: ensure revaluation is not trivial
        if abs(new_value - asset.net_book_value) / max(
            asset.net_book_value, Decimal("1")
        ) < Decimal("0.01"):
            result = InvariantResult()
            result.add_warning("Revaluation change is less than 1% of NBV")
            return result
        return InvariantResult.success()

    @staticmethod
    def validate_impairment_allowed(asset: FixedAsset, impairment_loss: Decimal) -> InvariantResult:
        """Check if impairment can be recognized."""
        if impairment_loss <= 0:
            return InvariantResult.failure(f"Impairment loss must be positive: {impairment_loss}")
        if impairment_loss > asset.net_book_value:
            return InvariantResult.failure(
                f"Impairment loss {impairment_loss} exceeds NBV {asset.net_book_value}"
            )
        return InvariantResult.success()


# ============================================================================
# Status Transition Validation
# ============================================================================

# Allowed transitions: from_status -> set of to_status
ALLOWED_STATUS_TRANSITIONS: dict[AssetStatus, set[AssetStatus]] = {
    AssetStatus.ACTIVE: {
        AssetStatus.FULLY_DEPRECIATED,
        AssetStatus.IDLE,
        AssetStatus.DISPOSED,
        AssetStatus.IMPAIRED,
    },
    AssetStatus.FULLY_DEPRECIATED: {AssetStatus.ACTIVE, AssetStatus.DISPOSED, AssetStatus.IDLE},
    AssetStatus.IDLE: {AssetStatus.ACTIVE, AssetStatus.FULLY_DEPRECIATED, AssetStatus.DISPOSED},
    AssetStatus.IMPAIRED: {AssetStatus.ACTIVE, AssetStatus.FULLY_DEPRECIATED, AssetStatus.DISPOSED},
    AssetStatus.UNDER_CONSTRUCTION: {AssetStatus.ACTIVE, AssetStatus.DISPOSED},
    AssetStatus.DISPOSED: set(),  # Terminal
}


def validate_status_transition(
    current_status: AssetStatus,
    new_status: AssetStatus,
    user_role: str = "user",
) -> InvariantResult:
    """Validate if a status transition is allowed."""
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        return InvariantResult.failure(
            f"Status transition from {current_status.display_name()} to {new_status.display_name()} is not allowed"
        )
    # Role-based restrictions
    if new_status == AssetStatus.DISPOSED and user_role not in (
        "finance_manager",
        "admin",
        "accountant",
    ):
        return InvariantResult.failure("Disposing an asset requires finance manager or admin role")
    if new_status == AssetStatus.ACTIVE and current_status in (AssetStatus.DISPOSED,):
        return InvariantResult.failure("Cannot reactivate a disposed asset")
    return InvariantResult.success()


# ============================================================================
# Fixed Asset Invariant Enforcer (Async)
# ============================================================================


class FixedAssetInvariantEnforcer:
    """
    Enforcer for all fixed asset invariants.

    Uses callbacks to retrieve existing codes and other dynamic data.

    Usage:
        enforcer = FixedAssetInvariantEnforcer(
            get_existing_codes=lambda: {"ASSET001", "ASSET002"}
        )
        result = await enforcer.enforce_asset_create(asset)
    """

    def __init__(
        self,
        get_existing_codes: Callable[[], set[str]] | None = None,
    ):
        self._get_existing_codes = get_existing_codes or (lambda: set())
        self._invariants = FixedAssetInvariants()

    async def enforce_asset_create(self, asset: FixedAsset) -> InvariantResult:
        """Enforce all invariants for a new asset before creation."""
        result = InvariantResult()

        # Basic field validations
        result.merge(self._invariants.validate_asset_code(asset.asset_code))
        result.merge(self._invariants.validate_asset_name(asset.name))
        result.merge(self._invariants.validate_asset_type(asset.asset_type))
        result.merge(self._invariants.validate_asset_status(asset.status))
        result.merge(self._invariants.validate_acquisition_date(asset.acquisition_date))
        result.merge(self._invariants.validate_cost(asset.acquisition_cost))
        result.merge(
            self._invariants.validate_salvage_value(asset.salvage_value, asset.acquisition_cost)
        )
        result.merge(
            self._invariants.validate_useful_life(asset.useful_life_years, asset.asset_type)
        )
        result.merge(
            self._invariants.validate_depreciation_method(
                asset.depreciation_method, asset.asset_type
            )
        )
        result.merge(
            self._invariants.validate_accumulated_depreciation(
                asset.accumulated_depreciation, asset.acquisition_cost, asset.salvage_value
            )
        )
        result.merge(
            self._invariants.validate_accumulated_impairment(
                asset.accumulated_impairment,
                asset.acquisition_cost - asset.accumulated_depreciation,
            )
        )
        result.merge(
            self._invariants.validate_net_book_value(
                asset.net_book_value,
                asset.acquisition_cost,
                asset.accumulated_depreciation,
                asset.accumulated_impairment,
            )
        )
        result.merge(self._invariants.validate_currency(asset.currency))

        # Uniqueness check - synchronous call, no await
        existing_codes = self._get_existing_codes()
        result.merge(self._invariants.validate_asset_unique_code(asset.asset_code, existing_codes))

        return result

    async def enforce_asset_update(
        self, asset: FixedAsset, old_asset: FixedAsset | None = None
    ) -> InvariantResult:
        """Enforce invariants for updating an existing asset."""
        result = InvariantResult()

        # Basic validations
        result.merge(self._invariants.validate_asset_code(asset.asset_code))
        result.merge(self._invariants.validate_asset_name(asset.name))
        result.merge(self._invariants.validate_asset_type(asset.asset_type))
        result.merge(self._invariants.validate_asset_status(asset.status))
        result.merge(self._invariants.validate_acquisition_date(asset.acquisition_date))
        result.merge(self._invariants.validate_cost(asset.acquisition_cost))
        result.merge(
            self._invariants.validate_salvage_value(asset.salvage_value, asset.acquisition_cost)
        )
        result.merge(
            self._invariants.validate_useful_life(asset.useful_life_years, asset.asset_type)
        )
        result.merge(
            self._invariants.validate_depreciation_method(
                asset.depreciation_method, asset.asset_type
            )
        )
        result.merge(
            self._invariants.validate_accumulated_depreciation(
                asset.accumulated_depreciation, asset.acquisition_cost, asset.salvage_value
            )
        )
        result.merge(
            self._invariants.validate_net_book_value(
                asset.net_book_value,
                asset.acquisition_cost,
                asset.accumulated_depreciation,
                asset.accumulated_impairment,
            )
        )
        result.merge(self._invariants.validate_currency(asset.currency))

        # If code changed, check uniqueness
        if old_asset and asset.asset_code != old_asset.asset_code:
            existing_codes = self._get_existing_codes()
            if old_asset.asset_code in existing_codes:
                existing_codes.discard(old_asset.asset_code)
            result.merge(
                self._invariants.validate_asset_unique_code(asset.asset_code, existing_codes)
            )

        return result

    async def enforce_depreciation(self, asset: FixedAsset, amount: Decimal) -> InvariantResult:
        """Enforce invariants for posting depreciation."""
        result = InvariantResult()
        if amount <= 0:
            result.add_error(f"Depreciation amount must be positive: {amount}")
        if amount > asset.net_book_value - asset.salvage_value:
            result.add_error(
                f"Depreciation amount {amount} would reduce NBV below salvage value {asset.salvage_value}"
            )
        return result

    async def enforce_disposal(self, asset: FixedAsset) -> InvariantResult:
        """Enforce invariants for disposing an asset."""
        return self._invariants.validate_disposal_allowed(asset)

    async def enforce_transfer(self, asset: FixedAsset, new_location: str) -> InvariantResult:
        """Enforce invariants for transferring an asset."""
        result = self._invariants.validate_transfer_allowed(asset)
        result.merge(validate_string_not_empty(new_location, "Destination location", min_len=1))
        return result

    async def enforce_revaluation(self, asset: FixedAsset, new_value: Decimal) -> InvariantResult:
        """Enforce invariants for revaluing an asset."""
        return self._invariants.validate_revaluation_allowed(asset, new_value)

    async def enforce_impairment(
        self, asset: FixedAsset, impairment_loss: Decimal
    ) -> InvariantResult:
        """Enforce invariants for recognizing impairment."""
        return self._invariants.validate_impairment_allowed(asset, impairment_loss)

    async def enforce_status_transition(
        self,
        current_status: AssetStatus,
        new_status: AssetStatus,
        user_role: str = "user",
    ) -> InvariantResult:
        """Enforce status transition invariants."""
        return validate_status_transition(current_status, new_status, user_role)


# ============================================================================
# Fixed Asset Invariants Validator (Synchronous for Service Layer)
# ============================================================================


class FixedAssetInvariantsValidator:
    """
    Simple synchronous validator for use in service layer.
    Provides direct validation methods that raise ValueError on failure.
    """

    @staticmethod
    def validate_asset_cost(asset: FixedAsset) -> None:
        """Check acquisition cost and salvage value."""
        if asset.acquisition_cost <= 0:
            raise ValueError(f"Acquisition cost must be positive: {asset.acquisition_cost}")
        if asset.salvage_value < 0:
            raise ValueError(f"Salvage value cannot be negative: {asset.salvage_value}")
        if asset.salvage_value > asset.acquisition_cost:
            raise ValueError(
                f"Salvage value {asset.salvage_value} cannot exceed cost {asset.acquisition_cost}"
            )

    @staticmethod
    def validate_useful_life(asset: FixedAsset) -> None:
        """Check useful life."""
        if asset.asset_type != AssetType.LAND and asset.useful_life_years <= 0:
            raise ValueError(
                f"Useful life must be positive for depreciable assets: {asset.useful_life_years}"
            )

    @staticmethod
    def validate_depreciation_method(asset: FixedAsset) -> None:
        """Check depreciation method."""
        # asset.depreciation_method may be a string or enum
        method = asset.depreciation_method
        if isinstance(method, str):
            # Try to convert to enum
            try:
                DepreciationMethod(method)
            except ValueError:
                raise ValueError(f"Invalid depreciation method: {method}")
        elif not isinstance(method, DepreciationMethod):
            raise ValueError(f"Invalid depreciation method: {method}")

    @staticmethod
    def validate_depreciation_amount(asset: FixedAsset, amount: Decimal) -> None:
        """Check depreciation amount is valid."""
        if amount < 0:
            raise ValueError(f"Depreciation amount cannot be negative: {amount}")
        if amount > asset.net_book_value - asset.salvage_value:
            raise ValueError(
                f"Depreciation amount {amount} would reduce NBV below salvage value {asset.salvage_value}"
            )

    @staticmethod
    def validate_asset_code_unique(code: str, existing_codes: set[str]) -> None:
        """Check asset code uniqueness."""
        if code in existing_codes:
            raise ValueError(f"Asset code '{code}' already exists")

    @staticmethod
    def validate_revaluation(asset: FixedAsset, new_value: Decimal) -> None:
        """Check revaluation validity."""
        if not asset.status.can_revalue():
            raise ValueError(f"Cannot revalue asset in status {asset.status.display_name()}")
        if new_value <= 0:
            raise ValueError(f"Revaluation value must be positive: {new_value}")
        if asset.asset_type != AssetType.TANGIBLE:
            raise ValueError("Only tangible assets can be revalued")

    @staticmethod
    def validate_disposal(asset: FixedAsset) -> None:
        """Check disposal validity."""
        if asset.is_disposed:
            raise ValueError(f"Asset {asset.asset_code} is already disposed")
        if asset.status == AssetStatus.UNDER_CONSTRUCTION:
            raise ValueError("Assets under construction cannot be disposed")

    @staticmethod
    def validate_transfer(asset: FixedAsset, new_location: str) -> None:
        """Check transfer validity."""
        if asset.is_disposed:
            raise ValueError(f"Asset {asset.asset_code} is already disposed")
        if not asset.status.can_transfer():
            raise ValueError(f"Asset in status {asset.status.display_name()} cannot be transferred")
        if not new_location or len(new_location.strip()) < 2:
            raise ValueError("Destination location must be provided")

    @staticmethod
    def validate_accumulated_depreciation(asset: FixedAsset) -> None:
        """Check accumulated depreciation bounds."""
        if asset.accumulated_depreciation > asset.acquisition_cost - asset.salvage_value:
            raise ValueError(
                f"Accumulated depreciation {asset.accumulated_depreciation} exceeds depreciable amount"
            )
        if asset.accumulated_depreciation < 0:
            raise ValueError("Accumulated depreciation cannot be negative")

    @staticmethod
    def validate_net_book_value(asset: FixedAsset) -> None:
        """Check net book value non-negative."""
        if asset.net_book_value < 0:
            raise ValueError(f"Net book value cannot be negative: {asset.net_book_value}")


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "FixedAssetInvariantEnforcer",
    "FixedAssetInvariants",
    "FixedAssetInvariantsValidator",
    "InvariantResult",
    "validate_date_not_future",
    "validate_date_sequence",
    "validate_non_negative_decimal",
    "validate_positive_decimal",
    "validate_status_transition",
    "validate_string_not_empty",
    "validate_version",
]
