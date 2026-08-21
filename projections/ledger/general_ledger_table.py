#!/usr/bin/env python3
"""
Module: general_ledger_table.py
Layer: Projections (Ledger)
Responsibility: Membangun dan memelihara read model General Ledger (tabel ledger)
               berdasarkan event dari event store.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable

# Add this line to your imports in projections/ledger/general_ledger_table.py
from infrastructure.persistence_orm.projection_checkpoint_table import ProjectionCheckpointTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "general_ledger"
BATCH_SIZE = 1000

# ============================================================================
# EXCEPTIONS
# ============================================================================


class GeneralLedgerProjectionError(Exception):
    pass


class RebuildInProgressError(GeneralLedgerProjectionError):
    pass


# ============================================================================
# GENERAL LEDGER PROJECTION
# ============================================================================


class GeneralLedgerTable:
    def __init__(self):
        self._event_store = None
        self._session_factory = None
        self._rebuild_lock = asyncio.Lock()
        self._last_event_id: UUID | None = None
        self._last_event_sequence: int = 0
        self._account_cache: dict[str, UUID] = {}

    async def _get_event_store(self):
        if self._event_store is None:
            from infrastructure.event_store.append_only_store import get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_checkpoint(self) -> tuple[UUID | None, int]:
        async with await self._get_session() as session:
            stmt = select(
                ProjectionCheckpointTable.last_event_id,
                ProjectionCheckpointTable.last_event_sequence,
            ).where(ProjectionCheckpointTable.projection_name == PROJECTION_NAME)
            result = await session.execute(stmt)
            row = result.first()
            if row:
                return row[0], row[1] or 0
            return None, 0

    async def _update_checkpoint(self, event_id: UUID, sequence: int) -> None:
        async with await self._get_session() as session, session.begin():
            stmt = (
                insert(ProjectionCheckpointTable)
                .values(
                    projection_name=PROJECTION_NAME,
                    last_event_id=event_id,
                    last_event_sequence=sequence,
                    last_processed_at=datetime.now(UTC),
                )
                .on_conflict_do_update(
                    index_elements=["projection_name"],
                    set_={
                        "last_event_id": event_id,
                        "last_event_sequence": sequence,
                        "last_processed_at": datetime.now(UTC),
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def rebuild(self, batch_size: int = BATCH_SIZE) -> dict[str, Any]:
        async with self._rebuild_lock:
            logger.info("Starting full rebuild of General Ledger projection")
            start_time = datetime.now(UTC)
            store = await self._get_event_store()
            async with await self._get_session() as session, session.begin():
                await session.execute(text("TRUNCATE TABLE ledger_entry"))
                await session.commit()

            events = await store.read_stream("journal", limit=1000000)
            journal_events = [e for e in events if e.get("event_type") == "JournalPosted"]

            total_processed = 0
            errors = 0
            for i in range(0, len(journal_events), batch_size):
                batch = journal_events[i : i + batch_size]
                try:
                    await self._process_event_batch(batch)
                    total_processed += len(batch)
                    logger.debug(f"Processed batch {i // batch_size + 1}: {len(batch)} events")
                except Exception as e:
                    logger.error(f"Error processing batch: {e}")
                    errors += len(batch)

            duration = (datetime.now(UTC) - start_time).total_seconds()
            result = {
                "success": errors == 0,
                "total_events_processed": total_processed,
                "errors": errors,
                "duration_seconds": duration,
                "projection_name": PROJECTION_NAME,
            }
            logger.info(f"General Ledger rebuild completed: {total_processed} events in {duration:.2f}s")
            if errors > 0:
                await trigger_alert(
                    title="General Ledger Rebuild Partial Failure",
                    message=f"{errors} events failed to process during rebuild",
                    severity="warning",
                    source="GeneralLedgerTable",
                )
            return result

    async def _process_event_batch(self, events: list[dict]) -> None:
        ledger_entries = []
        for event in events:
            data = event.get("data", {})
            journal_id = data.get("journal_id")
            lines = data.get("lines", [])
            posting_date = data.get("posting_date")
            if isinstance(posting_date, str):
                posting_date = datetime.fromisoformat(posting_date).date()

            for line in lines:
                account_code = line.get("account_code")
                debit = Decimal(str(line.get("debit_amount", 0)))
                credit = Decimal(str(line.get("credit_amount", 0)))
                account_id = await self._get_account_id(account_code)
                if not account_id:
                    logger.warning(f"Account not found for code {account_code}")
                    continue
                entry = LedgerEntryTable(
                    id=UUID(event.get("id")),
                    journal_id=UUID(journal_id),
                    account_id=account_id,
                    account_code=account_code,
                    line_number=line.get("line_number", 1),
                    debit_amount=debit,
                    credit_amount=credit,
                    currency=line.get("currency", "IDR"),
                    posting_date=posting_date,
                    cost_center=line.get("cost_center"),
                    department=line.get("department"),
                    reference_number=data.get("voucher_number"),
                    description=line.get("description"),
                    fiscal_year=posting_date.year,
                    period_month=posting_date.month,
                    legal_entity_id=data.get("legal_entity_id"),
                    created_by=data.get("posted_by"),
                )
                ledger_entries.append(entry)

        if ledger_entries:
            async with await self._get_session() as session, session.begin():
                session.add_all(ledger_entries)
                await session.commit()

    async def handle(self, event: dict) -> None:
        await self._process_event_batch([event])

    async def _get_account_id(self, account_code: str) -> UUID | None:
        if account_code in self._account_cache:
            return self._account_cache[account_code]
        async with await self._get_session() as session:
            stmt = select(AccountTable.id).where(AccountTable.account_code == account_code)
            result = await session.execute(stmt)
            account_id = result.scalar_one_or_none()
            if account_id:
                self._account_cache[account_code] = account_id
            return account_id

    async def get_ledger_entries(
        self,
        account_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        cost_center: str | None = None,
        legal_entity_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict]:
        async with await self._get_session() as session:
            conditions = []
            if account_id:
                conditions.append(LedgerEntryTable.account_id == account_id)
            if start_date:
                conditions.append(LedgerEntryTable.posting_date >= start_date)
            if end_date:
                conditions.append(LedgerEntryTable.posting_date <= end_date)
            if cost_center:
                conditions.append(LedgerEntryTable.cost_center == cost_center)
            if legal_entity_id:
                conditions.append(LedgerEntryTable.legal_entity_id == legal_entity_id)

            stmt = (
                select(LedgerEntryTable)
                .where(and_(*conditions) if conditions else True)
                .order_by(LedgerEntryTable.posting_date, LedgerEntryTable.id)
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            entries = result.scalars().all()
            return [
                {
                    "id": str(e.id),
                    "journal_id": str(e.journal_id),
                    "account_code": e.account_code,
                    "debit_amount": float(e.debit_amount),
                    "credit_amount": float(e.credit_amount),
                    "posting_date": e.posting_date.isoformat(),
                    "cost_center": e.cost_center,
                    "description": e.description,
                }
                for e in entries
            ]

    async def get_account_balance(
        self, account_id: UUID, as_of_date: date, legal_entity_id: UUID | None = None
    ) -> Decimal:
        async with await self._get_session() as session:
            conditions = [
                LedgerEntryTable.account_id == account_id,
                LedgerEntryTable.posting_date <= as_of_date,
            ]
            if legal_entity_id:
                conditions.append(LedgerEntryTable.legal_entity_id == legal_entity_id)

            stmt = select(
                func.sum(LedgerEntryTable.debit_amount).label("total_debit"),
                func.sum(LedgerEntryTable.credit_amount).label("total_credit"),
            ).where(and_(*conditions))
            result = await session.execute(stmt)
            row = result.first()
            total_debit = Decimal(str(row.total_debit or 0))
            total_credit = Decimal(str(row.total_credit or 0))
            return total_debit - total_credit

    async def incremental_update(self, from_sequence: int = 0) -> int:
        store = await self._get_event_store()
        last_event_id, last_sequence = await self._get_checkpoint()
        events = await store.read_stream("journal", limit=10000)
        new_events = [e for e in events if e.get("sequence_number", 0) > last_sequence]
        if not new_events:
            return 0
        await self._process_event_batch(new_events)
        last_event = new_events[-1]
        await self._update_checkpoint(UUID(last_event["id"]), last_event.get("sequence_number", 0))
        logger.info(f"Incremental update: {len(new_events)} events processed")
        return len(new_events)

    async def get_stats(self) -> dict[str, Any]:
        async with await self._get_session() as session:
            stmt = select(func.count()).select_from(LedgerEntryTable)
            result = await session.execute(stmt)
            total_entries = result.scalar() or 0
            stmt2 = select(
                func.sum(LedgerEntryTable.debit_amount).label("total_debit"),
                func.sum(LedgerEntryTable.credit_amount).label("total_credit"),
            )
            result2 = await session.execute(stmt2)
            row2 = result2.first()
            return {
                "total_entries": total_entries,
                "total_debit": float(row2.total_debit or 0),
                "total_credit": float(row2.total_credit or 0),
                "last_checkpoint_sequence": (await self._get_checkpoint())[1],
            }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_general_ledger_projection: GeneralLedgerTable | None = None

async def get_general_ledger_projection() -> GeneralLedgerTable:
    global _general_ledger_projection
    if _general_ledger_projection is None:
        _general_ledger_projection = GeneralLedgerTable()
    return _general_ledger_projection

GeneralLedgerProjection = GeneralLedgerTable

__all__ = [
    "GeneralLedgerProjection",
    "GeneralLedgerProjectionError",
    "GeneralLedgerTable",
    "get_general_ledger_projection",
]
