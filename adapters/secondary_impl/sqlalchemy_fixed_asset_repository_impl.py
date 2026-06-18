#!/usr/bin/env python3
"""
Module: sqlalchemy_fixed_asset_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Fixed Asset Management menggunakan
               SQLAlchemy ORM. Menyediakan operasi CRUD untuk aset tetap,
               depresiasi, revaluasi, disposal, impairment test, dan schedule
               depresiasi. Mendukung berbagai metode depresiasi: straight-line,
               declining balance, sum of years, units of production.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, func, and_, or_
- ports.primary.fixed_asset_repository_port (FixedAssetRepositoryPort)
- domain.fixed_asset.aggregate_root (FixedAssetAggregate, DepreciationSchedule)
- infrastructure.persistence_orm.fixed_asset_table, depreciation_schedule_table
- domain.shared_value_objects.money_vo (Money)
Audit: Setiap perubahan pada aset tetap (pembelian, depresiasi, revaluasi,
       disposal, impairment) dicatat di event store.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.fixed_asset.aggregate_root import FixedAssetAggregate

# Domain
from domain.fixed_asset.asset_entity import AssetStatus, DepreciationMethod
from domain.fixed_asset.depreciation_schedule_engine import DepreciationScheduleLine
from domain.fixed_asset.disposal_entity import Disposal
from domain.fixed_asset.impairment_tester import ImpairmentTest
from domain.fixed_asset.revaluation_entity import Revaluation

# Value objects
from domain.shared_value_objects.money_vo import Money
from infrastructure.persistence_orm.asset_category_table import AssetCategoryTable
from infrastructure.persistence_orm.depreciation_schedule_table import DepreciationScheduleTable
from infrastructure.persistence_orm.disposal_table import DisposalTable

# Infrastructure ORM
from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable
from infrastructure.persistence_orm.impairment_test_table import ImpairmentTestTable
from infrastructure.persistence_orm.revaluation_table import RevaluationTable

# Ports
from ports.primary.fixed_asset_repository_port import FixedAssetRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class FixedAssetRepositoryError(Exception):
    """Base exception untuk repository fixed asset."""

    pass


class DuplicateAssetCodeError(FixedAssetRepositoryError):
    """Kode aset sudah ada."""

    pass


class AssetNotFoundError(FixedAssetRepositoryError):
    """Aset tidak ditemukan."""

    pass


class DepreciationPeriodClosedError(FixedAssetRepositoryError):
    """Periode depresiasi sudah ditutup."""

    pass


class AssetAlreadyDisposedError(FixedAssetRepositoryError):
    """Aset sudah di-dispose."""

    pass


class OptimisticLockError(FixedAssetRepositoryError):
    """Version mismatch saat update."""

    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyFixedAssetRepository(FixedAssetRepositoryPort):
    """
    Implementasi repository Fixed Asset dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise FixedAssetRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain(self, table: FixedAssetTable) -> FixedAssetAggregate:
        """
        Mapping dari ORM model ke domain aggregate.
        """
        # Map enums
        depreciation_map = {
            "straight_line": DepreciationMethod.STRAIGHT_LINE,
            "declining_balance": DepreciationMethod.DECLINING_BALANCE,
            "sum_of_years": DepreciationMethod.SUM_OF_YEARS,
            "units_of_production": DepreciationMethod.UNITS_OF_PRODUCTION,
        }

        status_map = {
            "active": AssetStatus.ACTIVE,
            "fully_depreciated": AssetStatus.FULLY_DEPRECIATED,
            "disposed": AssetStatus.DISPOSED,
            "impaired": AssetStatus.IMPAIRED,
        }

        aggregate = FixedAssetAggregate(
            id=table.id,
            asset_code=table.asset_code,
            asset_name=table.asset_name,
            asset_category=table.asset_category,
            acquisition_date=table.acquisition_date,
            acquisition_cost=Money(
                amount=table.acquisition_cost, currency=table.currency_code or "IDR"
            ),
            residual_value=Money(
                amount=table.residual_value, currency=table.currency_code or "IDR"
            ),
            useful_life_years=table.useful_life_years,
            depreciation_method=depreciation_map.get(
                table.depreciation_method, DepreciationMethod.STRAIGHT_LINE
            ),
            depreciation_rate=Decimal(str(table.depreciation_rate))
            if table.depreciation_rate
            else None,
            accumulated_depreciation=Money(
                amount=table.accumulated_depreciation, currency=table.currency_code or "IDR"
            ),
            last_depreciation_date=table.last_depreciation_date,
            current_period_depreciation=Money(
                amount=table.current_period_depreciation, currency=table.currency_code or "IDR"
            ),
            location=table.location,
            responsible_party=table.responsible_party,
            supplier_id=table.supplier_id,
            purchase_order_id=table.purchase_order_id,
            invoice_id=table.invoice_id,
            serial_number=table.serial_number,
            is_active=table.is_active,
            status=status_map.get(table.status, AssetStatus.ACTIVE),
            notes=table.notes,
            revaluation_frequency=table.revaluation_frequency,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_id=table.legal_entity_id,
        )
        return aggregate

    async def _to_orm(self, aggregate: FixedAssetAggregate) -> FixedAssetTable:
        """Mapping dari domain ke ORM model."""
        depreciation_str = (
            aggregate.depreciation_method.value
            if hasattr(aggregate.depreciation_method, "value")
            else str(aggregate.depreciation_method)
        )
        status_str = (
            aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        )

        table = FixedAssetTable(
            id=aggregate.id,
            asset_code=aggregate.asset_code,
            asset_name=aggregate.asset_name,
            asset_category=aggregate.asset_category,
            acquisition_date=aggregate.acquisition_date,
            acquisition_cost=aggregate.acquisition_cost.amount,
            residual_value=aggregate.residual_value.amount,
            useful_life_years=aggregate.useful_life_years,
            depreciation_method=depreciation_str,
            depreciation_rate=float(aggregate.depreciation_rate)
            if aggregate.depreciation_rate
            else None,
            accumulated_depreciation=aggregate.accumulated_depreciation.amount,
            last_depreciation_date=aggregate.last_depreciation_date,
            current_period_depreciation=aggregate.current_period_depreciation.amount,
            location=aggregate.location,
            responsible_party=aggregate.responsible_party,
            supplier_id=aggregate.supplier_id,
            purchase_order_id=aggregate.purchase_order_id,
            invoice_id=aggregate.invoice_id,
            serial_number=aggregate.serial_number,
            is_active=aggregate.is_active,
            status=status_str,
            notes=aggregate.notes,
            revaluation_frequency=aggregate.revaluation_frequency,
            currency_code=aggregate.acquisition_cost.currency,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
        )
        return table

    def _to_domain_schedule_line(
        self, table: DepreciationScheduleTable
    ) -> DepreciationScheduleLine:
        """Mapping schedule line ORM ke domain."""
        return DepreciationScheduleLine(
            id=table.id,
            asset_id=table.asset_id,
            period=table.period,
            fiscal_year=table.fiscal_year,
            month=table.month,
            depreciation_amount=Money(
                amount=table.depreciation_amount, currency=table.currency or "IDR"
            ),
            accumulated_depreciation=Money(
                amount=table.accumulated_depreciation, currency=table.currency or "IDR"
            ),
            net_book_value=Money(amount=table.net_book_value, currency=table.currency or "IDR"),
            status=table.status,
            journal_id=table.journal_id,
            posted_at=table.posted_at,
        )

    # ========================================================================
    # ASSET CRUD METHODS
    # ========================================================================

    async def add_asset(self, asset: FixedAssetAggregate) -> None:
        """
        Menambahkan aset tetap baru.
        """
        try:
            # Cek duplikasi asset code
            exists = await self.exists_by_asset_code(asset.asset_code, asset.legal_entity_id)
            if exists:
                raise DuplicateAssetCodeError(
                    f"Asset code {asset.asset_code} already exists"
                )

            table = await self._to_orm(asset)
            self.session.add(table)
            await self.session.flush()
            logger.info(
                "Fixed asset added: %s (id=%s)",
                asset.asset_code,
                asset.id
            )

        except DuplicateAssetCodeError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add asset: %s", e)
            raise FixedAssetRepositoryError(f"Failed to add asset: {e}") from e

    async def get_asset_by_id(self, asset_id: UUID) -> FixedAssetAggregate | None:
        """Mengambil aset berdasarkan ID."""
        try:
            stmt = select(FixedAssetTable).where(
                FixedAssetTable.id == asset_id, FixedAssetTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None
            return self._to_domain(table)

        except Exception as e:
            logger.error("Failed to get asset by id %s: %s", asset_id, e)
            raise FixedAssetRepositoryError(f"Failed to get asset: {e}") from e

    async def get_asset_by_code(
        self, asset_code: str, legal_entity_id: UUID
    ) -> FixedAssetAggregate | None:
        """Mengambil aset berdasarkan kode aset."""
        try:
            stmt = select(FixedAssetTable).where(
                FixedAssetTable.asset_code == asset_code,
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None
            return self._to_domain(table)

        except Exception as e:
            logger.error("Failed to get asset by code %s: %s", asset_code, e)
            raise FixedAssetRepositoryError(f"Failed to get asset: {e}") from e

    async def update_asset(self, asset: FixedAssetAggregate) -> None:
        """Memperbarui data aset."""
        try:
            # Get current version
            stmt = select(FixedAssetTable.version).where(FixedAssetTable.id == asset.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise AssetNotFoundError(f"Asset {asset.id} not found")

            if current_version != asset.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {asset.version}, got {current_version}"
                )

            table = await self._to_orm(asset)
            table.version = asset.version + 1
            table.updated_at = datetime.utcnow()

            await self.session.merge(table)
            await self.session.flush()
            logger.info("Asset updated: %s", asset.asset_code)

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update asset %s: %s", asset.id, e)
            raise FixedAssetRepositoryError(f"Failed to update asset: {e}") from e

    async def delete_asset(self, asset_id: UUID) -> bool:
        """Soft delete aset."""
        try:
            stmt = (
                update(FixedAssetTable)
                .where(FixedAssetTable.id == asset_id)
                .values(deleted_at=datetime.utcnow(), is_active=False)
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount > 0

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete asset %s: %s", asset_id, e)
            raise FixedAssetRepositoryError(f"Failed to delete asset: {e}") from e

    async def list_assets(
        self,
        legal_entity_id: UUID,
        category: str | None = None,
        status: str | None = None,
        is_active: bool | None = True,
        location: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FixedAssetAggregate], int]:
        """List assets dengan filter dan pagination."""
        try:
            conditions = [
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
            ]

            if category:
                conditions.append(FixedAssetTable.asset_category == category)
            if status:
                conditions.append(FixedAssetTable.status == status)
            if is_active is not None:
                conditions.append(FixedAssetTable.is_active == is_active)
            if location:
                conditions.append(FixedAssetTable.location == location)
            if search:
                # Menggunakan func.concat untuk menghindari f-string dalam SQL
                conditions.append(
                    or_(
                        FixedAssetTable.asset_code.ilike(func.concat('%', search, '%')),
                        FixedAssetTable.asset_name.ilike(func.concat('%', search, '%')),
                    )
                )

            # Get total count
            count_stmt = select(func.count()).select_from(FixedAssetTable).where(and_(*conditions))
            count_result = await self.session.execute(count_stmt)
            total = count_result.scalar()

            # Get assets
            offset = (page - 1) * page_size
            stmt = (
                select(FixedAssetTable)
                .where(and_(*conditions))
                .order_by(FixedAssetTable.asset_code)
                .limit(page_size)
                .offset(offset)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            assets = [self._to_domain(table) for table in tables]
            return assets, total

        except Exception as e:
            logger.error("Failed to list assets: %s", e)
            raise FixedAssetRepositoryError(f"Failed to list assets: {e}") from e

    async def exists_by_asset_code(self, asset_code: str, legal_entity_id: UUID) -> bool:
        """Check apakah asset code sudah ada."""
        try:
            stmt = (
                select(func.count())
                .select_from(FixedAssetTable)
                .where(
                    FixedAssetTable.asset_code == asset_code,
                    FixedAssetTable.legal_entity_id == legal_entity_id,
                    FixedAssetTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            logger.error("Failed to check asset code %s: %s", asset_code, e)
            raise FixedAssetRepositoryError(f"Failed to check asset code: {e}") from e

    # ========================================================================
    # DEPRECIATION SCHEDULE METHODS
    # ========================================================================

    async def add_depreciation_schedule(
        self, schedule_lines: list[DepreciationScheduleLine]
    ) -> None:
        """Menambahkan schedule depresiasi untuk aset."""
        try:
            for line in schedule_lines:
                table = DepreciationScheduleTable(
                    id=line.id,
                    asset_id=line.asset_id,
                    period=line.period,
                    fiscal_year=line.fiscal_year,
                    month=line.month,
                    depreciation_amount=line.depreciation_amount.amount,
                    accumulated_depreciation=line.accumulated_depreciation.amount,
                    net_book_value=line.net_book_value.amount,
                    currency=line.depreciation_amount.currency,
                    status=line.status,
                    journal_id=line.journal_id,
                    posted_at=line.posted_at,
                )
                self.session.add(table)
            await self.session.flush()
            logger.info(
                "Depreciation schedule added for asset %s",
                schedule_lines[0].asset_id
            )

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add depreciation schedule: %s", e)
            raise FixedAssetRepositoryError(f"Failed to add schedule: {e}") from e

    async def get_depreciation_schedule(
        self, asset_id: UUID, fiscal_year: int | None = None, month: int | None = None
    ) -> list[DepreciationScheduleLine]:
        """Mendapatkan schedule depresiasi untuk aset."""
        try:
            conditions = [DepreciationScheduleTable.asset_id == asset_id]
            if fiscal_year:
                conditions.append(DepreciationScheduleTable.fiscal_year == fiscal_year)
            if month:
                conditions.append(DepreciationScheduleTable.month == month)

            stmt = (
                select(DepreciationScheduleTable)
                .where(and_(*conditions))
                .order_by(DepreciationScheduleTable.fiscal_year, DepreciationScheduleTable.month)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain_schedule_line(table) for table in tables]

        except Exception as e:
            logger.error(
                "Failed to get depreciation schedule for asset %s: %s",
                asset_id,
                e
            )
            raise FixedAssetRepositoryError(f"Failed to get schedule: {e}") from e

    async def update_depreciation_schedule_status(
        self, schedule_id: UUID, status: str, journal_id: UUID | None = None
    ) -> None:
        """Update status schedule line (posted/pending)."""
        try:
            values = {"status": status}
            if journal_id:
                values["journal_id"] = journal_id
                values["posted_at"] = datetime.utcnow()

            stmt = (
                update(DepreciationScheduleTable)
                .where(DepreciationScheduleTable.id == schedule_id)
                .values(**values)
            )
            await self.session.execute(stmt)
            await self.session.flush()

        except Exception as e:
            logger.error("Failed to update schedule status: %s", e)
            raise FixedAssetRepositoryError(f"Failed to update schedule: {e}") from e

    async def get_next_depreciation_period(self, asset_id: UUID) -> tuple[int, int] | None:
        """Mendapatkan periode depresiasi berikutnya yang belum diposting."""
        try:
            stmt = (
                select(DepreciationScheduleTable.fiscal_year, DepreciationScheduleTable.month)
                .where(
                    DepreciationScheduleTable.asset_id == asset_id,
                    DepreciationScheduleTable.status == "pending",
                )
                .order_by(DepreciationScheduleTable.fiscal_year, DepreciationScheduleTable.month)
                .limit(1)
            )

            result = await self.session.execute(stmt)
            row = result.first()

            if row:
                return (row.fiscal_year, row.month)
            return None

        except Exception as e:
            logger.error("Failed to get next depreciation period: %s", e)
            raise FixedAssetRepositoryError(f"Failed to get next period: {e}") from e

    async def update_asset_depreciation(
        self,
        asset_id: UUID,
        accumulated_depreciation: Decimal,
        last_depreciation_date: date,
        version: int,
    ) -> None:
        """Update accumulated depreciation dan last depreciation date."""
        try:
            stmt = (
                update(FixedAssetTable)
                .where(FixedAssetTable.id == asset_id, FixedAssetTable.version == version)
                .values(
                    accumulated_depreciation=accumulated_depreciation,
                    last_depreciation_date=last_depreciation_date,
                    version=version + 1,
                    updated_at=datetime.utcnow(),
                )
            )
            result = await self.session.execute(stmt)

            if result.rowcount == 0:
                raise OptimisticLockError(
                    f"Failed to update depreciation for asset {asset_id}"
                )

            await self.session.flush()

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update asset depreciation: %s", e)
            raise FixedAssetRepositoryError(f"Failed to update depreciation: {e}") from e

    # ========================================================================
    # REVALUATION METHODS
    # ========================================================================

    async def add_revaluation(self, revaluation: Revaluation) -> None:
        """Menambahkan record revaluasi aset."""
        try:
            table = RevaluationTable(
                id=revaluation.id,
                asset_id=revaluation.asset_id,
                revaluation_date=revaluation.revaluation_date,
                old_acquisition_cost=revaluation.old_acquisition_cost.amount,
                new_acquisition_cost=revaluation.new_acquisition_cost.amount,
                old_accumulated_depreciation=revaluation.old_accumulated_depreciation.amount,
                new_accumulated_depreciation=revaluation.new_accumulated_depreciation.amount,
                old_nbv=revaluation.old_nbv.amount,
                new_nbv=revaluation.new_nbv.amount,
                surplus_deficit=revaluation.surplus_deficit.amount,
                currency=revaluation.old_acquisition_cost.currency,
                reason=revaluation.reason,
                journal_id=revaluation.journal_id,
                created_by=revaluation.created_by,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Revaluation added for asset %s", revaluation.asset_id)

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add revaluation: %s", e)
            raise FixedAssetRepositoryError(f"Failed to add revaluation: {e}") from e

    # ========================================================================
    # DISPOSAL METHODS
    # ========================================================================

    async def add_disposal(self, disposal: Disposal) -> None:
        """Menambahkan record disposal aset."""
        try:
            table = DisposalTable(
                id=disposal.id,
                asset_id=disposal.asset_id,
                disposal_date=disposal.disposal_date,
                disposal_proceeds=disposal.disposal_proceeds.amount,
                disposal_cost=disposal.disposal_cost.amount,
                net_proceeds=disposal.net_proceeds.amount,
                nbv_at_disposal=disposal.nbv_at_disposal.amount,
                gain_loss=disposal.gain_loss.amount,
                currency=disposal.disposal_proceeds.currency,
                reason=disposal.reason,
                buyer_name=disposal.buyer_name,
                journal_id=disposal.journal_id,
                created_by=disposal.created_by,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)

            # Update asset status
            stmt = (
                update(FixedAssetTable)
                .where(FixedAssetTable.id == disposal.asset_id)
                .values(status="disposed", is_active=False, updated_at=datetime.utcnow())
            )
            await self.session.execute(stmt)
            await self.session.flush()
            logger.info("Disposal recorded for asset %s", disposal.asset_id)

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add disposal: %s", e)
            raise FixedAssetRepositoryError(f"Failed to add disposal: {e}") from e

    # ========================================================================
    # IMPAIRMENT METHODS
    # ========================================================================

    async def add_impairment_test(self, impairment: ImpairmentTest) -> None:
        """Menambahkan record impairment test."""
        try:
            table = ImpairmentTestTable(
                id=impairment.id,
                asset_id=impairment.asset_id,
                test_date=impairment.test_date,
                carrying_amount=impairment.carrying_amount.amount,
                recoverable_amount=impairment.recoverable_amount.amount,
                impairment_loss=impairment.impairment_loss.amount,
                currency=impairment.carrying_amount.currency,
                reason=impairment.reason,
                journal_id=impairment.journal_id,
                created_by=impairment.created_by,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)

            # Update asset status if impaired
            if impairment.impairment_loss.amount > 0:
                stmt = (
                    update(FixedAssetTable)
                    .where(FixedAssetTable.id == impairment.asset_id)
                    .values(status="impaired", updated_at=datetime.utcnow())
                )
                await self.session.execute(stmt)

            await self.session.flush()
            logger.info("Impairment test recorded for asset %s", impairment.asset_id)

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add impairment test: %s", e)
            raise FixedAssetRepositoryError(f"Failed to add impairment: {e}") from e

    # ========================================================================
    # CATEGORY METHODS
    # ========================================================================

    async def get_asset_categories(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Mendapatkan daftar kategori aset."""
        try:
            stmt = select(AssetCategoryTable).where(
                AssetCategoryTable.legal_entity_id == legal_entity_id,
                AssetCategoryTable.is_active == True,
            )
            result = await self.session.execute(stmt)
            categories = result.scalars().all()

            return [
                {
                    "id": c.id,
                    "code": c.code,
                    "name": c.name,
                    "default_useful_life": c.default_useful_life,
                    "default_depreciation_method": c.default_depreciation_method,
                }
                for c in categories
            ]

        except Exception as e:
            logger.error("Failed to get asset categories: %s", e)
            raise FixedAssetRepositoryError(f"Failed to get categories: {e}") from e

    # ========================================================================
    # SUMMARY METHODS
    # ========================================================================

    async def get_asset_summary(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """Mendapatkan summary aset tetap."""
        try:
            stmt = select(
                func.count(FixedAssetTable.id).label("total_assets"),
                func.coalesce(func.sum(FixedAssetTable.acquisition_cost), 0).label("total_cost"),
                func.coalesce(func.sum(FixedAssetTable.accumulated_depreciation), 0).label(
                    "total_depreciation"
                ),
                func.coalesce(func.sum(FixedAssetTable.current_period_depreciation), 0).label(
                    "current_depreciation"
                ),
            ).where(
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
                FixedAssetTable.status != "disposed",
            )

            result = await self.session.execute(stmt)
            row = result.first()

            total_cost = Decimal(str(row.total_cost)) if row.total_cost else Decimal(0)
            total_depreciation = (
                Decimal(str(row.total_depreciation)) if row.total_depreciation else Decimal(0)
            )

            return {
                "total_assets": row.total_assets or 0,
                "total_acquisition_cost": total_cost,
                "total_accumulated_depreciation": total_depreciation,
                "total_net_book_value": total_cost - total_depreciation,
                "monthly_depreciation_charge": Decimal(str(row.current_depreciation))
                if row.current_depreciation
                else Decimal(0),
            }

        except Exception as e:
            logger.error("Failed to get asset summary: %s", e)
            raise FixedAssetRepositoryError(f"Failed to get summary: {e}") from e

    # ========================================================================
    # GENERATE ASSET NUMBER
    # ========================================================================

    async def get_next_asset_number(self, prefix: str = "AST", year: int = None) -> str:
        """Generate asset number berikutnya."""
        if year is None:
            year = date.today().year

        try:
            # Gunakan func.concat untuk menghindari f-string dalam SQL
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = (
                select(FixedAssetTable.asset_code)
                .where(FixedAssetTable.asset_code.like(pattern))
                .order_by(FixedAssetTable.asset_code.desc())
                .limit(1)
            )

            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            return f"{prefix}-{year}-{seq:06d}"

        except Exception as e:
            logger.error("Failed to generate asset number: %s", e)
            raise FixedAssetRepositoryError(f"Failed to generate number: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AssetAlreadyDisposedError",
    "AssetNotFoundError",
    "DepreciationPeriodClosedError",
    "DuplicateAssetCodeError",
    "FixedAssetRepositoryError",
    "OptimisticLockError",
    "SQLAlchemyFixedAssetRepository",
]
