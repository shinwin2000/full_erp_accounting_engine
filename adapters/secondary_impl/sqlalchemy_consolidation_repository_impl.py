#!/usr/bin/env python3
"""
Module: sqlalchemy_consolidation_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk konsolidasi menggunakan SQLAlchemy.
               Mendukung pengelolaan grup konsolidasi, entitas, kepemilikan,
               transaksi antar perusahaan, dan ekuitas.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Numeric, String, Text, func, select, and_, or_
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from domain.consolidation.aggregate_root import ConsolidationGroup
from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# ORM MODELS (self-contained)
# ============================================================================

Base = declarative_base()


class ConsolidationGroupTable(Base):
    __tablename__ = "consolidation_groups"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    group_code = Column(String(50), nullable=False, unique=True)
    group_name = Column(String(200), nullable=False)
    parent_entity_id = Column(PGUUID(as_uuid=True), nullable=True)
    consolidation_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)


class ConsolidationEntityTable(Base):
    __tablename__ = "consolidation_entities"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(PGUUID(as_uuid=True), ForeignKey("consolidation_groups.id"), nullable=False)
    entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    entity_name = Column(String(200), nullable=False)
    ownership_percentage = Column(Numeric(5, 2), nullable=False)
    acquisition_date = Column(Date, nullable=True)
    is_parent = Column(Boolean, default=False)
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class IntercompanyTransactionTable(Base):
    __tablename__ = "intercompany_transactions"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(PGUUID(as_uuid=True), ForeignKey("consolidation_groups.id"), nullable=False)
    from_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    to_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    transaction_date = Column(Date, nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="IDR")
    transaction_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    eliminated = Column(Boolean, default=False)
    elimination_journal_id = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class OwnershipTable(Base):
    __tablename__ = "ownerships"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    subsidiary_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    ownership_percentage = Column(Numeric(5, 2), nullable=False)
    effective_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================

class SQLAlchemyConsolidationRepository(ConsolidationRepositoryPort):
    """
    Implementasi repository konsolidasi dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========================================================================
    # PORT METHODS
    # ========================================================================

    # ----- save_group (alias untuk save_consolidation) -----
    async def save_group(self, group: ConsolidationGroup) -> None:
        """Simpan grup konsolidasi (alias untuk save_consolidation)."""
        await self.save_consolidation(group)

    async def save_consolidation(self, group: ConsolidationGroup) -> None:
        """Simpan atau update grup konsolidasi."""
        session = await self._get_session()
        orm_group = ConsolidationGroupTable(
            id=group.id,
            legal_entity_id=group.legal_entity_id,
            group_code=group.group_code,
            group_name=group.group_name,
            parent_entity_id=group.parent_entity_id,
            consolidation_date=group.consolidation_date,
            status=getattr(group, "status", "draft"),
            description=getattr(group, "description", None),
            created_by=getattr(group, "created_by", None),
        )
        existing = await session.get(ConsolidationGroupTable, group.id)
        if existing:
            for key, value in orm_group.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(orm_group)
        await session.flush()

    # ----- find_group (alias untuk get_consolidation) -----
    async def find_group(self, group_id: uuid.UUID) -> ConsolidationGroup | None:
        """Ambil grup konsolidasi berdasarkan ID (alias untuk get_consolidation)."""
        return await self.get_consolidation(group_id)

    async def get_consolidation(self, group_id: uuid.UUID) -> ConsolidationGroup | None:
        """Ambil grup konsolidasi berdasarkan ID."""
        session = await self._get_session()
        stmt = select(ConsolidationGroupTable).where(ConsolidationGroupTable.id == group_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return ConsolidationGroup(
            id=row.id,
            legal_entity_id=row.legal_entity_id,
            group_code=row.group_code,
            group_name=row.group_name,
            parent_entity_id=row.parent_entity_id,
            consolidation_date=row.consolidation_date,
            status=row.status,
            description=row.description,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    async def list_consolidations(self, legal_entity_id: uuid.UUID) -> list[ConsolidationGroup]:
        """Daftar semua grup konsolidasi untuk entitas hukum."""
        session = await self._get_session()
        stmt = select(ConsolidationGroupTable).where(
            ConsolidationGroupTable.legal_entity_id == legal_entity_id
        ).order_by(ConsolidationGroupTable.consolidation_date.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            ConsolidationGroup(
                id=r.id,
                legal_entity_id=r.legal_entity_id,
                group_code=r.group_code,
                group_name=r.group_name,
                parent_entity_id=r.parent_entity_id,
                consolidation_date=r.consolidation_date,
                status=r.status,
                description=r.description,
                created_at=r.created_at,
                created_by=r.created_by,
            ) for r in rows
        ]

    async def get_entity_equity(self, entity_id: uuid.UUID, as_of_date: date) -> Decimal:
        """Hitung ekuitas entitas pada tanggal tertentu."""
        session = await self._get_session()
        try:
            from infrastructure.persistence_orm.account_table import AccountTable
            stmt = select(
                func.coalesce(func.sum(AccountTable.balance), 0)
            ).where(
                AccountTable.legal_entity_id == entity_id,
                AccountTable.account_type == "EQUITY",
                AccountTable.balance_date <= as_of_date,
            )
            result = await session.execute(stmt)
            return Decimal(str(result.scalar() or 0))
        except ImportError:
            logger.debug("AccountTable not available, returning 0 for equity")
            return Decimal(0)
        except Exception as e:
            logger.warning(f"Failed to get entity equity: {str(e)}")
            return Decimal(0)

    async def get_intercompany_balances(self, group_id: uuid.UUID) -> list[dict[str, Any]]:
        """Ambil saldo antar perusahaan dalam grup (agregasi transaksi)."""
        session = await self._get_session()
        stmt = (
            select(
                IntercompanyTransactionTable.from_entity_id,
                IntercompanyTransactionTable.to_entity_id,
                func.sum(IntercompanyTransactionTable.amount).label("total_amount"),
                IntercompanyTransactionTable.currency,
            )
            .where(IntercompanyTransactionTable.group_id == group_id)
            .group_by(
                IntercompanyTransactionTable.from_entity_id,
                IntercompanyTransactionTable.to_entity_id,
                IntercompanyTransactionTable.currency,
            )
        )
        result = await session.execute(stmt)
        rows = result.all()
        return [
            {
                "from_entity_id": row.from_entity_id,
                "to_entity_id": row.to_entity_id,
                "total_amount": row.total_amount,
                "currency": row.currency,
            }
            for row in rows
        ]

    async def get_intercompany_transactions(self, group_id: uuid.UUID) -> list[dict[str, Any]]:
        """Ambil semua transaksi antar perusahaan dalam grup."""
        session = await self._get_session()
        stmt = select(IntercompanyTransactionTable).where(
            IntercompanyTransactionTable.group_id == group_id
        ).order_by(IntercompanyTransactionTable.transaction_date)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "from_entity_id": r.from_entity_id,
                "to_entity_id": r.to_entity_id,
                "transaction_date": r.transaction_date,
                "amount": r.amount,
                "currency": r.currency,
                "transaction_type": r.transaction_type,
                "description": r.description,
                "eliminated": r.eliminated,
            }
            for r in rows
        ]

    async def get_ownership_percentage(self, parent_id: uuid.UUID, subsidiary_id: uuid.UUID) -> Decimal:
        """Ambil persentase kepemilikan parent terhadap subsidiary."""
        session = await self._get_session()
        stmt = select(OwnershipTable.ownership_percentage).where(
            OwnershipTable.parent_entity_id == parent_id,
            OwnershipTable.subsidiary_entity_id == subsidiary_id,
        ).order_by(OwnershipTable.effective_date.desc()).limit(1)
        result = await session.execute(stmt)
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else Decimal(0)

    async def save_intercompany_transaction(self, transaction: dict[str, Any]) -> None:
        """Simpan transaksi antar perusahaan."""
        session = await self._get_session()
        trx = IntercompanyTransactionTable(
            id=transaction.get("id", uuid.uuid4()),
            group_id=transaction["group_id"],
            from_entity_id=transaction["from_entity_id"],
            to_entity_id=transaction["to_entity_id"],
            transaction_date=transaction["transaction_date"],
            amount=transaction["amount"],
            currency=transaction.get("currency", "IDR"),
            transaction_type=transaction["transaction_type"],
            description=transaction.get("description"),
            eliminated=transaction.get("eliminated", False),
            elimination_journal_id=transaction.get("elimination_journal_id"),
        )
        session.add(trx)
        await session.flush()


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SqlAlchemyConsolidationRepository = SQLAlchemyConsolidationRepository
SQLAlchemyConsolidationRepositoryImpl = SQLAlchemyConsolidationRepository

__all__ = [
    "SQLAlchemyConsolidationRepository",
    "SqlAlchemyConsolidationRepository",
    "SQLAlchemyConsolidationRepositoryImpl",
]