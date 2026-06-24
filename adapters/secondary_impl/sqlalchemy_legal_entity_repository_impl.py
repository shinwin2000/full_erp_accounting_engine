#!/usr/bin/env python3
"""
Module: sqlalchemy_legal_entity_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Legal Entity Management menggunakan
               SQLAlchemy ORM. LENGKAP dengan semua method port.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, UTC, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update, and_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.legal_entity.aggregate_root import EntityType, LegalEntityAggregate, LegalEntityStatus
from domain.legal_entity.company_tax_profile_vo import CompanyTaxProfile
from domain.shared_value_objects.npwp_vo import NPWPVO
from infrastructure.persistence_orm.consolidation_group_member_table import (
    ConsolidationGroupMemberTable,
)
from infrastructure.persistence_orm.consolidation_group_table import ConsolidationGroupTable
from infrastructure.persistence_orm.legal_entity_branch_table import LegalEntityBranchTable
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable
from ports.primary.legal_entity_repository_port import LegalEntityRepositoryPort

logger = logging.getLogger(__name__)

DEFAULT_COUNTRY = "ID"
DEFAULT_CURRENCY = "IDR"


class LegalEntityRepositoryError(Exception):
    pass


class DuplicateNPWPError(LegalEntityRepositoryError):
    pass


class DuplicateTaxIDError(LegalEntityRepositoryError):
    pass


class LegalEntityNotFoundError(LegalEntityRepositoryError):
    pass


class LegalEntityHasBranchesError(LegalEntityRepositoryError):
    pass


class ConsolidationGroupNotFoundError(LegalEntityRepositoryError):
    pass


class OptimisticLockError(LegalEntityRepositoryError):
    pass


class SQLAlchemyLegalEntityRepository(LegalEntityRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: List[Dict[str, Any]] = []

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
        return LegalEntityAggregate(
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

    async def _to_orm(self, aggregate: LegalEntityAggregate) -> LegalEntityTable:
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

    async def _log_audit(self, action: str, entity_id: UUID, details: Dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "entity_id": str(entity_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # EXISTING CRUD METHODS
    # ========================================================================

    async def add(self, entity: LegalEntityAggregate) -> None:
        try:
            if entity.npwp:
                exists = await self.exists_by_npwp(str(entity.npwp))
                if exists:
                    raise DuplicateNPWPError(f"NPWP {entity.npwp} already registered")
            table = await self._to_orm(entity)
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

    async def get_by_id(self, entity_id: UUID) -> LegalEntityAggregate | None:
        try:
            stmt = select(LegalEntityTable).where(LegalEntityTable.id == entity_id, LegalEntityTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain(table)
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get legal entity: {e}") from e

    async def get_by_npwp(self, tax_id_number: str) -> LegalEntityAggregate | None:
        try:
            stmt = select(LegalEntityTable).where(LegalEntityTable.npwp == tax_id_number, LegalEntityTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain(table)
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get legal entity by NPWP: {e}") from e

    async def get_by_tax_id(self, tax_id: str) -> LegalEntityAggregate | None:
        """Alias for get_by_npwp."""
        return await self.get_by_npwp(tax_id)

    async def get_by_code(self, entity_code: str) -> LegalEntityAggregate | None:
        """Get entity by registration number or code."""
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
            return self._to_domain(table)
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get entity by code: {e}") from e

    async def update(self, entity: LegalEntityAggregate) -> None:
        try:
            stmt = select(LegalEntityTable.version).where(LegalEntityTable.id == entity.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise LegalEntityNotFoundError(f"Legal entity {entity.id} not found")
            if current_version != entity.version:
                raise OptimisticLockError(f"Version mismatch: expected {entity.version}, got {current_version}")
            table = await self._to_orm(entity)
            table.version = entity.version + 1
            table.updated_at = datetime.utcnow()
            await self.session.merge(table)
            await self.session.flush()
            await self._log_audit("UPDATE", entity.id, {"legal_name": entity.legal_name})
            logger.info("Legal entity updated: %s", entity.legal_name)
        except (LegalEntityNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to update legal entity: {e}") from e

    async def delete(self, entity_id: UUID) -> bool:
        try:
            branch_stmt = select(func.count()).select_from(LegalEntityBranchTable).where(
                LegalEntityBranchTable.parent_entity_id == entity_id,
                LegalEntityBranchTable.deleted_at.is_(None),
            )
            branch_result = await self.session.execute(branch_stmt)
            if branch_result.scalar() > 0:
                raise LegalEntityHasBranchesError(f"Legal entity {entity_id} has branches")
            stmt = update(LegalEntityTable).where(LegalEntityTable.id == entity_id).values(
                deleted_at=datetime.utcnow(), is_active=False, status="inactive"
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            deleted = result.rowcount > 0
            if deleted:
                await self._log_audit("DELETE", entity_id, {})
                logger.info("Legal entity %s soft deleted", entity_id)
            return deleted
        except LegalEntityHasBranchesError:
            raise
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to delete legal entity: {e}") from e

    async def restore(self, entity_id: UUID) -> bool:
        """Restore a soft-deleted entity."""
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
                await self._log_audit("RESTORE", entity_id, {})
                logger.info("Legal entity %s restored", entity_id)
                return True
            return False
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to restore entity: {e}") from e

    async def find_all_active(self) -> list[LegalEntityAggregate]:
        try:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.is_active == True,
                LegalEntityTable.deleted_at.is_(None),
            ).order_by(LegalEntityTable.legal_name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to find active entities: {e}") from e

    async def get_all(self, include_inactive: bool = False, limit: int = 100, offset: int = 0) -> list[LegalEntityAggregate]:
        """Get all legal entities with pagination."""
        try:
            conditions = [LegalEntityTable.deleted_at.is_(None)]
            if not include_inactive:
                conditions.append(LegalEntityTable.is_active == True)
            stmt = select(LegalEntityTable).where(and_(*conditions)).order_by(
                LegalEntityTable.legal_name
            ).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get all entities: {e}") from e

    async def get_children(self, parent_company_id: UUID) -> list[LegalEntityAggregate]:
        """Get subsidiaries/children of a parent company."""
        try:
            stmt = select(LegalEntityTable).where(
                LegalEntityTable.parent_company_id == parent_company_id,
                LegalEntityTable.deleted_at.is_(None),
            ).order_by(LegalEntityTable.legal_name)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get children: {e}") from e

    async def get_tree(self, root_entity_id: UUID) -> Dict[str, Any]:
        """Get hierarchical tree of entities."""
        try:
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
        except LegalEntityNotFoundError:
            raise
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get tree: {e}") from e

    async def exists_by_npwp(self, npwp: str) -> bool:
        try:
            stmt = select(func.count()).select_from(LegalEntityTable).where(
                LegalEntityTable.npwp == npwp, LegalEntityTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to check NPWP: {e}") from e

    async def find_by_name_contains(self, name_fragment: str, limit: int = 50) -> list[LegalEntityAggregate]:
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
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to search entities: {e}") from e

    # ========================================================================
    # TAX PROFILE METHODS
    # ========================================================================

    async def get_tax_profile(self, entity_id: UUID) -> CompanyTaxProfile | None:
        """Get tax profile of a legal entity."""
        entity = await self.get_by_id(entity_id)
        if not entity:
            return None
        return entity.tax_profile

    async def update_tax_profile(self, entity_id: UUID, tax_profile: CompanyTaxProfile) -> bool:
        """Update tax profile of a legal entity."""
        entity = await self.get_by_id(entity_id)
        if not entity:
            return False
        entity.tax_profile = tax_profile
        await self.update(entity)
        await self._log_audit("UPDATE_TAX_PROFILE", entity_id, {})
        return True

    # ========================================================================
    # FISCAL YEAR METHODS
    # ========================================================================

    async def get_fiscal_year_range(self, entity_id: UUID) -> Tuple[int, int]:
        """Get fiscal year start and end (as integers)."""
        entity = await self.get_by_id(entity_id)
        if not entity:
            raise LegalEntityNotFoundError(f"Entity {entity_id} not found")
        if not entity.fiscal_year_start or not entity.fiscal_year_end:
            # Default to calendar year
            return 1, 12
        return entity.fiscal_year_start, entity.fiscal_year_end

    async def get_previous_fiscal_year(self, entity_id: UUID) -> Tuple[int, int]:
        """Get previous fiscal year period."""
        start_month, end_month = await self.get_fiscal_year_range(entity_id)
        current_year = datetime.now(UTC).year
        if start_month > datetime.now(UTC).month:
            # If current month is before fiscal year start, previous year is current_year - 1
            prev_year = current_year - 1
        else:
            prev_year = current_year
        return prev_year, prev_year - 1  # returns (year, previous_year)

    # ========================================================================
    # STATISTICS
    # ========================================================================

    async def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about legal entities."""
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

    async def export_to_csv(self, include_inactive: bool = False) -> str:
        """Export legal entities to CSV string."""
        entities = await self.get_all(include_inactive, limit=10000)
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
                e.trade_name,
                e.entity_type.value,
                e.registration_number or "",
                str(e.npwp) if e.npwp else "",
                e.address or "",
                e.city or "",
                e.country or "",
                e.phone or "",
                e.email or "",
                e.base_currency,
                e.functional_currency,
                e.status.value,
                "1" if e.is_active else "0",
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, created_by: UUID) -> int:
        """Import legal entities from CSV string."""
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                npwp_val = row.get("npwp")
                entity_type = EntityType(row["entity_type"]) if row.get("entity_type") else EntityType.SUBSIDIARY
                status = LegalEntityStatus(row.get("status", "active")) if row.get("status") else LegalEntityStatus.ACTIVE
                entity = LegalEntityAggregate(
                    id=uuid4(),
                    legal_name=row["legal_name"],
                    trade_name=row.get("trade_name", row["legal_name"]),
                    entity_type=entity_type,
                    registration_number=row.get("registration_number"),
                    npwp=NPWPVO(npwp_val) if npwp_val else None,
                    tax_id=npwp_val,
                    address=row.get("address"),
                    city=row.get("city"),
                    country=row.get("country", "ID"),
                    phone=row.get("phone"),
                    email=row.get("email"),
                    base_currency=row.get("base_currency", "IDR"),
                    functional_currency=row.get("functional_currency", "IDR"),
                    status=status,
                    is_active=row.get("is_active", "1") == "1",
                    created_by=created_by,
                )
                await self.add(entity)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import entity row: {e}")
        return count

    # ========================================================================
    # BRANCH METHODS
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
                created_by=branch["created_by"],
            )
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("ADD_BRANCH", branch["parent_entity_id"], {"branch_name": branch["branch_name"]})
            logger.info("Branch added for entity %s: %s", branch["parent_entity_id"], branch["branch_name"])
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
    # CONSOLIDATION GROUP METHODS
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
            logger.info("Consolidation group created: %s", group_name)
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
            logger.info("Entity %s added to consolidation group %s", entity_id, group_id)
        except Exception as e:
            await self.session.rollback()
            raise LegalEntityRepositoryError(f"Failed to add to group: {e}") from e

    async def get_consolidation_groups(self, is_active: bool = True) -> list[dict[str, Any]]:
        try:
            stmt = select(ConsolidationGroupTable).where(ConsolidationGroupTable.is_active == is_active)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            groups = []
            for table in tables:
                member_stmt = select(func.count()).select_from(ConsolidationGroupMemberTable).where(
                    ConsolidationGroupMemberTable.group_id == table.id,
                    ConsolidationGroupMemberTable.deleted_at.is_(None),
                )
                member_result = await self.session.execute(member_stmt)
                groups.append({
                    "id": table.id,
                    "group_name": table.group_name,
                    "description": table.description,
                    "member_count": member_result.scalar() or 0,
                    "is_active": table.is_active,
                    "created_at": table.created_at,
                })
            return groups
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get consolidation groups: {e}") from e

    async def get_consolidation_group(self, group_id: UUID) -> list[LegalEntityAggregate]:
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
            return [self._to_domain(table) for table in tables]
        except Exception as e:
            raise LegalEntityRepositoryError(f"Failed to get consolidation group: {e}") from e

    # ========================================================================
    # AUDIT LOG & HEALTH
    # ========================================================================

    async def get_audit_log(self, entity_id: UUID | None = None, limit: int = 100) -> List[Dict[str, Any]]:
        logs = self._audit_log
        if entity_id:
            logs = [l for l in logs if l.get("entity_id") == str(entity_id)]
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[:limit]

    async def health_check(self) -> Dict[str, Any]:
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "LegalEntityRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "LegalEntityRepository", "error": str(e)}


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