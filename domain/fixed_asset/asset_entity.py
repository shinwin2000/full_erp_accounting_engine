#!/usr/bin/env python3
"""
Module: asset_entity.py

Layer: Domain / Fixed Asset

Responsibility:
    Entity for fixed asset (aset tetap). Immutable by replacement.
    Represents a tangible or intangible asset with acquisition cost,
    accumulated depreciation, net book value, useful life, depreciation method,
    and status (active, fully depreciated, disposed, idle, under construction).

Business rules:
    - Asset code must be unique across legal entity.
    - Acquisition cost must be positive.
    - Salvage value must be >= 0 and <= cost.
    - Useful life must be positive (years).
    - Accumulated depreciation cannot exceed cost - salvage value.
    - Net book value = cost - accumulated depreciation.
    - Depreciable amount = cost - salvage value.
    - Asset cannot be disposed if already disposed.
    - Revaluation can only be applied to active assets.
    - Impairment reduces net book value and increases accumulated impairment.
    - Version increments on every change (optimistic locking).

Dependencies:
    - Python standard library (uuid, datetime, decimal, logging)
    - domain.shared_value_objects.money_vo (Money) - optional

Audit:
    Every state change should be logged; domain events emitted separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# [FIX] ADDED: DepreciationMethod Enum
# ============================================================================


class DepreciationMethod(Enum):
    """Enum for acceptable depreciation methods."""

    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    SUM_OF_YEARS = "sum_of_years"

    def display_name(self) -> str:
        names = {
            DepreciationMethod.STRAIGHT_LINE: "Garis Lurus",
            DepreciationMethod.DECLINING_BALANCE: "Saldo Menurun",
            DepreciationMethod.SUM_OF_YEARS: "Jumlah Angka Tahun",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> DepreciationMethod | None:
        for method in cls:
            if method.value == value.lower():
                return method
        return None


# ============================================================================
# Enums (only those that do NOT depend on depreciation_schedule_engine)
# ============================================================================


class AssetStatus(Enum):
    """Status of a fixed asset."""

    ACTIVE = "active"
    FULLY_DEPRECIATED = "fully_depreciated"
    DISPOSED = "disposed"
    UNDER_CONSTRUCTION = "construction"
    IDLE = "idle"
    IMPAIRED = "impaired"

    def can_depreciate(self) -> bool:
        return self in (AssetStatus.ACTIVE, AssetStatus.IMPAIRED, AssetStatus.IDLE)

    def can_revalue(self) -> bool:
        return self in (AssetStatus.ACTIVE, AssetStatus.IMPAIRED)

    def can_transfer(self) -> bool:
        return self == AssetStatus.ACTIVE

    def display_name(self) -> str:
        names = {
            AssetStatus.ACTIVE: "Aktif",
            AssetStatus.FULLY_DEPRECIATED: "Habis Depresiasi",
            AssetStatus.DISPOSED: "Dihapuskan",
            AssetStatus.UNDER_CONSTRUCTION: "Dalam Konstruksi",
            AssetStatus.IDLE: "Menganggur",
            AssetStatus.IMPAIRED: "Penurunan Nilai",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> AssetStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


class AssetType(Enum):
    """Type of fixed asset."""

    TANGIBLE = "tangible"
    INTANGIBLE = "intangible"
    LAND = "land"

    def is_depreciable(self) -> bool:
        return self != AssetType.LAND

    def display_name(self) -> str:
        names = {
            AssetType.TANGIBLE: "Berwujud",
            AssetType.INTANGIBLE: "Tidak Berwujud",
            AssetType.LAND: "Tanah",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> AssetType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


class AssetCategory(Enum):
    """Category of fixed asset for reporting."""

    BUILDING = "building"
    MACHINERY = "machinery"
    VEHICLE = "vehicle"
    FURNITURE = "furniture"
    COMPUTER = "computer"
    LEASEHOLD = "leasehold"
    LAND = "land"
    OTHER = "other"
    SOFTWARE = "software"
    PATENT = "patent"
    GOODWILL = "goodwill"

    def is_tangible(self) -> bool:
        return self in (
            AssetCategory.BUILDING,
            AssetCategory.MACHINERY,
            AssetCategory.VEHICLE,
            AssetCategory.FURNITURE,
            AssetCategory.COMPUTER,
            AssetCategory.LEASEHOLD,
            AssetCategory.LAND,
            AssetCategory.OTHER,
        )

    def display_name(self) -> str:
        names = {
            AssetCategory.BUILDING: "Gedung",
            AssetCategory.MACHINERY: "Mesin",
            AssetCategory.VEHICLE: "Kendaraan",
            AssetCategory.FURNITURE: "Perabotan",
            AssetCategory.COMPUTER: "Komputer",
            AssetCategory.LEASEHOLD: "Bangunan Sewa",
            AssetCategory.LAND: "Tanah",
            AssetCategory.OTHER: "Lainnya",
            AssetCategory.SOFTWARE: "Perangkat Lunak",
            AssetCategory.PATENT: "Hak Paten",
            AssetCategory.GOODWILL: "Goodwill",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> AssetCategory | None:
        for c in cls:
            if c.value == value.lower():
                return c
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class FixedAssetError(ValueError):
    pass


class InvalidAssetCodeError(FixedAssetError):
    pass


class InvalidCostError(FixedAssetError):
    pass


class InvalidUsefulLifeError(FixedAssetError):
    pass


class InvalidDepreciationError(FixedAssetError):
    pass


class AssetAlreadyDisposedError(FixedAssetError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_asset_code(code: str) -> str:
    if not code or not isinstance(code, str):
        raise InvalidAssetCodeError("Asset code must be a non-empty string")
    cleaned = code.strip()
    if len(cleaned) < 2:
        raise InvalidAssetCodeError("Asset code must be at least 2 characters")
    if len(cleaned) > 30:
        raise InvalidAssetCodeError("Asset code must not exceed 30 characters")
    if not re.match(r"^[A-Za-z0-9\-_/]+$", cleaned):
        raise InvalidAssetCodeError(
            "Asset code can only contain letters, numbers, hyphens, underscores, and slashes"
        )
    return cleaned


def _validate_asset_name(name: str) -> str:
    if not name or not isinstance(name, str):
        raise FixedAssetError("Asset name must be a non-empty string")
    cleaned = name.strip()
    if len(cleaned) < 2:
        raise FixedAssetError("Asset name must be at least 2 characters")
    if len(cleaned) > 200:
        raise FixedAssetError("Asset name must not exceed 200 characters")
    return cleaned


def _validate_cost(cost: Decimal) -> Decimal:
    if not isinstance(cost, Decimal):
        try:
            cost = Decimal(str(cost))
        except Exception:
            raise InvalidCostError(f"Invalid cost type: {type(cost)}")
    if cost <= 0:
        raise InvalidCostError(f"Acquisition cost must be positive: {cost}")
    return cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_salvage_value(salvage: Decimal, cost: Decimal) -> Decimal:
    if not isinstance(salvage, Decimal):
        try:
            salvage = Decimal(str(salvage))
        except Exception:
            raise FixedAssetError(f"Invalid salvage value type: {type(salvage)}")
    if salvage < 0:
        raise FixedAssetError(f"Salvage value cannot be negative: {salvage}")
    if salvage > cost:
        raise FixedAssetError(f"Salvage value {salvage} exceeds cost {cost}")
    return salvage.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_useful_life(years: int) -> int:
    if not isinstance(years, int):
        try:
            years = int(years)
        except Exception:
            raise InvalidUsefulLifeError(f"Useful life must be integer, got {type(years)}")
    if years <= 0:
        raise InvalidUsefulLifeError(f"Useful life must be positive: {years}")
    if years > 100:
        raise InvalidUsefulLifeError(f"Useful life exceeds maximum 100 years: {years}")
    return years


def _validate_accumulated_depreciation(
    acc_dep: Decimal, cost: Decimal, salvage: Decimal
) -> Decimal:
    if not isinstance(acc_dep, Decimal):
        try:
            acc_dep = Decimal(str(acc_dep))
        except Exception:
            raise FixedAssetError(f"Invalid accumulated depreciation type: {type(acc_dep)}")
    if acc_dep < 0:
        raise FixedAssetError(f"Accumulated depreciation cannot be negative: {acc_dep}")
    max_dep = cost - salvage
    if acc_dep > max_dep and acc_dep - max_dep > Decimal("0.01"):
        raise FixedAssetError(
            f"Accumulated depreciation {acc_dep} exceeds depreciable amount {max_dep}"
        )
    return acc_dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_impairment(impairment: Decimal | None, nbv: Decimal) -> Decimal | None:
    if impairment is None:
        return Decimal("0")
    if not isinstance(impairment, Decimal):
        try:
            impairment = Decimal(str(impairment))
        except Exception:
            raise FixedAssetError(f"Invalid impairment type: {type(impairment)}")
    if impairment < 0:
        raise FixedAssetError(f"Accumulated impairment cannot be negative: {impairment}")
    if impairment > nbv:
        raise FixedAssetError(f"Accumulated impairment {impairment} exceeds NBV {nbv}")
    return impairment.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_revaluation_surplus(surplus: Decimal | None) -> Decimal | None:
    if surplus is None:
        return Decimal("0")
    if not isinstance(surplus, Decimal):
        try:
            surplus = Decimal(str(surplus))
        except Exception:
            raise FixedAssetError(f"Invalid revaluation surplus type: {type(surplus)}")
    if surplus < 0:
        raise FixedAssetError(f"Revaluation surplus cannot be negative: {surplus}")
    return surplus.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_currency(currency: str) -> str:
    if not currency or not isinstance(currency, str):
        raise FixedAssetError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise FixedAssetError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise FixedAssetError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


# ============================================================================
# Entity: FixedAsset (depreciation_method stored as string)
# ============================================================================


@dataclass
class FixedAsset:
    """
    Entity for fixed asset. depreciation_method is stored as string
    (e.g., "straight_line") to avoid circular import with DepreciationMethod enum.
    """

    id: UUID
    legal_entity_id: UUID
    asset_code: str
    name: str
    asset_type: AssetType
    status: AssetStatus
    acquisition_date: date
    acquisition_cost: Decimal
    salvage_value: Decimal
    useful_life_years: int
    depreciation_method: str  # string representation of DepreciationMethod value

    accumulated_depreciation: Decimal
    net_book_value: Decimal

    description: str | None = None
    location: str | None = None
    responsible_person: UUID | None = None
    supplier_id: UUID | None = None
    po_number: str | None = None
    category: str | None = None
    currency: str = "IDR"
    disposed_at: date | None = None
    disposed_reason: str | None = None
    last_depreciation_date: date | None = None
    accumulated_impairment: Decimal = Decimal("0")
    revaluation_surplus: Decimal = Decimal("0")
    created_by: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    version: int = 1

    def __post_init__(self) -> None:
        # Validate asset_code
        normalized_code = _validate_asset_code(self.asset_code)
        if normalized_code != self.asset_code:
            object.__setattr__(self, "asset_code", normalized_code)

        # Validate name
        normalized_name = _validate_asset_name(self.name)
        if normalized_name != self.name:
            object.__setattr__(self, "name", normalized_name)

        # Validate asset_type
        if not isinstance(self.asset_type, AssetType):
            raise FixedAssetError(f"Invalid asset_type: {self.asset_type}")

        # Validate status
        if not isinstance(self.status, AssetStatus):
            raise FixedAssetError(f"Invalid status: {self.status}")

        # Validate dates
        if self.acquisition_date > date.today():
            raise FixedAssetError(
                f"Acquisition date {self.acquisition_date} cannot be in the future"
            )
        if self.disposed_at and self.disposed_at < self.acquisition_date:
            raise FixedAssetError(
                f"Disposal date {self.disposed_at} cannot be before acquisition date"
            )

        # Validate cost
        normalized_cost = _validate_cost(self.acquisition_cost)
        if normalized_cost != self.acquisition_cost:
            object.__setattr__(self, "acquisition_cost", normalized_cost)

        # Validate salvage value
        normalized_salvage = _validate_salvage_value(self.salvage_value, self.acquisition_cost)
        if normalized_salvage != self.salvage_value:
            object.__setattr__(self, "salvage_value", normalized_salvage)

        # Validate useful life (only if asset is depreciable)
        if self.asset_type.is_depreciable():
            normalized_life = _validate_useful_life(self.useful_life_years)
            if normalized_life != self.useful_life_years:
                object.__setattr__(self, "useful_life_years", normalized_life)
        else:
            if self.useful_life_years != 0:
                object.__setattr__(self, "useful_life_years", 0)

        # Validate accumulated depreciation
        normalized_acc_dep = _validate_accumulated_depreciation(
            self.accumulated_depreciation, self.acquisition_cost, self.salvage_value
        )
        if normalized_acc_dep != self.accumulated_depreciation:
            object.__setattr__(self, "accumulated_depreciation", normalized_acc_dep)

        # Validate accumulated impairment
        nbv_before_impairment = self.acquisition_cost - self.accumulated_depreciation
        normalized_impairment = _validate_impairment(
            self.accumulated_impairment, nbv_before_impairment
        )
        if normalized_impairment != self.accumulated_impairment:
            object.__setattr__(self, "accumulated_impairment", normalized_impairment)

        # Validate net book value
        expected_nbv = (
            self.acquisition_cost - self.accumulated_depreciation - self.accumulated_impairment
        )
        if abs(self.net_book_value - expected_nbv) > Decimal("0.01"):
            raise FixedAssetError(
                f"Net book value mismatch: expected {expected_nbv}, got {self.net_book_value}"
            )
        if self.net_book_value < 0:
            raise FixedAssetError(f"Net book value cannot be negative: {self.net_book_value}")

        # Validate revaluation surplus
        normalized_surplus = _validate_revaluation_surplus(self.revaluation_surplus)
        if normalized_surplus != self.revaluation_surplus:
            object.__setattr__(self, "revaluation_surplus", normalized_surplus)

        # Validate currency
        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        # Validate last_depreciation_date
        if self.last_depreciation_date and self.last_depreciation_date > date.today():
            raise FixedAssetError(
                f"Last depreciation date {self.last_depreciation_date} cannot be in the future"
            )

        # Validate status consistency
        if self.status == AssetStatus.DISPOSED and self.disposed_at is None:
            raise FixedAssetError("Disposed asset must have disposed_at date")
        if self.status != AssetStatus.DISPOSED and self.disposed_at is not None:
            raise FixedAssetError("Non-disposed asset cannot have disposed_at")
        if (
            self.status == AssetStatus.FULLY_DEPRECIATED
            and self.accumulated_depreciation < self.depreciable_amount
        ):
            raise FixedAssetError(
                "Fully depreciated asset but accumulated depreciation less than depreciable amount"
            )

        # Validate timestamps UTC
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at and self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise FixedAssetError("Version must be >= 1")

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def depreciable_amount(self) -> Decimal:
        return self.acquisition_cost - self.salvage_value

    @property
    def remaining_depreciable_amount(self) -> Decimal:
        return self.depreciable_amount - self.accumulated_depreciation

    @property
    def is_fully_depreciated(self) -> bool:
        return self.remaining_depreciable_amount <= Decimal("0.01")

    @property
    def is_disposed(self) -> bool:
        return self.status == AssetStatus.DISPOSED

    @property
    def is_active(self) -> bool:
        return self.status == AssetStatus.ACTIVE

    @property
    def is_depreciable(self) -> bool:
        return self.asset_type.is_depreciable()

    @property
    def age_in_years(self, as_of: date | None = None) -> float:
        as_of = as_of or date.today()
        if as_of < self.acquisition_date:
            return 0.0
        delta = as_of - self.acquisition_date
        return delta.days / 365.25

    @property
    def remaining_useful_life(self) -> float:
        if self.is_fully_depreciated or not self.is_depreciable:
            return 0.0
        proportion_depreciated = (
            self.accumulated_depreciation / self.depreciable_amount
            if self.depreciable_amount > 0
            else 0
        )
        return max(0, self.useful_life_years * (1 - proportion_depreciated))

    @property
    def book_value_after_revaluation(self) -> Decimal:
        return self.net_book_value + self.revaluation_surplus

    # [FIX] Added helper method to get DepreciationMethod enum
    def get_depreciation_method_enum(self) -> DepreciationMethod | None:
        """Convert the stored string to a DepreciationMethod enum."""
        return DepreciationMethod.from_string(self.depreciation_method)

    # ------------------------------------------------------------------------
    # Factory Methods (no import of DepreciationMethod)
    # ------------------------------------------------------------------------

    @classmethod
    def acquire(
        cls,
        legal_entity_id: UUID,
        asset_code: str,
        name: str,
        acquisition_cost: Decimal,
        acquisition_date: date,
        asset_type: AssetType = AssetType.TANGIBLE,
        salvage_value: Decimal = Decimal("0"),
        useful_life_years: int = 5,
        depreciation_method: str | Any = "straight_line",  # accept string
        currency: str = "IDR",
        created_by: UUID = None,
        **kwargs,
    ) -> FixedAsset:
        """
        Create a new fixed asset at acquisition.
        depreciation_method can be a string (e.g., "straight_line") or any object.
        """
        # Convert to string if not already
        if hasattr(depreciation_method, "value"):
            method_str = depreciation_method.value
        else:
            method_str = str(depreciation_method).lower()

        now = datetime.now(UTC)
        asset_id = uuid4()
        created_by_uuid = created_by or uuid4()
        return cls(
            id=asset_id,
            legal_entity_id=legal_entity_id,
            asset_code=asset_code,
            name=name,
            asset_type=asset_type,
            status=AssetStatus.ACTIVE,
            acquisition_date=acquisition_date,
            acquisition_cost=acquisition_cost,
            salvage_value=salvage_value,
            useful_life_years=useful_life_years,
            depreciation_method=method_str,
            accumulated_depreciation=Decimal("0"),
            net_book_value=acquisition_cost,
            currency=currency,
            created_by=created_by_uuid,
            created_at=now,
            updated_at=now,
            updated_by=created_by_uuid,
            version=1,
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FixedAsset:
        """Reconstruct from dictionary. depreciation_method is taken as string."""
        asset_type = AssetType.from_string(data["asset_type"])
        if asset_type is None:
            raise FixedAssetError(f"Invalid asset_type: {data['asset_type']}")
        status = AssetStatus.from_string(data["status"])
        if status is None:
            raise FixedAssetError(f"Invalid status: {data['status']}")

        def parse_date(key: str) -> date | None:
            val = data.get(key)
            if val is None:
                return None
            if isinstance(val, str):
                return date.fromisoformat(val)
            return val

        def parse_datetime(key: str) -> datetime | None:
            val = data.get(key)
            if val is None:
                return None
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return val

        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            legal_entity_id=UUID(data["legal_entity_id"])
            if isinstance(data["legal_entity_id"], str)
            else data["legal_entity_id"],
            asset_code=data["asset_code"],
            name=data["name"],
            description=data.get("description"),
            asset_type=asset_type,
            status=status,
            acquisition_date=parse_date("acquisition_date"),
            acquisition_cost=Decimal(str(data["acquisition_cost"])),
            salvage_value=Decimal(str(data.get("salvage_value", 0))),
            useful_life_years=data.get("useful_life_years", 0),
            depreciation_method=data.get("depreciation_method", "straight_line"),
            accumulated_depreciation=Decimal(str(data.get("accumulated_depreciation", 0))),
            net_book_value=Decimal(str(data.get("net_book_value", data["acquisition_cost"]))),
            location=data.get("location"),
            responsible_person=UUID(data["responsible_person"])
            if data.get("responsible_person")
            else None,
            supplier_id=UUID(data["supplier_id"]) if data.get("supplier_id") else None,
            po_number=data.get("po_number"),
            category=data.get("category"),
            currency=data.get("currency", "IDR"),
            disposed_at=parse_date("disposed_at"),
            disposed_reason=data.get("disposed_reason"),
            last_depreciation_date=parse_date("last_depreciation_date"),
            accumulated_impairment=Decimal(str(data.get("accumulated_impairment", 0))),
            revaluation_surplus=Decimal(str(data.get("revaluation_surplus", 0))),
            created_by=UUID(data["created_by"])
            if isinstance(data["created_by"], str)
            else data["created_by"],
            created_at=parse_datetime("created_at") or datetime.now(UTC),
            updated_at=parse_datetime("updated_at"),
            updated_by=UUID(data["updated_by"]) if data.get("updated_by") else None,
            version=data.get("version", 1),
        )

    # ------------------------------------------------------------------------
    # Business Logic
    # ------------------------------------------------------------------------

    def record_depreciation(self, period: str, amount: Decimal, posted_by: UUID) -> FixedAsset:
        if self.is_disposed:
            raise AssetAlreadyDisposedError(
                f"Cannot record depreciation for disposed asset {self.asset_code}"
            )
        if not self.is_depreciable:
            raise FixedAssetError(f"Asset {self.asset_code} is not depreciable")
        if not self.status.can_depreciate():
            raise FixedAssetError(
                f"Cannot record depreciation for asset in status {self.status.value}"
            )
        if amount <= 0:
            raise InvalidDepreciationError(f"Depreciation amount must be positive: {amount}")

        new_accumulated = self.accumulated_depreciation + amount
        new_nbv = self.acquisition_cost - new_accumulated - self.accumulated_impairment
        new_status = self.status
        if self.is_fully_depreciated or new_accumulated >= self.depreciable_amount - Decimal(
            "0.01"
        ):
            new_status = AssetStatus.FULLY_DEPRECIATED

        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=self.description,
            asset_type=self.asset_type,
            status=new_status,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=new_accumulated,
            net_book_value=new_nbv,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=self.disposed_at,
            disposed_reason=self.disposed_reason,
            last_depreciation_date=date.today(),
            accumulated_impairment=self.accumulated_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=posted_by,
            version=self.version + 1,
        )

    def apply_revaluation(self, new_value: Decimal, method: str, approved_by: UUID) -> FixedAsset:
        if not self.status.can_revalue():
            raise FixedAssetError(f"Cannot revalue asset in status {self.status.value}")
        if new_value <= 0:
            raise FixedAssetError(f"Revaluation value must be positive: {new_value}")

        old_nbv = self.net_book_value
        surplus = new_value - old_nbv
        if surplus < 0:
            new_impairment = self.accumulated_impairment + abs(surplus)
            new_surplus = Decimal("0")
            new_cost = self.acquisition_cost
        else:
            new_surplus = self.revaluation_surplus + surplus
            new_impairment = self.accumulated_impairment
            new_cost = self.acquisition_cost + surplus

        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=self.description,
            asset_type=self.asset_type,
            status=self.status,
            acquisition_date=self.acquisition_date,
            acquisition_cost=new_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=new_value,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=self.disposed_at,
            disposed_reason=self.disposed_reason,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=new_impairment,
            revaluation_surplus=new_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=approved_by,
            version=self.version + 1,
        )

    def recognize_impairment(
        self, impairment_loss: Decimal, tested_by: UUID, indicators: list[str]
    ) -> FixedAsset:
        if impairment_loss <= 0:
            raise FixedAssetError(f"Impairment loss must be positive: {impairment_loss}")
        if impairment_loss > self.net_book_value:
            raise FixedAssetError(
                f"Impairment loss {impairment_loss} exceeds NBV {self.net_book_value}"
            )

        new_impairment = self.accumulated_impairment + impairment_loss
        new_nbv = self.net_book_value - impairment_loss
        new_status = self.status
        if new_nbv <= self.salvage_value:
            new_status = AssetStatus.IMPAIRED

        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=self.description,
            asset_type=self.asset_type,
            status=new_status,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=new_nbv,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=self.disposed_at,
            disposed_reason=self.disposed_reason,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=new_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=tested_by,
            version=self.version + 1,
        )

    def dispose(
        self,
        disposal_date: date,
        disposal_type: str,
        proceeds: Decimal,
        reason: str,
        disposed_by: UUID,
    ) -> FixedAsset:
        if self.is_disposed:
            raise AssetAlreadyDisposedError(f"Asset {self.asset_code} is already disposed")
        if disposal_date < self.acquisition_date:
            raise FixedAssetError(
                f"Disposal date {disposal_date} cannot be before acquisition date"
            )
        if proceeds < 0:
            raise FixedAssetError(f"Proceeds cannot be negative: {proceeds}")

        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=self.description,
            asset_type=self.asset_type,
            status=AssetStatus.DISPOSED,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=self.net_book_value,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=disposal_date,
            disposed_reason=f"{disposal_type}: {reason}" if reason else disposal_type,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=self.accumulated_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=disposed_by,
            version=self.version + 1,
        )

    def transfer(self, new_location: str, transferred_by: UUID) -> FixedAsset:
        if not self.status.can_transfer():
            raise FixedAssetError(f"Cannot transfer asset in status {self.status.value}")
        if not new_location or len(new_location.strip()) < 2:
            raise FixedAssetError("New location must be provided")

        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=self.description,
            asset_type=self.asset_type,
            status=self.status,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=self.net_book_value,
            location=new_location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=self.disposed_at,
            disposed_reason=self.disposed_reason,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=self.accumulated_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=transferred_by,
            version=self.version + 1,
        )

    def change_responsible_person(
        self, new_responsible: UUID | None, changed_by: UUID
    ) -> FixedAsset:
        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=self.description,
            asset_type=self.asset_type,
            status=self.status,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=self.net_book_value,
            location=self.location,
            responsible_person=new_responsible,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=self.disposed_at,
            disposed_reason=self.disposed_reason,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=self.accumulated_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=changed_by,
            version=self.version + 1,
        )

    def update_name(self, new_name: str, updated_by: UUID) -> FixedAsset:
        normalized_name = _validate_asset_name(new_name)
        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=normalized_name,
            description=self.description,
            asset_type=self.asset_type,
            status=self.status,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=self.net_book_value,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=self.disposed_at,
            disposed_reason=self.disposed_reason,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=self.accumulated_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_description(self, new_description: str | None, updated_by: UUID) -> FixedAsset:
        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=new_description,
            asset_type=self.asset_type,
            status=self.status,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=self.net_book_value,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=self.disposed_at,
            disposed_reason=self.disposed_reason,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=self.accumulated_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def calculate_gain_loss_on_disposal(self, proceeds: Decimal) -> Decimal:
        return proceeds - self.net_book_value

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "asset_code": self.asset_code,
            "name": self.name,
            "description": self.description,
            "asset_type": self.asset_type.value,
            "asset_type_display": self.asset_type.display_name(),
            "status": self.status.value,
            "status_display": self.status.display_name(),
            "acquisition_date": self.acquisition_date.isoformat(),
            "acquisition_cost": str(self.acquisition_cost),
            "salvage_value": str(self.salvage_value),
            "useful_life_years": self.useful_life_years,
            "depreciation_method": self.depreciation_method,
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "net_book_value": str(self.net_book_value),
            "depreciable_amount": str(self.depreciable_amount),
            "remaining_depreciable": str(self.remaining_depreciable_amount),
            "is_fully_depreciated": self.is_fully_depreciated,
            "location": self.location,
            "responsible_person": str(self.responsible_person) if self.responsible_person else None,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "po_number": self.po_number,
            "category": self.category,
            "currency": self.currency,
            "disposed_at": self.disposed_at.isoformat() if self.disposed_at else None,
            "disposed_reason": self.disposed_reason,
            "last_depreciation_date": self.last_depreciation_date.isoformat()
            if self.last_depreciation_date
            else None,
            "accumulated_impairment": str(self.accumulated_impairment),
            "revaluation_surplus": str(self.revaluation_surplus),
            "book_value_after_revaluation": str(self.book_value_after_revaluation),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": str(self.created_by),
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "version": self.version,
        }

    def to_db_record(self) -> dict[str, Any]:
        return {
            "asset_id": self.id,
            "legal_entity_id": self.legal_entity_id,
            "asset_code": self.asset_code,
            "name": self.name,
            "description": self.description,
            "asset_type": self.asset_type.value,
            "status": self.status.value,
            "acquisition_date": self.acquisition_date,
            "acquisition_cost": self.acquisition_cost,
            "salvage_value": self.salvage_value,
            "useful_life_years": self.useful_life_years,
            "depreciation_method": self.depreciation_method,
            "accumulated_depreciation": self.accumulated_depreciation,
            "net_book_value": self.net_book_value,
            "location": self.location,
            "responsible_person": self.responsible_person,
            "supplier_id": self.supplier_id,
            "po_number": self.po_number,
            "category": self.category,
            "currency": self.currency,
            "disposed_at": self.disposed_at,
            "disposed_reason": self.disposed_reason,
            "last_depreciation_date": self.last_depreciation_date,
            "accumulated_impairment": self.accumulated_impairment,
            "revaluation_surplus": self.revaluation_surplus,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
            "version": self.version,
        }

    def __str__(self) -> str:
        return f"{self.asset_code} - {self.name} (NBV: {self.net_book_value} {self.currency})"

    def __repr__(self) -> str:
        return f"FixedAsset({self.asset_code}, status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FixedAsset):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    # ==================== TAMBAHAN METHOD ENTITY DASAR ====================
    # Tambahkan kode ini ke dalam class FixedAsset di asset_entity.py

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: UUID) -> FixedAsset:
        """Record asset creation (acquisition)."""
        self._record_audit("CREATE", str(created_by), {"asset_code": self.asset_code})
        return self

    def update(self, updated_by: UUID, **kwargs) -> FixedAsset:
        """Update asset attributes."""
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_asset = self.from_dict(data)
        new_asset._record_audit("UPDATE", str(updated_by), {"changes": kwargs})
        return new_asset

    def delete(self, deleted_by: UUID, reason: str | None = None) -> FixedAsset:
        """Soft delete asset (dispose)."""
        if self.is_disposed:
            raise FixedAssetError(f"Asset {self.asset_code} is already disposed")
        return self.dispose(
            date.today(), "deletion", Decimal("0"), reason or "Deleted by user", deleted_by
        )

    def restore(self, restored_by: UUID) -> FixedAsset:
        """Restore a disposed asset."""
        if not self.is_disposed:
            raise FixedAssetError(f"Asset {self.asset_code} is not disposed")
        # Restore to previous status before disposal
        now = datetime.now(UTC)
        return FixedAsset(
            id=self.id,
            legal_entity_id=self.legal_entity_id,
            asset_code=self.asset_code,
            name=self.name,
            description=self.description,
            asset_type=self.asset_type,
            status=AssetStatus.ACTIVE,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=self.accumulated_depreciation,
            net_book_value=self.net_book_value,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=None,
            disposed_reason=None,
            last_depreciation_date=self.last_depreciation_date,
            accumulated_impairment=self.accumulated_impairment,
            revaluation_surplus=self.revaluation_surplus,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
            updated_by=restored_by,
            version=self.version + 1,
        )

    def activate(self, activated_by: UUID) -> FixedAsset:
        """Activate asset (if under construction or idle)."""
        if self.status == AssetStatus.ACTIVE:
            return self
        if self.status not in (AssetStatus.UNDER_CONSTRUCTION, AssetStatus.IDLE):
            raise FixedAssetError(f"Cannot activate asset in status {self.status.value}")
        now = datetime.now(UTC)
        return FixedAsset(
            **{
                **self.__dict__,
                "status": AssetStatus.ACTIVE,
                "updated_at": now,
                "updated_by": activated_by,
                "version": self.version + 1,
            }
        )

    def deactivate(self, deactivated_by: UUID, reason: str | None = None) -> FixedAsset:
        """Deactivate asset (set to idle)."""
        if self.status != AssetStatus.ACTIVE:
            raise FixedAssetError(f"Cannot deactivate asset in status {self.status.value}")
        now = datetime.now(UTC)
        return FixedAsset(
            **{
                **self.__dict__,
                "status": AssetStatus.IDLE,
                "updated_at": now,
                "updated_by": deactivated_by,
                "version": self.version + 1,
            }
        )

    def lock(self, locked_by: UUID, reason: str) -> FixedAsset:
        """Lock asset (prevent modifications)."""
        now = datetime.now(UTC)
        # Add lock metadata
        metadata = getattr(self, "metadata", {}) or {}
        metadata["locked_by"] = str(locked_by)
        metadata["locked_at"] = now.isoformat()
        metadata["lock_reason"] = reason
        return FixedAsset(
            **{
                **self.__dict__,
                "metadata": metadata,
                "updated_at": now,
                "updated_by": locked_by,
                "version": self.version + 1,
            }
        )

    def unlock(self, unlocked_by: UUID) -> FixedAsset:
        """Unlock asset."""
        now = datetime.now(UTC)
        metadata = getattr(self, "metadata", {}) or {}
        metadata.pop("locked_by", None)
        metadata.pop("locked_at", None)
        metadata.pop("lock_reason", None)
        return FixedAsset(
            **{
                **self.__dict__,
                "metadata": metadata,
                "updated_at": now,
                "updated_by": unlocked_by,
                "version": self.version + 1,
            }
        )

    def validate(self) -> dict[str, Any]:
        """Validate all invariants."""
        errors = []
        try:
            self._validate()
        except FixedAssetError as e:
            errors.append(str(e))
        if self.acquisition_cost <= 0:
            errors.append(f"Acquisition cost must be positive: {self.acquisition_cost}")
        if self.salvage_value < 0:
            errors.append(f"Salvage value cannot be negative: {self.salvage_value}")
        if self.salvage_value > self.acquisition_cost:
            errors.append(
                f"Salvage value {self.salvage_value} exceeds cost {self.acquisition_cost}"
            )
        if self.asset_type.is_depreciable() and self.useful_life_years <= 0:
            errors.append(
                f"Useful life must be positive for depreciable asset: {self.useful_life_years}"
            )
        if self.accumulated_depreciation > self.acquisition_cost - self.salvage_value:
            errors.append(
                f"Accumulated depreciation {self.accumulated_depreciation} exceeds depreciable amount"
            )
        if self.net_book_value < 0:
            errors.append(f"Net book value cannot be negative: {self.net_book_value}")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "asset_id": str(self.id),
            "version": self.version,
        }

    def clone(self, new_code: str | None = None) -> FixedAsset:
        """Clone asset with new ID and optional new code."""
        new_id = uuid4()
        new_code_str = new_code or f"{self.asset_code}_COPY"
        now = datetime.now(UTC)
        cloned = FixedAsset(
            id=new_id,
            legal_entity_id=self.legal_entity_id,
            asset_code=new_code_str,
            name=f"{self.name} (COPY)",
            description=self.description,
            asset_type=self.asset_type,
            status=AssetStatus.DRAFT,
            acquisition_date=self.acquisition_date,
            acquisition_cost=self.acquisition_cost,
            salvage_value=self.salvage_value,
            useful_life_years=self.useful_life_years,
            depreciation_method=self.depreciation_method,
            accumulated_depreciation=Decimal("0"),
            net_book_value=self.acquisition_cost,
            location=self.location,
            responsible_person=self.responsible_person,
            supplier_id=self.supplier_id,
            po_number=self.po_number,
            category=self.category,
            currency=self.currency,
            disposed_at=None,
            disposed_reason=None,
            last_depreciation_date=None,
            accumulated_impairment=Decimal("0"),
            revaluation_surplus=Decimal("0"),
            created_by=self.created_by,
            created_at=now,
            updated_at=now,
            updated_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", str(self.created_by), {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        """Get current snapshot."""
        return {
            "version": self.version,
            "asset_id": str(self.id),
            "asset_code": self.asset_code,
            "name": self.name,
            "status": self.status.value,
            "nbv": str(self.net_book_value),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get audit trail entries."""
        return getattr(self, "_audit_trail", [])[-limit:]

    def touch(self, touched_by: UUID) -> FixedAsset:
        """Update timestamp without changing data."""
        now = datetime.now(UTC)
        return FixedAsset(
            **{
                **self.__dict__,
                "updated_at": now,
                "updated_by": touched_by,
                "version": self.version + 1,
            }
        )

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        """Record audit entry."""
        if not hasattr(self, "_audit_trail"):
            object.__setattr__(self, "_audit_trail", [])
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "asset_id": str(self.id),
            "details": details,
        }
        self._audit_trail.append(entry)


# ============================================================================
# Repository Protocol
# ============================================================================


class FixedAssetRepository:
    async def get_by_id(self, asset_id: UUID, legal_entity_id: UUID) -> FixedAsset | None:
        raise NotImplementedError

    async def get_by_code(self, asset_code: str, legal_entity_id: UUID) -> FixedAsset | None:
        raise NotImplementedError

    async def list_active_assets(
        self, legal_entity_id: UUID, limit: int = 1000
    ) -> list[FixedAsset]:
        raise NotImplementedError

    async def list_assets(
        self,
        legal_entity_id: UUID,
        asset_type: str | None = None,
        status: str | None = None,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FixedAsset]:
        raise NotImplementedError

    async def save_asset(self, aggregate: Any) -> None:
        raise NotImplementedError

    async def save_depreciation_entry(self, entry: Any) -> None:
        raise NotImplementedError

    async def sum_acquisition_cost(self, legal_entity_id: UUID) -> Decimal:
        raise NotImplementedError

    async def sum_accumulated_depreciation(self, legal_entity_id: UUID) -> Decimal:
        raise NotImplementedError

    async def count_assets(self, legal_entity_id: UUID) -> int:
        raise NotImplementedError

    async def get_depreciation_schedule(
        self,
        asset_id: UUID,
        from_year: int | None,
        to_year: int | None,
    ) -> list[Any]:
        raise NotImplementedError


FixedAssetEntity = FixedAsset

__all__ = [
    "AssetAlreadyDisposedError",
    "AssetCategory",
    "AssetStatus",
    "AssetType",
    "DepreciationMethod",
    "FixedAsset",
    "FixedAssetEntity",
    "FixedAssetError",
    "FixedAssetRepository",
    "InvalidAssetCodeError",
    "InvalidCostError",
    "InvalidDepreciationError",
    "InvalidUsefulLifeError",
]
