#!/usr/bin/env python3
"""
Module: sqlalchemy_legal_entity_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository Legal Entity dengan SQLAlchemy.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.legal_entity.aggregate_root import (
    EntityType,
    FiscalYearType,
    LegalEntityAggregate,
    LegalEntityStatus,
)
from domain.legal_entity.company_tax_profile_vo import (
    CompanyTaxProfile,
    Percentage,
    TaxPaymentMethod,
)
from domain.legal_entity.company_tax_profile_vo import TaxRegime as DomainTaxRegime
from domain.shared_value_objects.npwp_vo import NPWPVO, NPWPValidationError
from infrastructure.persistence_orm.consolidation_group_member_table import (
    ConsolidationGroupMemberTable,
)
from infrastructure.persistence_orm.consolidation_group_table import ConsolidationGroupTable
from infrastructure.persistence_orm.legal_entity_branch_table import LegalEntityBranchTable
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable
from ports.primary.legal_entity_repository_port import (
    LegalEntity,
    LegalEntityRepositoryPort,
    LegalEntityType,
    TaxProfile,
    TaxRegime,
)

logger = logging.getLogger(__name__)

DEFAULT_COUNTRY = "ID"
DEFAULT_CURRENCY = "IDR"


class LegalEntityRepositoryError(Exception):
    pass


class DuplicateNPWPError(LegalEntityRepositoryError):
    pass


class LegalEntityNotFoundError(LegalEntityRepositoryError):
    pass


class LegalEntityHasBranchesError(LegalEntityRepositoryError):
    pass


class OptimisticLockError(LegalEntityRepositoryError):
    pass


class SQLAlchemyLegalEntityRepository(LegalEntityRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise LegalEntityRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # MAPPING HELPERS (Port LegalEntity ↔ Domain LegalEntityAggregate)
    # ========================================================================

    def _safe_npwp(self, raw_npwp: str | None, entity_id: Any) -> NPWPVO | None:
        """NPWP di data lama/dummy kadang tidak valid checksum-nya (mis. data
        seed). Untuk read path, jangan biarkan itu menggagalkan seluruh query
        — log saja sebagai warning dan perlakukan sebagai None."""
        if not raw_npwp:
            return None
        try:
            return NPWPVO(raw_npwp)
        except NPWPValidationError:
            logger.warning(
                "Legal entity %s punya NPWP tidak valid di database ('%s'), "
                "diabaikan (di-set None) saat load.",
                entity_id, raw_npwp,
            )
            return None

    def _to_port(self, aggregate: LegalEntityAggregate) -> LegalEntity:
        """Konversi domain aggregate ke port DTO."""
        type_map = {
            EntityType.CORPORATION: LegalEntityType.CORPORATION,
            EntityType.LIMITED: LegalEntityType.LIMITED,
            EntityType.SOLE_PROPRIETORSHIP: LegalEntityType.SOLE_PROPRIETORSHIP,
            EntityType.PARTNERSHIP: LegalEntityType.LIMITED,  # port tidak punya PARTNERSHIP — approksimasi
            EntityType.COOPERATIVE: LegalEntityType.COOPERATIVE,
            EntityType.NON_PROFIT: LegalEntityType.FOUNDATION,
            EntityType.GOVERNMENT: LegalEntityType.GOVERNMENT,
        }
        entity_type = type_map.get(aggregate.entity_type, LegalEntityType.CORPORATION)

        domain_to_port_tax_regime = {
            DomainTaxRegime.GENERAL: TaxRegime.GENERAL,
            DomainTaxRegime.FINAL: TaxRegime.FINAL,
            DomainTaxRegime.GROSS_UP: TaxRegime.SPECIAL,
            DomainTaxRegime.WITHHOLDING: TaxRegime.SPECIAL,
        }

        tax_profile = TaxProfile(
            npwp=str(aggregate.npwp) if aggregate.npwp else None,
            tax_regime=(
                domain_to_port_tax_regime.get(aggregate.tax_profile.tax_regime, TaxRegime.GENERAL)
                if aggregate.tax_profile else TaxRegime.GENERAL
            ),
            is_pkp=aggregate.tax_profile.is_pkp if aggregate.tax_profile else False,
        )

        return LegalEntity(
            id=aggregate.id,
            entity_code=aggregate.entity_code,
            entity_name=aggregate.entity_name,
            legal_name=aggregate.legal_name,
            entity_type=entity_type,
            registration_number=None,  # domain tidak simpan field ini terpisah dari entity_code
            registration_date=None,
            established_date=aggregate.established_date,
            fiscal_year_start_month=aggregate.fiscal_year_start_month or 1,
            fiscal_year_end_month=12,  # domain tidak punya field ini, default kalender
            functional_currency=aggregate.functional_currency or "IDR",
            reporting_currency=aggregate.functional_currency or "IDR",
            addresses=[],
            contacts=[],
            tax_profile=tax_profile,
            parent_entity_id=aggregate.parent_entity_id,
            consolidation_group_id=None,  # domain simpan sebagai string (consolidation_group), bukan UUID
            is_active=aggregate.is_active,
            created_at=aggregate.created_at,
            created_by=UUID(int=0),  # domain simpan created_by sebagai string, bukan UUID
            updated_at=aggregate.updated_at,
            version=aggregate.version,
        )

    def _to_domain(self, port_entity: LegalEntity) -> LegalEntityAggregate:
        """Konversi port DTO ke domain aggregate."""
        # Mapping tipe
        type_map = {
            LegalEntityType.CORPORATION: EntityType.CORPORATION,
            LegalEntityType.LIMITED: EntityType.LIMITED,
            LegalEntityType.SOLE_PROPRIETORSHIP: EntityType.SOLE_PROPRIETORSHIP,
            LegalEntityType.COOPERATIVE: EntityType.COOPERATIVE,
            LegalEntityType.FOUNDATION: EntityType.NON_PROFIT,
            LegalEntityType.GOVERNMENT: EntityType.GOVERNMENT,
            LegalEntityType.REPRESENTATIVE_OFFICE: EntityType.CORPORATION,  # tidak ada padanan langsung di domain
        }
        entity_type = type_map.get(port_entity.entity_type, EntityType.CORPORATION)

        npwp_value = self._safe_npwp(
            port_entity.tax_profile.npwp if port_entity.tax_profile else None,
            port_entity.id,
        )

        tax_profile = CompanyTaxProfile(
            npwp=npwp_value,
            tax_office=port_entity.tax_profile.tax_office if port_entity.tax_profile else None,
            tax_office_code=port_entity.tax_profile.tax_office_code if port_entity.tax_profile else None,
            is_vat_collector=port_entity.tax_profile.is_pkp if port_entity.tax_profile else False,
            vat_collector_number=port_entity.tax_profile.pkp_number if port_entity.tax_profile else None,
        )

        return LegalEntityAggregate(
            id=port_entity.id,
            legal_name=port_entity.legal_name,
            trade_name=port_entity.entity_name,
            entity_type=entity_type,
            registration_number=port_entity.registration_number,
            npwp=npwp_value,
            tax_id=port_entity.tax_profile.npwp if port_entity.tax_profile else None,
            address=None,
            city=None,
            country=DEFAULT_COUNTRY,
            fiscal_year_start=port_entity.fiscal_year_start_month,
            fiscal_year_end=port_entity.fiscal_year_end_month,
            base_currency=port_entity.reporting_currency,
            functional_currency=port_entity.functional_currency,
            tax_profile=tax_profile,
            status=LegalEntityStatus.ACTIVE if port_entity.is_active else LegalEntityStatus.INACTIVE,
            is_active=port_entity.is_active,
            parent_company_id=port_entity.parent_entity_id,
            consolidation_group_id=port_entity.consolidation_group_id,
            created_at=port_entity.created_at,
            updated_at=port_entity.updated_at,
            created_by=port_entity.created_by,
            version=port_entity.version,
        )

    # ========================================================================
    # AUDIT LOG
    # ========================================================================

    async def _log_audit(self, action: str, entity_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "entity_id": str(entity_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # CRUD
    # ========================================================================

    async def add(self, entity: LegalEntity) -> None:
        try:
            if entity.tax_profile and entity.tax_profile.npwp:
                exists = await self.exists_by_npwp(entity.tax_profile.npwp)
                if exists:
                    raise DuplicateNPWPError(f"NPWP {entity.tax_profile.npwp} already registered")
            aggregate = self._to_domain(entity)
            table = await self._aggregate_to_orm(aggregate)
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("ADD", entity.id, {"legal_name": entity.legal_name})
            logger.info("Legal entity added: %s", entity.legal_name)
        except DuplicateNPWPError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            if "npwp" in str(e).lower():
                raise DuplicateNPWPError(f"NPWP already exists: {e}") from e
            raise LegalEntityRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to add legal entity: {e}") from e

    # ============================================================================
    # PERBAIKAN: Tambahkan pessimistic lock (SELECT FOR UPDATE) pada metode update
    # ============================================================================
    async def update(self, entity: LegalEntity) -> None:
        try:
            # Lock the row with SELECT FOR UPDATE to prevent race conditions
            stmt = select(LegalEntityTable).where(LegalEntityTable.id == entity.id).with_for_update()
            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                raise LegalEntityNotFoundError(f"Entity {entity.id} not found")

            # Check version for optimistic lock (double-check)
            if existing.version != entity.version:
                raise OptimisticLockError(f"Version mismatch: expected {entity.version}, got {existing.version}")

            aggregate = self._to_domain(entity)
            table = await self._aggregate_to_orm(aggregate)
            table.version = entity.version + 1
            table.updated_at = datetime.utcnow()
            # Since we have lock, we can merge or update directly
            await self.session.merge(table)
            await self.session.flush()
            await self._log_audit("UPDATE", entity.id, {"legal_name": entity.legal_name})
            logger.info("Legal entity updated: %s", entity.legal_name)
        except OptimisticLockError:
            raise
        except LegalEntityNotFoundError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to update legal entity: {e}") from e

    async def delete(self, entity_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        session = self.session
        try:
            async with session.begin():
                stmt_lock = select(LegalEntityTable).where(LegalEntityTable.id == entity_id).with_for_update()
                result = await session.execute(stmt_lock)
                table = result.scalar_one_or_none()
                if not table:
                    return False

                if not permanent:
                    # Check branches
                    branch_stmt = select(func.count()).select_from(LegalEntityBranchTable).where(
                        LegalEntityBranchTable.parent_entity_id == entity_id,
                        LegalEntityBranchTable.deleted_at.is_(None),
                    )
                    branch_result = await session.execute(branch_stmt)
                    if branch_result.scalar() > 0:
                        raise LegalEntityHasBranchesError(f"Entity {entity_id} has branches")

                    table.deleted_at = datetime.utcnow()
                    table.is_active = False
                    table.status = "inactive"
                    table.updated_at = datetime.utcnow()
                else:
                    await session.delete(table)

                await session.flush()
                await self._log_audit("DELETE" if permanent else "SOFT_DELETE", entity_id, {"user_id": str(user_id)})
                return True
        except LegalEntityHasBranchesError:
            raise
        except Exception as e:
            await session.rollback()
            raise LegalEntityRepositoryError(f"Failed to delete entity: {e}") from e

    async def restore(self, entity_id: UUID, user_id: UUID) -> bool:
        try:
            stmt = update(LegalEntityTable).where(
                LegalEntityTable.id == entity_id,
                LegalEntityTable.deleted_at.is_not(None),
            ).values(
                deleted_at=None,
                is_active=True,
                status="active",
                updated_at=datetime.utcnow(),
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            if result.rowcount > 0:
                await self._log_audit("RESTORE", entity_id, {"user_id": str(user_id)})
                return True
            return False
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to restore entity: {e}") from e

    # ========================================================================
    # QUERY
    # ========================================================================

    async def get_by_id(self, entity_id: UUID) -> LegalEntity | None:
        try:
            stmt = select(LegalEntityTable).where(LegalEntityTable.id == entity_id, LegalEntityTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            aggregate = self._orm_to_aggregate(table)
            return self._to_port(aggregate)
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get entity: {e}") from e

    async def get_by_npwp(self, npwp: str) -> LegalEntity | None:
        try:
            stmt = select(LegalEntityTable).where(LegalEntityTable.npwp == npwp, LegalEntityTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            aggregate = self._orm_to_aggregate(table)
            return self._to_port(aggregate)
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get entity by NPWP: {e}") from e

    async def get_by_tax_id(self, tax_id: str) -> LegalEntity | None:
        return await self.get_by_npwp(tax_id)

    async def get_by_code(self, entity_code: str) -> LegalEntity | None:
        try:
            stmt = select(LegalEntityTable).where(
                or_(
                    LegalEntityTable.registration_number == entity_code,
                    LegalEntityTable.trade_name == entity_code,
                ),
                LegalEntityTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            aggregate = self._orm_to_aggregate(table)
            return self._to_port(aggregate)
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get entity by code: {e}") from e

    async def find_all_active(self) -> list[LegalEntity]:
        try:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.is_active == True,
                LegalEntityTable.deleted_at.is_(None),
            ).order_by(LegalEntityTable.legal_name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_port(self._orm_to_aggregate(t)) for t in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to find active entities: {e}") from e

    async def get_all(self, include_inactive: bool = False, limit: int = 100, offset: int = 0) -> list[LegalEntity]:
        try:
            conditions = [LegalEntityTable.deleted_at.is_(None)]
            if not include_inactive:
                conditions.append(LegalEntityTable.is_active == True)
            stmt = select(LegalEntityTable).where(and_(*conditions)).order_by(
                LegalEntityTable.legal_name
            ).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_port(self._orm_to_aggregate(t)) for t in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get all entities: {e}") from e

    async def get_children(self, parent_entity_id: UUID) -> list[LegalEntity]:
        try:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.parent_company_id == parent_entity_id,
                LegalEntityTable.deleted_at.is_(None),
            ).order_by(LegalEntityTable.legal_name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_port(self._orm_to_aggregate(t)) for t in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get children: {e}") from e

    async def get_tree(self, root_entity_id: UUID) -> dict[str, Any]:
        root = await self.get_by_id(root_entity_id)
        if not root:
            raise LegalEntityNotFoundError(f"Entity {root_entity_id} not found")
        children = await self.get_children(root_entity_id)
        tree = {
            "id": str(root.id),
            "legal_name": root.legal_name,
            "entity_type": root.entity_type.value,
            "children": []
        }
        for child in children:
            child_tree = await self.get_tree(child.id)
            tree["children"].append(child_tree)
        return tree

    async def exists_by_npwp(self, npwp: str) -> bool:
        try:
            stmt = select(func.count()).select_from(LegalEntityTable).where(
                LegalEntityTable.npwp == npwp,
                LegalEntityTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to check NPWP: {e}") from e

    async def find_by_name_contains(self, name_fragment: str, limit: int = 50) -> list[LegalEntity]:
        try:
            stmt = select(LegalEntityTable).where(
                or_(
                    LegalEntityTable.legal_name.ilike(f"%{name_fragment}%"),
                    LegalEntityTable.trade_name.ilike(f"%{name_fragment}%"),
                ),
                LegalEntityTable.deleted_at.is_(None),
            ).limit(limit).order_by(LegalEntityTable.legal_name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_port(self._orm_to_aggregate(t)) for t in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to search entities: {e}") from e

    # ========================================================================
    # TAX PROFILE
    # ========================================================================

    async def get_tax_profile(self, entity_id: UUID) -> TaxProfile | None:
        entity = await self.get_by_id(entity_id)
        return entity.tax_profile if entity else None

    async def update_tax_profile(self, entity_id: UUID, tax_profile: TaxProfile, user_id: UUID) -> bool:
        entity = await self.get_by_id(entity_id)
        if not entity:
            return False
        # Update tax profile
        entity.tax_profile = tax_profile
        entity.updated_by = user_id
        entity.updated_at = datetime.now()
        entity.version += 1
        await self.update(entity)
        await self._log_audit("UPDATE_TAX_PROFILE", entity_id, {"user_id": str(user_id)})
        return True

    async def get_fiscal_year_range(self, entity_id: UUID, fiscal_year: int) -> tuple[date, date]:
        entity = await self.get_by_id(entity_id)
        if not entity:
            raise LegalEntityNotFoundError(f"Entity {entity_id} not found")
        start_month = entity.fiscal_year_start_month
        end_month = entity.fiscal_year_end_month
        start_date = date(fiscal_year, start_month, 1)
        if end_month == 12:
            end_date = date(fiscal_year, 12, 31)
        else:
            end_date = date(fiscal_year, end_month + 1, 1) - timedelta(days=1)
        return start_date, end_date

    async def get_previous_fiscal_year(self, entity_id: UUID, fiscal_year: int) -> int:
        entity = await self.get_by_id(entity_id)
        if not entity:
            raise LegalEntityNotFoundError(f"Entity {entity_id} not found")
        start_month = entity.fiscal_year_start_month
        if start_month == 1:
            return fiscal_year - 1
        else:
            return fiscal_year

    # ========================================================================
    # BRANCH
    # ========================================================================

    async def add_branch(self, branch: dict[str, Any]) -> UUID:
        try:
            table = LegalEntityBranchTable(
                id=uuid4(),
                parent_entity_id=branch["parent_entity_id"],
                branch_name=branch["branch_name"],
                branch_code=branch.get("branch_code"),
                address=branch.get("address"),
                city=branch.get("city"),
                phone=branch.get("phone"),
                manager_name=branch.get("manager_name"),
                is_active=True,
                created_at=datetime.utcnow(),
                created_by=branch.get("created_by"),
            )
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("ADD_BRANCH", branch["parent_entity_id"], {"branch_name": branch["branch_name"]})
            return table.id
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to add branch: {e}") from e

    async def get_branches(self, parent_entity_id: UUID) -> list[dict[str, Any]]:
        try:
            stmt = select(LegalEntityBranchTable).where(
                LegalEntityBranchTable.parent_entity_id == parent_entity_id,
                LegalEntityBranchTable.deleted_at.is_(None),
            ).order_by(LegalEntityBranchTable.branch_name)
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
            raise LegalEntityRepositoryError(f"Failed to get branches: {e}") from e

    # ========================================================================
    # CONSOLIDATION — DIPERBAIKI (tanpa query dalam loop)
    # ========================================================================

    async def create_consolidation_group(self, group_name: str, description: str | None = None, created_by: UUID | None = None) -> UUID:
        try:
            table = ConsolidationGroupTable(
                id=uuid4(),
                group_name=group_name,
                description=description,
                is_active=True,
                created_at=datetime.utcnow(),
                created_by=created_by,
            )
            self.session.add(table)
            await self.session.flush()
            return table.id
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to create consolidation group: {e}") from e

    async def add_to_consolidation_group(self, group_id: UUID, entity_id: UUID, ownership_percentage: Decimal) -> None:
        try:
            stmt = select(func.count()).select_from(ConsolidationGroupMemberTable).where(
                ConsolidationGroupMemberTable.group_id == group_id,
                ConsolidationGroupMemberTable.entity_id == entity_id,
                ConsolidationGroupMemberTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            if result.scalar() > 0:
                return
            table = ConsolidationGroupMemberTable(
                id=uuid4(),
                group_id=group_id,
                entity_id=entity_id,
                ownership_percentage=float(ownership_percentage),
                joined_at=datetime.utcnow(),
            )
            self.session.add(table)
            stmt2 = update(LegalEntityTable).where(LegalEntityTable.id == entity_id).values(consolidation_group_id=group_id)
            await self.session.execute(stmt2)
            await self.session.flush()
            await self._log_audit("ADD_TO_CONSOLIDATION", entity_id, {"group_id": str(group_id)})
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to add to group: {e}") from e

    async def get_consolidation_groups(self, is_active: bool = True) -> list[dict[str, Any]]:
        """
        Ambil semua group konsolidasi beserta jumlah anggota masing-masing.
        Menggunakan satu query agregasi (LEFT JOIN + GROUP BY) untuk menghindari N+1.
        """
        try:
            # Satu query: LEFT JOIN dengan member, group by group id, count member id
            stmt = (
                select(
                    ConsolidationGroupTable.id,
                    ConsolidationGroupTable.group_name,
                    ConsolidationGroupTable.description,
                    ConsolidationGroupTable.is_active,
                    ConsolidationGroupTable.created_at,
                    func.count(ConsolidationGroupMemberTable.id).label("member_count"),
                )
                .outerjoin(
                    ConsolidationGroupMemberTable,
                    and_(
                        ConsolidationGroupMemberTable.group_id == ConsolidationGroupTable.id,
                        ConsolidationGroupMemberTable.deleted_at.is_(None),
                    )
                )
                .where(ConsolidationGroupTable.is_active == is_active)
                .group_by(ConsolidationGroupTable.id)
                .order_by(ConsolidationGroupTable.group_name)
            )
            result = await self.session.execute(stmt)
            rows = result.all()
            groups = []
            for row in rows:
                groups.append({
                    "id": row.id,
                    "group_name": row.group_name,
                    "description": row.description,
                    "member_count": row.member_count or 0,
                    "is_active": row.is_active,
                    "created_at": row.created_at,
                })
            return groups
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get consolidation groups: {e}") from e

    async def get_consolidation_group(self, group_id: UUID) -> list[LegalEntity]:
        try:
            member_stmt = select(ConsolidationGroupMemberTable.entity_id).where(
                ConsolidationGroupMemberTable.group_id == group_id,
                ConsolidationGroupMemberTable.deleted_at.is_(None),
            )
            member_result = await self.session.execute(member_stmt)
            entity_ids = member_result.scalars().all()
            if not entity_ids:
                return []
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.id.in_(entity_ids),
                LegalEntityTable.deleted_at.is_(None),
            ).order_by(LegalEntityTable.legal_name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_port(self._orm_to_aggregate(t)) for t in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get consolidation group: {e}") from e

    # ========================================================================
    # ORM HELPERS
    # ========================================================================

    def _orm_to_aggregate(self, table: LegalEntityTable) -> LegalEntityAggregate:
        entity_type_map = {
            "corporation": EntityType.CORPORATION,
            "limited": EntityType.LIMITED,
            "sole": EntityType.SOLE_PROPRIETORSHIP,
            "sole_proprietorship": EntityType.SOLE_PROPRIETORSHIP,
            "partnership": EntityType.PARTNERSHIP,
            "cooperative": EntityType.COOPERATIVE,
            "non_profit": EntityType.NON_PROFIT,
            "government": EntityType.GOVERNMENT,
            "parent_company": EntityType.CORPORATION,
            "subsidiary": EntityType.CORPORATION,
            "branch": EntityType.CORPORATION,
            "representative_office": EntityType.CORPORATION,
            "joint_venture": EntityType.CORPORATION,
        }
        status_map = {
            "active": LegalEntityStatus.ACTIVE,
            "inactive": LegalEntityStatus.INACTIVE,
            "suspended": LegalEntityStatus.SUSPENDED,
            "dissolved": LegalEntityStatus.DISSOLVED,
            "liquidated": LegalEntityStatus.DISSOLVED,
        }
        tax_profile = CompanyTaxProfile(
            is_pkp=bool(table.is_vat_collector),
            tax_regime=DomainTaxRegime.GENERAL,
            corporate_income_tax_rate=Percentage(Decimal("22")),
            vat_rate=Percentage(Decimal("11")),
            vat_collection_method="output",
            income_tax_article=None,
            tax_bracket=table.tax_classification,
            payment_method=TaxPaymentMethod.MONTHLY_INSTALLMENT,
            annual_return_deadline_month=(
                table.annual_tax_return_due_date.month
                if table.annual_tax_return_due_date else 4
            ),
        )

        entity_code = (table.registration_number or str(table.id))[:20]
        if len(entity_code) < 3:
            entity_code = entity_code.ljust(3, "0")

        return LegalEntityAggregate(
            entity_id=table.id,
            entity_code=entity_code,
            entity_name=table.trade_name or table.legal_name,
            legal_name=table.legal_name,
            entity_type=entity_type_map.get(table.entity_type, EntityType.CORPORATION),
            status=status_map.get(table.status, LegalEntityStatus.ACTIVE),
            npwp=self._safe_npwp(table.npwp, table.id),
            tax_profile=tax_profile,
            address=table.address or "Alamat belum diisi",
            city=table.city or "N/A",
            province="N/A",  # kolom province tidak ada di LegalEntityTable
            postal_code=table.postal_code or "",
            country=table.country or "ID",
            phone=table.phone,
            email=table.email,
            website=table.website,
            fiscal_year_type=FiscalYearType.CALENDAR,
            fiscal_year_start_month=table.fiscal_year_start or 1,
            functional_currency=table.functional_currency or "IDR",
            parent_entity_id=table.parent_company_id,
            consolidation_group=str(table.consolidation_group_id) if table.consolidation_group_id else None,
            established_date=table.established_date,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=str(table.created_by) if table.created_by else "system",
            version=table.version or 1,
        )

    async def _aggregate_to_orm(self, aggregate: LegalEntityAggregate) -> LegalEntityTable:
        entity_type_str = aggregate.entity_type.value if hasattr(aggregate.entity_type, "value") else str(aggregate.entity_type)
        status_str = aggregate.status.value if hasattr(aggregate.status, "value") else str(aggregate.status)
        return LegalEntityTable(
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
            tax_office_code=aggregate.tax_profile.tax_office_code if aggregate.tax_profile else None,
            tax_classification=aggregate.tax_profile.tax_classification if aggregate.tax_profile else None,
            taxable_date=aggregate.tax_profile.taxable_date if aggregate.tax_profile else None,
            annual_tax_return_due_date=aggregate.tax_profile.annual_tax_return_due_date if aggregate.tax_profile else None,
            monthly_tax_due_date=aggregate.tax_profile.monthly_tax_due_date if aggregate.tax_profile else None,
            is_vat_collector=aggregate.tax_profile.is_vat_collector if aggregate.tax_profile else False,
            vat_collector_number=aggregate.tax_profile.vat_collector_number if aggregate.tax_profile else None,
            is_withholding_agent=aggregate.tax_profile.is_withholding_agent if aggregate.tax_profile else False,
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

    # ========================================================================
    # STATISTICS
    # ========================================================================

    async def get_statistics(self) -> dict[str, Any]:
        try:
            total_stmt = select(func.count()).select_from(LegalEntityTable).where(LegalEntityTable.deleted_at.is_(None))
            total = (await self.session.execute(total_stmt)).scalar() or 0
            active_stmt = select(func.count()).where(
                LegalEntityTable.is_active == True,
                LegalEntityTable.deleted_at.is_(None),
            )
            active = (await self.session.execute(active_stmt)).scalar() or 0
            type_stmt = select(LegalEntityTable.entity_type, func.count()).where(
                LegalEntityTable.deleted_at.is_(None),
            ).group_by(LegalEntityTable.entity_type)
            type_result = await self.session.execute(type_stmt)
            type_breakdown = {row[0]: row[1] for row in type_result.all()}
            return {
                "total_entities": total,
                "active_entities": active,
                "inactive_entities": total - active,
                "type_breakdown": type_breakdown,
            }
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get statistics: {e}") from e

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    async def export_to_csv(self) -> str:
        entities = await self.get_all(include_inactive=True, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "legal_name", "trade_name", "entity_type", "registration_number",
            "npwp", "address", "city", "country", "phone", "email",
            "base_currency", "functional_currency", "status", "is_active"
        ])
        for e in entities:
            writer.writerow([
                e.legal_name,
                e.entity_name,
                e.entity_type.value,
                e.registration_number or "",
                e.tax_profile.npwp if e.tax_profile else "",
                "",
                "",
                "",
                "",
                "",
                e.reporting_currency,
                e.functional_currency,
                "active" if e.is_active else "inactive",
                "1" if e.is_active else "0",
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, created_by: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                entity_type = LegalEntityType(row.get("entity_type", "corporation"))
                tax_profile = TaxProfile(
                    npwp=row.get("npwp"),
                    tax_regime=TaxRegime.GENERAL,
                    is_pkp=True,
                )
                entity = LegalEntity(
                    id=uuid4(),
                    entity_code=row.get("registration_number") or f"ENT-{count:06d}",
                    entity_name=row.get("trade_name") or row.get("legal_name", ""),
                    legal_name=row.get("legal_name", ""),
                    entity_type=entity_type,
                    registration_number=row.get("registration_number"),
                    registration_date=None,
                    established_date=None,
                    fiscal_year_start_month=1,
                    fiscal_year_end_month=12,
                    functional_currency=row.get("functional_currency", "IDR"),
                    reporting_currency=row.get("base_currency", "IDR"),
                    tax_profile=tax_profile,
                    is_active=row.get("is_active", "1") == "1",
                    created_by=created_by,
                    updated_by=created_by,
                )
                await self.add(entity)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import entity row: {e}")
        return count

    # ========================================================================
    # AUDIT & HEALTH
    # ========================================================================

    async def get_audit_log(self, entity_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if entity_id:
            logs = [l for l in logs if l.get("entity_id") == str(entity_id)]
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[:limit]

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "LegalEntityRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "LegalEntityRepository", "error": str(e)}


# ============================================================================
# ALIAS
# ============================================================================

SQLAlchemyLegalEntityRepositoryImpl = SQLAlchemyLegalEntityRepository

__all__ = [
    "DuplicateNPWPError",
    "LegalEntityHasBranchesError",
    "LegalEntityNotFoundError",
    "LegalEntityRepositoryError",
    "OptimisticLockError",
    "SQLAlchemyLegalEntityRepository",
    "SQLAlchemyLegalEntityRepositoryImpl",
]
