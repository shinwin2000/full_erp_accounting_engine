#!/usr/bin/env python3
"""
Module: asset_entity.py
Layer: Domain / Intangible Asset
Responsibility: Entitas aset tak berwujud dengan semua method entity dasar.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intangible_asset.amortization_method_enum import AmortizationMethod

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class IntangibleAssetStatus(Enum):
    ACTIVE = "active"
    FULLY_AMORTIZED = "fully_amortized"
    IMPAIRED = "impaired"
    DISPOSED = "disposed"
    UNDER_DEVELOPMENT = "development"
    PENDING_ACTIVATION = "pending"

    def can_amortize(self) -> bool:
        return self in (IntangibleAssetStatus.ACTIVE, IntangibleAssetStatus.IMPAIRED)

    def can_impair(self) -> bool:
        return self in (IntangibleAssetStatus.ACTIVE, IntangibleAssetStatus.UNDER_DEVELOPMENT)

    def can_dispose(self) -> bool:
        return self != IntangibleAssetStatus.DISPOSED

    def display_name(self) -> str:
        names = {
            IntangibleAssetStatus.ACTIVE: "Aktif",
            IntangibleAssetStatus.FULLY_AMORTIZED: "Tersusut Penuh",
            IntangibleAssetStatus.IMPAIRED: "Penurunan Nilai",
            IntangibleAssetStatus.DISPOSED: "Dihapuskan",
            IntangibleAssetStatus.UNDER_DEVELOPMENT: "Dalam Pengembangan",
            IntangibleAssetStatus.PENDING_ACTIVATION: "Menunggu Aktivasi",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> IntangibleAssetStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


class IntangibleAssetType(Enum):
    PATENT = "patent"
    TRADEMARK = "trademark"
    COPYRIGHT = "copyright"
    LICENSE = "license"
    SOFTWARE = "software"
    GOODWILL = "goodwill"
    CUSTOMER_RELATIONSHIP = "customer_relationship"
    RESEARCH_DEVELOPMENT = "r_and_d"
    OTHER = "other"

    def display_name(self) -> str:
        names = {
            IntangibleAssetType.PATENT: "Paten",
            IntangibleAssetType.TRADEMARK: "Merek Dagang",
            IntangibleAssetType.COPYRIGHT: "Hak Cipta",
            IntangibleAssetType.LICENSE: "Lisensi",
            IntangibleAssetType.SOFTWARE: "Perangkat Lunak",
            IntangibleAssetType.GOODWILL: "Goodwill",
            IntangibleAssetType.CUSTOMER_RELATIONSHIP: "Hubungan Pelanggan",
            IntangibleAssetType.RESEARCH_DEVELOPMENT: "Litbang",
            IntangibleAssetType.OTHER: "Lainnya",
        }
        return names.get(self, self.value)

    def is_amortizable(self) -> bool:
        return self != IntangibleAssetType.GOODWILL

    def has_legal_protection(self) -> bool:
        return self in (
            IntangibleAssetType.PATENT,
            IntangibleAssetType.TRADEMARK,
            IntangibleAssetType.COPYRIGHT,
        )

    @classmethod
    def from_string(cls, value: str) -> IntangibleAssetType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class IntangibleAssetError(ValueError):
    pass


class InvalidAssetCodeError(IntangibleAssetError):
    pass


class InvalidCostError(IntangibleAssetError):
    pass


class InvalidUsefulLifeError(IntangibleAssetError):
    pass


class AssetAlreadyDisposedError(IntangibleAssetError):
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
        raise IntangibleAssetError("Asset name must be a non-empty string")
    cleaned = name.strip()
    if len(cleaned) < 2:
        raise IntangibleAssetError("Asset name must be at least 2 characters")
    if len(cleaned) > 200:
        raise IntangibleAssetError("Asset name must not exceed 200 characters")
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


def _validate_residual_value(residual: Decimal, cost: Decimal) -> Decimal:
    if not isinstance(residual, Decimal):
        try:
            residual = Decimal(str(residual))
        except Exception:
            raise IntangibleAssetError(f"Invalid residual value type: {type(residual)}")
    if residual < 0:
        raise IntangibleAssetError(f"Residual value cannot be negative: {residual}")
    if residual > cost:
        raise IntangibleAssetError(f"Residual value {residual} exceeds cost {cost}")
    return residual.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_useful_life(years: int, is_amortizable: bool) -> int:
    if not isinstance(years, int):
        try:
            years = int(years)
        except Exception:
            raise InvalidUsefulLifeError(f"Useful life must be integer, got {type(years)}")
    if is_amortizable and years <= 0:
        raise InvalidUsefulLifeError(
            f"Useful life must be positive for amortizable assets: {years}"
        )
    if years > 100:
        raise InvalidUsefulLifeError(f"Useful life exceeds maximum 100 years: {years}")
    return years


def _validate_accumulated_amortization(
    acc_amort: Decimal, cost: Decimal, residual: Decimal
) -> Decimal:
    if not isinstance(acc_amort, Decimal):
        try:
            acc_amort = Decimal(str(acc_amort))
        except Exception:
            raise IntangibleAssetError(f"Invalid accumulated amortization type: {type(acc_amort)}")
    if acc_amort < 0:
        raise IntangibleAssetError(f"Accumulated amortization cannot be negative: {acc_amort}")
    max_amort = cost - residual
    if acc_amort > max_amort and acc_amort - max_amort > Decimal("0.01"):
        raise IntangibleAssetError(
            f"Accumulated amortization {acc_amort} exceeds amortizable amount {max_amort}"
        )
    return acc_amort.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _validate_currency(currency: str) -> str:
    if not currency or not isinstance(currency, str):
        raise IntangibleAssetError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise IntangibleAssetError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise IntangibleAssetError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


# ============================================================================
# Intangible Asset Entity
# ============================================================================


@dataclass
class IntangibleAssetEntity:
    asset_id: UUID
    asset_code: str
    asset_name: str
    asset_type: IntangibleAssetType
    acquisition_date: datetime
    cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    amortization_method: AmortizationMethod
    accumulated_amortization: Decimal
    nbv: Decimal
    currency: str = "IDR"
    status: IntangibleAssetStatus = IntangibleAssetStatus.ACTIVE
    legal_owner: str | None = None
    registration_number: str | None = None
    expiry_date: datetime | None = None
    supplier_id: UUID | None = None
    supplier_name: str | None = None
    last_amortization_date: datetime | None = None
    impairment_history: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        # Validate asset_code
        normalized_code = _validate_asset_code(self.asset_code)
        if normalized_code != self.asset_code:
            object.__setattr__(self, "asset_code", normalized_code)

        # Validate asset_name
        normalized_name = _validate_asset_name(self.asset_name)
        if normalized_name != self.asset_name:
            object.__setattr__(self, "asset_name", normalized_name)

        # Validate asset_type
        if not isinstance(self.asset_type, IntangibleAssetType):
            raise IntangibleAssetError(f"Invalid asset_type: {self.asset_type}")

        # Validate status
        if not isinstance(self.status, IntangibleAssetStatus):
            raise IntangibleAssetError(f"Invalid status: {self.status}")

        # Validate dates UTC
        if self.acquisition_date.tzinfo is None:
            object.__setattr__(self, "acquisition_date", self.acquisition_date.replace(tzinfo=UTC))
        if self.expiry_date and self.expiry_date.tzinfo is None:
            object.__setattr__(self, "expiry_date", self.expiry_date.replace(tzinfo=UTC))
        if self.last_amortization_date and self.last_amortization_date.tzinfo is None:
            object.__setattr__(
                self, "last_amortization_date", self.last_amortization_date.replace(tzinfo=UTC)
            )
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate acquisition date not future
        if self.acquisition_date > datetime.now(UTC):
            raise IntangibleAssetError(
                f"Acquisition date {self.acquisition_date} cannot be in the future"
            )

        # Validate expiry date > acquisition date
        if self.expiry_date and self.expiry_date <= self.acquisition_date:
            raise IntangibleAssetError(
                f"Expiry date {self.expiry_date} must be after acquisition date"
            )

        # Validate cost
        normalized_cost = _validate_cost(self.cost)
        if normalized_cost != self.cost:
            object.__setattr__(self, "cost", normalized_cost)

        # Validate residual value
        normalized_residual = _validate_residual_value(self.residual_value, self.cost)
        if normalized_residual != self.residual_value:
            object.__setattr__(self, "residual_value", normalized_residual)

        # Validate useful life
        is_amortizable = (
            self.asset_type.is_amortizable()
            and self.amortization_method != AmortizationMethod.NO_AMORTIZATION
        )
        normalized_life = _validate_useful_life(self.useful_life_years, is_amortizable)
        if normalized_life != self.useful_life_years:
            object.__setattr__(self, "useful_life_years", normalized_life)

        # Validate amortization method
        if not isinstance(self.amortization_method, AmortizationMethod):
            raise IntangibleAssetError(f"Invalid amortization_method: {self.amortization_method}")
        if (
            self.has_indefinite_life
            and self.amortization_method != AmortizationMethod.NO_AMORTIZATION
        ):
            raise IntangibleAssetError("Asset with indefinite life must use NO_AMORTIZATION method")

        # Validate accumulated amortization
        normalized_acc = _validate_accumulated_amortization(
            self.accumulated_amortization, self.cost, self.residual_value
        )
        if normalized_acc != self.accumulated_amortization:
            object.__setattr__(self, "accumulated_amortization", normalized_acc)

        # Validate NBV
        expected_nbv = self.cost - self.accumulated_amortization
        if abs(self.nbv - expected_nbv) > Decimal("0.01"):
            raise IntangibleAssetError(f"NBV mismatch: expected {expected_nbv}, got {self.nbv}")
        if self.nbv < 0:
            raise IntangibleAssetError(f"NBV cannot be negative: {self.nbv}")

        # Validate currency
        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        # Validate version
        if self.version < 1:
            raise IntangibleAssetError("Version must be >= 1")

        # Validate status consistency
        if self.status == IntangibleAssetStatus.DISPOSED and self.last_amortization_date:
            pass  # OK
        if self.is_fully_amortized and self.status != IntangibleAssetStatus.FULLY_AMORTIZED:
            object.__setattr__(self, "status", IntangibleAssetStatus.FULLY_AMORTIZED)

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "status": self.status.value,
            "nbv": str(self.nbv),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "asset_id": str(self.asset_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== PROPERTIES ====================

    @property
    def amortizable_amount(self) -> Decimal:
        return self.cost - self.residual_value

    @property
    def is_fully_amortized(self) -> bool:
        if self.has_indefinite_life:
            return False
        return self.accumulated_amortization >= self.amortizable_amount - Decimal("0.01")

    @property
    def has_indefinite_life(self) -> bool:
        return self.useful_life_years == 0

    @property
    def remaining_amortizable(self) -> Decimal:
        return max(Decimal(0), self.amortizable_amount - self.accumulated_amortization)

    @property
    def amortization_percentage(self) -> Decimal:
        if self.amortizable_amount == 0:
            return Decimal(0)
        return (self.accumulated_amortization / self.amortizable_amount * 100).quantize(
            Decimal("0.01")
        )

    @property
    def is_active(self) -> bool:
        return self.status == IntangibleAssetStatus.ACTIVE

    @property
    def is_impaired(self) -> bool:
        return self.status == IntangibleAssetStatus.IMPAIRED

    @property
    def is_disposed(self) -> bool:
        return self.status == IntangibleAssetStatus.DISPOSED

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> IntangibleAssetEntity:
        self._record_audit("CREATE", created_by, {"asset_code": self.asset_code})
        return self

    def update(self, updated_by: str, **kwargs) -> IntangibleAssetEntity:
        if self.status == IntangibleAssetStatus.DISPOSED:
            raise IntangibleAssetError(f"Cannot update disposed asset {self.asset_code}")

        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("asset_id", "created_at", "created_by", "version"):
                data[key] = value

        new_asset = self.from_dict(data)
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_asset

    def delete(self, deleted_by: str, reason: str | None = None) -> IntangibleAssetEntity:
        if self.status == IntangibleAssetStatus.DISPOSED:
            return self
        return self.dispose(datetime.now(UTC), Decimal(0), deleted_by)

    def restore(self, restored_by: str) -> IntangibleAssetEntity:
        if self.status != IntangibleAssetStatus.DISPOSED:
            raise IntangibleAssetError(f"Cannot restore asset in status {self.status.value}")

        new_asset = self._copy()
        new_asset.status = IntangibleAssetStatus.ACTIVE
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("RESTORE", restored_by, {})
        return new_asset

    def activate(self, activated_by: str) -> IntangibleAssetEntity:
        if self.status == IntangibleAssetStatus.ACTIVE:
            return self
        if self.status != IntangibleAssetStatus.PENDING_ACTIVATION:
            raise IntangibleAssetError(f"Cannot activate asset in status {self.status.value}")

        new_asset = self._copy()
        new_asset.status = IntangibleAssetStatus.ACTIVE
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("ACTIVATE", activated_by, {})
        return new_asset

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IntangibleAssetEntity:
        if self.status == IntangibleAssetStatus.UNDER_DEVELOPMENT:
            return self
        if self.status != IntangibleAssetStatus.ACTIVE:
            raise IntangibleAssetError(f"Cannot deactivate asset in status {self.status.value}")

        new_asset = self._copy()
        new_asset.status = IntangibleAssetStatus.UNDER_DEVELOPMENT
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_asset

    def lock(self, locked_by: str, reason: str) -> IntangibleAssetEntity:
        new_asset = self._copy()
        new_asset.metadata["locked_by"] = locked_by
        new_asset.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_asset.metadata["lock_reason"] = reason
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("LOCK", locked_by, {"reason": reason})
        return new_asset

    def unlock(self, unlocked_by: str) -> IntangibleAssetEntity:
        new_asset = self._copy()
        new_asset.metadata.pop("locked_by", None)
        new_asset.metadata.pop("locked_at", None)
        new_asset.metadata.pop("lock_reason", None)
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("UNLOCK", unlocked_by, {})
        return new_asset

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except IntangibleAssetError as e:
            errors.append(str(e))

        if self.accumulated_amortization > self.amortizable_amount:
            errors.append(
                f"Accumulated amortization {self.accumulated_amortization} exceeds amortizable amount {self.amortizable_amount}"
            )

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "asset_id": str(self.asset_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_type": self.asset_type.value,
            "acquisition_date": self.acquisition_date.isoformat(),
            "cost": str(self.cost),
            "currency": self.currency,
            "residual_value": str(self.residual_value),
            "useful_life_years": self.useful_life_years,
            "amortization_method": self.amortization_method.value,
            "accumulated_amortization": str(self.accumulated_amortization),
            "nbv": str(self.nbv),
            "status": self.status.value,
            "legal_owner": self.legal_owner,
            "registration_number": self.registration_number,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "supplier_name": self.supplier_name,
            "last_amortization_date": self.last_amortization_date.isoformat()
            if self.last_amortization_date
            else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "metadata": self.metadata,
            "has_indefinite_life": self.has_indefinite_life,
            "is_fully_amortized": self.is_fully_amortized,
            "amortizable_amount": str(self.amortizable_amount),
            "remaining_amortizable": str(self.remaining_amortizable),
            "amortization_percentage": str(self.amortization_percentage),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntangibleAssetEntity:
        asset_type = IntangibleAssetType.from_string(data["asset_type"])
        if asset_type is None:
            raise IntangibleAssetError(f"Invalid asset_type: {data['asset_type']}")
        status = (
            IntangibleAssetStatus.from_string(data.get("status", "active"))
            or IntangibleAssetStatus.ACTIVE
        )
        amortization_method = (
            AmortizationMethod.from_string(data["amortization_method"])
            or AmortizationMethod.STRAIGHT_LINE
        )
        acquisition_date = datetime.fromisoformat(data["acquisition_date"])
        expiry_date = (
            datetime.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None
        )
        last_amortization_date = (
            datetime.fromisoformat(data["last_amortization_date"])
            if data.get("last_amortization_date")
            else None
        )
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        return cls(
            asset_id=UUID(data["asset_id"]),
            asset_code=data["asset_code"],
            asset_name=data["asset_name"],
            asset_type=asset_type,
            acquisition_date=acquisition_date,
            cost=Decimal(data["cost"]),
            currency=data.get("currency", "IDR"),
            residual_value=Decimal(data.get("residual_value", "0")),
            useful_life_years=data.get("useful_life_years", 0),
            amortization_method=amortization_method,
            accumulated_amortization=Decimal(data.get("accumulated_amortization", "0")),
            nbv=Decimal(data["nbv"]),
            status=status,
            legal_owner=data.get("legal_owner"),
            registration_number=data.get("registration_number"),
            expiry_date=expiry_date,
            supplier_id=UUID(data["supplier_id"]) if data.get("supplier_id") else None,
            supplier_name=data.get("supplier_name"),
            last_amortization_date=last_amortization_date,
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self, new_code: str | None = None) -> IntangibleAssetEntity:
        new_id = uuid4()
        new_code_str = new_code or f"{self.asset_code}_COPY"
        now = datetime.now(UTC)
        cloned = IntangibleAssetEntity(
            asset_id=new_id,
            asset_code=new_code_str,
            asset_name=f"{self.asset_name} (COPY)",
            asset_type=self.asset_type,
            acquisition_date=self.acquisition_date,
            cost=self.cost,
            currency=self.currency,
            residual_value=self.residual_value,
            useful_life_years=self.useful_life_years,
            amortization_method=self.amortization_method,
            accumulated_amortization=Decimal(0),
            nbv=self.cost,
            status=IntangibleAssetStatus.PENDING_ACTIVATION,
            legal_owner=self.legal_owner,
            registration_number=self.registration_number,
            expiry_date=self.expiry_date,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.asset_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "status": self.status.value,
            "nbv": str(self.nbv),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IntangibleAssetEntity:
        new_asset = self._copy()
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("TOUCH", touched_by, {})
        return new_asset

    # ==================== BUSINESS METHODS ====================

    def record_amortization(
        self, period: str, amount: Decimal, posted_by: str
    ) -> IntangibleAssetEntity:
        if self.status == IntangibleAssetStatus.DISPOSED:
            raise AssetAlreadyDisposedError(f"Cannot amortize disposed asset {self.asset_code}")
        if not self.status.can_amortize():
            raise IntangibleAssetError(f"Cannot amortize asset in status {self.status.value}")
        if self.has_indefinite_life:
            raise IntangibleAssetError(
                f"Asset {self.asset_code} has indefinite life and is not amortized"
            )
        if amount <= 0:
            raise IntangibleAssetError(f"Amortization amount must be positive: {amount}")

        new_accumulated = self.accumulated_amortization + amount
        if new_accumulated > self.amortizable_amount:
            raise IntangibleAssetError(
                f"Amortization amount {amount} would exceed amortizable amount {self.amortizable_amount}"
            )

        new_nbv = self.cost - new_accumulated
        new_status = self.status
        if new_accumulated >= self.amortizable_amount - Decimal("0.01"):
            new_status = IntangibleAssetStatus.FULLY_AMORTIZED

        return IntangibleAssetEntity(
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            asset_type=self.asset_type,
            acquisition_date=self.acquisition_date,
            cost=self.cost,
            currency=self.currency,
            residual_value=self.residual_value,
            useful_life_years=self.useful_life_years,
            amortization_method=self.amortization_method,
            accumulated_amortization=new_accumulated,
            nbv=new_nbv,
            status=new_status,
            legal_owner=self.legal_owner,
            registration_number=self.registration_number,
            expiry_date=self.expiry_date,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            last_amortization_date=datetime.now(UTC),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=posted_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def impair(self, impairment_loss: Decimal, impaired_by: str) -> IntangibleAssetEntity:
        if self.status == IntangibleAssetStatus.DISPOSED:
            raise AssetAlreadyDisposedError(f"Cannot impair disposed asset {self.asset_code}")
        if not self.status.can_impair():
            raise IntangibleAssetError(f"Cannot impair asset in status {self.status.value}")
        if impairment_loss <= 0:
            raise IntangibleAssetError(f"Impairment loss must be positive: {impairment_loss}")
        if impairment_loss > self.nbv:
            raise IntangibleAssetError(f"Impairment loss {impairment_loss} exceeds NBV {self.nbv}")

        new_nbv = self.nbv - impairment_loss
        new_cost = self.cost
        # For impairment, we reduce cost directly (or add to accumulated impairment)
        new_impairment_history = self.impairment_history + [
            {
                "date": datetime.now(UTC).isoformat(),
                "loss": str(impairment_loss),
                "nbv_before": str(self.nbv),
                "nbv_after": str(new_nbv),
                "impaired_by": impaired_by,
            }
        ]

        return IntangibleAssetEntity(
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            asset_type=self.asset_type,
            acquisition_date=self.acquisition_date,
            cost=new_cost,
            currency=self.currency,
            residual_value=self.residual_value,
            useful_life_years=self.useful_life_years,
            amortization_method=self.amortization_method,
            accumulated_amortization=self.accumulated_amortization,
            nbv=new_nbv,
            status=IntangibleAssetStatus.IMPAIRED,
            legal_owner=self.legal_owner,
            registration_number=self.registration_number,
            expiry_date=self.expiry_date,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            last_amortization_date=self.last_amortization_date,
            impairment_history=new_impairment_history,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=impaired_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def reverse_impairment(
        self, reversal_amount: Decimal, reversed_by: str
    ) -> IntangibleAssetEntity:
        if self.status != IntangibleAssetStatus.IMPAIRED:
            raise IntangibleAssetError(
                f"Cannot reverse impairment for asset in status {self.status.value}"
            )
        if reversal_amount <= 0:
            raise IntangibleAssetError(f"Reversal amount must be positive: {reversal_amount}")
        if reversal_amount > self.nbv:
            raise IntangibleAssetError(f"Reversal amount {reversal_amount} exceeds NBV {self.nbv}")

        new_nbv = self.nbv + reversal_amount
        new_cost = self.cost + reversal_amount

        return IntangibleAssetEntity(
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            asset_type=self.asset_type,
            acquisition_date=self.acquisition_date,
            cost=new_cost,
            currency=self.currency,
            residual_value=self.residual_value,
            useful_life_years=self.useful_life_years,
            amortization_method=self.amortization_method,
            accumulated_amortization=self.accumulated_amortization,
            nbv=new_nbv,
            status=IntangibleAssetStatus.ACTIVE,
            legal_owner=self.legal_owner,
            registration_number=self.registration_number,
            expiry_date=self.expiry_date,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            last_amortization_date=self.last_amortization_date,
            impairment_history=self.impairment_history,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=reversed_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def dispose(
        self, disposal_date: datetime, proceeds: Decimal, disposed_by: str
    ) -> IntangibleAssetEntity:
        if not self.status.can_dispose():
            raise IntangibleAssetError(f"Cannot dispose asset in status {self.status.value}")

        if disposal_date.tzinfo is None:
            disposal_date = disposal_date.replace(tzinfo=UTC)

        gain_loss = proceeds - self.nbv

        return IntangibleAssetEntity(
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            asset_type=self.asset_type,
            acquisition_date=self.acquisition_date,
            cost=self.cost,
            currency=self.currency,
            residual_value=self.residual_value,
            useful_life_years=self.useful_life_years,
            amortization_method=self.amortization_method,
            accumulated_amortization=self.accumulated_amortization,
            nbv=self.nbv,
            status=IntangibleAssetStatus.DISPOSED,
            legal_owner=self.legal_owner,
            registration_number=self.registration_number,
            expiry_date=self.expiry_date,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            last_amortization_date=self.last_amortization_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=disposed_by,
            version=self.version + 1,
            metadata=self.metadata,
        )

    def calculate_gain_loss_on_disposal(self, proceeds: Decimal) -> Decimal:
        return proceeds - self.nbv

    def update_registration(
        self, registration_number: str, updated_by: str
    ) -> IntangibleAssetEntity:
        new_asset = self._copy()
        new_asset.registration_number = registration_number
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit(
            "UPDATE_REGISTRATION", updated_by, {"registration_number": registration_number}
        )
        return new_asset

    def update_legal_owner(self, legal_owner: str, updated_by: str) -> IntangibleAssetEntity:
        new_asset = self._copy()
        new_asset.legal_owner = legal_owner
        new_asset.updated_at = datetime.now(UTC)
        new_asset.version = self.version + 1
        new_asset._record_audit("UPDATE_LEGAL_OWNER", updated_by, {"legal_owner": legal_owner})
        return new_asset

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> IntangibleAssetEntity:
        return IntangibleAssetEntity(
            asset_id=self.asset_id,
            asset_code=self.asset_code,
            asset_name=self.asset_name,
            asset_type=self.asset_type,
            acquisition_date=self.acquisition_date,
            cost=self.cost,
            currency=self.currency,
            residual_value=self.residual_value,
            useful_life_years=self.useful_life_years,
            amortization_method=self.amortization_method,
            accumulated_amortization=self.accumulated_amortization,
            nbv=self.nbv,
            status=self.status,
            legal_owner=self.legal_owner,
            registration_number=self.registration_number,
            expiry_date=self.expiry_date,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            last_amortization_date=self.last_amortization_date,
            impairment_history=self.impairment_history.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class IntangibleAssetEntityRepository:
    _storage: ClassVar[dict[UUID, IntangibleAssetEntity]] = {}

    @classmethod
    async def get_by_id(cls, asset_id: UUID, legal_entity_id: UUID) -> IntangibleAssetEntity | None:
        asset = cls._storage.get(asset_id)
        if asset and asset.legal_entity_id == legal_entity_id:
            return asset
        return None

    @classmethod
    async def get_by_code(
        cls, asset_code: str, legal_entity_id: UUID
    ) -> IntangibleAssetEntity | None:
        for asset in cls._storage.values():
            if asset.asset_code == asset_code and asset.legal_entity_id == legal_entity_id:
                return asset
        return None

    @classmethod
    async def get_by_type(
        cls, asset_type: IntangibleAssetType, legal_entity_id: UUID
    ) -> list[IntangibleAssetEntity]:
        return [
            a
            for a in cls._storage.values()
            if a.asset_type == asset_type and a.legal_entity_id == legal_entity_id
        ]

    @classmethod
    async def get_by_status(
        cls, status: IntangibleAssetStatus, legal_entity_id: UUID
    ) -> list[IntangibleAssetEntity]:
        return [
            a
            for a in cls._storage.values()
            if a.status == status and a.legal_entity_id == legal_entity_id
        ]

    @classmethod
    async def get_active(cls, legal_entity_id: UUID) -> list[IntangibleAssetEntity]:
        return [
            a
            for a in cls._storage.values()
            if a.status == IntangibleAssetStatus.ACTIVE and a.legal_entity_id == legal_entity_id
        ]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[IntangibleAssetEntity]:
        return [a for a in cls._storage.values() if a.legal_entity_id == legal_entity_id]

    @classmethod
    async def save(cls, asset: IntangibleAssetEntity, legal_entity_id: UUID) -> None:
        if asset.legal_entity_id != legal_entity_id:
            raise IntangibleAssetError("Asset legal entity mismatch")
        cls._storage[asset.asset_id] = asset

    @classmethod
    async def update(cls, asset: IntangibleAssetEntity, legal_entity_id: UUID) -> None:
        await cls.save(asset, legal_entity_id)

    @classmethod
    async def delete(cls, asset_id: UUID, legal_entity_id: UUID) -> None:
        cls._storage.pop(asset_id, None)

    @classmethod
    async def exists(cls, asset_id: UUID, legal_entity_id: UUID) -> bool:
        asset = cls._storage.get(asset_id)
        return asset is not None and asset.legal_entity_id == legal_entity_id

    @classmethod
    async def count(cls, legal_entity_id: UUID) -> int:
        return len([a for a in cls._storage.values() if a.legal_entity_id == legal_entity_id])

    @classmethod
    async def list(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[IntangibleAssetEntity]:
        assets = await cls.get_all(legal_entity_id)
        return assets[offset : offset + limit]

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        to_delete = [k for k, v in cls._storage.items() if v.legal_entity_id == legal_entity_id]
        for k in to_delete:
            cls._storage.pop(k, None)


__all__ = [
    "AssetAlreadyDisposedError",
    "IntangibleAssetEntity",
    "IntangibleAssetEntityRepository",
    "IntangibleAssetError",
    "IntangibleAssetStatus",
    "IntangibleAssetType",
    "InvalidAssetCodeError",
    "InvalidCostError",
    "InvalidUsefulLifeError",
]
