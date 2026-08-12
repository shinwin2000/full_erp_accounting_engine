#!/usr/bin/env python3
"""
Module: sqlalchemy_intangible_asset_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk intangible assets menggunakan SQLAlchemy.
Perbaikan:
  - [FIX] Race condition pada update dan delete_asset dengan pessimistic locking.
  - [FIX] Menggunakan field yang ada di IntangibleAssetTable (asset_type, is_active, disposed_date, dll.)
          menggantikan field yang tidak ada (status, expiry_date, asset_category, dll.).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Numeric,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from domain.intangible_asset.aggregate_root import IntangibleAsset
from domain.intangible_asset.asset_entity import IntangibleAssetEntity
from infrastructure.database.session_factory_sqlalchemy import get_async_session
from infrastructure.persistence_orm.intangible_asset_table import (
    IntangibleAssetTable,
    IntangibleAssetType,
)
from ports.primary.intangible_asset_repository_port import IntangibleAssetRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


# ============================================================================
# ORM MODELS (tambahan untuk schedules dan revaluations)
# ============================================================================

class AmortizationScheduleTable(Base):
    __tablename__ = "intangible_amortization_schedules"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_date = Column(Date, nullable=False)
    planned_amount = Column(Numeric(20, 2), nullable=False)
    actual_amount = Column(Numeric(20, 2), nullable=False)
    journal_id = Column(PGUUID(as_uuid=True), nullable=True)
    period_id = Column(PGUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class RevaluationRecordTable(Base):
    __tablename__ = "intangible_revaluation_records"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id = Column(PGUUID(as_uuid=True), nullable=False)
    old_amount = Column(Numeric(20, 2), nullable=False)
    new_amount = Column(Numeric(20, 2), nullable=False)
    surplus = Column(Numeric(20, 2), nullable=False)
    revaluation_date = Column(Date, nullable=False)
    approved_by = Column(PGUUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================

class SQLAlchemyIntangibleAssetRepository(IntangibleAssetRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            self._session = await get_async_session()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========================================================================
    # MAPPING: ORM ↔ Domain DTO
    # ========================================================================

    def _from_orm(self, orm: IntangibleAssetTable) -> IntangibleAssetEntity:
        """Convert ORM model to DTO/entity."""
        from dataclasses import dataclass

        @dataclass(kw_only=True)
        class AssetDTO:
            id: UUID
            asset_code: str
            asset_name: str
            asset_category: str  # dari asset_type
            legal_entity_id: UUID
            acquisition_date: date
            acquisition_cost: Decimal
            residual_value: Decimal
            useful_life_years: int
            amortization_method: str
            amortization_rate: Decimal | None
            accumulated_amortization: Decimal
            accumulated_impairment: Decimal  # dari impairment_loss
            net_book_value: Decimal
            current_period_amortization: Decimal
            registration_number: str | None
            issuing_authority: str | None
            expiry_date: date | None  # dihitung dari acquisition_date + useful_life_years
            status: str  # dari is_active dan disposed_date
            is_active: bool
            is_locked: bool  # default False
            use_fiscal_amortization: bool  # default False
            notes: str | None  # default None
            attachment_ids: list[UUID] | None  # default None
            created_at: datetime
            updated_at: datetime
            created_by: UUID
            created_by_name: str | None
            version: int  # default 1

            def to_dict(self) -> dict[str, Any]:
                return {
                    "id": self.id,
                    "asset_code": self.asset_code,
                    "asset_name": self.asset_name,
                    "asset_category": self.asset_category,
                    "legal_entity_id": self.legal_entity_id,
                    "acquisition_date": self.acquisition_date,
                    "acquisition_cost": self.acquisition_cost,
                    "residual_value": self.residual_value,
                    "useful_life_years": self.useful_life_years,
                    "amortization_method": self.amortization_method,
                    "amortization_rate": self.amortization_rate,
                    "accumulated_amortization": self.accumulated_amortization,
                    "accumulated_impairment": self.accumulated_impairment,
                    "net_book_value": self.net_book_value,
                    "current_period_amortization": self.current_period_amortization,
                    "registration_number": self.registration_number,
                    "issuing_authority": self.issuing_authority,
                    "expiry_date": self.expiry_date,
                    "status": self.status,
                    "is_active": self.is_active,
                    "is_locked": self.is_locked,
                    "use_fiscal_amortization": self.use_fiscal_amortization,
                    "notes": self.notes,
                    "attachment_ids": self.attachment_ids,
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                    "created_by": self.created_by,
                    "created_by_name": self.created_by_name,
                    "version": self.version,
                }

        # Hitung net book value
        net_book_value = (
            orm.acquisition_cost
            - (orm.accumulated_amortization or Decimal("0"))
            - (orm.impairment_loss or Decimal("0"))
        )

        # Tentukan status dari is_active dan disposed_date
        if orm.disposed_date:
            status = "DISPOSED"
        elif not orm.is_active:
            status = "INACTIVE"
        else:
            status = "ACTIVE"

        # Hitung expiry_date dari acquisition_date + useful_life_years (jika ada)
        expiry_date = None
        if orm.acquisition_date and orm.useful_life_years:
            try:
                expiry_date = orm.acquisition_date.replace(year=orm.acquisition_date.year + orm.useful_life_years)
            except ValueError:
                # Handle leap year, gunakan pendekatan aman
                from dateutil.relativedelta import relativedelta
                expiry_date = orm.acquisition_date + relativedelta(years=orm.useful_life_years)

        # Hitung amortization_rate (1/useful_life_years)
        amortization_rate = None
        if orm.useful_life_years > 0:
            amortization_rate = Decimal("1") / Decimal(orm.useful_life_years)

        # asset_category dari asset_type (enum)
        asset_category = orm.asset_type.value if hasattr(orm.asset_type, "value") else str(orm.asset_type)

        return AssetDTO(
            id=orm.id,
            asset_code=orm.asset_code,
            asset_name=orm.asset_name,
            asset_category=asset_category,
            legal_entity_id=orm.legal_entity_id,
            acquisition_date=orm.acquisition_date,
            acquisition_cost=orm.acquisition_cost,
            residual_value=orm.residual_value or Decimal("0"),
            useful_life_years=orm.useful_life_years,
            amortization_method=orm.amortization_method.value if hasattr(orm.amortization_method, "value") else str(orm.amortization_method),
            amortization_rate=amortization_rate,
            accumulated_amortization=orm.accumulated_amortization or Decimal("0"),
            accumulated_impairment=orm.impairment_loss or Decimal("0"),
            net_book_value=net_book_value,
            current_period_amortization=Decimal("0"),  # tidak ada di ORM, default
            registration_number=None,  # tidak ada di ORM
            issuing_authority=None,    # tidak ada di ORM
            expiry_date=expiry_date,
            status=status,
            is_active=orm.is_active,
            is_locked=False,           # default
            use_fiscal_amortization=False,  # default
            notes=None,                # tidak ada di ORM
            attachment_ids=None,       # tidak ada di ORM
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            created_by=orm.created_by or UUID(int=0),  # jika None, beri default
            created_by_name=None,
            version=1,                 # tidak ada version di ORM
        )

    def _to_orm(self, asset: Any) -> IntangibleAssetTable:
        """Convert DTO/entity to ORM model."""
        # Konversi asset_type dari string ke enum
        asset_type_str = getattr(asset, "asset_category", "OTHER")
        try:
            asset_type = IntangibleAssetType(asset_type_str)
        except ValueError:
            asset_type = IntangibleAssetType.OTHER

        return IntangibleAssetTable(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_type=asset_type,
            legal_entity_id=asset.legal_entity_id,
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=asset.amortization_method,
            accumulated_amortization=asset.accumulated_amortization,
            impairment_loss=asset.accumulated_impairment,  # mapping
            carrying_amount=asset.net_book_value,  # atau dihitung ulang
            is_active=asset.is_active,
            # Field lain kita set default atau dari asset jika ada
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=asset.created_by,
        )

    # ========================================================================
    # PORT METHODS (sesuai signature)
    # ========================================================================

    # ---- save ----
    async def save(self, asset: IntangibleAssetEntity) -> None:
        session = await self._get_session()
        try:
            orm_asset = self._to_orm(asset)
            # Hitung carrying_amount
            orm_asset.carrying_amount = (
                orm_asset.acquisition_cost
                - orm_asset.accumulated_amortization
                - orm_asset.impairment_loss
            )
            session.add(orm_asset)
            await session.flush()
            logger.debug(f"Saved intangible asset: {asset.asset_code}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to save intangible asset: {e}")
            raise

    # ---- update (dengan pessimistic locking) ----
    async def update(self, asset: IntangibleAssetEntity) -> None:
        session = await self._get_session()
        try:
            stmt = select(IntangibleAssetTable).where(
                IntangibleAssetTable.id == asset.id
            ).with_for_update()
            result = await session.execute(stmt)
            orm_asset = result.scalar_one_or_none()
            if not orm_asset:
                raise ValueError(f"Asset {asset.id} not found")

            # Update field yang tersedia
            orm_asset.asset_code = asset.asset_code
            orm_asset.asset_name = asset.asset_name
            # asset_type dari asset_category
            try:
                orm_asset.asset_type = IntangibleAssetType(asset.asset_category)
            except ValueError:
                orm_asset.asset_type = IntangibleAssetType.OTHER
            orm_asset.acquisition_date = asset.acquisition_date
            orm_asset.acquisition_cost = asset.acquisition_cost
            orm_asset.residual_value = asset.residual_value
            orm_asset.useful_life_years = asset.useful_life_years
            orm_asset.amortization_method = asset.amortization_method
            orm_asset.accumulated_amortization = asset.accumulated_amortization
            orm_asset.impairment_loss = asset.accumulated_impairment
            orm_asset.is_active = asset.is_active
            orm_asset.carrying_amount = (
                orm_asset.acquisition_cost
                - orm_asset.accumulated_amortization
                - orm_asset.impairment_loss
            )
            orm_asset.updated_at = datetime.utcnow()
            # version tidak ada, kita skip
            await session.flush()
            logger.debug(f"Updated intangible asset: {asset.asset_code}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update intangible asset: {e}")
            raise

    # ---- get_by_id (1 parameter) ----
    async def get_by_id(self, asset_id: UUID) -> IntangibleAssetEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        result = await session.execute(
            select(IntangibleAssetTable).where(
                IntangibleAssetTable.id == asset_id,
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return self._from_orm(row)
        return None

    # ---- list_by_legal_entity ----
    async def list_by_legal_entity(
        self, legal_entity_id: UUID, include_inactive: bool = False
    ) -> list[IntangibleAssetEntity]:
        session = await self._get_session()
        query = select(IntangibleAssetTable).where(
            IntangibleAssetTable.legal_entity_id == legal_entity_id
        )
        if not include_inactive:
            query = query.where(IntangibleAssetTable.is_active == True)
        result = await session.execute(query)
        rows = result.scalars().all()
        return [self._from_orm(row) for row in rows]

    # ---- get_active_assets_for_amortization (2 parameter) ----
    async def get_active_assets_for_amortization(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[IntangibleAssetEntity]:
        session = await self._get_session()
        # Karena tidak ada expiry_date, kita hanya filter is_active dan acquisition_date <= as_of_date
        # Dan asumsi amortisasi dilakukan untuk aset yang belum didispose
        query = select(IntangibleAssetTable).where(
            IntangibleAssetTable.legal_entity_id == legal_entity_id,
            IntangibleAssetTable.is_active == True,
            IntangibleAssetTable.disposed_date.is_(None),  # belum dispose
            IntangibleAssetTable.acquisition_date <= as_of_date,
        )
        result = await session.execute(query)
        rows = result.scalars().all()
        return [self._from_orm(row) for row in rows]

    # ---- save_schedules (2 parameter) ----
    async def save_schedules(self, asset_id: UUID, schedules: list[dict[str, Any]]) -> None:
        session = await self._get_session()
        for sched in schedules:
            schedule = AmortizationScheduleTable(
                id=uuid4(),
                asset_id=asset_id,
                period_date=sched["period_date"],
                planned_amount=sched["planned_amount"],
                actual_amount=sched["actual_amount"],
                journal_id=sched.get("journal_id"),
                period_id=sched["period_id"],
                created_at=datetime.utcnow(),
            )
            session.add(schedule)
        await session.flush()

    # ---- record_amortization_schedule (6 parameter) ----
    async def record_amortization_schedule(
        self,
        asset_id: UUID,
        period_date: date,
        planned_amount: Decimal,
        actual_amount: Decimal,
        journal_id: UUID | None,
        period_id: UUID,
    ) -> None:
        session = await self._get_session()
        schedule = AmortizationScheduleTable(
            id=uuid4(),
            asset_id=asset_id,
            period_date=period_date,
            planned_amount=planned_amount,
            actual_amount=actual_amount,
            journal_id=journal_id,
            period_id=period_id,
            created_at=datetime.utcnow(),
        )
        session.add(schedule)
        await session.flush()

    # ---- record_revaluation (6 parameter) ----
    async def record_revaluation(
        self,
        asset_id: UUID,
        old_amount: Decimal,
        new_amount: Decimal,
        surplus: Decimal,
        date: date,
        approved_by: UUID,
    ) -> None:
        session = await self._get_session()
        record = RevaluationRecordTable(
            id=uuid4(),
            asset_id=asset_id,
            old_amount=old_amount,
            new_amount=new_amount,
            surplus=surplus,
            revaluation_date=date,
            approved_by=approved_by,
            created_at=datetime.utcnow(),
        )
        session.add(record)
        await session.flush()

    # ---- get_aggregate_by_legal_entity ----
    async def get_aggregate_by_legal_entity(self, legal_entity_id: UUID) -> IntangibleAsset | None:
        # Untuk sementara, kita tidak punya aggregate root yang lengkap, kita return None
        logger.warning("get_aggregate_by_legal_entity not fully implemented")
        return None

    # ---- save_aggregate ----
    async def save_aggregate(self, aggregate: IntangibleAsset) -> None:
        logger.warning("save_aggregate not fully implemented")
        pass

    # ========================================================================
    # INTERNAL/LEGACY METHODS (untuk kompatibilitas)
    # ========================================================================

    async def save_asset(self, asset: Any) -> None:
        await self.save(asset)

    async def get_by_code(self, asset_code: str, legal_entity_id: UUID) -> Any | None:
        session = await self._get_session()
        result = await session.execute(
            select(IntangibleAssetTable).where(
                IntangibleAssetTable.asset_code == asset_code,
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return self._from_orm(row)
        return None

    async def list_assets(
        self,
        legal_entity_id: UUID,
        category: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        expiry_before: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        session = await self._get_session()
        query = select(IntangibleAssetTable).where(
            IntangibleAssetTable.legal_entity_id == legal_entity_id
        )
        if category:
            # category adalah asset_type
            try:
                asset_type = IntangibleAssetType(category)
                query = query.where(IntangibleAssetTable.asset_type == asset_type)
            except ValueError:
                pass
        if is_active is not None:
            query = query.where(IntangibleAssetTable.is_active == is_active)
        if search:
            query = query.where(
                or_(
                    IntangibleAssetTable.asset_code.ilike(f"%{search}%"),
                    IntangibleAssetTable.asset_name.ilike(f"%{search}%"),
                )
            )
        # status: kita mapping dari is_active dan disposed_date
        if status:
            if status.upper() == "ACTIVE":
                query = query.where(
                    IntangibleAssetTable.is_active == True,
                    IntangibleAssetTable.disposed_date.is_(None)
                )
            elif status.upper() == "INACTIVE":
                query = query.where(
                    IntangibleAssetTable.is_active == False,
                    IntangibleAssetTable.disposed_date.is_(None)
                )
            elif status.upper() == "DISPOSED":
                query = query.where(IntangibleAssetTable.disposed_date.isnot(None))
            # lainnya diabaikan

        # expiry_before: tidak ada expiry_date, kita abaikan

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        result = await session.execute(query)
        rows = result.scalars().all()

        # Count total (dengan filter yang sama tanpa offset/limit)
        count_query = select(text("COUNT(*)")).select_from(IntangibleAssetTable).where(
            IntangibleAssetTable.legal_entity_id == legal_entity_id
        )
        if category:
            try:
                asset_type = IntangibleAssetType(category)
                count_query = count_query.where(IntangibleAssetTable.asset_type == asset_type)
            except ValueError:
                pass
        if is_active is not None:
            count_query = count_query.where(IntangibleAssetTable.is_active == is_active)
        if search:
            count_query = count_query.where(
                or_(
                    IntangibleAssetTable.asset_code.ilike(f"%{search}%"),
                    IntangibleAssetTable.asset_name.ilike(f"%{search}%"),
                )
            )
        if status:
            if status.upper() == "ACTIVE":
                count_query = count_query.where(
                    IntangibleAssetTable.is_active == True,
                    IntangibleAssetTable.disposed_date.is_(None)
                )
            elif status.upper() == "INACTIVE":
                count_query = count_query.where(
                    IntangibleAssetTable.is_active == False,
                    IntangibleAssetTable.disposed_date.is_(None)
                )
            elif status.upper() == "DISPOSED":
                count_query = count_query.where(IntangibleAssetTable.disposed_date.isnot(None))

        count_result = await session.execute(count_query)
        total = count_result.scalar()

        return {
            "items": [self._from_orm(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        }

    # ---- delete_asset (dengan pessimistic locking) ----
    async def delete_asset(self, asset_id: UUID, legal_entity_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = select(IntangibleAssetTable).where(
                IntangibleAssetTable.id == asset_id,
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
            ).with_for_update()
            result = await session.execute(stmt)
            orm_asset = result.scalar_one_or_none()
            if not orm_asset:
                return False

            # Soft delete: set is_active False dan disposed_date
            orm_asset.is_active = False
            orm_asset.disposed_date = date.today()
            orm_asset.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Archived intangible asset: {asset_id}")
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to delete intangible asset: {e}")
            raise

    async def exists(self, asset_id: UUID, legal_entity_id: UUID) -> bool:
        session = await self._get_session()
        result = await session.execute(
            select(text("1")).where(
                IntangibleAssetTable.id == asset_id,
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
            ).limit(1)
        )
        return result.scalar() is not None

    async def count_by_category(self, legal_entity_id: UUID) -> dict[str, int]:
        session = await self._get_session()
        result = await session.execute(
            text("""
                SELECT asset_type, COUNT(*) as count
                FROM intangible_asset
                WHERE legal_entity_id = :legal_entity_id
                AND disposed_date IS NULL
                GROUP BY asset_type
            """),
            {"legal_entity_id": str(legal_entity_id)}
        )
        rows = result.all()
        return {row.asset_type: row.count for row in rows}

    async def get_total_acquisition_cost(self, legal_entity_id: UUID) -> Decimal:
        session = await self._get_session()
        result = await session.execute(
            select(text("COALESCE(SUM(acquisition_cost), 0)")).select_from(
                IntangibleAssetTable
            ).where(
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
                IntangibleAssetTable.disposed_date.is_(None),  # asumsi belum dispose
            )
        )
        return Decimal(str(result.scalar() or 0))

    async def get_total_nbv(self, legal_entity_id: UUID) -> Decimal:
        session = await self._get_session()
        result = await session.execute(
            select(text("COALESCE(SUM(acquisition_cost - accumulated_amortization - impairment_loss), 0)")).select_from(
                IntangibleAssetTable
            ).where(
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
                IntangibleAssetTable.disposed_date.is_(None),
            )
        )
        return Decimal(str(result.scalar() or 0))


# ============================================================================
# FACTORY
# ============================================================================

async def create_intangible_asset_repository() -> SQLAlchemyIntangibleAssetRepository:
    return SQLAlchemyIntangibleAssetRepository()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["SQLAlchemyIntangibleAssetRepository", "create_intangible_asset_repository"]
