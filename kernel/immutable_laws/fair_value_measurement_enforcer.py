#!/usr/bin/env python3
"""
Module: fair_value_measurement_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: pengukuran nilai wajar harus berdasar pasar aktif.
               Memastikan bahwa pengukuran nilai wajar untuk aset dan liabilitas
               (PSAK 68/IFRS 13) menggunakan data pasar aktif, atau jika tidak
               tersedia, menggunakan metode valuasi yang dapat diandalkan.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, FairValueMeasurementViolation)

Audit: Setiap pengukuran nilai wajar dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    FairValueMeasurementViolation,
    LawViolationSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackMarketDataRepository:
    """Fallback market data repository dengan data dummy untuk testing."""

    def __init__(self):
        self._prices: dict[str, dict[str, Any]] = {}
        self._indices: dict[str, dict[str, Any]] = {}
        self._volatility: dict[str, dict[str, Any]] = {}

    async def get_market_price(
        self,
        asset_type: str,
        as_of: datetime,
        legal_entity_id: UUID,
    ) -> Any | None:
        key = f"{asset_type}:{as_of.strftime('%Y-%m-%d')}"
        data = self._prices.get(key)
        if data:
            return _MarketPriceProxy(data)
        return None

    async def get_price_history(
        self,
        asset_type: str,
        from_date: datetime,
        to_date: datetime,
        legal_entity_id: UUID,
    ) -> list[Any]:
        result = []
        current = from_date
        while current <= to_date:
            key = f"{asset_type}:{current.strftime('%Y-%m-%d')}"
            data = self._prices.get(key)
            if data:
                result.append(_MarketPriceProxy(data))
            current += timedelta(days=1)
        return result

    async def get_market_index(
        self,
        index_code: str,
        as_of: datetime,
        legal_entity_id: UUID,
    ) -> Decimal | None:
        key = f"{index_code}:{as_of.strftime('%Y-%m-%d')}"
        data = self._indices.get(key)
        if data:
            return Decimal(str(data.get("value", 0)))
        return None

    async def get_volatility(
        self,
        asset_type: str,
        as_of: datetime,
        lookback_days: int,
        legal_entity_id: UUID,
    ) -> Decimal | None:
        key = f"{asset_type}:{as_of.strftime('%Y-%m-%d')}"
        data = self._volatility.get(key)
        if data:
            return Decimal(str(data.get("volatility", 0)))
        return Decimal("0.15")  # default 15%

    async def add_market_price(
        self,
        asset_type: str,
        date: datetime,
        price: Decimal,
        source: str = "fallback",
        is_active_market: bool = False,
    ) -> None:
        key = f"{asset_type}:{date.strftime('%Y-%m-%d')}"
        self._prices[key] = {
            "asset_type": asset_type,
            "price": price,
            "source": source,
            "date": date,
            "is_active_market": is_active_market,
        }

    async def add_market_index(
        self,
        index_code: str,
        date: datetime,
        value: Decimal,
    ) -> None:
        key = f"{index_code}:{date.strftime('%Y-%m-%d')}"
        self._indices[key] = {"value": value, "date": date}

    def clear(self) -> None:
        self._prices.clear()
        self._indices.clear()
        self._volatility.clear()


class _FallbackValuationRepository:
    """Fallback valuation repository jika infrastructure belum tersedia."""

    def __init__(self):
        self._measurements: list[dict[str, Any]] = []
        self._observable_inputs: dict[UUID, list[dict[str, Any]]] = {}
        self._unobservable_inputs: dict[UUID, list[dict[str, Any]]] = {}
        self._sensitivity: dict[tuple[UUID, str], dict[str, Any]] = {}

    async def get_observable_inputs(
        self,
        asset_id: UUID,
        measurement_date: datetime,
    ) -> list[Any]:
        inputs = self._observable_inputs.get(asset_id, [])
        date_str = measurement_date.isoformat()
        return [_ObservableInputProxy(i) for i in inputs if i.get("measurement_date") == date_str]

    async def get_unobservable_inputs(
        self,
        asset_id: UUID,
        measurement_date: datetime,
    ) -> list[Any]:
        inputs = self._unobservable_inputs.get(asset_id, [])
        date_str = measurement_date.isoformat()
        return [_UnobservableInputProxy(i) for i in inputs if i.get("measurement_date") == date_str]

    async def get_sensitivity_analysis(
        self,
        asset_id: UUID,
        measurement_date: datetime,
    ) -> dict[str, Any] | None:
        date_str = measurement_date.isoformat()
        return self._sensitivity.get((asset_id, date_str))

    async def get_last_measurement(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
    ) -> datetime | None:
        measurements = [
            m
            for m in self._measurements
            if m.get("asset_id") == asset_id and m.get("legal_entity_id") == legal_entity_id
        ]
        if measurements:
            latest = max(measurements, key=lambda m: m.get("measurement_date", datetime.min))
            return latest.get("measurement_date")
        return None

    async def record_measurement(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        fair_value: Decimal,
        measurement_date: datetime,
        hierarchy_level: int,
        valuation_technique: str | None,
        measured_by: str,
        measured_at: datetime,
    ) -> None:
        self._measurements.append(
            {
                "asset_id": asset_id,
                "legal_entity_id": legal_entity_id,
                "fair_value": fair_value,
                "measurement_date": measurement_date,
                "hierarchy_level": hierarchy_level,
                "valuation_technique": valuation_technique,
                "measured_by": measured_by,
                "measured_at": measured_at,
            }
        )

    async def get_measurement_history(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        limit: int = 10,
    ) -> list[Any]:
        measurements = [
            m
            for m in self._measurements
            if m.get("asset_id") == asset_id and m.get("legal_entity_id") == legal_entity_id
        ]
        measurements.sort(key=lambda m: m.get("measurement_date", datetime.min), reverse=True)
        return [_MeasurementProxy(m) for m in measurements[:limit]]

    async def add_observable_input(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        input_type: str,
        value: Any,
        source: str,
    ) -> None:
        if asset_id not in self._observable_inputs:
            self._observable_inputs[asset_id] = []
        self._observable_inputs[asset_id].append(
            {
                "measurement_date": measurement_date.isoformat(),
                "input_type": input_type,
                "value": value,
                "source": source,
            }
        )

    async def add_unobservable_input(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        input_type: str,
        value: Any,
        justification: str,
    ) -> None:
        if asset_id not in self._unobservable_inputs:
            self._unobservable_inputs[asset_id] = []
        self._unobservable_inputs[asset_id].append(
            {
                "measurement_date": measurement_date.isoformat(),
                "input_type": input_type,
                "value": value,
                "justification": justification,
            }
        )

    async def add_sensitivity_analysis(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        analysis: dict[str, Any],
    ) -> None:
        date_str = measurement_date.isoformat()
        self._sensitivity[(asset_id, date_str)] = analysis

    def clear(self) -> None:
        self._measurements.clear()
        self._observable_inputs.clear()
        self._unobservable_inputs.clear()
        self._sensitivity.clear()


class _MarketPriceProxy:
    def __init__(self, data: dict[str, Any]):
        self.asset_type = data.get("asset_type")
        self.price = data.get("price", Decimal(0))
        self.source = data.get("source", "")
        self.date = data.get("date")
        self.is_active_market = data.get("is_active_market", False)


class _ObservableInputProxy:
    def __init__(self, data: dict[str, Any]):
        self.input_type = data.get("input_type")
        self.value = data.get("value")
        self.source = data.get("source")


class _UnobservableInputProxy:
    def __init__(self, data: dict[str, Any]):
        self.input_type = data.get("input_type")
        self.value = data.get("value")
        self.justification = data.get("justification")


class _MeasurementProxy:
    def __init__(self, data: dict[str, Any]):
        self.measurement_date = data.get("measurement_date")
        self.fair_value = data.get("fair_value")
        self.hierarchy_level = data.get("hierarchy_level")
        self.valuation_technique = data.get("valuation_technique")
        self.measured_by = data.get("measured_by")
        self.measured_at = data.get("measured_at")


# === 2. CONSTANTS & ENUMS ===


class FairValueHierarchy(Enum):
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3


class ValuationTechnique(Enum):
    MARKET_APPROACH = "market_approach"
    INCOME_APPROACH = "income_approach"
    COST_APPROACH = "cost_approach"


class AssetClass(Enum):
    FINANCIAL_INSTRUMENT = "financial_instrument"
    INVESTMENT_PROPERTY = "investment_property"
    BIOLOGICAL_ASSET = "biological_asset"
    INTANGIBLE_ASSET = "intangible_asset"
    PROPERTY_PLANT_EQUIPMENT = "property_plant_equipment"


@dataclass
class FairValueMeasurement:
    measurement_id: UUID
    asset_id: UUID
    asset_class: AssetClass
    legal_entity_id: UUID
    fair_value: Decimal
    measurement_date: datetime
    hierarchy_level: FairValueHierarchy
    valuation_technique: ValuationTechnique | None
    measured_by: str
    measured_at: datetime
    market_price_used: Decimal | None = None
    market_price_source: str | None = None
    observable_inputs: dict[str, Any] | None = None
    sensitivity_analysis: dict[str, Any] | None = None
    notes: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.measurement_id}|{self.asset_id}|{self.asset_class.value}|"
            f"{self.legal_entity_id}|{self.fair_value}|{self.measurement_date.isoformat()}|"
            f"{self.hierarchy_level.value}|{self.valuation_technique.value if self.valuation_technique else ''}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurement_id": str(self.measurement_id),
            "asset_id": str(self.asset_id),
            "asset_class": self.asset_class.value,
            "legal_entity_id": str(self.legal_entity_id),
            "fair_value": str(self.fair_value),
            "measurement_date": self.measurement_date.isoformat(),
            "hierarchy_level": self.hierarchy_level.value,
            "valuation_technique": self.valuation_technique.value
            if self.valuation_technique
            else None,
            "measured_by": self.measured_by,
            "measured_at": self.measured_at.isoformat(),
        }


@dataclass
class FairValueValidationResult:
    validation_id: UUID
    asset_id: UUID
    legal_entity_id: UUID
    measurement_id: UUID
    hierarchy_level: FairValueHierarchy
    is_valid: bool
    severity: LawViolationSeverity
    message: str
    issues: list[str]
    validated_by: str
    validated_at: datetime
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.validation_id}|{self.asset_id}|{self.hierarchy_level.value}|"
            f"{self.is_valid}|{self.severity.value}|{self.message[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_id": str(self.validation_id),
            "asset_id": str(self.asset_id),
            "legal_entity_id": str(self.legal_entity_id),
            "measurement_id": str(self.measurement_id),
            "hierarchy_level": self.hierarchy_level.value,
            "is_valid": self.is_valid,
            "severity": self.severity.name,
            "message": self.message,
            "issues": self.issues[:5],
            "validated_by": self.validated_by,
            "validated_at": self.validated_at.isoformat(),
        }


# ============================================================================
# BASE FAIR VALUE MEASUREMENT ENFORCER (ABSTRACT)
# ============================================================================

class BaseFairValueMeasurementEnforcer(ABC):
    """Base contract untuk Fair Value Measurement Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode."""
        pass

    @abstractmethod
    async def enforce_fair_value_measurement(
        self,
        asset_id: UUID,
        asset_class: AssetClass,
        legal_entity_id: UUID,
        fair_value: Decimal,
        measurement_date: datetime,
        hierarchy_level: FairValueHierarchy,
        valuation_technique: ValuationTechnique | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, FairValueMeasurementViolation | None]:
        """Enforce fair value measurement."""
        pass

    @abstractmethod
    async def enforce_recurring_measurement(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        measurement_frequency_days: int = 365,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, FairValueMeasurementViolation | None]:
        """Enforce recurring measurement requirement."""
        pass

    @abstractmethod
    async def record_observable_input(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        input_type: str,
        value: Any,
        source: str,
        user_id: str | None = None,
    ) -> None:
        """Record observable input."""
        pass

    @abstractmethod
    async def record_unobservable_input(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        input_type: str,
        value: Any,
        justification: str,
        user_id: str | None = None,
    ) -> None:
        """Record unobservable input."""
        pass

    @abstractmethod
    async def record_sensitivity_analysis(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        analysis: dict[str, Any],
        user_id: str | None = None,
    ) -> None:
        """Record sensitivity analysis."""
        pass

    @abstractmethod
    async def get_fair_value_history(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        limit: int = 10,
    ) -> list[FairValueMeasurement]:
        """Get fair value measurement history."""
        pass

    @abstractmethod
    async def get_market_price(
        self,
        asset_class: AssetClass,
        as_of: datetime,
        legal_entity_id: UUID,
    ) -> Decimal | None:
        """Get market price for asset class."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        min_severity: LawViolationSeverity = LawViolationSeverity.LOW,
    ) -> list[FairValueMeasurementViolation]:
        """Get violation history."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset state."""
        pass

    # ==================== CHECKER METHODS ====================

    @abstractmethod
    def check(self, context: dict) -> list[str]:
        """Sync check method untuk compliance checker."""
        pass

    @abstractmethod
    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseFairValueMeasurementEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseFairValueMeasurementEnforcer:
        """Clone instance."""
        pass

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        pass

    @abstractmethod
    def version(self) -> int:
        """Dapatkan versi."""
        pass

    @abstractmethod
    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        pass

    @abstractmethod
    def touch(self, touched_by: str) -> BaseFairValueMeasurementEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# FAIR VALUE MEASUREMENT ENFORCER (CONCRETE)
# ============================================================================

class FairValueMeasurementEnforcer(BaseFairValueMeasurementEnforcer):
    """
    Enforcer untuk hukum fair value measurement.

    Business context: Memastikan pengukuran nilai wajar sesuai standar
    akuntansi (PSAK 68/IFRS 13) untuk aset keuangan, properti investasi,
    aset biologis, dan liabilitas tertentu.
    """

    MARKET_PRICE_TOLERANCE = Decimal("0.02")  # 2%
    DEFAULT_MEASUREMENT_FREQUENCY_DAYS = 365
    LEVEL_3_DISCLOSURE_REQUIRED = True

    def __init__(
        self,
        market_data_repo: Any | None = None,
        valuation_repo: Any | None = None,
    ):
        self._market_data_repo = market_data_repo or _FallbackMarketDataRepository()
        self._valuation_repo = valuation_repo or _FallbackValuationRepository()
        self._measurement_history: list[FairValueMeasurement] = []
        self._validation_history: list[FairValueValidationResult] = []
        self._violation_history: list[FairValueMeasurementViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._strict_mode = True
        # Entity fields
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        asset_id = context.get("asset_id")
        asset_class = context.get("asset_class")
        fair_value = context.get("fair_value")
        measurement_date = context.get("measurement_date")
        hierarchy_level = context.get("hierarchy_level")

        if not asset_id:
            errors.append("asset_id is required")
        else:
            try:
                UUID(str(asset_id))
            except Exception:
                errors.append("asset_id must be a valid UUID")
        if not asset_class:
            errors.append("asset_class is required")
        else:
            try:
                AssetClass(asset_class)
            except ValueError:
                errors.append(f"asset_class '{asset_class}' is not a valid AssetClass")
        if fair_value is None:
            errors.append("fair_value is required")
        else:
            try:
                Decimal(str(fair_value))
            except Exception:
                errors.append("fair_value must be a valid number")
        if not measurement_date:
            errors.append("measurement_date is required")
        else:
            try:
                if isinstance(measurement_date, str):
                    datetime.fromisoformat(measurement_date)
                elif not isinstance(measurement_date, datetime):
                    errors.append("measurement_date must be a datetime or ISO string")
            except ValueError:
                errors.append("measurement_date must be a valid ISO format date")
        if hierarchy_level is not None:
            try:
                FairValueHierarchy(int(hierarchy_level))
            except (ValueError, TypeError):
                errors.append("hierarchy_level must be 1, 2, or 3")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if self.MARKET_PRICE_TOLERANCE < 0:
            errors.append("MARKET_PRICE_TOLERANCE must be non-negative")
        if self.DEFAULT_MEASUREMENT_FREQUENCY_DAYS <= 0:
            errors.append("DEFAULT_MEASUREMENT_FREQUENCY_DAYS must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "max_history": self._max_history,
                "measurements_count": len(self._measurement_history),
                "violations_count": len(self._violation_history),
                "market_price_tolerance": str(self.MARKET_PRICE_TOLERANCE),
                "default_measurement_frequency_days": self.DEFAULT_MEASUREMENT_FREQUENCY_DAYS,
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FairValueMeasurementEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._strict_mode = data.get("strict_mode", True)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> FairValueMeasurementEnforcer:
        """Clone instance."""
        new_instance = FairValueMeasurementEnforcer()
        new_instance._enabled = self._enabled
        new_instance._strict_mode = self._strict_mode
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "measurements_count": len(self._measurement_history),
                "violations_count": len(self._violation_history),
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> FairValueMeasurementEnforcer:
        """Touch instance (increment version)."""
        self._version += 1
        self._audit_trail.append({
            "action": "TOUCH",
            "performed_by": touched_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
        })
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "details": details,
        })

    # ==================== ORIGINAL BUSINESS METHODS ====================

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"Fair value measurement enforcer enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        self._strict_mode = strict
        self._record_audit("SET_STRICT_MODE", "system", {"strict": strict})
        logger.info(f"Fair value measurement enforcer strict mode: {strict}")

    async def enforce_fair_value_measurement(
        self,
        asset_id: UUID,
        asset_class: AssetClass,
        legal_entity_id: UUID,
        fair_value: Decimal,
        measurement_date: datetime,
        hierarchy_level: FairValueHierarchy,
        valuation_technique: ValuationTechnique | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, FairValueMeasurementViolation | None]:
        if not self._enabled:
            return True, None

        if user_id is None:
            user_id = get_current_user() or "unknown"

        # Level 1: Market price from active market
        if hierarchy_level == FairValueHierarchy.LEVEL_1:
            _, violation = await self._validate_level_1(
                asset_id=asset_id,
                asset_class=asset_class,
                legal_entity_id=legal_entity_id,
                fair_value=fair_value,
                measurement_date=measurement_date,
                user_id=user_id,
            )
            if violation:
                self._record_violation(violation)
                if raise_on_violation:
                    raise violation
                return False, violation

        # Level 2: Observable inputs
        elif hierarchy_level == FairValueHierarchy.LEVEL_2:
            _, violation = await self._validate_level_2(
                asset_id=asset_id,
                asset_class=asset_class,
                legal_entity_id=legal_entity_id,
                fair_value=fair_value,
                measurement_date=measurement_date,
                valuation_technique=valuation_technique,
                user_id=user_id,
            )
            if violation:
                self._record_violation(violation)
                if raise_on_violation:
                    raise violation
                return False, violation

        # Level 3: Unobservable inputs
        elif hierarchy_level == FairValueHierarchy.LEVEL_3:
            _, violation = await self._validate_level_3(
                asset_id=asset_id,
                asset_class=asset_class,
                legal_entity_id=legal_entity_id,
                fair_value=fair_value,
                measurement_date=measurement_date,
                valuation_technique=valuation_technique,
                user_id=user_id,
            )
            if violation:
                self._record_violation(violation)
                if raise_on_violation:
                    raise violation
                return False, violation

        # Record measurement
        measurement = await self._record_measurement(
            asset_id=asset_id,
            asset_class=asset_class,
            legal_entity_id=legal_entity_id,
            fair_value=fair_value,
            measurement_date=measurement_date,
            hierarchy_level=hierarchy_level,
            valuation_technique=valuation_technique,
            measured_by=user_id,
        )

        with self._lock:
            self._measurement_history.append(measurement)
            if len(self._measurement_history) > self._max_history:
                self._measurement_history = self._measurement_history[-self._max_history :]

        self._record_audit("FAIR_VALUE_MEASUREMENT", user_id, {
            "asset_id": str(asset_id),
            "asset_class": asset_class.value,
            "hierarchy_level": hierarchy_level.value,
        })
        logger.info(
            f"Fair value measurement recorded for {asset_id}: {fair_value} (Level {hierarchy_level.value})"
        )
        return True, None

    async def _validate_level_1(
        self,
        asset_id: UUID,
        asset_class: AssetClass,
        legal_entity_id: UUID,
        fair_value: Decimal,
        measurement_date: datetime,
        user_id: str,
    ) -> tuple[bool, FairValueMeasurementViolation | None]:
        market_price_data = await self._market_data_repo.get_market_price(
            asset_type=asset_class.value,
            as_of=measurement_date,
            legal_entity_id=legal_entity_id,
        )

        if not market_price_data:
            violation = FairValueMeasurementViolation(
                message=(
                    f"No active market price available for {asset_class.value} on {measurement_date.date()}"
                ),
                asset_id=str(asset_id),
                hierarchy_level=1,
                severity=LawViolationSeverity.HIGH,
                details={
                    "asset_id": str(asset_id),
                    "asset_class": asset_class.value,
                    "measurement_date": measurement_date.isoformat(),
                    "hierarchy": "LEVEL_1",
                },
            )
            return False, violation

        if not getattr(market_price_data, "is_active_market", False):
            violation = FairValueMeasurementViolation(
                message=(
                    f"Price for {asset_class.value} is not from active market "
                    f"(source: {getattr(market_price_data, 'source', 'unknown')})"
                ),
                asset_id=str(asset_id),
                hierarchy_level=1,
                severity=LawViolationSeverity.MEDIUM,
                details={
                    "asset_id": str(asset_id),
                    "source": getattr(market_price_data, "source", "unknown"),
                },
            )
            return False, violation

        market_price = getattr(market_price_data, "price", Decimal(0))
        if market_price == 0:
            violation = FairValueMeasurementViolation(
                message=f"Market price for {asset_class.value} is zero on {measurement_date.date()}",
                asset_id=str(asset_id),
                hierarchy_level=1,
                severity=LawViolationSeverity.HIGH,
                details={"market_price": str(market_price)},
            )
            return False, violation

        deviation = abs(fair_value - market_price) / market_price
        if deviation > self.MARKET_PRICE_TOLERANCE:
            violation = FairValueMeasurementViolation(
                message=(
                    f"Fair value {fair_value} deviates {deviation:.2%} from market price {market_price}"
                ),
                asset_id=str(asset_id),
                hierarchy_level=1,
                severity=LawViolationSeverity.HIGH,
                details={
                    "fair_value": str(fair_value),
                    "market_price": str(market_price),
                    "deviation": str(deviation),
                    "tolerance": str(self.MARKET_PRICE_TOLERANCE),
                },
            )
            return False, violation

        return True, None

    async def _validate_level_2(
        self,
        asset_id: UUID,
        asset_class: AssetClass,
        legal_entity_id: UUID,
        fair_value: Decimal,
        measurement_date: datetime,
        valuation_technique: ValuationTechnique | None,
        user_id: str,
    ) -> tuple[bool, FairValueMeasurementViolation | None]:
        if not valuation_technique:
            violation = FairValueMeasurementViolation(
                message="Level 2 fair value requires valuation technique specification",
                asset_id=str(asset_id),
                hierarchy_level=2,
                severity=LawViolationSeverity.MEDIUM,
                details={"asset_id": str(asset_id)},
            )
            return False, violation

        observable_inputs = await self._valuation_repo.get_observable_inputs(
            asset_id=asset_id,
            measurement_date=measurement_date,
        )

        if not observable_inputs:
            if self._strict_mode:
                violation = FairValueMeasurementViolation(
                    message="Level 2 fair value requires observable inputs",
                    asset_id=str(asset_id),
                    hierarchy_level=2,
                    severity=LawViolationSeverity.HIGH,
                    details={"asset_id": str(asset_id)},
                )
                return False, violation
            else:
                logger.warning(f"Level 2 fair value for asset {asset_id} missing observable inputs")

        return True, None

    async def _validate_level_3(
        self,
        asset_id: UUID,
        asset_class: AssetClass,
        legal_entity_id: UUID,
        fair_value: Decimal,
        measurement_date: datetime,
        valuation_technique: ValuationTechnique | None,
        user_id: str,
    ) -> tuple[bool, FairValueMeasurementViolation | None]:
        if not valuation_technique:
            violation = FairValueMeasurementViolation(
                message="Level 3 fair value requires valuation technique",
                asset_id=str(asset_id),
                hierarchy_level=3,
                severity=LawViolationSeverity.HIGH,
                details={"asset_id": str(asset_id)},
            )
            return False, violation

        sensitivity = await self._valuation_repo.get_sensitivity_analysis(
            asset_id=asset_id,
            measurement_date=measurement_date,
        )

        if not sensitivity:
            if self._strict_mode:
                violation = FairValueMeasurementViolation(
                    message="Level 3 fair value requires sensitivity analysis",
                    asset_id=str(asset_id),
                    hierarchy_level=3,
                    severity=LawViolationSeverity.HIGH,
                    details={"asset_id": str(asset_id)},
                )
                return False, violation
            else:
                logger.warning(
                    f"Level 3 fair value for asset {asset_id} missing sensitivity analysis"
                )
        else:
            required_keys = ["key_assumptions", "impact_of_changes"]
            missing = [k for k in required_keys if k not in (sensitivity or {})]
            if missing:
                violation = FairValueMeasurementViolation(
                    message=f"Level 3 sensitivity analysis missing required components: {missing}",
                    asset_id=str(asset_id),
                    hierarchy_level=3,
                    severity=LawViolationSeverity.MEDIUM,
                    details={"missing_components": missing},
                )
                return False, violation

        unobservable_inputs = await self._valuation_repo.get_unobservable_inputs(
            asset_id=asset_id,
            measurement_date=measurement_date,
        )
        if not unobservable_inputs:
            logger.warning(
                f"Level 3 fair value for asset {asset_id} missing unobservable inputs documentation"
            )

        return True, None

    async def enforce_recurring_measurement(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        measurement_frequency_days: int = DEFAULT_MEASUREMENT_FREQUENCY_DAYS,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, FairValueMeasurementViolation | None]:
        if not self._enabled:
            return True, None

        last_measurement_date = await self._valuation_repo.get_last_measurement(
            asset_id=asset_id,
            legal_entity_id=legal_entity_id,
        )

        if last_measurement_date:
            days_since = (datetime.now(UTC) - last_measurement_date).days
            if days_since > measurement_frequency_days:
                violation = FairValueMeasurementViolation(
                    message=(
                        f"Fair value measurement for asset {asset_id} overdue by "
                        f"{days_since - measurement_frequency_days} days"
                    ),
                    asset_id=str(asset_id),
                    hierarchy_level=0,
                    severity=LawViolationSeverity.MEDIUM,
                    details={
                        "asset_id": str(asset_id),
                        "last_measurement": last_measurement_date.isoformat(),
                        "days_since": days_since,
                        "required_frequency_days": measurement_frequency_days,
                    },
                )
                self._record_violation(violation)
                if raise_on_violation:
                    raise violation
                return False, violation

        return True, None

    async def _record_measurement(
        self,
        asset_id: UUID,
        asset_class: AssetClass,
        legal_entity_id: UUID,
        fair_value: Decimal,
        measurement_date: datetime,
        hierarchy_level: FairValueHierarchy,
        valuation_technique: ValuationTechnique | None,
        measured_by: str,
    ) -> FairValueMeasurement:
        measurement = FairValueMeasurement(
            measurement_id=uuid4(),
            asset_id=asset_id,
            asset_class=asset_class,
            legal_entity_id=legal_entity_id,
            fair_value=fair_value,
            measurement_date=measurement_date,
            hierarchy_level=hierarchy_level,
            valuation_technique=valuation_technique,
            measured_by=measured_by,
            measured_at=datetime.now(UTC),
            cryptographic_hash="",
        )
        measurement.cryptographic_hash = measurement.compute_hash()

        await self._valuation_repo.record_measurement(
            asset_id=asset_id,
            legal_entity_id=legal_entity_id,
            fair_value=fair_value,
            measurement_date=measurement_date,
            hierarchy_level=hierarchy_level.value,
            valuation_technique=valuation_technique.value if valuation_technique else None,
            measured_by=measured_by,
            measured_at=measurement.measured_at,
        )

        return measurement

    async def record_observable_input(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        input_type: str,
        value: Any,
        source: str,
        user_id: str | None = None,
    ) -> None:
        if user_id is None:
            user_id = get_current_user() or "system"
        await self._valuation_repo.add_observable_input(
            asset_id=asset_id,
            measurement_date=measurement_date,
            input_type=input_type,
            value=value,
            source=source,
        )
        self._record_audit("RECORD_OBSERVABLE_INPUT", user_id, {
            "asset_id": str(asset_id),
            "input_type": input_type,
        })
        logger.info(
            f"Observable input recorded for asset {asset_id}: {input_type}={value} from {source}"
        )

    async def record_unobservable_input(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        input_type: str,
        value: Any,
        justification: str,
        user_id: str | None = None,
    ) -> None:
        if user_id is None:
            user_id = get_current_user() or "system"
        await self._valuation_repo.add_unobservable_input(
            asset_id=asset_id,
            measurement_date=measurement_date,
            input_type=input_type,
            value=value,
            justification=justification,
        )
        self._record_audit("RECORD_UNOBSERVABLE_INPUT", user_id, {
            "asset_id": str(asset_id),
            "input_type": input_type,
        })
        logger.info(f"Unobservable input recorded for asset {asset_id}: {input_type}={value}")

    async def record_sensitivity_analysis(
        self,
        asset_id: UUID,
        measurement_date: datetime,
        analysis: dict[str, Any],
        user_id: str | None = None,
    ) -> None:
        if user_id is None:
            user_id = get_current_user() or "system"
        await self._valuation_repo.add_sensitivity_analysis(
            asset_id=asset_id,
            measurement_date=measurement_date,
            analysis=analysis,
        )
        self._record_audit("RECORD_SENSITIVITY_ANALYSIS", user_id, {
            "asset_id": str(asset_id),
        })
        logger.info(f"Sensitivity analysis recorded for asset {asset_id}")

    async def get_fair_value_history(
        self,
        asset_id: UUID,
        legal_entity_id: UUID,
        limit: int = 10,
    ) -> list[FairValueMeasurement]:
        measurements = await self._valuation_repo.get_measurement_history(
            asset_id=asset_id,
            legal_entity_id=legal_entity_id,
            limit=limit,
        )
        result = []
        for m in measurements:
            result.append(
                FairValueMeasurement(
                    measurement_id=uuid4(),
                    asset_id=asset_id,
                    asset_class=AssetClass.PROPERTY_PLANT_EQUIPMENT,
                    legal_entity_id=legal_entity_id,
                    fair_value=getattr(m, "fair_value", Decimal(0)),
                    measurement_date=getattr(m, "measurement_date", datetime.now(UTC)),
                    hierarchy_level=FairValueHierarchy.LEVEL_1,
                    valuation_technique=None,
                    measured_by=getattr(m, "measured_by", "unknown"),
                    measured_at=getattr(m, "measured_at", datetime.now(UTC)),
                )
            )
        return result

    async def get_market_price(
        self,
        asset_class: AssetClass,
        as_of: datetime,
        legal_entity_id: UUID,
    ) -> Decimal | None:
        price_data = await self._market_data_repo.get_market_price(
            asset_type=asset_class.value,
            as_of=as_of,
            legal_entity_id=legal_entity_id,
        )
        if price_data:
            return getattr(price_data, "price", None)
        return None

    def _record_violation(self, violation: FairValueMeasurementViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]
            # Use getattr to safely access attributes that may not exist
            user_id = getattr(violation, "user_id", None) or "system"
            message = getattr(violation, "message", str(violation))
            severity = getattr(violation, "severity", LawViolationSeverity.MEDIUM)
            self._record_audit(
                "VIOLATION",
                user_id,
                {
                    "message": message,
                    "severity": severity.name if hasattr(severity, "name") else str(severity),
                }
            )

    def get_violations(
        self,
        limit: int = 100,
        min_severity: LawViolationSeverity = LawViolationSeverity.LOW,
    ) -> list[FairValueMeasurementViolation]:
        with self._lock:
            result = [v for v in self._violation_history if v.severity.value >= min_severity.value]
            return result[-limit:]

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_measurements = len(self._measurement_history)
            total_violations = len(self._violation_history)

            if total_measurements == 0 and total_violations == 0:
                return {
                    "total_measurements": 0,
                    "total_violations": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                    "version": self._version,
                }

            by_hierarchy: dict[str, int] = {}  # type annotation added
            for m in self._measurement_history:
                level = f"LEVEL_{m.hierarchy_level.value}"
                by_hierarchy[level] = by_hierarchy.get(level, 0) + 1

            by_severity: dict[str, int] = {}  # type annotation added
            for v in self._violation_history:
                sev_name = v.severity.name if hasattr(v, "severity") else str(v.severity)
                by_severity[sev_name] = by_severity.get(sev_name, 0) + 1

            # Safely get timestamp from latest violation if exists
            latest_violation_ts = None
            if self._violation_history:
                latest_v = self._violation_history[-1]
                if hasattr(latest_v, "timestamp"):
                    latest_violation_ts = latest_v.timestamp.isoformat()

            return {
                "total_measurements": total_measurements,
                "total_violations": total_violations,
                "by_hierarchy": by_hierarchy,
                "by_severity": by_severity,
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "market_price_tolerance": str(self.MARKET_PRICE_TOLERANCE),
                "default_measurement_frequency_days": self.DEFAULT_MEASUREMENT_FREQUENCY_DAYS,
                "version": self._version,
                "latest_measurement": self._measurement_history[-1].measurement_date.isoformat()
                if self._measurement_history
                else None,
                "latest_violation": latest_violation_ts,
            }

    def reset(self) -> None:
        with self._lock:
            self._measurement_history = []
            self._validation_history = []
            self._violation_history = []
            self._enabled = True
            self._strict_mode = True
            self._version += 1
            self._audit_trail = []
            if hasattr(self._market_data_repo, "clear"):
                self._market_data_repo.clear()
            if hasattr(self._valuation_repo, "clear"):
                self._valuation_repo.clear()


# === 4. SINGLETON ACCESSOR ===

_fair_value_measurement_enforcer_instance: FairValueMeasurementEnforcer | None = None
_lock_instance = threading.Lock()


def get_fair_value_measurement_enforcer() -> FairValueMeasurementEnforcer:
    global _fair_value_measurement_enforcer_instance
    if _fair_value_measurement_enforcer_instance is None:
        with _lock_instance:
            if _fair_value_measurement_enforcer_instance is None:
                _fair_value_measurement_enforcer_instance = FairValueMeasurementEnforcer()
    return _fair_value_measurement_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "AssetClass",
    "FairValueHierarchy",
    "FairValueMeasurement",
    "FairValueMeasurementEnforcer",
    "FairValueValidationResult",
    "ValuationTechnique",
    "get_fair_value_measurement_enforcer",
]
