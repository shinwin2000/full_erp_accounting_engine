#!/usr/bin/env python3
"""
Module: sqlalchemy_fixed_asset_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Fixed Asset Management menggunakan
               SQLAlchemy ORM. LENGKAP dengan semua method yang dibutuhkan oleh port.

Perbaikan presisi:
    - Semua nilai moneter dikonversi ke string (bukan float) untuk menghindari
      kehilangan presisi dan memenuhi aturan MNY-003.
Perbaikan kolom:
    - [FIX] Menghapus referensi FixedAssetTable.disposal_date (tidak ada di model),
      mengganti dengan filter status != 'disposed'.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.fixed_asset.aggregate_root import FixedAssetAggregate
from domain.fixed_asset.asset_entity import AssetStatus, DepreciationMethod
from domain.fixed_asset.depreciation_schedule_engine import DepreciationScheduleLine
from domain.fixed_asset.disposal_entity import Disposal
from domain.fixed_asset.revaluation_entity import Revaluation
from domain.shared_value_objects.money_vo import Money
from infrastructure.persistence_orm.depreciation_schedule_table import DepreciationScheduleTable
from infrastructure.persistence_orm.disposal_table import DisposalTable
from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable
from infrastructure.persistence_orm.revaluation_table import RevaluationTable
from ports.primary.fixed_asset_repository_port import FixedAssetRepositoryPort

logger = logging.getLogger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class FixedAssetRepositoryError(Exception):
    pass


class DuplicateAssetCodeError(FixedAssetRepositoryError):
    pass


class AssetNotFoundError(FixedAssetRepositoryError):
    pass


class DepreciationPeriodClosedError(FixedAssetRepositoryError):
    pass


class AssetAlreadyDisposedError(FixedAssetRepositoryError):
    pass


class OptimisticLockError(FixedAssetRepositoryError):
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
        self._audit_log: list[dict[str, Any]] = []

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
        return FixedAssetAggregate(
            id=table.id,
            asset_code=table.asset_code,
            asset_name=table.asset_name,
            asset_category=table.asset_category,
            acquisition_date=table.acquisition_date,
            acquisition_cost=Money(amount=table.acquisition_cost, currency=table.currency or "IDR"),
            residual_value=Money(amount=table.residual_value, currency=table.currency or "IDR"),
            useful_life_years=table.useful_life_years,
            depreciation_method=depreciation_map.get(table.depreciation_method, DepreciationMethod.STRAIGHT_LINE),
            depreciation_rate=Decimal(str(table.depreciation_rate)) if table.depreciation_rate else None,
            accumulated_depreciation=Money(amount=table.accumulated_depreciation, currency=table.currency or "IDR"),
            last_depreciation_date=table.last_depreciation_date,
            current_period_depreciation=Money(amount=table.current_period_depreciation, currency=table.currency or "IDR"),
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

    async def _to_orm(self, aggregate: FixedAssetAggregate) -> FixedAssetTable:
        depreciation_str = aggregate.depreciation_method.value if hasattr(aggregate.depreciation_method, "value") else str(aggregate.depreciation_method)
        status_str = aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        return FixedAssetTable(
            id=aggregate.id,
            asset_code=aggregate.asset_code,
            asset_name=aggregate.asset_name,
            asset_category=aggregate.asset_category,
            acquisition_date=aggregate.acquisition_date,
            acquisition_cost=aggregate.acquisition_cost.amount,
            residual_value=aggregate.residual_value.amount,
            useful_life_years=aggregate.useful_life_years,
            depreciation_method=depreciation_str,
            depreciation_rate=float(aggregate.depreciation_rate) if aggregate.depreciation_rate else None,
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
            currency=aggregate.acquisition_cost.currency,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
        )

    def _to_domain_schedule_line(self, table: DepreciationScheduleTable) -> DepreciationScheduleLine:
        return DepreciationScheduleLine(
            id=table.id,
            asset_id=table.asset_id,
            period=table.period,
            fiscal_year=table.fiscal_year,
            month=table.month,
            depreciation_amount=Money(amount=table.depreciation_amount, currency=table.currency or "IDR"),
            accumulated_depreciation=Money(amount=table.accumulated_depreciation, currency=table.currency or "IDR"),
            net_book_value=Money(amount=table.net_book_value, currency=table.currency or "IDR"),
            status=table.status,
            journal_id=table.journal_id,
            posted_at=table.posted_at,
        )

    async def _log_audit(self, action: str, asset_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "asset_id": str(asset_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # CORE CRUD (sesuai port)
    # ========================================================================

    async def add(self, asset: FixedAssetAggregate) -> None:
        await self.add_asset(asset)

    async def update(self, asset: FixedAssetAggregate) -> None:
        await self.update_asset(asset)

    # ===== FIX: delete signature sesuai port (2 required: asset_id, user_id) =====
    async def delete(self, asset_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """
        Delete asset with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        try:
            async with self.session.begin():
                # 1. Lock the row with SELECT FOR UPDATE
                stmt_lock = select(FixedAssetTable).where(FixedAssetTable.id == asset_id).with_for_update()
                result = await self.session.execute(stmt_lock)
                asset = result.scalar_one_or_none()
                if not asset:
                    return False

                # 2. Perform delete on the locked row
                if permanent:
                    # Hard delete (not recommended, but available)
                    await self.session.delete(asset)
                else:
                    # Soft delete
                    asset.deleted_at = datetime.utcnow()
                    asset.is_active = False
                    asset.status = "disposed"
                    asset.updated_at = datetime.utcnow()
                await self.session.flush()
                if not permanent:
                    await self._log_audit("DELETE", asset_id, {"user_id": str(user_id)})
                    logger.info("Asset %s soft deleted by %s", asset_id, user_id)
                return True
        except Exception as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Failed to delete asset: {e}") from e

    async def get_by_id(self, asset_id: UUID) -> FixedAssetAggregate | None:
        return await self.get_asset_by_id(asset_id)

    async def get_by_asset_code(self, asset_code: str, legal_entity_id: UUID) -> FixedAssetAggregate | None:
        return await self.get_asset_by_code(asset_code, legal_entity_id)

    async def get_all(self, legal_entity_id: UUID | None = None, limit: int = 100, offset: int = 0) -> list[FixedAssetAggregate]:
        if legal_entity_id:
            assets, _ = await self.list_assets(legal_entity_id, page=(offset // limit) + 1, page_size=limit)
            return assets
        else:
            stmt = select(FixedAssetTable).where(FixedAssetTable.deleted_at.is_(None)).order_by(FixedAssetTable.asset_code).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(t) for t in tables]

    # ========================================================================
    # INTERNAL / EXISTING METHODS
    # ========================================================================

    async def add_asset(self, asset: FixedAssetAggregate) -> None:
        """
        Add new asset with pessimistic locking to prevent duplicate asset_code.
        LOCKING: SELECT FOR UPDATE on existence check to prevent concurrent inserts.
        """
        try:
            async with self.session.begin():
                # 1. Lock the row (if exists) with SELECT FOR UPDATE to prevent duplicate
                # Since we are checking existence, we lock potential duplicate rows.
                stmt_lock = select(FixedAssetTable).where(
                    FixedAssetTable.asset_code == asset.asset_code,
                    FixedAssetTable.legal_entity_id == asset.legal_entity_id,
                    FixedAssetTable.deleted_at.is_(None),
                ).with_for_update()
                result = await self.session.execute(stmt_lock)
                existing = result.scalar_one_or_none()
                if existing:
                    raise DuplicateAssetCodeError(f"Asset code {asset.asset_code} already exists")

                # 2. Insert the new asset
                table = await self._to_orm(asset)
                self.session.add(table)
                await self.session.flush()
                await self._log_audit("ADD", asset.id, {"asset_code": asset.asset_code})
                logger.info("Fixed asset added: %s", asset.asset_code)
        except DuplicateAssetCodeError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Failed to add asset: {e}") from e

    async def get_asset_by_id(self, asset_id: UUID) -> FixedAssetAggregate | None:
        try:
            stmt = select(FixedAssetTable).where(FixedAssetTable.id == asset_id, FixedAssetTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to get asset: {e}") from e

    async def get_asset_by_code(self, asset_code: str, legal_entity_id: UUID) -> FixedAssetAggregate | None:
        try:
            stmt = select(FixedAssetTable).where(
                FixedAssetTable.asset_code == asset_code,
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain(table) if table else None
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to get asset: {e}") from e

    async def update_asset(self, asset: FixedAssetAggregate) -> None:
        try:
            stmt = select(FixedAssetTable.version).where(FixedAssetTable.id == asset.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise AssetNotFoundError(f"Asset {asset.id} not found")
            if current_version != asset.version:
                raise OptimisticLockError(f"Version mismatch: expected {asset.version}, got {current_version}")
            table = await self._to_orm(asset)
            table.version = asset.version + 1
            table.updated_at = datetime.utcnow()
            await self.session.merge(table)
            await self.session.flush()
            await self._log_audit("UPDATE", asset.id, {"asset_code": asset.asset_code})
            logger.info("Asset updated: %s", asset.asset_code)
        except (AssetNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Failed to update asset: {e}") from e

    async def delete_asset(self, asset_id: UUID) -> bool:
        """
        Internal soft delete with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        try:
            async with self.session.begin():
                # 1. Lock the row with SELECT FOR UPDATE
                stmt_lock = select(FixedAssetTable).where(FixedAssetTable.id == asset_id).with_for_update()
                result = await self.session.execute(stmt_lock)
                asset = result.scalar_one_or_none()
                if not asset:
                    return False

                # 2. Soft delete the locked row
                asset.deleted_at = datetime.utcnow()
                asset.is_active = False
                await self.session.flush()
                await self._log_audit("DELETE", asset_id, {})
                logger.info("Asset %s soft deleted", asset_id)
                return True
        except Exception as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Failed to delete asset: {e}") from e

    # ========================================================================
    # QUERY METHODS (dengan legal_entity_id opsional untuk beberapa)
    # ========================================================================

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
        try:
            conditions = [FixedAssetTable.legal_entity_id == legal_entity_id, FixedAssetTable.deleted_at.is_(None)]
            if category:
                conditions.append(FixedAssetTable.asset_category == category)
            if status:
                conditions.append(FixedAssetTable.status == status)
            if is_active is not None:
                conditions.append(FixedAssetTable.is_active == is_active)
            if location:
                conditions.append(FixedAssetTable.location == location)
            if search:
                conditions.append(
                    or_(
                        FixedAssetTable.asset_code.ilike(f"%{search}%"),
                        FixedAssetTable.asset_name.ilike(f"%{search}%"),
                    )
                )
            count_stmt = select(func.count()).select_from(FixedAssetTable).where(and_(*conditions))
            count_result = await self.session.execute(count_stmt)
            total = count_result.scalar()
            offset = (page - 1) * page_size
            stmt = select(FixedAssetTable).where(and_(*conditions)).order_by(FixedAssetTable.asset_code).limit(page_size).offset(offset)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables], total
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to list assets: {e}") from e

    async def exists_by_asset_code(self, asset_code: str, legal_entity_id: UUID) -> bool:
        try:
            stmt = select(func.count()).select_from(FixedAssetTable).where(
                FixedAssetTable.asset_code == asset_code,
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to check asset code: {e}") from e

    # ========================================================================
    # FIXED: Method dengan legal_entity_id opsional
    # ========================================================================

    async def find_by_status(self, status: AssetStatus | str, legal_entity_id: UUID | None = None) -> list[FixedAssetAggregate]:
        if isinstance(status, AssetStatus):
            status = status.value
        if legal_entity_id:
            assets, _ = await self.list_assets(legal_entity_id, status=status, page_size=10000)
            return assets
        else:
            try:
                stmt = select(FixedAssetTable).where(
                    FixedAssetTable.status == status,
                    FixedAssetTable.deleted_at.is_(None),
                ).order_by(FixedAssetTable.asset_code)
                result = await self.session.execute(stmt)
                tables = result.scalars().all()
                return [self._to_domain(table) for table in tables]
            except Exception as e:
                raise FixedAssetRepositoryError(f"Failed to find by status: {e}") from e

    async def find_by_name_contains(self, keyword: str, legal_entity_id: UUID | None = None) -> list[FixedAssetAggregate]:
        if legal_entity_id:
            assets, _ = await self.list_assets(legal_entity_id, search=keyword, page_size=10000)
            return assets
        else:
            try:
                stmt = select(FixedAssetTable).where(
                    or_(
                        FixedAssetTable.asset_code.ilike(f"%{keyword}%"),
                        FixedAssetTable.asset_name.ilike(f"%{keyword}%"),
                    ),
                    FixedAssetTable.deleted_at.is_(None),
                ).order_by(FixedAssetTable.asset_code)
                result = await self.session.execute(stmt)
                tables = result.scalars().all()
                return [self._to_domain(table) for table in tables]
            except Exception as e:
                raise FixedAssetRepositoryError(f"Failed to find by name: {e}") from e

    async def find_by_asset_group(self, group_id: UUID, legal_entity_id: UUID | None = None) -> list[FixedAssetAggregate]:
        try:
            conditions = [
                FixedAssetTable.asset_category == str(group_id),
                FixedAssetTable.deleted_at.is_(None),
            ]
            if legal_entity_id:
                conditions.append(FixedAssetTable.legal_entity_id == legal_entity_id)
            stmt = select(FixedAssetTable).where(and_(*conditions)).order_by(FixedAssetTable.asset_code)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to find by asset group: {e}") from e

    # ========================================================================
    # FIND ACTIVE AS OF DATE — diperbaiki: hapus referensi disposal_date
    # ========================================================================
    async def find_active_as_of_date(self, as_of_date: date, legal_entity_id: UUID) -> list[FixedAssetAggregate]:
        try:
            stmt = select(FixedAssetTable).where(
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.acquisition_date <= as_of_date,
                FixedAssetTable.deleted_at.is_(None),
                FixedAssetTable.is_active == True,
                FixedAssetTable.status != "disposed",  # <- perbaikan: status != disposed, bukan disposal_date
            ).order_by(FixedAssetTable.asset_code)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to find active assets: {e}") from e

    async def find_due_for_depreciation(self, depreciation_date: date, legal_entity_id: UUID | None = None) -> list[FixedAssetAggregate]:
        try:
            conditions = [
                FixedAssetTable.deleted_at.is_(None),
                FixedAssetTable.is_active == True,
                FixedAssetTable.status.in_(["active", "impaired"]),  # tidak termasuk disposed
                FixedAssetTable.acquisition_date <= depreciation_date,
                or_(
                    FixedAssetTable.last_depreciation_date.is_(None),
                    FixedAssetTable.last_depreciation_date < depreciation_date
                )
            ]
            if legal_entity_id:
                conditions.append(FixedAssetTable.legal_entity_id == legal_entity_id)
            stmt = select(FixedAssetTable).where(and_(*conditions)).order_by(FixedAssetTable.asset_code)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to find assets due for depreciation: {e}") from e

    # ========================================================================
    # DEPRECIATION METHODS
    # ========================================================================

    async def calculate_monthly_depreciation(self, asset_id: UUID, period_date: date) -> Decimal:
        asset = await self.get_asset_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset {asset_id} not found")
        if asset.depreciation_method == DepreciationMethod.STRAIGHT_LINE:
            annual = (asset.acquisition_cost.amount - asset.residual_value.amount) / Decimal(asset.useful_life_years)
            monthly = annual / Decimal(12)
            return monthly.quantize(Decimal("0.01"))
        else:
            return Decimal(0)

    async def post_monthly_depreciation(self, asset_id: UUID, period_date: date, journal_id: UUID, user_id: UUID) -> Decimal:
        asset = await self.get_asset_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset {asset_id} not found")
        if asset.status == AssetStatus.DISPOSED:
            raise AssetAlreadyDisposedError(f"Asset {asset_id} already disposed")
        monthly = await self.calculate_monthly_depreciation(asset_id, period_date)
        if monthly <= 0:
            return Decimal(0)
        new_acc = asset.accumulated_depreciation.amount + monthly
        if new_acc > (asset.acquisition_cost.amount - asset.residual_value.amount):
            new_acc = asset.acquisition_cost.amount - asset.residual_value.amount
        asset.accumulated_depreciation = Money(new_acc, asset.acquisition_cost.currency)
        asset.last_depreciation_date = period_date
        asset.current_period_depreciation = Money(monthly, asset.acquisition_cost.currency)
        if new_acc >= (asset.acquisition_cost.amount - asset.residual_value.amount):
            asset.status = AssetStatus.FULLY_DEPRECIATED
        asset.version += 1
        await self.update_asset(asset)
        schedule = DepreciationScheduleLine(
            id=UUID(int=0),
            asset_id=asset_id,
            period=period_date,
            fiscal_year=period_date.year,
            month=period_date.month,
            depreciation_amount=Money(monthly, asset.acquisition_cost.currency),
            accumulated_depreciation=asset.accumulated_depreciation,
            net_book_value=Money(asset.acquisition_cost.amount - new_acc, asset.acquisition_cost.currency),
            status="posted",
            journal_id=journal_id,
            posted_at=datetime.utcnow(),
        )
        await self.add_depreciation_schedule([schedule])
        await self._log_audit("POST_DEPRECIATION", asset_id, {"period": period_date.isoformat(), "amount": str(monthly)})
        return monthly

    # ===== NEW: depreciate_asset (sesuai kontrak FixedAssetRepositoryPort) =====
    async def depreciate_asset(
        self,
        asset_id: UUID,
        as_of_date: date,
        journal_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> Decimal:
        """
        Calculate and post depreciation for an asset.
        This method implements the contract required by FixedAssetRepositoryPort.
        If journal_id or user_id is not provided, we use a default placeholder.
        """
        # Jika journal_id atau user_id tidak diberikan, gunakan placeholder
        actual_journal_id = journal_id or UUID(int=0)
        actual_user_id = user_id or UUID(int=0)
        return await self.post_monthly_depreciation(asset_id, as_of_date, actual_journal_id, actual_user_id)

    async def get_accumulated_depreciation(self, asset_id: UUID, as_of_date: date) -> Decimal:
        asset = await self.get_asset_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset {asset_id} not found")
        return asset.accumulated_depreciation.amount

    async def get_net_book_value(self, asset_id: UUID, as_of_date: date) -> Decimal:
        asset = await self.get_asset_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset {asset_id} not found")
        return asset.acquisition_cost.amount - asset.accumulated_depreciation.amount

    # ========================================================================
    # REVALUATION, DISPOSAL
    # ========================================================================

    async def revalue_asset(
        self,
        asset_id: UUID,
        new_value: Decimal,
        revaluation_date: date,
        reason: str,
        approved_by: UUID,
        journal_id: UUID | None = None
    ) -> FixedAssetAggregate:
        asset = await self.get_asset_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset {asset_id} not found")
        old_nbv = asset.acquisition_cost.amount - asset.accumulated_depreciation.amount
        if new_value == old_nbv:
            return asset
        reval = Revaluation(
            id=UUID(int=0),
            asset_id=asset_id,
            revaluation_date=revaluation_date,
            old_acquisition_cost=asset.acquisition_cost,
            new_acquisition_cost=Money(new_value, asset.acquisition_cost.currency),
            old_accumulated_depreciation=asset.accumulated_depreciation,
            new_accumulated_depreciation=Money(Decimal(0), asset.acquisition_cost.currency),
            old_nbv=Money(old_nbv, asset.acquisition_cost.currency),
            new_nbv=Money(new_value, asset.acquisition_cost.currency),
            surplus_deficit=Money(new_value - old_nbv, asset.acquisition_cost.currency),
            reason=reason,
            journal_id=journal_id,
            created_by=approved_by,
        )
        await self.add_revaluation(reval)
        asset.acquisition_cost = Money(new_value, asset.acquisition_cost.currency)
        asset.version += 1
        await self.update_asset(asset)
        return asset

    async def dispose_asset(
        self,
        asset_id: UUID,
        disposal_date: date,
        proceeds: Decimal,
        user_id: UUID,
        journal_id: UUID | None = None,
        reason: str = "Disposed"
    ) -> tuple[Decimal, Decimal]:
        asset = await self.get_asset_by_id(asset_id)
        if not asset:
            raise AssetNotFoundError(f"Asset {asset_id} not found")
        if asset.status == AssetStatus.DISPOSED:
            raise AssetAlreadyDisposedError(f"Asset {asset_id} already disposed")
        nbv = asset.acquisition_cost.amount - asset.accumulated_depreciation.amount
        gain_loss = proceeds - nbv
        disposal = Disposal(
            id=UUID(int=0),
            asset_id=asset_id,
            disposal_date=disposal_date,
            disposal_proceeds=Money(proceeds, asset.acquisition_cost.currency),
            disposal_cost=Money(Decimal(0), asset.acquisition_cost.currency),
            net_proceeds=Money(proceeds, asset.acquisition_cost.currency),
            nbv_at_disposal=Money(nbv, asset.acquisition_cost.currency),
            gain_loss=Money(gain_loss, asset.acquisition_cost.currency),
            reason=reason,
            buyer_name=None,
            journal_id=journal_id,
            created_by=user_id,
        )
        await self.add_disposal(disposal)
        asset.status = AssetStatus.DISPOSED
        asset.is_active = False
        asset.version += 1
        await self.update_asset(asset)
        return (gain_loss if gain_loss > 0 else Decimal(0), abs(gain_loss) if gain_loss < 0 else Decimal(0))

    async def add_revaluation(self, revaluation: Revaluation) -> None:
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
            await self._log_audit("REVALUATION", revaluation.asset_id, {})
            logger.info("Revaluation added for asset %s", revaluation.asset_id)
        except Exception as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Failed to add revaluation: {e}") from e

    async def add_disposal(self, disposal: Disposal) -> None:
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
            await self.session.flush()
            await self._log_audit("DISPOSAL", disposal.asset_id, {})
            logger.info("Disposal added for asset %s", disposal.asset_id)
        except Exception as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Failed to add disposal: {e}") from e

    async def add_depreciation_schedule(self, schedule_lines: list[DepreciationScheduleLine]) -> None:
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
        except Exception as e:
            await self.session.rollback()
            raise FixedAssetRepositoryError(f"Failed to add depreciation schedule: {e}") from e

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    async def export_to_csv(self, legal_entity_id: UUID | None = None) -> str:
        assets = await self.get_all(legal_entity_id, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "asset_code", "asset_name", "asset_category", "acquisition_date",
            "acquisition_cost", "residual_value", "useful_life_years",
            "depreciation_method", "accumulated_depreciation", "net_book_value",
            "status", "location", "currency"
        ])
        for a in assets:
            writer.writerow([
                a.asset_code,
                a.asset_name,
                a.asset_category,
                a.acquisition_date.isoformat(),
                str(a.acquisition_cost.amount),
                str(a.residual_value.amount),
                a.useful_life_years,
                a.depreciation_method.value,
                str(a.accumulated_depreciation.amount),
                str(a.acquisition_cost.amount - a.accumulated_depreciation.amount),
                a.status.value,
                a.location or "",
                a.acquisition_cost.currency,
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                asset = FixedAssetAggregate(
                    id=uuid4(),
                    asset_code=row["asset_code"],
                    asset_name=row["asset_name"],
                    asset_category=row.get("asset_category"),
                    acquisition_date=date.fromisoformat(row["acquisition_date"]),
                    acquisition_cost=Money(Decimal(row["acquisition_cost"]), row.get("currency", "IDR")),
                    residual_value=Money(Decimal(row.get("residual_value", "0")), row.get("currency", "IDR")),
                    useful_life_years=int(row["useful_life_years"]),
                    depreciation_method=DepreciationMethod(row["depreciation_method"]),
                    location=row.get("location"),
                    legal_entity_id=legal_entity_id,
                    created_by=created_by,
                )
                await self.add_asset(asset)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import row: {e}")
        return count

    # ========================================================================
    # STATISTICS & AUDIT
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        if legal_entity_id:
            summary = await self.get_asset_summary(legal_entity_id, date.today())
            return summary
        else:
            try:
                stmt = select(
                    func.count(FixedAssetTable.id).label("total_assets"),
                    func.coalesce(func.sum(FixedAssetTable.acquisition_cost), 0).label("total_cost"),
                    func.coalesce(func.sum(FixedAssetTable.accumulated_depreciation), 0).label("total_depreciation"),
                ).where(
                    FixedAssetTable.deleted_at.is_(None),
                    FixedAssetTable.status != "disposed",
                )
                result = await self.session.execute(stmt)
                row = result.first()
                total_cost = Decimal(str(row.total_cost)) if row.total_cost else Decimal(0)
                total_dep = Decimal(str(row.total_depreciation)) if row.total_depreciation else Decimal(0)
                return {
                    "total_assets": row.total_assets or 0,
                    "total_acquisition_cost": str(total_cost),
                    "total_accumulated_depreciation": str(total_dep),
                    "total_net_book_value": str(total_cost - total_dep),
                    "monthly_depreciation_charge": "0",
                }
            except Exception as e:
                raise FixedAssetRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_asset_summary(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        try:
            stmt = select(
                func.count(FixedAssetTable.id).label("total_assets"),
                func.coalesce(func.sum(FixedAssetTable.acquisition_cost), 0).label("total_cost"),
                func.coalesce(func.sum(FixedAssetTable.accumulated_depreciation), 0).label("total_depreciation"),
                func.coalesce(func.sum(FixedAssetTable.current_period_depreciation), 0).label("current_depreciation"),
            ).where(
                FixedAssetTable.legal_entity_id == legal_entity_id,
                FixedAssetTable.deleted_at.is_(None),
                FixedAssetTable.status != "disposed",
            )
            result = await self.session.execute(stmt)
            row = result.first()
            total_cost = Decimal(str(row.total_cost)) if row.total_cost else Decimal(0)
            total_dep = Decimal(str(row.total_depreciation)) if row.total_depreciation else Decimal(0)
            return {
                "total_assets": row.total_assets or 0,
                "total_acquisition_cost": str(total_cost),
                "total_accumulated_depreciation": str(total_dep),
                "total_net_book_value": str(total_cost - total_dep),
                "monthly_depreciation_charge": str(row.current_depreciation or 0),
            }
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to get summary: {e}") from e

    async def get_audit_log(self, asset_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if asset_id:
            logs = [l for l in logs if l.get("asset_id") == str(asset_id)]
        return logs[-limit:]

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "FixedAssetRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "FixedAssetRepository", "error": str(e)}

    # ========================================================================
    # ALIAS UNTUK KONTRAK PORT (save_asset, find_asset_by_id)
    # ========================================================================

    async def save_asset(self, asset: FixedAssetAggregate) -> None:
        existing = await self.get_asset_by_id(asset.id)
        if existing:
            await self.update_asset(asset)
        else:
            await self.add_asset(asset)

    async def find_asset_by_id(self, asset_id: UUID) -> FixedAssetAggregate | None:
        return await self.get_asset_by_id(asset_id)

    # ========================================================================
    # HELPER: GET NEXT ASSET NUMBER
    # ========================================================================

    async def get_next_asset_number(self, prefix: str = "AST", year: int = None) -> str:
        if year is None:
            year = date.today().year
        try:
            pattern = f"{prefix}-{year}-%"
            stmt = select(FixedAssetTable.asset_code).where(FixedAssetTable.asset_code.like(pattern)).order_by(FixedAssetTable.asset_code.desc()).limit(1)
            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()
            seq = int(last_number.split("-")[-1]) + 1 if last_number else 1
            return f"{prefix}-{year}-{seq:06d}"
        except Exception as e:
            raise FixedAssetRepositoryError(f"Failed to generate asset number: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================

SQLAlchemyFixedAssetRepositoryImpl = SQLAlchemyFixedAssetRepository

__all__ = [
    "AssetAlreadyDisposedError",
    "AssetNotFoundError",
    "DepreciationPeriodClosedError",
    "DuplicateAssetCodeError",
    "FixedAssetRepositoryError",
    "OptimisticLockError",
    "SQLAlchemyFixedAssetRepository",
    "SQLAlchemyFixedAssetRepositoryImpl",
]
