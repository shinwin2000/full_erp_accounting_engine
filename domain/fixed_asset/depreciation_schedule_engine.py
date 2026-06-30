#!/usr/bin/env python3
"""
Module: depreciation_schedule_engine.py

Layer: Domain / Fixed Asset

Responsibility:
    Engine for calculating depreciation schedules for fixed assets.
    Supports Straight Line, Double Declining Balance, Sum of Years' Digits,
    and Units of Production methods.
    All monetary values are handled as Decimal for precision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from domain.fixed_asset.asset_entity import FixedAsset

logger = logging.getLogger(__name__)


class DepreciationMethod(Enum):
    STRAIGHT_LINE = "straight_line"
    DOUBLE_DECLINING = "double_declining"
    SUM_OF_YEARS_DIGITS = "sum_of_years_digits"
    UNITS_OF_PRODUCTION = "units_of_production"

    def display_name(self) -> str:
        names = {
            DepreciationMethod.STRAIGHT_LINE: "Garis Lurus",
            DepreciationMethod.DOUBLE_DECLINING: "Saldo Menurun Ganda",
            DepreciationMethod.SUM_OF_YEARS_DIGITS: "Jumlah Angka Tahun",
            DepreciationMethod.UNITS_OF_PRODUCTION: "Unit Produksi",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> DepreciationMethod | None:
        for m in cls:
            if m.value == value.lower():
                return m
        return None


class DepreciationError(ValueError):
    pass


class InvalidDepreciationMethodError(DepreciationError):
    pass


class NegativeDepreciationError(DepreciationError):
    pass


class InsufficientUnitsError(DepreciationError):
    pass


@dataclass(frozen=True)
class DepreciationEntry:
    """Single depreciation entry for a period."""

    period: int
    period_start: date
    period_end: date
    opening_nbv: Decimal
    depreciation_amount: Decimal
    closing_nbv: Decimal
    accumulated_depreciation: Decimal
    is_partial: bool = False

    # __slots__ dihapus untuk menghindari konflik dengan field dataclass yang memiliki default

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "opening_nbv": str(self.opening_nbv),
            "depreciation_amount": str(self.depreciation_amount),
            "closing_nbv": str(self.closing_nbv),
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "is_partial": self.is_partial,
        }


@dataclass
class DepreciationSchedule:
    """Complete depreciation schedule for an asset."""

    asset_id: UUID
    asset_code: str
    asset_name: str
    acquisition_date: date
    cost: Decimal
    salvage_value: Decimal
    useful_life_years: int
    depreciation_method: DepreciationMethod
    entries: list[DepreciationEntry] = field(default_factory=list)
    total_depreciation: Decimal = Decimal("0")
    final_nbv: Decimal = Decimal("0")
    currency: str = "IDR"

    # __slots__ dihapus untuk menghindari konflik dengan field dataclass yang memiliki default

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "acquisition_date": self.acquisition_date.isoformat(),
            "cost": str(self.cost),
            "salvage_value": str(self.salvage_value),
            "useful_life_years": self.useful_life_years,
            "depreciation_method": self.depreciation_method.value,
            "entries": [e.to_dict() for e in self.entries],
            "total_depreciation": str(self.total_depreciation),
            "final_nbv": str(self.final_nbv),
            "currency": self.currency,
        }


def _days_in_year(year: int) -> int:
    """Return number of days in a given year (leap year aware)."""
    return 366 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 365


def _prorate_factor(asset_date: date, period_start: date, period_end: date) -> Decimal:
    """Calculate proration factor for partial period depreciation."""
    if asset_date <= period_start:
        return Decimal("1")
    if asset_date >= period_end:
        return Decimal("0")
    total_days = (period_end - period_start).days
    days_remaining = (period_end - asset_date).days
    if total_days <= 0:
        return Decimal("0")
    return Decimal(days_remaining) / Decimal(total_days)


def _round_decimal(value: Decimal, places: int = 2) -> Decimal:
    """Round Decimal to specified number of decimal places."""
    if places == 0:
        quantize = Decimal("1")
    else:
        quantize = Decimal(f"1.{'0' * places}")
    return value.quantize(quantize, rounding=ROUND_HALF_EVEN)


class DepreciationScheduleEngine:
    """
    Engine for calculating depreciation schedules.
    All monetary values are Decimal for precision.
    """

    ROUNDING_PLACES = 2
    ROUNDING = ROUND_HALF_EVEN

    # ------------------------------------------------------------------------
    # Straight Line Method
    # ------------------------------------------------------------------------

    def calculate_straight_line(
        self,
        asset: FixedAsset,
        start_date: date | None = None,
        end_date: date | None = None,
        include_partial_first_year: bool = True,
    ) -> DepreciationSchedule:
        cost = asset.acquisition_cost
        salvage = asset.salvage_value
        useful_life = asset.useful_life_years
        acquisition_date = asset.acquisition_date

        if useful_life <= 0:
            raise DepreciationError("Useful life must be positive")

        depreciable_amount = cost - salvage
        if depreciable_amount <= 0:
            return DepreciationSchedule(
                asset_id=asset.id,
                asset_code=asset.asset_code,
                asset_name=asset.name,
                acquisition_date=acquisition_date,
                cost=cost,
                salvage_value=salvage,
                useful_life_years=useful_life,
                depreciation_method=DepreciationMethod.STRAIGHT_LINE,
                currency=asset.currency,
            )

        annual_depreciation = (depreciable_amount / Decimal(useful_life)).quantize(
            Decimal("0.01"), rounding=self.ROUNDING
        )

        entries = []
        current_nbv = cost
        accumulated = Decimal("0")
        period_counter = 1

        first_year_start = date(acquisition_date.year, 1, 1)
        if include_partial_first_year and acquisition_date > first_year_start:
            year_end = date(acquisition_date.year, 12, 31)
            days_in_year = _days_in_year(acquisition_date.year)
            days_from_acq = (year_end - acquisition_date).days + 1
            factor = Decimal(days_from_acq) / Decimal(days_in_year)
            depreciation = _round_decimal(annual_depreciation * factor)

            if depreciation > 0 and depreciation <= current_nbv - salvage:
                accumulated += depreciation
                current_nbv -= depreciation
                entries.append(
                    DepreciationEntry(
                        period=1,
                        period_start=acquisition_date,
                        period_end=year_end,
                        opening_nbv=current_nbv + depreciation,
                        depreciation_amount=depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=True,
                    )
                )
            period_counter = 2
        else:
            period_counter = 1

        for year in range(period_counter, period_counter + useful_life):
            if current_nbv <= salvage + Decimal("0.01"):
                break
            year_start = date(acquisition_date.year + (year - 1), 1, 1)
            year_end = date(acquisition_date.year + (year - 1), 12, 31)

            depreciation = annual_depreciation
            if current_nbv - depreciation < salvage:
                depreciation = current_nbv - salvage

            if depreciation < 0:
                depreciation = Decimal("0")

            if depreciation > 0:
                accumulated += depreciation
                current_nbv -= depreciation
                entries.append(
                    DepreciationEntry(
                        period=year,
                        period_start=year_start,
                        period_end=year_end,
                        opening_nbv=current_nbv + depreciation,
                        depreciation_amount=depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=False,
                    )
                )

        if current_nbv > salvage + Decimal("0.01"):
            last_depreciation = current_nbv - salvage
            if last_depreciation > 0:
                accumulated += last_depreciation
                current_nbv = salvage
                entries.append(
                    DepreciationEntry(
                        period=len(entries) + 1,
                        period_start=entries[-1].period_end if entries else acquisition_date,
                        period_end=date(acquisition_date.year + useful_life, 12, 31),
                        opening_nbv=current_nbv + last_depreciation,
                        depreciation_amount=last_depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=True,
                    )
                )

        return DepreciationSchedule(
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            acquisition_date=acquisition_date,
            cost=cost,
            salvage_value=salvage,
            useful_life_years=useful_life,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            entries=entries,
            total_depreciation=accumulated,
            final_nbv=current_nbv,
            currency=asset.currency,
        )

    # ------------------------------------------------------------------------
    # Double Declining Balance Method
    # ------------------------------------------------------------------------

    def calculate_double_declining(
        self,
        asset: FixedAsset,
        start_date: date | None = None,
        end_date: date | None = None,
        multiplier: Decimal = Decimal("2"),
        switch_to_straight_line: bool = True,
    ) -> DepreciationSchedule:
        cost = asset.acquisition_cost
        salvage = asset.salvage_value
        useful_life = asset.useful_life_years
        acquisition_date = asset.acquisition_date

        if useful_life <= 0:
            raise DepreciationError("Useful life must be positive")
        if multiplier <= 0:
            raise DepreciationError("Multiplier must be positive")

        rate = multiplier / Decimal(useful_life)

        entries = []
        current_nbv = cost
        accumulated = Decimal("0")
        period_counter = 1

        first_year_start = date(acquisition_date.year, 1, 1)
        if acquisition_date > first_year_start:
            year_end = date(acquisition_date.year, 12, 31)
            days_in_year = _days_in_year(acquisition_date.year)
            days_from_acq = (year_end - acquisition_date).days + 1
            factor = Decimal(days_from_acq) / Decimal(days_in_year)
            depreciation = current_nbv * rate * factor
            if depreciation > current_nbv - salvage:
                depreciation = current_nbv - salvage
            if depreciation < 0:
                depreciation = Decimal("0")
            depreciation = _round_decimal(depreciation)

            if depreciation > 0:
                accumulated += depreciation
                current_nbv -= depreciation
                entries.append(
                    DepreciationEntry(
                        period=1,
                        period_start=acquisition_date,
                        period_end=year_end,
                        opening_nbv=current_nbv + depreciation,
                        depreciation_amount=depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=True,
                    )
                )
            period_counter = 2

        for year in range(period_counter, period_counter + useful_life):
            if current_nbv <= salvage + Decimal("0.01"):
                break

            ddb_depreciation = current_nbv * rate

            if switch_to_straight_line:
                remaining_life = useful_life - (year - 1)
                if remaining_life > 0:
                    sl_depreciation = (current_nbv - salvage) / Decimal(remaining_life)
                    sl_depreciation = _round_decimal(sl_depreciation)
                    depreciation = max(ddb_depreciation, sl_depreciation)
                else:
                    depreciation = ddb_depreciation
            else:
                depreciation = ddb_depreciation

            if depreciation > current_nbv - salvage:
                depreciation = current_nbv - salvage

            if depreciation < 0:
                depreciation = Decimal("0")

            depreciation = _round_decimal(depreciation)

            if depreciation > 0:
                accumulated += depreciation
                current_nbv -= depreciation
                year_start = date(acquisition_date.year + (year - 1), 1, 1)
                year_end = date(acquisition_date.year + (year - 1), 12, 31)
                entries.append(
                    DepreciationEntry(
                        period=year,
                        period_start=year_start,
                        period_end=year_end,
                        opening_nbv=current_nbv + depreciation,
                        depreciation_amount=depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=False,
                    )
                )
            else:
                break

        if current_nbv > salvage + Decimal("0.01"):
            last_depreciation = current_nbv - salvage
            last_depreciation = _round_decimal(last_depreciation)
            accumulated += last_depreciation
            current_nbv = salvage
            entries.append(
                DepreciationEntry(
                    period=len(entries) + 1,
                    period_start=entries[-1].period_end if entries else acquisition_date,
                    period_end=date(acquisition_date.year + useful_life, 12, 31),
                    opening_nbv=current_nbv + last_depreciation,
                    depreciation_amount=last_depreciation,
                    closing_nbv=current_nbv,
                    accumulated_depreciation=accumulated,
                    is_partial=True,
                )
            )

        return DepreciationSchedule(
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            acquisition_date=acquisition_date,
            cost=cost,
            salvage_value=salvage,
            useful_life_years=useful_life,
            depreciation_method=DepreciationMethod.DOUBLE_DECLINING,
            entries=entries,
            total_depreciation=accumulated,
            final_nbv=current_nbv,
            currency=asset.currency,
        )

    # ------------------------------------------------------------------------
    # Sum of Years' Digits Method
    # ------------------------------------------------------------------------

    def calculate_sum_of_years_digits(
        self,
        asset: FixedAsset,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DepreciationSchedule:
        cost = asset.acquisition_cost
        salvage = asset.salvage_value
        useful_life = asset.useful_life_years
        acquisition_date = asset.acquisition_date

        if useful_life <= 0:
            raise DepreciationError("Useful life must be positive")

        depreciable_amount = cost - salvage
        if depreciable_amount <= 0:
            return DepreciationSchedule(
                asset_id=asset.id,
                asset_code=asset.asset_code,
                asset_name=asset.name,
                acquisition_date=acquisition_date,
                cost=cost,
                salvage_value=salvage,
                useful_life_years=useful_life,
                depreciation_method=DepreciationMethod.SUM_OF_YEARS_DIGITS,
                currency=asset.currency,
            )

        sum_of_years = useful_life * (useful_life + 1) // 2

        entries = []
        current_nbv = cost
        accumulated = Decimal("0")
        period_counter = 1

        first_year_start = date(acquisition_date.year, 1, 1)
        if acquisition_date > first_year_start:
            year_end = date(acquisition_date.year, 12, 31)
            days_in_year = _days_in_year(acquisition_date.year)
            days_from_acq = (year_end - acquisition_date).days + 1
            factor = Decimal(days_from_acq) / Decimal(days_in_year)

            fraction = Decimal(useful_life) / Decimal(sum_of_years)
            full_depreciation = depreciable_amount * fraction
            depreciation = full_depreciation * factor
            depreciation = _round_decimal(depreciation)

            if depreciation > 0 and depreciation <= current_nbv - salvage:
                accumulated += depreciation
                current_nbv -= depreciation
                entries.append(
                    DepreciationEntry(
                        period=1,
                        period_start=acquisition_date,
                        period_end=year_end,
                        opening_nbv=current_nbv + depreciation,
                        depreciation_amount=depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=True,
                    )
                )
            period_counter = 2

        for year in range(period_counter, useful_life + 1):
            if current_nbv <= salvage + Decimal("0.01"):
                break

            remaining_life = useful_life - (year - 1)
            fraction = Decimal(remaining_life) / Decimal(sum_of_years)
            depreciation = depreciable_amount * fraction
            depreciation = _round_decimal(depreciation)

            if depreciation > current_nbv - salvage:
                depreciation = current_nbv - salvage

            if depreciation < 0:
                depreciation = Decimal("0")

            if depreciation > 0:
                accumulated += depreciation
                current_nbv -= depreciation
                year_start = date(acquisition_date.year + (year - 1), 1, 1)
                year_end = date(acquisition_date.year + (year - 1), 12, 31)
                entries.append(
                    DepreciationEntry(
                        period=year,
                        period_start=year_start,
                        period_end=year_end,
                        opening_nbv=current_nbv + depreciation,
                        depreciation_amount=depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=False,
                    )
                )

        if current_nbv > salvage + Decimal("0.01"):
            last_depreciation = current_nbv - salvage
            last_depreciation = _round_decimal(last_depreciation)
            accumulated += last_depreciation
            current_nbv = salvage
            entries.append(
                DepreciationEntry(
                    period=len(entries) + 1,
                    period_start=entries[-1].period_end if entries else acquisition_date,
                    period_end=date(acquisition_date.year + useful_life, 12, 31),
                    opening_nbv=current_nbv + last_depreciation,
                    depreciation_amount=last_depreciation,
                    closing_nbv=current_nbv,
                    accumulated_depreciation=accumulated,
                    is_partial=True,
                )
            )

        return DepreciationSchedule(
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            acquisition_date=acquisition_date,
            cost=cost,
            salvage_value=salvage,
            useful_life_years=useful_life,
            depreciation_method=DepreciationMethod.SUM_OF_YEARS_DIGITS,
            entries=entries,
            total_depreciation=accumulated,
            final_nbv=current_nbv,
            currency=asset.currency,
        )

    # ------------------------------------------------------------------------
    # Units of Production Method
    # ------------------------------------------------------------------------

    def calculate_units_of_production(
        self,
        asset: FixedAsset,
        total_units: Decimal,
        units_produced_by_period: list[tuple[date, date, Decimal]],
        start_date: date | None = None,
    ) -> DepreciationSchedule:
        cost = asset.acquisition_cost
        salvage = asset.salvage_value
        acquisition_date = asset.acquisition_date

        if total_units <= 0:
            raise DepreciationError("Total units must be positive")

        depreciable_amount = cost - salvage
        rate_per_unit = depreciable_amount / total_units

        entries = []
        current_nbv = cost
        accumulated = Decimal("0")
        period_counter = 1

        for period_start, period_end, units in units_produced_by_period:
            if period_end < acquisition_date:
                continue
            if units <= 0:
                continue

            effective_start = max(period_start, acquisition_date)
            depreciation = rate_per_unit * units
            depreciation = _round_decimal(depreciation)

            if depreciation > current_nbv - salvage:
                depreciation = current_nbv - salvage

            if depreciation < 0:
                depreciation = Decimal("0")

            if depreciation > 0:
                accumulated += depreciation
                current_nbv -= depreciation
                entries.append(
                    DepreciationEntry(
                        period=period_counter,
                        period_start=effective_start,
                        period_end=period_end,
                        opening_nbv=current_nbv + depreciation,
                        depreciation_amount=depreciation,
                        closing_nbv=current_nbv,
                        accumulated_depreciation=accumulated,
                        is_partial=False,
                    )
                )
                period_counter += 1

            if current_nbv <= salvage:
                break

        return DepreciationSchedule(
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            acquisition_date=acquisition_date,
            cost=cost,
            salvage_value=salvage,
            useful_life_years=asset.useful_life_years,
            depreciation_method=DepreciationMethod.UNITS_OF_PRODUCTION,
            entries=entries,
            total_depreciation=accumulated,
            final_nbv=current_nbv,
            currency=asset.currency,
        )

    # ------------------------------------------------------------------------
    # Generic Methods
    # ------------------------------------------------------------------------

    def calculate_depreciation(
        self,
        asset: FixedAsset,
        as_of_date: date | None = None,
    ) -> DepreciationSchedule:
        method_str = asset.depreciation_method
        method = DepreciationMethod.from_string(method_str)
        if method is None:
            raise InvalidDepreciationMethodError(f"Unknown depreciation method: {method_str}")

        if method == DepreciationMethod.STRAIGHT_LINE:
            return self.calculate_straight_line(asset, end_date=as_of_date)
        elif method == DepreciationMethod.DOUBLE_DECLINING:
            return self.calculate_double_declining(asset, end_date=as_of_date)
        elif method == DepreciationMethod.SUM_OF_YEARS_DIGITS:
            return self.calculate_sum_of_years_digits(asset, end_date=as_of_date)
        elif method == DepreciationMethod.UNITS_OF_PRODUCTION:
            raise DepreciationError("Units of production requires manual unit data")
        else:
            raise InvalidDepreciationMethodError(f"Unknown depreciation method: {method}")

    def calculate_depreciation_as_of(
        self,
        asset: FixedAsset,
        as_of_date: date,
    ) -> Decimal:
        if as_of_date < asset.acquisition_date:
            return Decimal("0")
        schedule = self.calculate_depreciation(asset, as_of_date)
        total = Decimal("0")
        for entry in schedule.entries:
            if entry.period_end <= as_of_date:
                total += entry.depreciation_amount
            elif entry.period_start <= as_of_date < entry.period_end:
                days_in_period = (entry.period_end - entry.period_start).days
                if days_in_period > 0:
                    days_elapsed = (as_of_date - entry.period_start).days
                    factor = Decimal(days_elapsed) / Decimal(days_in_period)
                    total += entry.depreciation_amount * factor
                break
        return _round_decimal(total)

    def get_monthly_depreciation(
        self,
        asset: FixedAsset,
    ) -> Decimal:
        if not asset.is_depreciable or asset.is_fully_depreciated:
            return Decimal("0")
        if asset.depreciation_method == DepreciationMethod.STRAIGHT_LINE.value:
            annual = (asset.acquisition_cost - asset.salvage_value) / Decimal(
                asset.useful_life_years
            )
            return _round_decimal(annual / Decimal("12"))
        else:
            schedule = self.calculate_depreciation(asset)
            total_dep = schedule.total_depreciation
            months = asset.useful_life_years * 12
            if months <= 0:
                return Decimal("0")
            return _round_decimal(total_dep / Decimal(months))

    def get_yearly_depreciation(
        self,
        asset: FixedAsset,
        year: int,
    ) -> Decimal:
        schedule = self.calculate_depreciation(asset)
        for entry in schedule.entries:
            if entry.period == year:
                return entry.depreciation_amount
        return Decimal("0")


def calculate_remaining_useful_life(
    asset: FixedAsset,
    as_of_date: date,
) -> float:
    """
    Calculate remaining useful life in years (as float for display).
    This is not a monetary value, so float is acceptable.
    """
    if asset.acquisition_date >= as_of_date:
        return float(asset.useful_life_years)
    age_days = (as_of_date - asset.acquisition_date).days
    age_years = age_days / 365.25
    return max(0, asset.useful_life_years - age_years)


def is_fully_depreciated(
    asset: FixedAsset,
    as_of_date: date | None = None,
    engine: DepreciationScheduleEngine | None = None,
) -> bool:
    if engine is None:
        engine = DepreciationScheduleEngine()
    accumulated = engine.calculate_depreciation_as_of(asset, as_of_date or date.today())
    depreciable_amount = asset.acquisition_cost - asset.salvage_value
    return accumulated >= depreciable_amount - Decimal("0.01")


# === ALIAS FOR REPOSITORY COMPATIBILITY ===
DepreciationScheduleLine = DepreciationEntry

# === ALIAS FOR TEST COMPATIBILITY ===
DepreciationEngine = DepreciationScheduleEngine


__all__ = [
    "DepreciationEntry",
    "DepreciationError",
    "DepreciationMethod",
    "DepreciationSchedule",
    "DepreciationScheduleEngine",
    "DepreciationScheduleLine",
    "DepreciationEngine",  
    "InvalidDepreciationMethodError",
    "calculate_remaining_useful_life",
    "is_fully_depreciated",
]