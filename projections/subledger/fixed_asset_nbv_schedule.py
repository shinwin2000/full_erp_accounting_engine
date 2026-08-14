#!/usr/bin/env python3
"""
Module: fixed_asset_nbv_schedule.py
Layer: Projections (Subledger)
Responsibility: Membangun read model schedule Net Book Value (NBV) untuk aset tetap.
               Menyimpan NBV per periode (bulanan) untuk setiap aset, termasuk
               acquisition cost, accumulated depreciation, dan nilai sisa.
               Mendukung query untuk laporan NBV, depresiasi yang akan datang,
               dan analisis umur aset.
Dependencies:
- asyncio, logging, datetime, decimal, math
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.fixed_asset_table
- infrastructure.persistence_orm.depreciation_schedule_table (opsional)
- infrastructure.event_store.append_only_store (untuk rebuild dari event)
Audit: NBV schedule digunakan untuk laporan keuangan dan perhitungan pajak.
       Proses rebuild dicatat.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    and_,
    delete,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "fixed_asset_nbv_schedule"

# Depreciation methods
DEPRECIATION_METHOD_STRAIGHT_LINE = "straight_line"
DEPRECIATION_METHOD_DECLINING_BALANCE = "declining_balance"
DEPRECIATION_METHOD_SUM_OF_YEARS = "sum_of_years"
DEPRECIATION_METHOD_UNITS_OF_PRODUCTION = "units_of_production"

# ============================================================================
# ORM MODEL
# ============================================================================

Base = declarative_base()


class FixedAssetNBVScheduleTable(Base):
    __tablename__ = "fixed_asset_nbv_schedule"
    __table_args__ = (
        Index("idx_fa_nbv_asset", "asset_id"),
        Index("idx_fa_nbv_period", "period_date"),
        Index("idx_fa_nbv_legal_entity", "legal_entity_id"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    asset_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_date = Column(Date, nullable=False)
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    depreciation_amount = Column(Numeric(20, 2), nullable=False, default=0)
    accumulated_depreciation = Column(Numeric(20, 2), nullable=False, default=0)
    net_book_value = Column(Numeric(20, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="projected")  # posted or projected
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


# ============================================================================
# EXCEPTIONS
# ============================================================================


class FixedAssetNBVError(Exception):
    """Base exception untuk fixed asset NBV schedule projection."""

    pass


# ============================================================================
# NBV SCHEDULE PROJECTION
# ============================================================================


class FixedAssetNBVSchedule:
    """
    Read model NBV schedule untuk aset tetap.

    Fitur:
    - Menghitung depresiasi per periode berdasarkan metode
    - Menyimpan NBV per aset per periode (monthly)
    - Query NBV as of date tertentu
    - Mendukung rebuild dari event store atau dari master data
    - Analisis aset yang akan habis masa depresiasi
    """

    def __init__(self):
        self._session_factory = None
        self._depreciation_cache: dict[str, dict] = {}

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    def _calculate_depreciation_amount(
        self, asset: FixedAssetTable, period: int, total_periods: int, remaining_nbv: Decimal
    ) -> Decimal:
        """
        Menghitung depresiasi untuk satu periode berdasarkan metode.

        Args:
            asset: Aset tetap
            period: Nomor periode (1-based)
            total_periods: Total periode umur ekonomis (bulan)
            remaining_nbv: NBV awal periode (untuk declining balance)

        Returns:
            Depresiasi periode ini
        """
        acquisition_cost = asset.acquisition_cost
        residual_value = asset.residual_value
        depreciable_amount = acquisition_cost - residual_value

        method = asset.depreciation_method

        if method == DEPRECIATION_METHOD_STRAIGHT_LINE:
            return depreciable_amount / Decimal(total_periods)

        elif method == DEPRECIATION_METHOD_DECLINING_BALANCE:
            # Double-declining balance rate = 2 / useful life (years)
            # Convert to monthly rate
            useful_years = asset.useful_life_years
            annual_rate = (
                Decimal("2") / Decimal(useful_years) if useful_years > 0 else Decimal("0.2")
            )
            monthly_rate = annual_rate / Decimal("12")
            return remaining_nbv * monthly_rate

        elif method == DEPRECIATION_METHOD_SUM_OF_YEARS:
            # Annual depreciation, then divide by 12 for monthly
            remaining_life_years = total_periods / 12 - (period - 1) / 12
            sum_of_years = Decimal(total_periods / 12 * (total_periods / 12 + 1) / 2)
            annual_dep = depreciable_amount * Decimal(remaining_life_years) / sum_of_years
            return annual_dep / Decimal("12")

        else:  # units_of_production
            # This would need total estimated production; we'll use straight line as fallback
            return depreciable_amount / Decimal(total_periods)

    async def generate_schedule_for_asset(
        self, asset_id: UUID, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[dict]:
        """
        Menghasilkan NBV schedule untuk satu aset dari start_date hingga end_date.

        Args:
            asset_id: ID aset
            legal_entity_id: Legal entity
            start_date: Tanggal mulai schedule (biasanya acquisition_date)
            end_date: Tanggal akhir schedule (biasanya akhir masa manfaat atau sekarang)

        Returns:
            List schedule entries per month
        """
        async with await self._get_session() as session:
            asset_stmt = select(FixedAssetTable).where(
                FixedAssetTable.id == asset_id,
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
            )
            asset_result = await session.execute(asset_stmt)
            asset = asset_result.scalar_one_or_none()
            if not asset:
                raise FixedAssetNBVError(f"Asset {asset_id} not found")

            acquisition_cost = asset.acquisition_cost
            residual_value = asset.residual_value
            accumulated_depreciation_start = asset.accumulated_depreciation
            if not start_date:
                start_date = asset.acquisition_date

            # Calculate number of months between start and end
            months = (
                (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month) + 1
            )
            total_months = asset.useful_life_years * 12

            schedule = []
            current_nbv = acquisition_cost - accumulated_depreciation_start
            current_accumulated = accumulated_depreciation_start

            for i in range(months):
                period_date = start_date + timedelta(days=30 * i)  # approx month
                # Ensure we don't go beyond end_date
                if period_date > end_date:
                    break

                # Calculate depreciation for this month
                dep_amount = self._calculate_depreciation_amount(
                    asset, i + 1, total_months, current_nbv
                )
                # Cap depreciation so NBV doesn't go below residual
                if current_nbv - dep_amount < residual_value:
                    dep_amount = current_nbv - residual_value

                current_accumulated += dep_amount
                current_nbv -= dep_amount

                schedule.append(
                    {
                        "period_date": period_date.isoformat(),
                        "period_year": period_date.year,
                        "period_month": period_date.month,
                        "depreciation_amount": float(dep_amount),
                        "accumulated_depreciation": float(current_accumulated),
                        "net_book_value": float(current_nbv),
                        "status": "projected" if period_date > date.today() else "posted",
                    }
                )

                if current_nbv <= residual_value:
                    break

            return schedule

    async def rebuild_for_asset(self, asset_id: UUID, legal_entity_id: UUID) -> None:
        """
        Membangun ulang NBV schedule untuk satu aset (menyimpan ke tabel).
        """
        async with await self._get_session() as session:
            asset_stmt = select(FixedAssetTable).where(
                FixedAssetTable.id == asset_id, FixedAssetTable.legal_entity_id == legal_entity_id
            )
            asset_result = await session.execute(asset_stmt)
            asset = asset_result.scalar_one_or_none()
            if not asset:
                return

            end_date = datetime.now(UTC).date()
            start_date = asset.acquisition_date

            schedule = await self.generate_schedule_for_asset(
                asset_id, legal_entity_id, start_date, end_date
            )

            # Delete existing schedule for this asset
            await session.execute(
                delete(FixedAssetNBVScheduleTable).where(
                    FixedAssetNBVScheduleTable.asset_id == asset_id
                )
            )

            # Insert new schedule
            for entry in schedule:
                stmt = insert(FixedAssetNBVScheduleTable).values(
                    id=uuid4(),
                    asset_id=asset_id,
                    period_date=date.fromisoformat(entry["period_date"]),
                    period_year=entry["period_year"],
                    period_month=entry["period_month"],
                    depreciation_amount=Decimal(str(entry["depreciation_amount"])),
                    accumulated_depreciation=Decimal(str(entry["accumulated_depreciation"])),
                    net_book_value=Decimal(str(entry["net_book_value"])),
                    status=entry["status"],
                    created_at=datetime.now(UTC),
                )
                await session.execute(stmt)

            await session.commit()
            logger.info(f"NBV schedule rebuilt for asset {asset_id}")

    async def rebuild_all(self, legal_entity_id: UUID) -> dict[str, int]:
        """
        Membangun ulang NBV schedule untuk semua aset dalam legal entity.
        """
        async with await self._get_session() as session:
            stmt = select(FixedAssetTable.id).where(
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            asset_ids = result.scalars().all()

        success = 0
        errors = 0
        for asset_id in asset_ids:
            try:
                await self.rebuild_for_asset(asset_id, legal_entity_id)
                success += 1
            except Exception as e:
                logger.error(f"Failed to rebuild NBV schedule for asset {asset_id}: {e}")
                errors += 1

        logger.info(f"NBV schedule rebuild completed: {success} assets, {errors} errors")
        return {"success": success, "errors": errors}

    async def get_nbv_as_of_date(self, asset_id: UUID, as_of_date: date) -> Decimal | None:
        """
        Mendapatkan NBV aset pada tanggal tertentu.
        """
        async with await self._get_session() as session:
            stmt = (
                select(FixedAssetNBVScheduleTable.net_book_value)
                .where(
                    FixedAssetNBVScheduleTable.asset_id == asset_id,
                    FixedAssetNBVScheduleTable.period_date <= as_of_date,
                )
                .order_by(FixedAssetNBVScheduleTable.period_date.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            nbv = result.scalar_one_or_none()
            if nbv is not None:
                return Decimal(str(nbv))
            return None

    async def get_schedule(
        self, asset_id: UUID, from_date: date | None = None, to_date: date | None = None
    ) -> list[dict]:
        """
        Mendapatkan NBV schedule untuk aset dalam rentang tanggal.
        """
        async with await self._get_session() as session:
            conditions = [FixedAssetNBVScheduleTable.asset_id == asset_id]
            if from_date:
                conditions.append(FixedAssetNBVScheduleTable.period_date >= from_date)
            if to_date:
                conditions.append(FixedAssetNBVScheduleTable.period_date <= to_date)

            stmt = (
                select(FixedAssetNBVScheduleTable)
                .where(and_(*conditions))
                .order_by(FixedAssetNBVScheduleTable.period_date)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "period_date": row.period_date.isoformat(),
                    "depreciation_amount": float(row.depreciation_amount),
                    "accumulated_depreciation": float(row.accumulated_depreciation),
                    "net_book_value": float(row.net_book_value),
                    "status": row.status,
                }
                for row in rows
            ]

    async def get_assets_nearing_full_depreciation(
        self, legal_entity_id: UUID, threshold_months: int = 6
    ) -> list[dict]:
        """
        Mendapatkan aset yang akan habis masa depresiasi dalam threshold_months.
        """
        today = date.today()
        future_date = today + timedelta(days=30 * threshold_months)

        async with await self._get_session() as session:
            # Get assets where NBV > residual but will be <= residual within threshold
            # Simplified: get assets with remaining NBV > residual and projected end date within threshold
            stmt = (
                select(
                    FixedAssetTable.id,
                    FixedAssetTable.asset_code,
                    FixedAssetTable.asset_name,
                    FixedAssetTable.acquisition_cost,
                    FixedAssetTable.accumulated_depreciation,
                    FixedAssetTable.residual_value,
                    FixedAssetNBVScheduleTable.net_book_value.label("current_nbv"),
                    FixedAssetNBVScheduleTable.period_date,
                )
                .join(
                    FixedAssetNBVScheduleTable,
                    FixedAssetTable.id == FixedAssetNBVScheduleTable.asset_id,
                )
                .where(
                    FixedAssetTable.legal_entity_id == legal_entity_id,
                    FixedAssetTable.status == "active",
                    FixedAssetNBVScheduleTable.period_date == today,
                    FixedAssetTable.net_book_value > FixedAssetTable.residual_value,
                )
            )
            result = await session.execute(stmt)
            rows = result.all()

            assets_nearing = []
            for row in rows:
                # Check if NBV will drop to residual within threshold
                # Simplified: get schedule entry at future_date
                future_nbv = await self.get_nbv_as_of_date(row[0], future_date)
                if future_nbv is not None and future_nbv <= row[5]:
                    assets_nearing.append(
                        {
                            "asset_id": str(row[0]),
                            "asset_code": row[1],
                            "asset_name": row[2],
                            "current_nbv": float(row[6]),
                            "residual_value": float(row[5]),
                            "months_to_full_depreciation": threshold_months,  # placeholder
                        }
                    )
            return assets_nearing

    async def get_depreciation_forecast(
        self, legal_entity_id: UUID, months_ahead: int = 12
    ) -> list[dict]:
        """
        Mendapatkan forecast depresiasi bulanan untuk aset aktif.
        """
        forecast = []
        today = date.today()

        for month_offset in range(months_ahead):
            forecast_date = today + timedelta(days=30 * month_offset)
            total_depreciation = Decimal(0)

            async with await self._get_session() as session:
                stmt = select(FixedAssetNBVScheduleTable.depreciation_amount).where(
                    FixedAssetNBVScheduleTable.period_date == forecast_date,
                    FixedAssetNBVScheduleTable.asset_id.in_(
                        select(FixedAssetTable.id).where(
                            FixedAssetTable.legal_entity_id == legal_entity_id,
                            FixedAssetTable.status == "active",
                        )
                    ),
                )
                result = await session.execute(stmt)
                amounts = result.scalars().all()
                total_depreciation = sum(Decimal(str(a)) for a in amounts)

            forecast.append(
                {
                    "period_date": forecast_date.isoformat(),
                    "total_depreciation": float(total_depreciation),
                }
            )

        return forecast

    async def incremental_update(self, asset_id: UUID, legal_entity_id: UUID) -> None:
        """
        Incremental update ketika ada perubahan pada aset (revaluasi, disposal, dll).
        """
        await self.rebuild_for_asset(asset_id, legal_entity_id)
        logger.info(f"NBV schedule incrementally updated for asset {asset_id}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_fixed_asset_nbv_schedule: FixedAssetNBVSchedule | None = None


async def get_fixed_asset_nbv_schedule() -> FixedAssetNBVSchedule:
    """Get singleton instance of FixedAssetNBVSchedule."""
    global _fixed_asset_nbv_schedule
    if _fixed_asset_nbv_schedule is None:
        _fixed_asset_nbv_schedule = FixedAssetNBVSchedule()
    return _fixed_asset_nbv_schedule


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["FixedAssetNBVError", "FixedAssetNBVSchedule", "get_fixed_asset_nbv_schedule"]
