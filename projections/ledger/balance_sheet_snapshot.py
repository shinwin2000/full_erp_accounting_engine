#!/usr/bin/env python3
"""
Module: balance_sheet_snapshot.py
Layer: Projections (Ledger)
Responsibility: Membangun read model Balance Sheet snapshot untuk setiap periode
               akuntansi.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Numeric,
    String,
    delete,
    func,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "balance_sheet_snapshot"
BATCH_SIZE = 100

# ============================================================================
# EXCEPTIONS
# ============================================================================


class BalanceSheetSnapshotError(Exception):
    pass


# ============================================================================
# ORM MODEL
# ============================================================================

Base = declarative_base()


class BalanceSheetSnapshotTable(Base):
    __tablename__: ClassVar[str] = "balance_sheet_snapshot"
    __table_args__: ClassVar[dict] = {"schema": "projections"}

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_name = Column(String(100), nullable=False)
    as_of_date = Column(Date, nullable=False)
    total_assets = Column(Numeric(20, 2), nullable=False, default=0)
    total_liabilities = Column(Numeric(20, 2), nullable=False, default=0)
    total_equity = Column(Numeric(20, 2), nullable=False, default=0)
    is_balanced = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# BALANCE SHEET SNAPSHOT PROJECTION
# ============================================================================


class BalanceSheetSnapshot:
    def __init__(self):
        self._event_store = None
        self._session_factory = None
        self._snapshots: dict[str, dict] = {}

    async def _get_event_store(self):
        if self._event_store is None:
            from infrastructure.event_store.append_only_store import get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def compute_snapshot(self, legal_entity_id: UUID, period_id: UUID) -> dict[str, Any]:
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise BalanceSheetSnapshotError(f"Period {period_id} not found")
            as_of_date = period.end_date

            account_stmt = select(AccountTable).where(
                AccountTable.legal_entity_id == legal_entity_id, AccountTable.deleted_at.is_(None)
            )
            account_result = await session.execute(account_stmt)
            accounts = account_result.scalars().all()

            total_assets = Decimal(0)
            total_liabilities = Decimal(0)
            total_equity = Decimal(0)

            for account in accounts:
                balance_stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
                ).where(
                    LedgerEntryTable.account_id == account.id,
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date <= as_of_date,
                )
                balance_result = await session.execute(balance_stmt)
                row = balance_result.first()
                debit = Decimal(str(row.debit or 0))
                credit = Decimal(str(row.credit or 0))
                if account.normal_balance == "debit":
                    balance = debit - credit
                else:
                    balance = credit - debit

                account_type = account.account_type
                if account_type in ("Asset", "ContraAsset"):
                    total_assets += balance
                elif account_type in ("Liability", "ContraLiability"):
                    total_liabilities += balance
                elif account_type in ("Equity", "ContraEquity"):
                    total_equity += balance

            return {
                "period_id": str(period_id),
                "period_name": period.period_name,
                "as_of_date": as_of_date.isoformat(),
                "legal_entity_id": str(legal_entity_id),
                "total_assets": float(total_assets),
                "total_liabilities": float(total_liabilities),
                "total_equity": float(total_equity),
                "is_balanced": abs(total_assets - (total_liabilities + total_equity)) < Decimal("0.01"),
                "created_at": datetime.now(UTC).isoformat(),
            }

    async def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        async with await self._get_session() as session, session.begin():
            await session.execute(
                delete(BalanceSheetSnapshotTable).where(
                    BalanceSheetSnapshotTable.legal_entity_id == UUID(snapshot["legal_entity_id"]),
                    BalanceSheetSnapshotTable.period_id == UUID(snapshot["period_id"]),
                )
            )
            stmt = insert(BalanceSheetSnapshotTable).values(
                id=uuid4(),
                legal_entity_id=UUID(snapshot["legal_entity_id"]),
                period_id=UUID(snapshot["period_id"]),
                period_name=snapshot["period_name"],
                as_of_date=date.fromisoformat(snapshot["as_of_date"]),
                total_assets=Decimal(str(snapshot["total_assets"])),
                total_liabilities=Decimal(str(snapshot["total_liabilities"])),
                total_equity=Decimal(str(snapshot["total_equity"])),
                is_balanced=snapshot["is_balanced"],
                created_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def rebuild_for_legal_entity(self, legal_entity_id: UUID) -> dict[str, Any]:
        logger.info(f"Rebuilding balance sheet snapshots for legal entity {legal_entity_id}")
        start_time = datetime.now(UTC)
        async with await self._get_session() as session:
            period_stmt = (
                select(FiscalPeriodTable)
                .where(
                    FiscalPeriodTable.legal_entity_id == legal_entity_id,
                    FiscalPeriodTable.status == "closed",
                )
                .order_by(FiscalPeriodTable.end_date)
            )
            period_result = await session.execute(period_stmt)
            periods = period_result.scalars().all()

        success_count = 0
        error_count = 0
        for period in periods:
            try:
                snapshot = await self.compute_snapshot(legal_entity_id, period.id)
                await self.save_snapshot(snapshot)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to compute snapshot for period {period.id}: {e}")
                error_count += 1

        duration = (datetime.now(UTC) - start_time).total_seconds()
        result = {
            "legal_entity_id": str(legal_entity_id),
            "periods_processed": len(periods),
            "success": success_count,
            "errors": error_count,
            "duration_seconds": duration,
        }
        logger.info(f"Balance sheet snapshots rebuild completed: {success_count} periods, {error_count} errors")
        if error_count > 0:
            await trigger_alert(
                title="Balance Sheet Snapshot Rebuild Partial Failure",
                message=f"{error_count} periods failed to generate snapshot",
                severity="warning",
                source="BalanceSheetSnapshot",
            )
        return result

    async def rebuild_all(self) -> dict[str, Any]:
        async with await self._get_session() as session:
            stmt = select(AccountTable.legal_entity_id).distinct()
            result = await session.execute(stmt)
            legal_entity_ids = result.scalars().all()

        total_success = 0
        total_errors = 0
        for le_id in legal_entity_ids:
            res = await self.rebuild_for_legal_entity(le_id)
            total_success += res["success"]
            total_errors += res["errors"]

        return {
            "legal_entities_processed": len(legal_entity_ids),
            "total_success": total_success,
            "total_errors": total_errors,
            "completed_at": datetime.now(UTC).isoformat(),
        }

    async def get_snapshot(self, legal_entity_id: UUID, period_id: UUID) -> dict | None:
        async with await self._get_session() as session:
            stmt = select(BalanceSheetSnapshotTable).where(
                BalanceSheetSnapshotTable.legal_entity_id == legal_entity_id,
                BalanceSheetSnapshotTable.period_id == period_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "period_id": str(row.period_id),
                "period_name": row.period_name,
                "as_of_date": row.as_of_date.isoformat(),
                "total_assets": float(row.total_assets),
                "total_liabilities": float(row.total_liabilities),
                "total_equity": float(row.total_equity),
                "is_balanced": row.is_balanced,
                "created_at": row.created_at.isoformat(),
            }

    async def get_snapshot_history(self, legal_entity_id: UUID, limit: int = 12) -> list[dict]:
        async with await self._get_session() as session:
            stmt = (
                select(BalanceSheetSnapshotTable)
                .where(BalanceSheetSnapshotTable.legal_entity_id == legal_entity_id)
                .order_by(BalanceSheetSnapshotTable.as_of_date.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "period_id": str(r.period_id),
                    "period_name": r.period_name,
                    "as_of_date": r.as_of_date.isoformat(),
                    "total_assets": float(r.total_assets),
                    "total_liabilities": float(r.total_liabilities),
                    "total_equity": float(r.total_equity),
                    "net_assets": float(r.total_assets - (r.total_liabilities + r.total_equity)),
                }
                for r in rows
            ]

    async def incremental_update(self, period_id: UUID) -> None:
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                logger.warning(f"Period {period_id} not found for snapshot update")
                return
            snapshot = await self.compute_snapshot(period.legal_entity_id, period_id)
            await self.save_snapshot(snapshot)
            logger.info(f"Balance sheet snapshot updated for period {period.period_name}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_balance_sheet_snapshot: BalanceSheetSnapshot | None = None


async def get_balance_sheet_snapshot() -> BalanceSheetSnapshot:
    global _balance_sheet_snapshot
    if _balance_sheet_snapshot is None:
        _balance_sheet_snapshot = BalanceSheetSnapshot()
    return _balance_sheet_snapshot


class BalanceSheetProjection:
    def __init__(self, for_date: date):
        self.for_date = for_date

    def generate(self):
        return {
            "as_of_date": self.for_date.isoformat(),
            "assets": 0,
            "liabilities": 0,
            "equity": 0,
        }


__all__ = [
    "BalanceSheetProjection",
    "BalanceSheetSnapshot",
    "BalanceSheetSnapshotError",
    "get_balance_sheet_snapshot",
]
