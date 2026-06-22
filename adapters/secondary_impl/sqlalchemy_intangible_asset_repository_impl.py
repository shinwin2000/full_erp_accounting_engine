#!/usr/bin/env python3
"""
Module: sqlalchemy_intangible_asset_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk intangible assets menggunakan SQLAlchemy.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session_factory_sqlalchemy import get_async_session
from infrastructure.persistence_orm.intangible_asset_table import IntangibleAssetTable
from ports.primary.intangible_asset_repository_port import IntangibleAssetRepositoryPort

logger = logging.getLogger(__name__)


# ============================================================================
# IMPLEMENTATION
# ============================================================================


class SQLAlchemyIntangibleAssetRepository(IntangibleAssetRepositoryPort):
    """
    Implementasi SQLAlchemy repository untuk intangible assets.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            self._session = await get_async_session()
        return self._session

    async def save_asset(self, asset: Any) -> None:
        """
        Save an intangible asset.
        """
        session = await self._get_session()
        try:
            # Convert DTO/entity to ORM model
            orm_asset = self._to_orm(asset)
            session.add(orm_asset)
            await session.flush()
            logger.debug(f"Saved intangible asset: {asset.asset_code}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to save intangible asset: {e}")
            raise

    async def get_by_id(self, asset_id: UUID, legal_entity_id: UUID) -> Any | None:
        """
        Get intangible asset by ID.
        """
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

    async def get_by_code(self, asset_code: str, legal_entity_id: UUID) -> Any | None:
        """
        Get intangible asset by asset code.
        """
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
        """
        List intangible assets with pagination and filters.
        """
        session = await self._get_session()
        query = select(IntangibleAssetTable).where(
            IntangibleAssetTable.legal_entity_id == legal_entity_id
        )

        if category:
            query = query.where(IntangibleAssetTable.asset_category == category)
        if status:
            query = query.where(IntangibleAssetTable.status == status)
        if is_active is not None:
            query = query.where(IntangibleAssetTable.is_active == is_active)
        if search:
            query = query.where(
                or_(
                    IntangibleAssetTable.asset_code.ilike(f"%{search}%"),
                    IntangibleAssetTable.asset_name.ilike(f"%{search}%"),
                )
            )
        if expiry_before:
            query = query.where(IntangibleAssetTable.expiry_date < expiry_before)

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await session.execute(query)
        rows = result.scalars().all()

        # Count total
        count_query = select(text("count(*)")).select_from(IntangibleAssetTable).where(
            IntangibleAssetTable.legal_entity_id == legal_entity_id
        )
        if category:
            count_query = count_query.where(IntangibleAssetTable.asset_category == category)
        if status:
            count_query = count_query.where(IntangibleAssetTable.status == status)
        if is_active is not None:
            count_query = count_query.where(IntangibleAssetTable.is_active == is_active)
        if search:
            count_query = count_query.where(
                or_(
                    IntangibleAssetTable.asset_code.ilike(f"%{search}%"),
                    IntangibleAssetTable.asset_name.ilike(f"%{search}%"),
                )
            )
        if expiry_before:
            count_query = count_query.where(IntangibleAssetTable.expiry_date < expiry_before)

        count_result = await session.execute(count_query)
        total = count_result.scalar()

        return {
            "items": [self._from_orm(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        }

    async def update_asset(self, asset: Any) -> None:
        """
        Update an intangible asset.
        """
        session = await self._get_session()
        try:
            orm_asset = await session.get(IntangibleAssetTable, asset.id)
            if not orm_asset:
                raise ValueError(f"Asset {asset.id} not found")

            # Update fields
            for key, value in asset.to_dict().items():
                if hasattr(orm_asset, key):
                    setattr(orm_asset, key, value)

            orm_asset.updated_at = datetime.utcnow()
            await session.flush()
            logger.debug(f"Updated intangible asset: {asset.asset_code}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update intangible asset: {e}")
            raise

    async def delete_asset(self, asset_id: UUID, legal_entity_id: UUID) -> bool:
        """
        Delete (archive) an intangible asset.
        """
        session = await self._get_session()
        try:
            result = await session.execute(
                select(IntangibleAssetTable).where(
                    IntangibleAssetTable.id == asset_id,
                    IntangibleAssetTable.legal_entity_id == legal_entity_id,
                )
            )
            orm_asset = result.scalar_one_or_none()
            if not orm_asset:
                return False

            orm_asset.status = "ARCHIVED"
            orm_asset.is_active = False
            orm_asset.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Archived intangible asset: {asset_id}")
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to delete intangible asset: {e}")
            raise

    async def exists(self, asset_id: UUID, legal_entity_id: UUID) -> bool:
        """
        Check if an intangible asset exists.
        """
        session = await self._get_session()
        result = await session.execute(
            select(text("1")).where(
                IntangibleAssetTable.id == asset_id,
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
            ).limit(1)
        )
        return result.scalar() is not None

    async def count_by_category(self, legal_entity_id: UUID) -> dict[str, int]:
        """
        Count intangible assets by category.
        """
        session = await self._get_session()
        result = await session.execute(
            text("""
                SELECT asset_category, COUNT(*) as count
                FROM intangible_asset_table
                WHERE legal_entity_id = :legal_entity_id
                AND status != 'ARCHIVED'
                GROUP BY asset_category
            """),
            {"legal_entity_id": str(legal_entity_id)}
        )
        rows = result.all()
        return {row.asset_category: row.count for row in rows}

    async def get_total_acquisition_cost(self, legal_entity_id: UUID) -> Decimal:
        """
        Get total acquisition cost of all intangible assets.
        """
        session = await self._get_session()
        result = await session.execute(
            select(text("COALESCE(SUM(acquisition_cost), 0)")).select_from(
                IntangibleAssetTable
            ).where(
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
                IntangibleAssetTable.status != "ARCHIVED",
            )
        )
        return Decimal(str(result.scalar() or 0))

    async def get_total_nbv(self, legal_entity_id: UUID) -> Decimal:
        """
        Get total net book value of all intangible assets.
        """
        session = await self._get_session()
        result = await session.execute(
            select(text("COALESCE(SUM(acquisition_cost - accumulated_amortization - accumulated_impairment), 0)")).select_from(
                IntangibleAssetTable
            ).where(
                IntangibleAssetTable.legal_entity_id == legal_entity_id,
                IntangibleAssetTable.status != "ARCHIVED",
            )
        )
        return Decimal(str(result.scalar() or 0))

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _to_orm(self, asset: Any) -> IntangibleAssetTable:
        """Convert DTO/entity to ORM model."""
        from infrastructure.persistence_orm.intangible_asset_table import IntangibleAssetTable

        return IntangibleAssetTable(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_category=asset.asset_category,
            legal_entity_id=asset.legal_entity_id,
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=asset.amortization_method,
            amortization_rate=asset.amortization_rate,
            accumulated_amortization=asset.accumulated_amortization,
            accumulated_impairment=asset.accumulated_impairment,
            registration_number=asset.registration_number,
            issuing_authority=asset.issuing_authority,
            expiry_date=asset.expiry_date,
            status=asset.status,
            is_active=asset.is_active,
            is_locked=asset.is_locked,
            use_fiscal_amortization=asset.use_fiscal_amortization,
            notes=asset.notes,
            attachment_ids=asset.attachment_ids,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=asset.created_by,
            version=asset.version,
        )

    def _from_orm(self, orm: IntangibleAssetTable) -> Any:
        """Convert ORM model to DTO/entity."""
        from dataclasses import dataclass
        from datetime import datetime
        from decimal import Decimal
        from uuid import UUID

        @dataclass(kw_only=True)
        class AssetDTO:
            id: UUID
            asset_code: str
            asset_name: str
            asset_category: str
            legal_entity_id: UUID
            acquisition_date: date
            acquisition_cost: Decimal
            residual_value: Decimal
            useful_life_years: int
            amortization_method: str
            amortization_rate: Decimal | None
            accumulated_amortization: Decimal
            accumulated_impairment: Decimal
            net_book_value: Decimal
            current_period_amortization: Decimal
            registration_number: str | None
            issuing_authority: str | None
            expiry_date: date | None
            status: str
            is_active: bool
            is_locked: bool
            use_fiscal_amortization: bool
            notes: str | None
            attachment_ids: list[UUID] | None
            created_at: datetime
            updated_at: datetime
            created_by: UUID
            created_by_name: str | None
            version: int

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

        net_book_value = (
            orm.acquisition_cost
            - (orm.accumulated_amortization or Decimal("0"))
            - (orm.accumulated_impairment or Decimal("0"))
        )

        return AssetDTO(
            id=orm.id,
            asset_code=orm.asset_code,
            asset_name=orm.asset_name,
            asset_category=orm.asset_category,
            legal_entity_id=orm.legal_entity_id,
            acquisition_date=orm.acquisition_date,
            acquisition_cost=orm.acquisition_cost,
            residual_value=orm.residual_value or Decimal("0"),
            useful_life_years=orm.useful_life_years,
            amortization_method=orm.amortization_method,
            amortization_rate=orm.amortization_rate,
            accumulated_amortization=orm.accumulated_amortization or Decimal("0"),
            accumulated_impairment=orm.accumulated_impairment or Decimal("0"),
            net_book_value=net_book_value,
            current_period_amortization=Decimal("0"),
            registration_number=orm.registration_number,
            issuing_authority=orm.issuing_authority,
            expiry_date=orm.expiry_date,
            status=orm.status,
            is_active=orm.is_active,
            is_locked=orm.is_locked,
            use_fiscal_amortization=orm.use_fiscal_amortization,
            notes=orm.notes,
            attachment_ids=orm.attachment_ids,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            created_by=orm.created_by,
            created_by_name=None,
            version=orm.version or 1,
        )

    # ========================================================================
    # METODE TAMBAHAN UNTUK MEMENUHI KONTRAK PORT (stub)
    # ========================================================================

    async def save(self, asset: Any) -> None:
        """Save or update an intangible asset (delegates to save_asset)."""
        await self.save_asset(asset)

    async def update(self, asset: Any) -> None:
        """Update an existing intangible asset (delegates to update_asset)."""
        await self.update_asset(asset)

    async def list_by_legal_entity(self, legal_entity_id: UUID) -> list[Any]:
        """
        List all intangible assets for a legal entity (delegates to list_assets).
        """
        result = await self.list_assets(legal_entity_id, page=1, page_size=1000)
        return result["items"]

    async def get_active_assets_for_amortization(self, as_of_date: date) -> list[Any]:
        """Stub: return empty list."""
        logger.warning("get_active_assets_for_amortization not fully implemented")
        return []

    async def get_aggregate_by_legal_entity(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Stub: return dummy aggregate."""
        logger.warning("get_aggregate_by_legal_entity not fully implemented")
        return {"legal_entity_id": legal_entity_id, "total_nbv": 0}

    async def save_aggregate(self, aggregate: Any) -> None:
        """Stub."""
        logger.warning("save_aggregate not fully implemented")
        pass

    async def save_schedules(self, schedules: Any) -> None:
        """Stub."""
        logger.warning("save_schedules not fully implemented")
        pass

    async def record_amortization_schedule(self, schedule: Any) -> None:
        """Stub."""
        logger.warning("record_amortization_schedule not fully implemented")
        pass

    async def record_revaluation(self, revaluation: Any) -> None:
        """Stub."""
        logger.warning("record_revaluation not fully implemented")
        pass


# ============================================================================
# FACTORY
# ============================================================================


async def create_intangible_asset_repository() -> SQLAlchemyIntangibleAssetRepository:
    return SQLAlchemyIntangibleAssetRepository()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["SQLAlchemyIntangibleAssetRepository", "create_intangible_asset_repository"]