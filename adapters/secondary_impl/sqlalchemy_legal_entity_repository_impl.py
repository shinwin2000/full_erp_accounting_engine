#!/usr/bin/env python3
"""
Module: sqlalchemy_legal_entity_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Legal Entity Management menggunakan
               SQLAlchemy ORM. Menyediakan operasi CRUD untuk entitas hukum,
               termasuk perusahaan, cabang, dan grup konsolidasi. Mendukung
               soft delete, optimistic locking, dan validasi unik per NPWP.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, func, and_, or_
- ports.primary.legal_entity_repository_port (LegalEntityRepositoryPort)
- domain.legal_entity.aggregate_root (LegalEntityAggregate)
- infrastructure.persistence_orm.legal_entity_table
- infrastructure.persistence_orm.legal_entity_branch_table
- infrastructure.persistence_orm.consolidation_group_table
- domain.shared_value_objects.npwp_vo (NPWPVO)
Audit: Setiap perubahan pada entitas hukum (tambah, ubah, nonaktifkan)
       dicatat di event store. Data entitas hukum digunakan untuk RLS.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.legal_entity.aggregate_root import EntityType, LegalEntityAggregate, LegalEntityStatus
from domain.legal_entity.company_tax_profile_vo import CompanyTaxProfile

# Value objects
from domain.shared_value_objects.npwp_vo import NPWPVO
from infrastructure.persistence_orm.consolidation_group_member_table import (
    ConsolidationGroupMemberTable,
)
from infrastructure.persistence_orm.consolidation_group_table import ConsolidationGroupTable
from infrastructure.persistence_orm.legal_entity_branch_table import LegalEntityBranchTable

# Infrastructure ORM
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable

# Ports
from ports.primary.legal_entity_repository_port import LegalEntityRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_COUNTRY = "ID"
DEFAULT_CURRENCY = "IDR"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class LegalEntityRepositoryError(Exception):
    """Base exception untuk repository legal entity."""

    pass


class DuplicateNPWPError(LegalEntityRepositoryError):
    """NPWP sudah terdaftar untuk entitas hukum lain."""

    pass


class DuplicateTaxIDError(LegalEntityRepositoryError):
    """Tax ID (NPWP) sudah ada."""

    pass


class LegalEntityNotFoundError(LegalEntityRepositoryError):
    """Entitas hukum tidak ditemukan."""

    pass


class LegalEntityHasBranchesError(LegalEntityRepositoryError):
    """Entitas hukum memiliki cabang, tidak bisa dihapus."""

    pass


class ConsolidationGroupNotFoundError(LegalEntityRepositoryError):
    """Grup konsolidasi tidak ditemukan."""

    pass


class OptimisticLockError(LegalEntityRepositoryError):
    """Version mismatch saat update."""

    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyLegalEntityRepository(LegalEntityRepositoryPort):
    """
    Implementasi repository Legal Entity dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise LegalEntityRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain(self, table: LegalEntityTable) -> LegalEntityAggregate:
        """
        Mapping dari ORM model ke domain LegalEntityAggregate.
        """
        # Map enums
        entity_type_map = {
            "parent_company": EntityType.PARENT_COMPANY,
            "subsidiary": EntityType.SUBSIDIARY,
            "branch": EntityType.BRANCH,
            "representative_office": EntityType.REPRESENTATIVE_OFFICE,
            "joint_venture": EntityType.JOINT_VENTURE,
        }

        status_map = {
            "active": LegalEntityStatus.ACTIVE,
            "inactive": LegalEntityStatus.INACTIVE,
            "suspended": LegalEntityStatus.SUSPENDED,
            "liquidated": LegalEntityStatus.LIQUIDATED,
        }

        # Build tax profile
        tax_profile = CompanyTaxProfile(
            npwp=NPWPVO(table.npwp) if table.npwp else None,
            tax_office=table.tax_office,
            tax_office_code=table.tax_office_code,
            tax_classification=table.tax_classification,
            taxable_date=table.taxable_date,
            annual_tax_return_due_date=table.annual_tax_return_due_date,
            monthly_tax_due_date=table.monthly_tax_due_date,
            is_vat_collector=table.is_vat_collector,
            vat_collector_number=table.vat_collector_number,
            is_withholding_agent=table.is_withholding_agent,
        )

        aggregate = LegalEntityAggregate(
            id=table.id,
            legal_name=table.legal_name,
            trade_name=table.trade_name,
            entity_type=entity_type_map.get(table.entity_type, EntityType.SUBSIDIARY),
            registration_number=table.registration_number,
            npwp=NPWPVO(table.npwp) if table.npwp else None,
            tax_id=table.npwp,
            address=table.address,
            city=table.city,
            postal_code=table.postal_code,
            country=table.country or DEFAULT_COUNTRY,
            phone=table.phone,
            email=table.email,
            website=table.website,
            established_date=table.established_date,
            fiscal_year_start=table.fiscal_year_start,
            fiscal_year_end=table.fiscal_year_end,
            base_currency=table.base_currency or DEFAULT_CURRENCY,
            functional_currency=table.functional_currency or DEFAULT_CURRENCY,
            tax_profile=tax_profile,
            status=status_map.get(table.status, LegalEntityStatus.ACTIVE),
            is_active=table.is_active,
            parent_company_id=table.parent_company_id,
            consolidation_group_id=table.consolidation_group_id,
            logo_url=table.logo_url,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
        )
        return aggregate

    async def _to_orm(self, aggregate: LegalEntityAggregate) -> LegalEntityTable:
        """Mapping dari domain ke ORM model."""
        entity_type_str = (
            aggregate.entity_type.value
            if hasattr(aggregate.entity_type, "value")
            else str(aggregate.entity_type)
        )
        status_str = (
            aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        )

        table = LegalEntityTable(
            id=aggregate.id,
            legal_name=aggregate.legal_name,
            trade_name=aggregate.trade_name,
            entity_type=entity_type_str,
            registration_number=aggregate.registration_number,
            npwp=str(aggregate.npwp) if aggregate.npwp else None,
            address=aggregate.address,
            city=aggregate.city,
            postal_code=aggregate.postal_code,
            country=aggregate.country,
            phone=aggregate.phone,
            email=aggregate.email,
            website=aggregate.website,
            established_date=aggregate.established_date,
            fiscal_year_start=aggregate.fiscal_year_start,
            fiscal_year_end=aggregate.fiscal_year_end,
            base_currency=aggregate.base_currency,
            functional_currency=aggregate.functional_currency,
            tax_office=aggregate.tax_profile.tax_office if aggregate.tax_profile else None,
            tax_office_code=aggregate.tax_profile.tax_office_code
            if aggregate.tax_profile
            else None,
            tax_classification=aggregate.tax_profile.tax_classification
            if aggregate.tax_profile
            else None,
            taxable_date=aggregate.tax_profile.taxable_date if aggregate.tax_profile else None,
            annual_tax_return_due_date=aggregate.tax_profile.annual_tax_return_due_date
            if aggregate.tax_profile
            else None,
            monthly_tax_due_date=aggregate.tax_profile.monthly_tax_due_date
            if aggregate.tax_profile
            else None,
            is_vat_collector=aggregate.tax_profile.is_vat_collector
            if aggregate.tax_profile
            else False,
            vat_collector_number=aggregate.tax_profile.vat_collector_number
            if aggregate.tax_profile
            else None,
            is_withholding_agent=aggregate.tax_profile.is_withholding_agent
            if aggregate.tax_profile
            else False,
            status=status_str,
            is_active=aggregate.is_active,
            parent_company_id=aggregate.parent_company_id,
            consolidation_group_id=aggregate.consolidation_group_id,
            logo_url=aggregate.logo_url,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
        )
        return table

    # ========================================================================
    # LEGAL ENTITY CRUD METHODS
    # ========================================================================

    async def add(self, entity: LegalEntityAggregate) -> None:
        """
        Menambahkan entitas hukum baru.
        """
        try:
            # Cek duplikasi NPWP
            if entity.npwp:
                exists = await self.exists_by_npwp(str(entity.npwp))
                if exists:
                    raise DuplicateNPWPError(f"NPWP {entity.npwp} already registered")

            table = await self._to_orm(entity)
            self.session.add(table)
            await self.session.flush()
            logger.info("Legal entity added: %s (id=%s)", entity.legal_name, entity.id)

        except DuplicateNPWPError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            if "npwp" in str(e).lower():
                raise DuplicateNPWPError(f"NPWP already exists: {e}") from e
            raise LegalEntityRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add legal entity: %s", e)
            raise LegalEntityRepositoryError(f"Failed to add legal entity: {e}") from e

    async def get_by_id(self, entity_id: UUID) -> LegalEntityAggregate | None:
        """Mengambil entitas hukum berdasarkan ID."""
        try:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.id == entity_id, LegalEntityTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None
            return self._to_domain(table)

        except Exception as e:
            logger.error("Failed to get legal entity by id %s: %s", entity_id, e)
            raise LegalEntityRepositoryError(f"Failed to get legal entity: {e}") from e

    async def get_by_npwp(self, tax_id_number: str) -> LegalEntityAggregate | None:
        """Mengambil entitas hukum berdasarkan NPWP."""
        try:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.npwp == tax_id_number, LegalEntityTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None
            return self._to_domain(table)

        except Exception as e:
            logger.error("Failed to get legal entity by NPWP %s: %s", tax_id_number, e)
            raise LegalEntityRepositoryError(f"Failed to get legal entity: {e}") from e

    async def update(self, entity: LegalEntityAggregate) -> None:
        """Memperbarui entitas hukum."""
        try:
            # Get current version
            stmt = select(LegalEntityTable.version).where(LegalEntityTable.id == entity.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise LegalEntityNotFoundError(f"Legal entity {entity.id} not found")

            if current_version != entity.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {entity.version}, got {current_version}"
                )

            table = await self._to_orm(entity)
            table.version = entity.version + 1
            table.updated_at = datetime.utcnow()

            await self.session.merge(table)
            await self.session.flush()
            logger.info("Legal entity updated: %s", entity.legal_name)

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update legal entity %s: %s", entity.id, e)
            raise LegalEntityRepositoryError(f"Failed to update legal entity: {e}") from e

    async def delete(self, entity_id: UUID) -> bool:
        """Soft delete entitas hukum."""
        try:
            # Check if has branches
            branch_stmt = (
                select(func.count())
                .select_from(LegalEntityBranchTable)
                .where(
                    LegalEntityBranchTable.parent_entity_id == entity_id,
                    LegalEntityBranchTable.deleted_at.is_(None),
                )
            )
            branch_result = await self.session.execute(branch_stmt)
            branch_count = branch_result.scalar()

            if branch_count > 0:
                raise LegalEntityHasBranchesError(
                    f"Legal entity {entity_id} has {branch_count} branches"
                )

            stmt = (
                update(LegalEntityTable)
                .where(LegalEntityTable.id == entity_id)
                .values(deleted_at=datetime.utcnow(), is_active=False, status="inactive")
            )
            result = await self.session.execute(stmt)
            await self.session.flush()

            deleted = result.rowcount > 0
            if deleted:
                logger.info("Legal entity %s soft deleted", entity_id)
            return deleted

        except LegalEntityHasBranchesError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete legal entity %s: %s", entity_id, e)
            raise LegalEntityRepositoryError(f"Failed to delete legal entity: {e}") from e

    async def find_all_active(self) -> list[LegalEntityAggregate]:
        """Semua entitas hukum yang aktif."""
        try:
            stmt = (
                select(LegalEntityTable)
                .where(LegalEntityTable.is_active == True, LegalEntityTable.deleted_at.is_(None))
                .order_by(LegalEntityTable.legal_name)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain(table) for table in tables]

        except Exception as e:
            logger.error("Failed to find active legal entities: %s", e)
            raise LegalEntityRepositoryError(f"Failed to find active entities: {e}") from e

    async def get_consolidation_group(self, group_id: UUID) -> list[LegalEntityAggregate]:
        """Entitas dalam grup konsolidasi."""
        try:
            # Get group members
            member_stmt = select(ConsolidationGroupMemberTable.entity_id).where(
                ConsolidationGroupMemberTable.group_id == group_id,
                ConsolidationGroupMemberTable.deleted_at.is_(None),
            )
            member_result = await self.session.execute(member_stmt)
            entity_ids = member_result.scalars().all()

            if not entity_ids:
                return []

            stmt = (
                select(LegalEntityTable)
                .where(LegalEntityTable.id.in_(entity_ids), LegalEntityTable.deleted_at.is_(None))
                .order_by(LegalEntityTable.legal_name)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain(table) for table in tables]

        except Exception as e:
            logger.error("Failed to get consolidation group %s: %s", group_id, e)
            raise LegalEntityRepositoryError(f"Failed to get consolidation group: {e}") from e

    async def exists_by_npwp(self, npwp: str) -> bool:
        """Check apakah NPWP sudah terdaftar."""
        try:
            stmt = (
                select(func.count())
                .select_from(LegalEntityTable)
                .where(LegalEntityTable.npwp == npwp, LegalEntityTable.deleted_at.is_(None))
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            logger.error("Failed to check NPWP %s: %s", npwp, e)
            raise LegalEntityRepositoryError(f"Failed to check NPWP: {e}") from e

    async def find_by_name_contains(
        self, name_fragment: str, limit: int = 50
    ) -> list[LegalEntityAggregate]:
        """Pencarian entitas berdasarkan nama."""
        try:
            # Menggunakan func.concat untuk menghindari f-string dalam SQL
            stmt = (
                select(LegalEntityTable)
                .where(
                    or_(
                        LegalEntityTable.legal_name.ilike(func.concat('%', name_fragment, '%')),
                        LegalEntityTable.trade_name.ilike(func.concat('%', name_fragment, '%')),
                    ),
                    LegalEntityTable.deleted_at.is_(None),
                )
                .limit(limit)
                .order_by(LegalEntityTable.legal_name)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain(table) for table in tables]

        except Exception as e:
            logger.error("Failed to search legal entities: %s", e)
            raise LegalEntityRepositoryError(f"Failed to search entities: {e}") from e

    # ========================================================================
    # BRANCH METHODS
    # ========================================================================

    async def add_branch(self, branch: dict[str, Any]) -> UUID:
        """Menambahkan cabang dari entitas hukum."""
        try:
            table = LegalEntityBranchTable(
                id=UUID,
                parent_entity_id=branch["parent_entity_id"],
                branch_name=branch["branch_name"],
                branch_code=branch.get("branch_code"),
                address=branch.get("address"),
                city=branch.get("city"),
                phone=branch.get("phone"),
                manager_name=branch.get("manager_name"),
                is_active=True,
                created_at=datetime.utcnow(),
                created_by=branch["created_by"],
            )
            self.session.add(table)
            await self.session.flush()
            logger.info(
                "Branch added for entity %s: %s",
                branch["parent_entity_id"],
                branch["branch_name"]
            )
            return table.id

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add branch: %s", e)
            raise LegalEntityRepositoryError(f"Failed to add branch: {e}") from e

    async def get_branches(self, parent_entity_id: UUID) -> list[dict[str, Any]]:
        """Mendapatkan semua cabang dari entitas hukum."""
        try:
            stmt = (
                select(LegalEntityBranchTable)
                .where(
                    LegalEntityBranchTable.parent_entity_id == parent_entity_id,
                    LegalEntityBranchTable.deleted_at.is_(None),
                )
                .order_by(LegalEntityBranchTable.branch_name)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            return [
                {
                    "id": t.id,
                    "branch_name": t.branch_name,
                    "branch_code": t.branch_code,
                    "address": t.address,
                    "city": t.city,
                    "phone": t.phone,
                    "manager_name": t.manager_name,
                    "is_active": t.is_active,
                }
                for t in tables
            ]

        except Exception as e:
            logger.error("Failed to get branches for %s: %s", parent_entity_id, e)
            raise LegalEntityRepositoryError(f"Failed to get branches: {e}") from e

    # ========================================================================
    # CONSOLIDATION GROUP METHODS
    # ========================================================================

    async def create_consolidation_group(
        self, group_name: str, description: str | None = None, created_by: UUID | None = None
    ) -> UUID:
        """Membuat grup konsolidasi baru."""
        try:
            table = ConsolidationGroupTable(
                id=UUID,
                group_name=group_name,
                description=description,
                is_active=True,
                created_at=datetime.utcnow(),
                created_by=created_by,
            )
            self.session.add(table)
            await self.session.flush()
            logger.info("Consolidation group created: %s", group_name)
            return table.id

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to create consolidation group: %s", e)
            raise LegalEntityRepositoryError(f"Failed to create group: {e}") from e

    async def add_to_consolidation_group(
        self, group_id: UUID, entity_id: UUID, ownership_percentage: Decimal
    ) -> None:
        """Menambahkan entitas ke grup konsolidasi."""
        try:
            # Check if already member
            stmt = (
                select(func.count())
                .select_from(ConsolidationGroupMemberTable)
                .where(
                    ConsolidationGroupMemberTable.group_id == group_id,
                    ConsolidationGroupMemberTable.entity_id == entity_id,
                    ConsolidationGroupMemberTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()

            if count > 0:
                logger.warning("Entity %s already in group %s", entity_id, group_id)
                return

            table = ConsolidationGroupMemberTable(
                id=UUID,
                group_id=group_id,
                entity_id=entity_id,
                ownership_percentage=float(ownership_percentage),
                joined_at=datetime.utcnow(),
            )
            self.session.add(table)

            # Update legal entity's consolidation group
            stmt2 = (
                update(LegalEntityTable)
                .where(LegalEntityTable.id == entity_id)
                .values(consolidation_group_id=group_id)
            )
            await self.session.execute(stmt2)
            await self.session.flush()

            logger.info("Entity %s added to consolidation group %s", entity_id, group_id)

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add entity to consolidation group: %s", e)
            raise LegalEntityRepositoryError(f"Failed to add to group: {e}") from e

    async def get_consolidation_groups(self, is_active: bool = True) -> list[dict[str, Any]]:
        """Mendapatkan semua grup konsolidasi."""
        try:
            stmt = select(ConsolidationGroupTable).where(
                ConsolidationGroupTable.is_active == is_active
            )
            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            groups = []
            for table in tables:
                # Get member count
                member_stmt = (
                    select(func.count())
                    .select_from(ConsolidationGroupMemberTable)
                    .where(
                        ConsolidationGroupMemberTable.group_id == table.id,
                        ConsolidationGroupMemberTable.deleted_at.is_(None),
                    )
                )
                member_result = await self.session.execute(member_stmt)
                member_count = member_result.scalar() or 0

                groups.append(
                    {
                        "id": table.id,
                        "group_name": table.group_name,
                        "description": table.description,
                        "member_count": member_count,
                        "is_active": table.is_active,
                        "created_at": table.created_at,
                    }
                )

            return groups

        except Exception as e:
            logger.error("Failed to get consolidation groups: %s", e)
            raise LegalEntityRepositoryError(f"Failed to get groups: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ConsolidationGroupNotFoundError",
    "DuplicateNPWPError",
    "DuplicateTaxIDError",
    "LegalEntityHasBranchesError",
    "LegalEntityNotFoundError",
    "LegalEntityRepositoryError",
    "OptimisticLockError",
    "SQLAlchemyLegalEntityRepository",
]
