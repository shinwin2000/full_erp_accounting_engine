#!/usr/bin/env python3
"""
Module: amortization_schedule_engine.py
Layer: Domain / Intangible Asset
Responsibility: Mesin amortisasi aset tak berwujud dengan semua method.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from domain.intangible_asset.amortization_method_enum import AmortizationMethod

if TYPE_CHECKING:
    from domain.intangible_asset.asset_entity import IntangibleAssetEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class AmortizationEntry:
    period: int
    period_start: datetime
    period_end: datetime
    opening_nbv: Decimal
    amortization_amount: Decimal
    closing_nbv: Decimal
    accumulated_amortization: Decimal
    is_partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "opening_nbv": str(self.opening_nbv),
            "amortization_amount": str(self.amortization_amount),
            "closing_nbv": str(self.closing_nbv),
            "accumulated_amortization": str(self.accumulated_amortization),
            "is_partial": self.is_partial,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmortizationEntry:
        return cls(
            period=data["period"],
            period_start=datetime.fromisoformat(data["period_start"]),
            period_end=datetime.fromisoformat(data["period_end"]),
            opening_nbv=Decimal(data["opening_nbv"]),
            amortization_amount=Decimal(data["amortization_amount"]),
            closing_nbv=Decimal(data["closing_nbv"]),
            accumulated_amortization=Decimal(data["accumulated_amortization"]),
            is_partial=data.get("is_partial", False),
        )


@dataclass(frozen=True)
class AmortizationSchedule:
    asset_id: UUID
    asset_code: str
    asset_name: str
    acquisition_date: datetime
    cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    amortization_method: AmortizationMethod
    entries: list[AmortizationEntry] = field(default_factory=list)
    total_amortization: Decimal = Decimal(0)
    final_nbv: Decimal = Decimal(0)
    currency: str = "IDR"

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "acquisition_date": self.acquisition_date.isoformat(),
            "cost": str(self.cost),
            "residual_value": str(self.residual_value),
            "useful_life_years": self.useful_life_years,
            "amortization_method": self.amortization_method.value,
            "entries": [e.to_dict() for e in self.entries],
            "total_amortization": str(self.total_amortization),
            "final_nbv": str(self.final_nbv),
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmortizationSchedule:
        amortization_method = (
            AmortizationMethod.from_string(data["amortization_method"])
            or AmortizationMethod.STRAIGHT_LINE
        )
        entries = [AmortizationEntry.from_dict(e) for e in data.get("entries", [])]
        return cls(
            asset_id=UUID(data["asset_id"]),
            asset_code=data["asset_code"],
            asset_name=data["asset_name"],
            acquisition_date=datetime.fromisoformat(data["acquisition_date"]),
            cost=Decimal(data["cost"]),
            residual_value=Decimal(data["residual_value"]),
            useful_life_years=data["useful_life_years"],
            amortization_method=amortization_method,
            entries=entries,
            total_amortization=Decimal(data["total_amortization"]),
            final_nbv=Decimal(data["final_nbv"]),
            currency=data.get("currency", "IDR"),
        )


# ============================================================================
# Helper Functions
# ============================================================================


def _days_in_year(year: int) -> int:
    return 366 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 365


def _prorate_factor(asset_date: datetime, period_start: datetime, period_end: datetime) -> Decimal:
    if asset_date <= period_start:
        return Decimal("1")
    if asset_date >= period_end:
        return Decimal("0")
    total_days = (period_end - period_start).days
    if total_days <= 0:
        return Decimal("0")
    days_remaining = (period_end - asset_date).days
    return Decimal(days_remaining) / Decimal(total_days)


def _round_decimal(value: Decimal, places: int = 2) -> Decimal:
    if places == 0:
        quantize = Decimal("1")
    else:
        quantize = Decimal(f"1.{'0' * places}")
    return value.quantize(quantize, rounding=ROUND_HALF_EVEN)


# ============================================================================
# Amortization Schedule Engine
# ============================================================================


class AmortizationScheduleEngine:
    ROUNDING_PLACES = 2
    ROUNDING = ROUND_HALF_EVEN

    # ------------------------------------------------------------------------
    # Straight Line Method
    # ------------------------------------------------------------------------

    def calculate_straight_line(
        self,
        asset: IntangibleAssetEntity,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        include_partial_first_year: bool = True,
    ) -> AmortizationSchedule:
        """Calculate straight line amortization schedule."""
        if asset.has_indefinite_life:
            return AmortizationSchedule(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                residual_value=asset.residual_value,
                useful_life_years=asset.useful_life_years,
                amortization_method=AmortizationMethod.NO_AMORTIZATION,
                currency=asset.currency,
            )

        start_date = start_date or asset.acquisition_date
        end_date = end_date or datetime.now(UTC)

        amortizable_amount = asset.amortizable_amount
        if amortizable_amount <= 0:
            return AmortizationSchedule(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                residual_value=asset.residual_value,
                useful_life_years=asset.useful_life_years,
                amortization_method=AmortizationMethod.STRAIGHT_LINE,
                currency=asset.currency,
            )

        annual_amortization = amortizable_amount / Decimal(asset.useful_life_years)
        monthly_amortization = annual_amortization / Decimal(12)

        entries = []
        current_nbv = asset.cost
        accumulated = Decimal(0)
        period_counter = 1

        # Handle partial first year if acquisition date not at start of year
        first_year_start = datetime(asset.acquisition_date.year, 1, 1, tzinfo=UTC)
        if include_partial_first_year and asset.acquisition_date > first_year_start:
            year_end = datetime(asset.acquisition_date.year, 12, 31, tzinfo=UTC)
            days_in_year = _days_in_year(asset.acquisition_date.year)
            days_from_acq = (year_end - asset.acquisition_date).days + 1
            factor = Decimal(days_from_acq) / Decimal(days_in_year)
            amortization = _round_decimal(annual_amortization * factor)

            if amortization > 0 and amortization <= current_nbv - asset.residual_value:
                accumulated += amortization
                current_nbv -= amortization
                entries.append(
                    AmortizationEntry(
                        period=1,
                        period_start=asset.acquisition_date,
                        period_end=year_end,
                        opening_nbv=current_nbv + amortization,
                        amortization_amount=amortization,
                        closing_nbv=current_nbv,
                        accumulated_amortization=accumulated,
                        is_partial=True,
                    )
                )
            period_counter = 2
        else:
            period_counter = 1

        # Calculate full years
        for year in range(period_counter, period_counter + asset.useful_life_years):
            if current_nbv <= asset.residual_value + Decimal("0.01"):
                break

            year_start = datetime(asset.acquisition_date.year + (year - 1), 1, 1, tzinfo=UTC)
            year_end = datetime(asset.acquisition_date.year + (year - 1), 12, 31, tzinfo=UTC)

            if year_end > end_date and not entries:
                # First entry beyond end date, prorate
                days_in_year = _days_in_year(year_start.year)
                days_needed = (end_date - year_start).days
                if days_needed > 0:
                    factor = Decimal(days_needed) / Decimal(days_in_year)
                    amortization = _round_decimal(annual_amortization * factor)
                else:
                    break
            else:
                amortization = annual_amortization

            if current_nbv - amortization < asset.residual_value:
                amortization = current_nbv - asset.residual_value

            if amortization < 0:
                amortization = Decimal("0")

            if amortization > 0:
                accumulated += amortization
                current_nbv -= amortization
                entries.append(
                    AmortizationEntry(
                        period=year,
                        period_start=year_start,
                        period_end=min(year_end, end_date),
                        opening_nbv=current_nbv + amortization,
                        amortization_amount=amortization,
                        closing_nbv=current_nbv,
                        accumulated_amortization=accumulated,
                        is_partial=False,
                    )
                )

            if year_end >= end_date:
                break

        # Final adjustment if needed
        if current_nbv > asset.residual_value + Decimal("0.01"):
            last_amortization = current_nbv - asset.residual_value
            if last_amortization > 0:
                last_amortization = _round_decimal(last_amortization)
                accumulated += last_amortization
                current_nbv = asset.residual_value
                entries.append(
                    AmortizationEntry(
                        period=len(entries) + 1,
                        period_start=entries[-1].period_end if entries else asset.acquisition_date,
                        period_end=datetime(
                            asset.acquisition_date.year + asset.useful_life_years,
                            12,
                            31,
                            tzinfo=UTC,
                        ),
                        opening_nbv=current_nbv + last_amortization,
                        amortization_amount=last_amortization,
                        closing_nbv=current_nbv,
                        accumulated_amortization=accumulated,
                        is_partial=True,
                    )
                )

        return AmortizationSchedule(
            asset_id=asset.asset_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            acquisition_date=asset.acquisition_date,
            cost=asset.cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=AmortizationMethod.STRAIGHT_LINE,
            entries=entries,
            total_amortization=accumulated,
            final_nbv=current_nbv,
            currency=asset.currency,
        )

    # ------------------------------------------------------------------------
    # Declining Balance Method
    # ------------------------------------------------------------------------

    def calculate_declining_balance(
        self,
        asset: IntangibleAssetEntity,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        rate_multiplier: Decimal = Decimal("2"),
        switch_to_straight_line: bool = True,
    ) -> AmortizationSchedule:
        """Calculate declining balance amortization schedule."""
        if asset.has_indefinite_life:
            return AmortizationSchedule(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                residual_value=asset.residual_value,
                useful_life_years=asset.useful_life_years,
                amortization_method=AmortizationMethod.NO_AMORTIZATION,
                currency=asset.currency,
            )

        start_date = start_date or asset.acquisition_date
        end_date = end_date or datetime.now(UTC)

        if asset.useful_life_years <= 0:
            raise ValueError("Useful life must be positive for declining balance method")

        rate = rate_multiplier / Decimal(asset.useful_life_years)

        entries = []
        current_nbv = asset.cost
        accumulated = Decimal(0)
        period_counter = 1

        # Handle partial first year
        first_year_start = datetime(asset.acquisition_date.year, 1, 1, tzinfo=UTC)
        if asset.acquisition_date > first_year_start:
            year_end = datetime(asset.acquisition_date.year, 12, 31, tzinfo=UTC)
            days_in_year = _days_in_year(asset.acquisition_date.year)
            days_from_acq = (year_end - asset.acquisition_date).days + 1
            factor = Decimal(days_from_acq) / Decimal(days_in_year)
            amortization = current_nbv * rate * factor
            if amortization > current_nbv - asset.residual_value:
                amortization = current_nbv - asset.residual_value
            if amortization < 0:
                amortization = Decimal("0")
            amortization = _round_decimal(amortization)

            if amortization > 0:
                accumulated += amortization
                current_nbv -= amortization
                entries.append(
                    AmortizationEntry(
                        period=1,
                        period_start=asset.acquisition_date,
                        period_end=year_end,
                        opening_nbv=current_nbv + amortization,
                        amortization_amount=amortization,
                        closing_nbv=current_nbv,
                        accumulated_amortization=accumulated,
                        is_partial=True,
                    )
                )
            period_counter = 2

        # Calculate full years
        for year in range(period_counter, period_counter + asset.useful_life_years):
            if current_nbv <= asset.residual_value + Decimal("0.01"):
                break

            ddb_amortization = current_nbv * rate

            if switch_to_straight_line:
                remaining_life = asset.useful_life_years - (year - 1)
                if remaining_life > 0:
                    sl_amortization = (current_nbv - asset.residual_value) / Decimal(remaining_life)
                    sl_amortization = _round_decimal(sl_amortization)
                    amortization = max(ddb_amortization, sl_amortization)
                else:
                    amortization = ddb_amortization
            else:
                amortization = ddb_amortization

            if amortization > current_nbv - asset.residual_value:
                amortization = current_nbv - asset.residual_value

            if amortization < 0:
                amortization = Decimal("0")

            amortization = _round_decimal(amortization)

            if amortization > 0:
                accumulated += amortization
                current_nbv -= amortization
                year_start = datetime(asset.acquisition_date.year + (year - 1), 1, 1, tzinfo=UTC)
                year_end_dt = datetime(asset.acquisition_date.year + (year - 1), 12, 31, tzinfo=UTC)
                entries.append(
                    AmortizationEntry(
                        period=year,
                        period_start=year_start,
                        period_end=min(year_end_dt, end_date),
                        opening_nbv=current_nbv + amortization,
                        amortization_amount=amortization,
                        closing_nbv=current_nbv,
                        accumulated_amortization=accumulated,
                        is_partial=False,
                    )
                )

            if year_end_dt >= end_date:
                break

        # Final adjustment
        if current_nbv > asset.residual_value + Decimal("0.01"):
            last_amortization = current_nbv - asset.residual_value
            last_amortization = _round_decimal(last_amortization)
            if last_amortization > 0:
                accumulated += last_amortization
                current_nbv = asset.residual_value
                entries.append(
                    AmortizationEntry(
                        period=len(entries) + 1,
                        period_start=entries[-1].period_end if entries else asset.acquisition_date,
                        period_end=datetime(
                            asset.acquisition_date.year + asset.useful_life_years,
                            12,
                            31,
                            tzinfo=UTC,
                        ),
                        opening_nbv=current_nbv + last_amortization,
                        amortization_amount=last_amortization,
                        closing_nbv=current_nbv,
                        accumulated_amortization=accumulated,
                        is_partial=True,
                    )
                )

        return AmortizationSchedule(
            asset_id=asset.asset_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            acquisition_date=asset.acquisition_date,
            cost=asset.cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=AmortizationMethod.DECLINING_BALANCE,
            entries=entries,
            total_amortization=accumulated,
            final_nbv=current_nbv,
            currency=asset.currency,
        )

    # ------------------------------------------------------------------------
    # Units of Production Method
    # ------------------------------------------------------------------------

    def calculate_units_of_production(
        self,
        asset: IntangibleAssetEntity,
        total_units: Decimal,
        units_produced_by_period: list[tuple[datetime, datetime, Decimal]],
        start_date: datetime | None = None,
    ) -> AmortizationSchedule:
        """Calculate units of production amortization schedule."""
        if asset.has_indefinite_life:
            return AmortizationSchedule(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                residual_value=asset.residual_value,
                useful_life_years=asset.useful_life_years,
                amortization_method=AmortizationMethod.NO_AMORTIZATION,
                currency=asset.currency,
            )

        if total_units <= 0:
            raise ValueError("Total units must be positive")

        amortizable_amount = asset.amortizable_amount
        if amortizable_amount <= 0:
            return AmortizationSchedule(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                residual_value=asset.residual_value,
                useful_life_years=asset.useful_life_years,
                amortization_method=AmortizationMethod.UNITS_OF_PRODUCTION,
                currency=asset.currency,
            )

        rate_per_unit = amortizable_amount / total_units

        entries = []
        current_nbv = asset.cost
        accumulated = Decimal(0)
        period_counter = 1

        for period_start, period_end, units in units_produced_by_period:
            if period_end < asset.acquisition_date:
                continue
            if units <= 0:
                continue

            effective_start = max(period_start, asset.acquisition_date)
            amortization = rate_per_unit * units
            amortization = _round_decimal(amortization)

            if amortization > current_nbv - asset.residual_value:
                amortization = current_nbv - asset.residual_value

            if amortization < 0:
                amortization = Decimal("0")

            if amortization > 0:
                accumulated += amortization
                current_nbv -= amortization
                entries.append(
                    AmortizationEntry(
                        period=period_counter,
                        period_start=effective_start,
                        period_end=period_end,
                        opening_nbv=current_nbv + amortization,
                        amortization_amount=amortization,
                        closing_nbv=current_nbv,
                        accumulated_amortization=accumulated,
                        is_partial=False,
                    )
                )
                period_counter += 1

            if current_nbv <= asset.residual_value:
                break

        return AmortizationSchedule(
            asset_id=asset.asset_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            acquisition_date=asset.acquisition_date,
            cost=asset.cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=AmortizationMethod.UNITS_OF_PRODUCTION,
            entries=entries,
            total_amortization=accumulated,
            final_nbv=current_nbv,
            currency=asset.currency,
        )

    # ------------------------------------------------------------------------
    # Generic Methods
    # ------------------------------------------------------------------------

    def calculate_amortization(
        self,
        asset: IntangibleAssetEntity,
        as_of_date: datetime | None = None,
    ) -> Decimal:
        """Calculate accumulated amortization as of a specific date."""
        if asset.has_indefinite_life:
            return Decimal("0")

        as_of = as_of_date or datetime.now(UTC)

        if asset.amortization_method == AmortizationMethod.STRAIGHT_LINE:
            schedule = self.calculate_straight_line(asset, end_date=as_of)
        elif asset.amortization_method == AmortizationMethod.DECLINING_BALANCE:
            schedule = self.calculate_declining_balance(asset, end_date=as_of)
        elif asset.amortization_method == AmortizationMethod.UNITS_OF_PRODUCTION:
            raise ValueError("Units of production requires manual unit data")
        else:
            schedule = self.calculate_straight_line(asset, end_date=as_of)

        return schedule.total_amortization

    def calculate_amortization_as_of(
        self,
        asset: IntangibleAssetEntity,
        as_of_date: datetime,
    ) -> Decimal:
        """Calculate amortization amount as of a specific date (including partial period)."""
        if as_of_date < asset.acquisition_date:
            return Decimal("0")

        schedule = self.calculate_amortization(asset, as_of_date)
        total = Decimal("0")
        for entry in schedule.entries:
            if entry.period_end <= as_of_date:
                total += entry.amortization_amount
            elif entry.period_start <= as_of_date < entry.period_end:
                days_in_period = (entry.period_end - entry.period_start).days
                if days_in_period > 0:
                    days_elapsed = (as_of_date - entry.period_start).days
                    factor = Decimal(days_elapsed) / Decimal(days_in_period)
                    total += entry.amortization_amount * factor
                break
        return _round_decimal(total)

    def get_monthly_amortization(
        self,
        asset: IntangibleAssetEntity,
    ) -> Decimal:
        """Get monthly amortization amount (straight line)."""
        if not asset.is_amortizable or asset.has_indefinite_life:
            return Decimal("0")

        annual = asset.amortizable_amount / Decimal(asset.useful_life_years)
        monthly = annual / Decimal("12")
        return _round_decimal(monthly)

    def get_yearly_amortization(
        self,
        asset: IntangibleAssetEntity,
        year: int,
    ) -> Decimal:
        """Get amortization amount for a specific year."""
        schedule = self.calculate_amortization(asset)
        for entry in schedule.entries:
            if entry.period == year:
                return entry.amortization_amount
        return Decimal("0")

    def get_remaining_amortization(
        self,
        asset: IntangibleAssetEntity,
        as_of_date: datetime | None = None,
    ) -> Decimal:
        """Get remaining amortizable amount."""
        if asset.has_indefinite_life:
            return Decimal("0")
        accumulated = self.calculate_amortization_as_of(asset, as_of_date or datetime.now(UTC))
        remaining = asset.amortizable_amount - accumulated
        return max(Decimal("0"), remaining)

    def get_remaining_months(
        self,
        asset: IntangibleAssetEntity,
        as_of_date: datetime | None = None,
    ) -> int:
        """Get remaining months of amortization."""
        if asset.has_indefinite_life:
            return 0
        remaining = self.get_remaining_amortization(asset, as_of_date)
        monthly = self.get_monthly_amortization(asset)
        if monthly <= 0:
            return 0
        months = int((remaining / monthly).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN))
        return max(0, months)

    def is_fully_amortized(
        self,
        asset: IntangibleAssetEntity,
        as_of_date: datetime | None = None,
    ) -> bool:
        """Check if asset is fully amortized as of date."""
        if asset.has_indefinite_life:
            return False
        accumulated = self.calculate_amortization_as_of(asset, as_of_date or datetime.now(UTC))
        return accumulated >= asset.amortizable_amount - Decimal("0.01")

    def get_schedule_summary(self, schedule: AmortizationSchedule) -> dict[str, Any]:
        """Get summary of amortization schedule."""
        return {
            "asset_id": str(schedule.asset_id),
            "asset_code": schedule.asset_code,
            "asset_name": schedule.asset_name,
            "total_periods": len(schedule.entries),
            "total_amortization": str(schedule.total_amortization),
            "final_nbv": str(schedule.final_nbv),
            "avg_monthly": str(
                schedule.total_amortization / Decimal(max(1, len(schedule.entries) * 12))
            ),
        }


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_remaining_useful_life(
    asset: IntangibleAssetEntity,
    as_of_date: datetime,
) -> float:
    """Calculate remaining useful life in years."""
    if asset.has_indefinite_life:
        return 0.0
    if asset.acquisition_date >= as_of_date:
        return float(asset.useful_life_years)
    age_days = (as_of_date - asset.acquisition_date).days
    age_years = age_days / 365.25
    return max(0, asset.useful_life_years - age_years)


def is_fully_amortized(
    asset: IntangibleAssetEntity,
    as_of_date: datetime | None = None,
    engine: AmortizationScheduleEngine | None = None,
) -> bool:
    """Quick check if asset is fully amortized."""
    if engine is None:
        engine = AmortizationScheduleEngine()
    return engine.is_fully_amortized(asset, as_of_date)


def calculate_amortization_rate(asset: IntangibleAssetEntity) -> Decimal:
    """Calculate annual amortization rate percentage."""
    if asset.has_indefinite_life or asset.useful_life_years <= 0:
        return Decimal("0")
    return (Decimal("100") / Decimal(asset.useful_life_years)).quantize(Decimal("0.01"))


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AmortizationEntry",
    "AmortizationSchedule",
    "AmortizationScheduleEngine",
    "calculate_amortization_rate",
    "calculate_remaining_useful_life",
    "is_fully_amortized",
]
