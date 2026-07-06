#!/usr/bin/env python3
"""
Module: sqlalchemy_consolidation_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk konsolidasi menggunakan SQLAlchemy.
               Mendukung pengelolaan grup konsolidasi, entitas, kepemilikan,
               transaksi antar perusahaan, dan hasil konsolidasi.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    and_,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from domain.consolidation.aggregate_root import ConsolidationGroup
from domain.consolidation.elimination_entry import EliminationEntry
from domain.consolidation.intercompany_transaction import IntercompanyTransaction
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


class ConsolidationResultTable(Base):
    """Tabel untuk menyimpan hasil konsolidasi (rows, eliminations, NCI)."""
    __tablename__ = "consolidation_results"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consolidation_id = Column(PGUUID(as_uuid=True), nullable=False)  # refer ke ConsolidationGroupTable.id
    group_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_end_date = Column(Date, nullable=False)
    currency = Column(String(3), nullable=False, default="IDR")
    rows_json = Column(Text, nullable=False)  # JSON array of rows
    eliminations_json = Column(Text, nullable=False)  # JSON array of EliminationEntry
    nci_total = Column(Numeric(20, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)


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
    # INTERNAL HELPERS
    # ========================================================================

    def _to_domain_transaction(self, row: IntercompanyTransactionTable) -> IntercompanyTransaction:
        return IntercompanyTransaction(
            id=row.id,
            from_entity_id=row.from_entity_id,
            to_entity_id=row.to_entity_id,
            amount=row.amount,
            currency=row.currency,
            transaction_date=row.transaction_date,
            transaction_type=row.transaction_type,
            description=row.description,
            eliminated=row.eliminated,
            elimination_journal_id=row.elimination_journal_id,
        )

    async def _get_entities_for_group(self, group_id: UUID) -> list[ConsolidationEntityTable]:
        """Helper untuk mengambil daftar entitas dalam grup."""
        session = await self._get_session()
        stmt = select(ConsolidationEntityTable).where(
            ConsolidationEntityTable.group_id == group_id,
            ConsolidationEntityTable.status == "active"
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========================================================================
    # PORT METHODS (sesuai signature)
    # ========================================================================

    # ---- get_intercompany_transactions ----
    async def get_intercompany_transactions(
        self, entity_ids: list[UUID], as_of_date: date
    ) -> list[IntercompanyTransaction]:
        """Get all intercompany transactions between entities up to a date."""
        if not entity_ids:
            return []
        session = await self._get_session()
        # Cari transaksi di mana dari atau ke entitas ada dalam list
        stmt = (
            select(IntercompanyTransactionTable)
            .where(
                and_(
                    or_(
                        IntercompanyTransactionTable.from_entity_id.in_(entity_ids),
                        IntercompanyTransactionTable.to_entity_id.in_(entity_ids),
                    ),
                    IntercompanyTransactionTable.transaction_date <= as_of_date,
                )
            )
            .order_by(IntercompanyTransactionTable.transaction_date)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain_transaction(row) for row in rows]

    # ---- get_intercompany_balances ----
    async def get_intercompany_balances(
        self, entity_id: UUID, as_of_date: date
    ) -> list[Any]:   # type: ignore[override]
        """Get intercompany balances for an entity as of a date."""
        session = await self._get_session()
        # Agregasi dari transaksi: total receivable dan payable per counterparty
        stmt = (
            select(
                IntercompanyTransactionTable.to_entity_id.label("counterparty_id"),
                IntercompanyTransactionTable.currency,
                func.sum(
                    IntercompanyTransactionTable.amount
                ).label("total_amount"),
            )
            .where(
                IntercompanyTransactionTable.from_entity_id == entity_id,
                IntercompanyTransactionTable.transaction_date <= as_of_date,
                IntercompanyTransactionTable.eliminated == False,
            )
            .group_by(
                IntercompanyTransactionTable.to_entity_id,
                IntercompanyTransactionTable.currency,
            )
        )
        result = await session.execute(stmt)
        rows = result.all()

        # Tambahkan payable (from counterparty to entity)
        stmt2 = (
            select(
                IntercompanyTransactionTable.from_entity_id.label("counterparty_id"),
                IntercompanyTransactionTable.currency,
                func.sum(
                    IntercompanyTransactionTable.amount
                ).label("total_amount"),
            )
            .where(
                IntercompanyTransactionTable.to_entity_id == entity_id,
                IntercompanyTransactionTable.transaction_date <= as_of_date,
                IntercompanyTransactionTable.eliminated == False,
            )
            .group_by(
                IntercompanyTransactionTable.from_entity_id,
                IntercompanyTransactionTable.currency,
            )
        )
        result2 = await session.execute(stmt2)
        rows2 = result2.all()

        # Gabungkan dan format
        balances = []
        for row in rows:
            balances.append({
                "counterparty_id": str(row.counterparty_id),
                "currency": row.currency,
                "receivable": float(row.total_amount),
                "payable": 0.0,
            })
        for row in rows2:
            # Cek apakah counterparty sudah ada
            found = False
            for b in balances:
                if b["counterparty_id"] == str(row.counterparty_id) and b["currency"] == row.currency:
                    b["payable"] = float(row.total_amount)
                    found = True
                    break
            if not found:
                balances.append({
                    "counterparty_id": str(row.counterparty_id),
                    "currency": row.currency,
                    "receivable": 0.0,
                    "payable": float(row.total_amount),
                })
        return balances

    # ---- save_consolidation ----
    async def save_consolidation(
        self,
        id: UUID,
        group_entity_id: UUID,
        period_end_date: date,
        currency: str,
        rows: list[Any],
        eliminations: list[EliminationEntry],
        nci_total: Decimal,
        created_at: datetime,
    ) -> None:
        """Save a consolidation result."""
        session = await self._get_session()
        # Simpan hasil konsolidasi ke ConsolidationResultTable
        # rows dan eliminations di-serialize ke JSON
        rows_json = json.dumps([r.to_dict() if hasattr(r, "to_dict") else r for r in rows], default=str)
        eliminations_json = json.dumps(
            [e.to_dict() if hasattr(e, "to_dict") else e for e in eliminations],
            default=str
        )
        result = ConsolidationResultTable(
            id=uuid.uuid4(),
            consolidation_id=id,
            group_entity_id=group_entity_id,
            period_end_date=period_end_date,
            currency=currency,
            rows_json=rows_json,
            eliminations_json=eliminations_json,
            nci_total=nci_total,
            created_at=created_at or datetime.utcnow(),
            created_by=None,  # bisa ditambahkan jika ada user context
        )
        # Cek apakah sudah ada (update jika ada)
        existing = await session.execute(
            select(ConsolidationResultTable).where(
                ConsolidationResultTable.consolidation_id == id
            )
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row:
            existing_row.rows_json = rows_json
            existing_row.eliminations_json = eliminations_json
            existing_row.nci_total = nci_total
            existing_row.period_end_date = period_end_date
            existing_row.currency = currency
            existing_row.created_at = datetime.utcnow()
        else:
            session.add(result)
        await session.flush()

    # ---- get_consolidation ----
    async def get_consolidation(self, consolidation_id: UUID) -> Any | None:   # type: ignore[override]
        """Retrieve a consolidation result by ID."""
        session = await self._get_session()
        stmt = select(ConsolidationResultTable).where(
            ConsolidationResultTable.consolidation_id == consolidation_id
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": row.id,
            "consolidation_id": row.consolidation_id,
            "group_entity_id": row.group_entity_id,
            "period_end_date": row.period_end_date,
            "currency": row.currency,
            "rows": json.loads(row.rows_json),
            "eliminations": json.loads(row.eliminations_json),
            "nci_total": row.nci_total,
            "created_at": row.created_at,
        }

    # ---- list_consolidations ----
    async def list_consolidations(
        self,
        group_entity_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[Any]:   # type: ignore[override]
        """List consolidations for a group entity."""
        session = await self._get_session()
        conditions = [ConsolidationResultTable.group_entity_id == group_entity_id]
        if from_date:
            conditions.append(ConsolidationResultTable.period_end_date >= from_date)
        if to_date:
            conditions.append(ConsolidationResultTable.period_end_date <= to_date)
        stmt = select(ConsolidationResultTable).where(and_(*conditions)).order_by(
            ConsolidationResultTable.period_end_date.desc()
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "consolidation_id": r.consolidation_id,
                "group_entity_id": r.group_entity_id,
                "period_end_date": r.period_end_date,
                "currency": r.currency,
                "nci_total": r.nci_total,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    # ---- get_ownership_percentage ----
    async def get_ownership_percentage(self, parent_id: UUID, child_id: UUID) -> Decimal:
        """Get ownership percentage of parent in child entity."""
        session = await self._get_session()
        stmt = select(OwnershipTable.ownership_percentage).where(
            OwnershipTable.parent_entity_id == parent_id,
            OwnershipTable.subsidiary_entity_id == child_id,
        ).order_by(OwnershipTable.effective_date.desc()).limit(1)
        result = await session.execute(stmt)
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else Decimal(0)

    # ---- get_entity_equity ----
    async def get_entity_equity(self, entity_id: UUID, as_of_date: date) -> Decimal:
        """Get total equity of an entity as of date (from trial balance)."""
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
            logger.warning(f"Failed to get entity equity: {e!s}")
            return Decimal(0)

    # ---- save_intercompany_transaction ----
    async def save_intercompany_transaction(self, tx: IntercompanyTransaction) -> None:
        """Save an intercompany transaction."""
        session = await self._get_session()
        # Cek apakah sudah ada
        stmt = select(IntercompanyTransactionTable).where(IntercompanyTransactionTable.id == tx.id)
        existing = await session.execute(stmt)
        existing_row = existing.scalar_one_or_none()
        if existing_row:
            # Update
            existing_row.from_entity_id = tx.from_entity_id
            existing_row.to_entity_id = tx.to_entity_id
            existing_row.amount = tx.amount
            existing_row.currency = tx.currency
            existing_row.transaction_date = tx.transaction_date
            existing_row.transaction_type = tx.transaction_type
            existing_row.description = tx.description
            existing_row.eliminated = tx.eliminated
            existing_row.elimination_journal_id = tx.elimination_journal_id
        else:
            # Insert
            new_tx = IntercompanyTransactionTable(
                id=tx.id,
                group_id=None,  # group_id tidak ada di domain tx, bisa diisi dari context
                from_entity_id=tx.from_entity_id,
                to_entity_id=tx.to_entity_id,
                transaction_date=tx.transaction_date,
                amount=tx.amount,
                currency=tx.currency,
                transaction_type=tx.transaction_type,
                description=tx.description,
                eliminated=tx.eliminated,
                elimination_journal_id=tx.elimination_journal_id,
            )
            session.add(new_tx)
        await session.flush()

    # ========================================================================
    # NEW: consolidate_entities (sesuai kontrak ConsolidationRepositoryPort)
    # ========================================================================

    async def consolidate_entities(
        self,
        group_id: UUID,
        period_end_date: date,
        currency: str = "IDR",
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        """
        Lakukan konsolidasi untuk grup tertentu pada tanggal tertentu.
        Method ini memenuhi kontrak ConsolidationRepositoryPort.
        Mengembalikan ringkasan hasil konsolidasi.
        """
        session = await self._get_session()

        # 1. Ambil grup
        group = await self.find_group(group_id)
        if not group:
            raise ValueError(f"Group with id {group_id} not found")

        # 2. Ambil entitas dalam grup
        entities = await self._get_entities_for_group(group_id)
        if not entities:
            raise ValueError(f"No active entities found for group {group_id}")

        # 3. Kumpulkan ID entitas
        entity_ids = [e.entity_id for e in entities]
        parent_entity_id = next((e.entity_id for e in entities if e.is_parent), None)

        # 4. Dapatkan transaksi antar perusahaan
        transactions = await self.get_intercompany_transactions(entity_ids, period_end_date)

        # 5. Hitung total ekuitas per entitas dan NCI
        total_equity = Decimal(0)
        nci_total = Decimal(0)
        entity_equities = []
        for entity in entities:
            equity = await self.get_entity_equity(entity.entity_id, period_end_date)
            entity_equities.append({
                "entity_id": entity.entity_id,
                "entity_name": entity.entity_name,
                "ownership_percentage": entity.ownership_percentage,
                "equity": equity,
            })
            total_equity += equity
            # NCI: jika bukan parent, hitung (1 - ownership) * equity
            if entity.entity_id != parent_entity_id:
                nci_total += (Decimal(1) - entity.ownership_percentage) * equity

        # 6. Buat elimination entries sederhana (untuk transaksi antar perusahaan)
        eliminations: list[EliminationEntry] = []
        for tx in transactions:
            if not tx.eliminated:
                # Buat entry eliminasi
                elim = EliminationEntry(
                    id=uuid.uuid4(),
                    transaction_id=tx.id,
                    from_entity_id=tx.from_entity_id,
                    to_entity_id=tx.to_entity_id,
                    amount=tx.amount,
                    currency=tx.currency,
                    description=f"Elimination of {tx.transaction_type} between {tx.from_entity_id} and {tx.to_entity_id}",
                )
                eliminations.append(elim)
                # Tandai transaksi sebagai sudah dieliminasi
                tx.eliminated = True
                await self.save_intercompany_transaction(tx)

        # 7. Simpan hasil konsolidasi
        rows = entity_equities  # rows adalah list equity per entity
        await self.save_consolidation(
            id=group_id,
            group_entity_id=parent_entity_id or group.parent_entity_id or group_id,
            period_end_date=period_end_date,
            currency=currency,
            rows=rows,
            eliminations=eliminations,
            nci_total=nci_total,
            created_at=datetime.utcnow(),
        )

        # 8. Kembalikan ringkasan
        return {
            "group_id": str(group_id),
            "group_code": group.group_code,
            "period_end_date": period_end_date.isoformat(),
            "total_equity": float(total_equity),
            "nci_total": float(nci_total),
            "parent_entity_id": str(parent_entity_id) if parent_entity_id else None,
            "entities": [
                {
                    "entity_id": str(e["entity_id"]),
                    "entity_name": e["entity_name"],
                    "ownership": float(e["ownership_percentage"]),
                    "equity": float(e["equity"]),
                }
                for e in entity_equities
            ],
            "eliminations_count": len(eliminations),
        }

    # ========================================================================
    # LEGACY/INTERNAL METHODS (untuk kompatibilitas)
    # ========================================================================

    async def save_group(self, group: ConsolidationGroup) -> None:
        """Simpan grup konsolidasi (alias untuk save_consolidation dengan domain)."""
        # Karena save_consolidation sekarang menerima parameter berbeda, kita panggil dengan konversi
        # Tapi kita tetap simpan ke ConsolidationGroupTable untuk kompatibilitas
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

    async def find_group(self, group_id: UUID) -> ConsolidationGroup | None:
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


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SqlAlchemyConsolidationRepository = SQLAlchemyConsolidationRepository
SQLAlchemyConsolidationRepositoryImpl = SQLAlchemyConsolidationRepository

__all__ = [
    "SQLAlchemyConsolidationRepository",
    "SQLAlchemyConsolidationRepositoryImpl",
    "SqlAlchemyConsolidationRepository",
]