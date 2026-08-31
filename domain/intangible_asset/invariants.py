#!/usr/bin/env python3
"""
Module: invariants.py
Layer: Domain / Intangible Asset
Responsibility: Invariants untuk aset tak berwujud dengan validator lengkap.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from domain.intangible_asset.amortization_method_enum import AmortizationMethod
from domain.intangible_asset.asset_entity import (
    IntangibleAssetEntity,
    IntangibleAssetStatus,
    IntangibleAssetType,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Result
# ============================================================================


@dataclass
class InvariantResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: InvariantResult) -> InvariantResult:
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
    if value <= 0:
        return InvariantResult.failure(f"{field_name} must be positive: {value}")
    return InvariantResult.success()


def validate_non_negative_decimal(value: Decimal, field_name: str = "Value") -> InvariantResult:
    if value < 0:
        return InvariantResult.failure(f"{field_name} cannot be negative: {value}")
    return InvariantResult.success()


def validate_string_not_empty(
    value: str | None, field_name: str = "Value", min_len: int = 1
) -> InvariantResult:
    if value is None:
        return InvariantResult.failure(f"{field_name} cannot be None")
    if not isinstance(value, str):
        return InvariantResult.failure(f"{field_name} must be a string")
    cleaned = value.strip()
    if len(cleaned) < min_len:
        return InvariantResult.failure(f"{field_name} must be at least {min_len} character(s)")
    return InvariantResult.success()


def validate_date_not_future(dt: datetime, field_name: str = "Date") -> InvariantResult:
    if dt > datetime.now(UTC):
        return InvariantResult.failure(f"{field_name} cannot be in the future: {dt}")
    return InvariantResult.success()


def validate_date_sequence(
    start_date: datetime, end_date: datetime, start_name: str = "Start", end_name: str = "End"
) -> InvariantResult:
    if start_date >= end_date:
        return InvariantResult.failure(
            f"{start_name} date {start_date} must be before {end_name} date {end_date}"
        )
    return InvariantResult.success()


def validate_version(version: int = 1, expected_version: int | None = None) -> InvariantResult:
    if version < 1:
        return InvariantResult.failure(f"Version must be >= 1, got {version}")
    if expected_version is not None and version != expected_version:
        return InvariantResult.failure(
            f"Version mismatch: expected {expected_version}, got {version}"
        )
    return InvariantResult.success()


def validate_currency(currency: str = "IDR") -> InvariantResult:
    if not currency or not isinstance(currency, str):
        return InvariantResult.failure("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        return InvariantResult.failure(
            f"Currency code must be exactly 3 characters, got '{cleaned}'"
        )
    if not re.match(r"^[A-Z]{3}$", cleaned):
        return InvariantResult.failure(f"Currency code must contain only letters, got '{cleaned}'")
    return InvariantResult.success()


# ============================================================================
# Intangible Asset Invariants
# ============================================================================


class IntangibleAssetInvariants:
    """Kumpulan invariant untuk Intangible Asset aggregate."""

    @staticmethod
    def validate_asset_code(code: str) -> InvariantResult:
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
        result = validate_string_not_empty(name, "Asset name", min_len=2)
        if not result:
            return result
        cleaned = name.strip()
        if len(cleaned) > 200:
            return InvariantResult.failure("Asset name must not exceed 200 characters")
        return InvariantResult.success()

    @staticmethod
    def validate_asset_type(asset_type: IntangibleAssetType) -> InvariantResult:
        if not isinstance(asset_type, IntangibleAssetType):
            return InvariantResult.failure(f"Invalid asset_type: {asset_type}")
        return InvariantResult.success()

    @staticmethod
    def validate_asset_status(status: IntangibleAssetStatus) -> InvariantResult:
        if not isinstance(status, IntangibleAssetStatus):
            return InvariantResult.failure(f"Invalid status: {status}")
        return InvariantResult.success()

    @staticmethod
    def validate_acquisition_date(date_val: datetime) -> InvariantResult:
        return validate_date_not_future(date_val, "Acquisition date")

    @staticmethod
    def validate_cost(cost: Decimal) -> InvariantResult:
        return validate_positive_decimal(cost, "Acquisition cost")

    @staticmethod
    def validate_residual_value(residual: Decimal, cost: Decimal) -> InvariantResult:
        result = validate_non_negative_decimal(residual, "Residual value")
        if not result:
            return result
        if residual > cost:
            return InvariantResult.failure(
                f"Residual value {residual} cannot exceed acquisition cost {cost}"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_useful_life(
        years: int, asset_type: IntangibleAssetType, amortization_method: AmortizationMethod
    ) -> InvariantResult:
        if asset_type == IntangibleAssetType.GOODWILL:
            if years != 0:
                return InvariantResult.success()
            return InvariantResult.success()
        if amortization_method == AmortizationMethod.NO_AMORTIZATION:
            return InvariantResult.success()
        if years <= 0:
            return InvariantResult.failure(
                f"Useful life must be positive for amortizable assets: {years}"
            )
        if years > 100:
            return InvariantResult.success(warnings=[f"Useful life {years} years is unusually long"])
        return InvariantResult.success()

    @staticmethod
    def validate_amortization_method(
        method: AmortizationMethod, asset_type: IntangibleAssetType, useful_life_years: int
    ) -> InvariantResult:
        if not isinstance(method, AmortizationMethod):
            return InvariantResult.failure(f"Invalid amortization method: {method}")
        if (
            asset_type == IntangibleAssetType.GOODWILL
            and method != AmortizationMethod.NO_AMORTIZATION
        ):
            return InvariantResult.failure("Goodwill must use NO_AMORTIZATION method")
        if useful_life_years == 0 and method != AmortizationMethod.NO_AMORTIZATION:
            return InvariantResult.failure(
                "Assets with indefinite life must use NO_AMORTIZATION method"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_accumulated_amortization(
        acc_amort: Decimal, cost: Decimal, residual: Decimal
    ) -> InvariantResult:
        result = validate_non_negative_decimal(acc_amort, "Accumulated amortization")
        if not result:
            return result
        max_amort = cost - residual
        if acc_amort > max_amort + Decimal("0.01"):
            return InvariantResult.failure(
                f"Accumulated amortization {acc_amort} exceeds amortizable amount {max_amort}"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_nbv(nbv: Decimal, cost: Decimal, acc_amort: Decimal) -> InvariantResult:
        expected = cost - acc_amort
        if abs(nbv - expected) > Decimal("0.01"):
            return InvariantResult.failure(f"NBV mismatch: expected {expected}, got {nbv}")
        if nbv < 0:
            return InvariantResult.failure(f"NBV cannot be negative: {nbv}")
        return InvariantResult.success()

    @staticmethod
    def validate_asset_code_unique(code: str, existing_codes: set[str]) -> InvariantResult:
        if code in existing_codes:
            return InvariantResult.failure(f"Asset code '{code}' already exists")
        return InvariantResult.success()

    @staticmethod
    def validate_disposal_allowed(asset: IntangibleAssetEntity) -> InvariantResult:
        if asset.status == IntangibleAssetStatus.DISPOSED:
            return InvariantResult.failure(f"Asset {asset.asset_code} is already disposed")
        return InvariantResult.success()

    @staticmethod
    def validate_impairment_allowed(
        asset: IntangibleAssetEntity, impairment_loss: Decimal
    ) -> InvariantResult:
        if impairment_loss <= 0:
            return InvariantResult.failure(f"Impairment loss must be positive: {impairment_loss}")
        if impairment_loss > asset.nbv:
            return InvariantResult.failure(
                f"Impairment loss {impairment_loss} exceeds NBV {asset.nbv}"
            )
        if not asset.status.can_impair():
            return InvariantResult.failure(
                f"Asset in status {asset.status.display_name()} cannot be impaired"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_amortization_allowed(
        asset: IntangibleAssetEntity, amount: Decimal
    ) -> InvariantResult:
        if amount <= 0:
            return InvariantResult.failure(f"Amortization amount must be positive: {amount}")
        if asset.has_indefinite_life:
            return InvariantResult.failure(
                f"Asset {asset.asset_code} has indefinite life and cannot be amortized"
            )
        if not asset.status.can_amortize():
            return InvariantResult.failure(
                f"Asset in status {asset.status.display_name()} cannot be amortized"
            )
        if amount > asset.remaining_amortizable:
            return InvariantResult.failure(
                f"Amortization amount {amount} exceeds remaining amortizable {asset.remaining_amortizable}"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_expiry_date(
        expiry_date: datetime | None, acquisition_date: datetime
    ) -> InvariantResult:
        if expiry_date and expiry_date <= acquisition_date:
            return InvariantResult.failure(
                f"Expiry date {expiry_date} must be after acquisition date {acquisition_date}"
            )
        return InvariantResult.success()

    # Added: validate_currency as static method
    @staticmethod
    def validate_currency(currency: str) -> InvariantResult:
        return validate_currency(currency)


# ============================================================================
# Status Transition Validation
# ============================================================================

ALLOWED_STATUS_TRANSITIONS: dict[IntangibleAssetStatus, set[IntangibleAssetStatus]] = {
    IntangibleAssetStatus.PENDING_ACTIVATION: {
        IntangibleAssetStatus.ACTIVE,
        IntangibleAssetStatus.DISPOSED,
    },
    IntangibleAssetStatus.ACTIVE: {
        IntangibleAssetStatus.FULLY_AMORTIZED,
        IntangibleAssetStatus.IMPAIRED,
        IntangibleAssetStatus.DISPOSED,
        IntangibleAssetStatus.UNDER_DEVELOPMENT,
    },
    IntangibleAssetStatus.UNDER_DEVELOPMENT: {
        IntangibleAssetStatus.ACTIVE,
        IntangibleAssetStatus.DISPOSED,
    },
    IntangibleAssetStatus.IMPAIRED: {
        IntangibleAssetStatus.ACTIVE,
        IntangibleAssetStatus.FULLY_AMORTIZED,
        IntangibleAssetStatus.DISPOSED,
    },
    IntangibleAssetStatus.FULLY_AMORTIZED: {IntangibleAssetStatus.DISPOSED},
    IntangibleAssetStatus.DISPOSED: set(),
}

TRANSITION_ROLE_REQUIREMENTS: dict[tuple[IntangibleAssetStatus, IntangibleAssetStatus], str] = {
    (IntangibleAssetStatus.PENDING_ACTIVATION, IntangibleAssetStatus.ACTIVE): "finance_manager",
    (IntangibleAssetStatus.ACTIVE, IntangibleAssetStatus.DISPOSED): "finance_manager",
    (IntangibleAssetStatus.ACTIVE, IntangibleAssetStatus.IMPAIRED): "accountant",
    (IntangibleAssetStatus.IMPAIRED, IntangibleAssetStatus.ACTIVE): "finance_manager",
}


def validate_status_transition(
    current_status: IntangibleAssetStatus,
    new_status: IntangibleAssetStatus,
    user_role: str = "user",
) -> InvariantResult:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        return InvariantResult.failure(
            f"Status transition from {current_status.display_name()} to {new_status.display_name()} is not allowed"
        )
    required_role = TRANSITION_ROLE_REQUIREMENTS.get((current_status, new_status))
    # Gabungkan kondisi bersarang menjadi satu dengan 'and'
    if required_role and user_role != required_role and user_role not in ("admin", "super_admin"):
        return InvariantResult.failure(
            f"Status transition requires role '{required_role}'. User has role '{user_role}'"
        )
    return InvariantResult.success()


# ============================================================================
# Intangible Asset Invariant Enforcer (Async)
# ============================================================================


class IntangibleAssetInvariantEnforcer:
    """Enforcer untuk semua invariant intangible asset."""

    def __init__(
        self,
        get_existing_codes: Callable[[], set[str]] | None = None,
    ):
        self._get_existing_codes = get_existing_codes or (lambda: set())
        self._invariants = IntangibleAssetInvariants()

    async def enforce_asset_create(self, asset: IntangibleAssetEntity) -> InvariantResult:
        result = InvariantResult()
        result.merge(self._invariants.validate_asset_code(asset.asset_code))
        result.merge(self._invariants.validate_asset_name(asset.asset_name))
        result.merge(self._invariants.validate_asset_type(asset.asset_type))
        result.merge(self._invariants.validate_asset_status(asset.status))
        result.merge(self._invariants.validate_acquisition_date(asset.acquisition_date))
        result.merge(self._invariants.validate_cost(asset.cost))
        result.merge(self._invariants.validate_residual_value(asset.residual_value, asset.cost))
        result.merge(
            self._invariants.validate_useful_life(
                asset.useful_life_years, asset.asset_type, asset.amortization_method
            )
        )
        result.merge(
            self._invariants.validate_amortization_method(
                asset.amortization_method, asset.asset_type, asset.useful_life_years
            )
        )
        result.merge(
            self._invariants.validate_accumulated_amortization(
                asset.accumulated_amortization, asset.cost, asset.residual_value
            )
        )
        result.merge(
            self._invariants.validate_nbv(asset.nbv, asset.cost, asset.accumulated_amortization)
        )
        result.merge(self._invariants.validate_currency(asset.currency))
        result.merge(
            self._invariants.validate_expiry_date(asset.expiry_date, asset.acquisition_date)
        )

        # remove await because the provider is synchronous
        existing_codes = self._get_existing_codes()
        result.merge(self._invariants.validate_asset_code_unique(asset.asset_code, existing_codes))
        return result

    async def enforce_asset_update(self, asset: IntangibleAssetEntity) -> InvariantResult:
        result = InvariantResult()
        result.merge(self._invariants.validate_asset_code(asset.asset_code))
        result.merge(self._invariants.validate_asset_name(asset.asset_name))
        result.merge(self._invariants.validate_asset_type(asset.asset_type))
        result.merge(self._invariants.validate_asset_status(asset.status))
        result.merge(self._invariants.validate_cost(asset.cost))
        result.merge(self._invariants.validate_residual_value(asset.residual_value, asset.cost))
        result.merge(
            self._invariants.validate_useful_life(
                asset.useful_life_years, asset.asset_type, asset.amortization_method
            )
        )
        result.merge(
            self._invariants.validate_amortization_method(
                asset.amortization_method, asset.asset_type, asset.useful_life_years
            )
        )
        result.merge(
            self._invariants.validate_accumulated_amortization(
                asset.accumulated_amortization, asset.cost, asset.residual_value
            )
        )
        result.merge(
            self._invariants.validate_nbv(asset.nbv, asset.cost, asset.accumulated_amortization)
        )
        result.merge(self._invariants.validate_currency(asset.currency))
        result.merge(
            self._invariants.validate_expiry_date(asset.expiry_date, asset.acquisition_date)
        )
        return result

    async def enforce_amortization(
        self, asset: IntangibleAssetEntity, amount: Decimal
    ) -> InvariantResult:
        result = self._invariants.validate_amortization_allowed(asset, amount)
        if result.is_valid:
            result.merge(
                self._invariants.validate_accumulated_amortization(
                    asset.accumulated_amortization + amount, asset.cost, asset.residual_value
                )
            )
        return result

    async def enforce_impairment(
        self, asset: IntangibleAssetEntity, impairment_loss: Decimal
    ) -> InvariantResult:
        return self._invariants.validate_impairment_allowed(asset, impairment_loss)

    async def enforce_disposal(self, asset: IntangibleAssetEntity) -> InvariantResult:
        return self._invariants.validate_disposal_allowed(asset)

    async def enforce_status_transition(
        self,
        current_status: IntangibleAssetStatus,
        new_status: IntangibleAssetStatus,
        user_role: str = "user",
    ) -> InvariantResult:
        return validate_status_transition(current_status, new_status, user_role)


# ============================================================================
# Synchronous Validator for Service Layer
# ============================================================================


class IntangibleAssetInvariantsValidator:
    """Validator sinkron untuk digunakan oleh service layer."""

    @staticmethod
    def validate_asset_cost(asset: IntangibleAssetEntity) -> None:
        if asset.cost <= 0:
            raise ValueError(f"Acquisition cost must be positive: {asset.cost}")
        if asset.residual_value < 0:
            raise ValueError(f"Residual value cannot be negative: {asset.residual_value}")
        if asset.residual_value > asset.cost:
            raise ValueError(
                f"Residual value {asset.residual_value} cannot exceed cost {asset.cost}"
            )

    @staticmethod
    def validate_useful_life(asset: IntangibleAssetEntity) -> None:
        # Gabungkan kondisi bersarang menjadi satu dengan 'and'
        if (
            asset.asset_type != IntangibleAssetType.GOODWILL
            and not asset.has_indefinite_life
            and asset.useful_life_years <= 0
        ):
            raise ValueError(f"Useful life must be positive: {asset.useful_life_years}")

    @staticmethod
    def validate_amortization_method(asset: IntangibleAssetEntity) -> None:
        valid_methods = [m.value for m in AmortizationMethod]
        if asset.amortization_method.value not in valid_methods:
            raise ValueError(f"Invalid amortization method: {asset.amortization_method}")

    @staticmethod
    def validate_amortization_amount(asset: IntangibleAssetEntity, amount: Decimal) -> None:
        if amount < 0:
            raise ValueError(f"Amortization amount cannot be negative: {amount}")
        if asset.has_indefinite_life:
            raise ValueError(
                f"Asset {asset.asset_code} has indefinite life and cannot be amortized"
            )
        if amount > asset.remaining_amortizable:
            raise ValueError(
                f"Amortization amount {amount} exceeds remaining amortizable {asset.remaining_amortizable}"
            )

    @staticmethod
    def validate_asset_code_unique(code: str, existing_codes: set[str]) -> None:
        if code in existing_codes:
            raise ValueError(f"Asset code '{code}' already exists")

    @staticmethod
    def validate_impairment(asset: IntangibleAssetEntity, impairment_loss: Decimal) -> None:
        if impairment_loss <= 0:
            raise ValueError(f"Impairment loss must be positive: {impairment_loss}")
        if impairment_loss > asset.nbv:
            raise ValueError(f"Impairment loss {impairment_loss} exceeds NBV {asset.nbv}")
        if not asset.status.can_impair():
            raise ValueError(f"Asset in status {asset.status.display_name()} cannot be impaired")

    @staticmethod
    def validate_disposal(asset: IntangibleAssetEntity) -> None:
        if asset.status == IntangibleAssetStatus.DISPOSED:
            raise ValueError(f"Asset {asset.asset_code} is already disposed")

    @staticmethod
    def validate_nbv(asset: IntangibleAssetEntity) -> None:
        if asset.nbv < 0:
            raise ValueError(f"NBV cannot be negative: {asset.nbv}")


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "IntangibleAssetInvariantEnforcer",
    "IntangibleAssetInvariants",
    "IntangibleAssetInvariantsValidator",
    "InvariantResult",
    "validate_currency",
    "validate_date_not_future",
    "validate_date_sequence",
    "validate_non_negative_decimal",
    "validate_positive_decimal",
    "validate_status_transition",
    "validate_string_not_empty",
    "validate_version",
]
