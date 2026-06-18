#!/usr/bin/env python3
"""
Module: bank_reconciliation_status.py
Layer: Projections (Subledger)
Responsibility: Membangun read model status rekonsiliasi bank per bank account
               dan per periode. Menyimpan informasi tentang rekonsiliasi terakhir,
               outstanding items, dan perbedaan. Mendukung query untuk dashboard
               monitoring dan laporan rekonsiliasi bank.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.bank_account_table
- infrastructure.persistence_orm.bank_reconciliation_table
- infrastructure.persistence_orm.bank_transaction_table
- infrastructure.event_store.append_only_store (untuk rebuild)
Audit: Status rekonsiliasi digunakan untuk compliance dan manajemen kas.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.bank_account_table import BankAccountTable
from infrastructure.persistence_orm.bank_reconciliation_table import BankReconciliationTable
from infrastructure.persistence_orm.bank_transaction_table import BankTransactionTable
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "bank_reconciliation_status"

# Reconciliation statuses
RECON_STATUS_PENDING = "pending"
RECON_STATUS_IN_PROGRESS = "in_progress"
RECON_STATUS_COMPLETED = "completed"
RECON_STATUS_ADJUSTED = "adjusted"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class BankReconciliationStatusError(Exception):
    """Base exception untuk bank reconciliation status projection."""

    pass


# ============================================================================
# BANK RECONCILIATION STATUS PROJECTION
# ============================================================================


class BankReconciliationStatus:
    """
    Read model status rekonsiliasi bank.

    Fitur:
    - Status rekonsiliasi per bank account per periode (bulanan)
    - Outstanding reconciling items (deposits in transit, outstanding checks)
    - Perbedaan jumlah sebelum dan sesudah rekonsiliasi
    - Monitoring overdue reconciliations
    - Alert untuk bank account yang belum direkonsiliasi
    """

    def __init__(self):
        self._session_factory = None
        self._recon_status_cache: dict[str, dict] = {}

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def compute_reconciliation_status(
        self, bank_account_id: UUID, period_end_date: date
    ) -> dict[str, Any]:
        """
        Menghitung status rekonsiliasi untuk bank account pada akhir periode.

        Args:
            bank_account_id: ID rekening bank
            period_end_date: Tanggal akhir periode (biasanya month end)

        Returns:
            Status rekonsiliasi dengan detail outstanding items
        """
        async with await self._get_session() as session:
            # Get bank account info
            account_stmt = select(BankAccountTable).where(
                BankAccountTable.id == bank_account_id, BankAccountTable.deleted_at.is_(None)
            )
            account_result = await session.execute(account_stmt)
            account = account_result.scalar_one_or_none()
            if not account:
                raise BankReconciliationStatusError(f"Bank account {bank_account_id} not found")

            # Get latest reconciliation for this account and period
            recon_stmt = (
                select(BankReconciliationTable)
                .where(
                    BankReconciliationTable.bank_account_id == bank_account_id,
                    BankReconciliationTable.statement_date == period_end_date,
                )
                .order_by(BankReconciliationTable.created_at.desc())
                .limit(1)
            )
            recon_result = await session.execute(recon_stmt)
            reconciliation = recon_result.scalar_one_or_none()

            status = {
                "bank_account_id": str(bank_account_id),
                "account_number": account.account_number,
                "bank_name": account.bank_name,
                "period_end_date": period_end_date.isoformat(),
                "reconciled": reconciliation is not None,
                "status": RECON_STATUS_COMPLETED if reconciliation else RECON_STATUS_PENDING,
                "statement_balance": None,
                "book_balance": None,
                "difference": None,
                "outstanding_deposits": Decimal(0),
                "outstanding_checks": Decimal(0),
                "last_reconciliation_date": reconciliation.created_at.isoformat()
                if reconciliation
                else None,
                "reconciled_by": str(reconciliation.created_by) if reconciliation else None,
            }

            if reconciliation:
                status["statement_balance"] = float(reconciliation.statement_balance)
                status["book_balance"] = float(reconciliation.book_balance)
                status["difference"] = float(reconciliation.difference)

            # Get outstanding reconciling items (transactions not yet reconciled)
            # Outstanding deposits (bank has not recorded yet) - assuming status = pending
            # For simplicity, we count unreconciled transactions after the period end
            unreconciled_stmt = select(
                func.sum(BankTransactionTable.amount).label("total_deposits")
            ).where(
                BankTransactionTable.bank_account_id == bank_account_id,
                BankTransactionTable.is_reconciled == False,
                BankTransactionTable.transaction_date <= period_end_date,
                BankTransactionTable.transaction_type == "deposit",
            )
            deposits_result = await session.execute(unreconciled_stmt)
            outstanding_deposits = deposits_result.scalar() or 0

            unreconciled_checks = select(
                func.sum(BankTransactionTable.amount).label("total_checks")
            ).where(
                BankTransactionTable.bank_account_id == bank_account_id,
                BankTransactionTable.is_reconciled == False,
                BankTransactionTable.transaction_date <= period_end_date,
                BankTransactionTable.transaction_type == "withdrawal",
            )
            checks_result = await session.execute(unreconciled_checks)
            outstanding_checks = checks_result.scalar() or 0

            status["outstanding_deposits"] = float(outstanding_deposits)
            status["outstanding_checks"] = float(outstanding_checks)

            return status

    async def save_reconciliation_status(self, status_data: dict[str, Any]) -> None:
        """
        Menyimpan status rekonsiliasi ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            # Delete existing for same account and period
            await session.execute(
                delete(BankReconciliationStatusTable).where(
                    BankReconciliationStatusTable.bank_account_id
                    == UUID(status_data["bank_account_id"]),
                    BankReconciliationStatusTable.period_end_date
                    == date.fromisoformat(status_data["period_end_date"]),
                )
            )

            stmt = insert(BankReconciliationStatusTable).values(
                id=uuid4(),
                bank_account_id=UUID(status_data["bank_account_id"]),
                period_end_date=date.fromisoformat(status_data["period_end_date"]),
                reconciled=status_data["reconciled"],
                status=status_data["status"],
                statement_balance=Decimal(str(status_data["statement_balance"]))
                if status_data["statement_balance"]
                else None,
                book_balance=Decimal(str(status_data["book_balance"]))
                if status_data["book_balance"]
                else None,
                difference=Decimal(str(status_data["difference"]))
                if status_data["difference"]
                else None,
                outstanding_deposits=Decimal(str(status_data["outstanding_deposits"])),
                outstanding_checks=Decimal(str(status_data["outstanding_checks"])),
                last_reconciliation_date=datetime.fromisoformat(
                    status_data["last_reconciliation_date"]
                )
                if status_data.get("last_reconciliation_date")
                else None,
                reconciled_by=UUID(status_data["reconciled_by"])
                if status_data.get("reconciled_by")
                else None,
                updated_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_reconciliation_status(
        self, bank_account_id: UUID, period_end_date: date
    ) -> dict | None:
        """
        Mendapatkan status rekonsiliasi yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = select(BankReconciliationStatusTable).where(
                BankReconciliationStatusTable.bank_account_id == bank_account_id,
                BankReconciliationStatusTable.period_end_date == period_end_date,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "bank_account_id": str(row.bank_account_id),
                "period_end_date": row.period_end_date.isoformat(),
                "reconciled": row.reconciled,
                "status": row.status,
                "statement_balance": float(row.statement_balance)
                if row.statement_balance
                else None,
                "book_balance": float(row.book_balance) if row.book_balance else None,
                "difference": float(row.difference) if row.difference else None,
                "outstanding_deposits": float(row.outstanding_deposits),
                "outstanding_checks": float(row.outstanding_checks),
                "last_reconciliation_date": row.last_reconciliation_date.isoformat()
                if row.last_reconciliation_date
                else None,
                "reconciled_by": str(row.reconciled_by) if row.reconciled_by else None,
            }

    async def generate_all_periods(self, bank_account_id: UUID) -> list[dict]:
        """
        Menghasilkan status rekonsiliasi untuk semua periode yang memiliki laporan.
        """
        async with await self._get_session() as session:
            # Get distinct statement dates from reconciliations
            recon_stmt = (
                select(BankReconciliationTable.statement_date)
                .where(BankReconciliationTable.bank_account_id == bank_account_id)
                .distinct()
                .order_by(BankReconciliationTable.statement_date)
            )
            recon_result = await session.execute(recon_stmt)
            statement_dates = recon_result.scalars().all()

            statuses = []
            for end_date in statement_dates:
                status = await self.compute_reconciliation_status(bank_account_id, end_date)
                await self.save_reconciliation_status(status)
                statuses.append(status)

            return statuses

    async def get_overdue_reconciliations(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict]:
        """
        Mendapatkan bank account yang belum direkonsiliasi untuk periode terakhir.
        """
        async with await self._get_session() as session:
            # Get all active bank accounts
            account_stmt = select(BankAccountTable).where(
                BankAccountTable.legal_entity_id == legal_entity_id,
                BankAccountTable.is_active == True,
                BankAccountTable.deleted_at.is_(None),
            )
            account_result = await session.execute(account_stmt)
            accounts = account_result.scalars().all()

            overdue = []
            for account in accounts:
                # Get latest available reconciliation
                recon_stmt = (
                    select(BankReconciliationStatusTable)
                    .where(BankReconciliationStatusTable.bank_account_id == account.id)
                    .order_by(BankReconciliationStatusTable.period_end_date.desc())
                    .limit(1)
                )
                recon_result = await session.execute(recon_stmt)
                last_status = recon_result.scalar_one_or_none()

                if not last_status or not last_status.reconciled:
                    # Check when last statement date was
                    last_stmt = await self.get_latest_statement_date(account.id)
                    if last_stmt and (as_of_date - last_stmt).days > 30:
                        overdue.append(
                            {
                                "bank_account_id": str(account.id),
                                "account_number": account.account_number,
                                "bank_name": account.bank_name,
                                "last_statement_date": last_stmt.isoformat(),
                                "days_overdue": (as_of_date - last_stmt).days,
                            }
                        )
                elif last_status and last_status.period_end_date < as_of_date - timedelta(days=30):
                    # Last reconciliation is more than 30 days ago
                    overdue.append(
                        {
                            "bank_account_id": str(account.id),
                            "account_number": account.account_number,
                            "bank_name": account.bank_name,
                            "last_reconciliation_date": last_status.period_end_date.isoformat(),
                            "days_overdue": (as_of_date - last_status.period_end_date).days,
                        }
                    )

            return overdue

    async def get_latest_statement_date(self, bank_account_id: UUID) -> date | None:
        """
        Mendapatkan tanggal statement terakhir yang direkonsiliasi.
        """
        async with await self._get_session() as session:
            stmt = (
                select(BankReconciliationStatusTable.period_end_date)
                .where(
                    BankReconciliationStatusTable.bank_account_id == bank_account_id,
                    BankReconciliationStatusTable.reconciled == True,
                )
                .order_by(BankReconciliationStatusTable.period_end_date.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_reconciliation_dashboard(self, legal_entity_id: UUID) -> dict[str, Any]:
        """
        Mendapatkan dashboard rekonsiliasi untuk monitoring.
        """
        today = date.today()
        overdue = await self.get_overdue_reconciliations(legal_entity_id, today)

        async with await self._get_session() as session:
            # Count total active accounts
            account_stmt = (
                select(func.count())
                .select_from(BankAccountTable)
                .where(
                    BankAccountTable.legal_entity_id == legal_entity_id,
                    BankAccountTable.is_active == True,
                )
            )
            account_result = await session.execute(account_stmt)
            total_accounts = account_result.scalar() or 0

            # Count reconciled in current month
            month_start = today.replace(day=1)
            reconciled_stmt = (
                select(func.count())
                .select_from(BankReconciliationStatusTable)
                .where(
                    BankReconciliationStatusTable.period_end_date >= month_start,
                    BankReconciliationStatusTable.reconciled == True,
                    BankReconciliationStatusTable.bank_account_id.in_(
                        select(BankAccountTable.id).where(
                            BankAccountTable.legal_entity_id == legal_entity_id
                        )
                    ),
                )
            )
            reconciled_result = await session.execute(reconciled_stmt)
            reconciled_current = reconciled_result.scalar() or 0

        return {
            "legal_entity_id": str(legal_entity_id),
            "total_bank_accounts": total_accounts,
            "reconciled_this_month": reconciled_current,
            "reconciliation_rate": (reconciled_current / total_accounts * 100)
            if total_accounts > 0
            else 0,
            "overdue_reconciliations": len(overdue),
            "overdue_details": overdue,
        }

    async def rebuild_all(self, legal_entity_id: UUID) -> dict[str, int]:
        """
        Membangun ulang status rekonsiliasi untuk semua bank account dalam legal entity.
        """
        async with await self._get_session() as session:
            account_stmt = select(BankAccountTable.id).where(
                BankAccountTable.legal_entity_id == legal_entity_id,
                BankAccountTable.deleted_at.is_(None),
            )
            account_result = await session.execute(account_stmt)
            account_ids = account_result.scalars().all()

        success = 0
        errors = 0
        for acc_id in account_ids:
            try:
                await self.generate_all_periods(acc_id)
                success += 1
            except Exception as e:
                logger.error(f"Failed to rebuild reconciliation status for account {acc_id}: {e}")
                errors += 1

        logger.info(
            f"Bank reconciliation status rebuild completed: {success} accounts, {errors} errors"
        )
        return {"success": success, "errors": errors}

    async def incremental_update(self, reconciliation_id: UUID) -> None:
        """
        Incremental update ketika rekonsiliasi baru diselesaikan.
        """
        async with await self._get_session() as session:
            recon_stmt = select(BankReconciliationTable).where(
                BankReconciliationTable.id == reconciliation_id
            )
            recon_result = await session.execute(recon_stmt)
            reconciliation = recon_result.scalar_one_or_none()
            if not reconciliation:
                return

            status = await self.compute_reconciliation_status(
                reconciliation.bank_account_id, reconciliation.statement_date
            )
            await self.save_reconciliation_status(status)
            logger.info(
                f"Reconciliation status updated for account {reconciliation.bank_account_id}"
            )


# ============================================================================
# ORM MODEL (tambahan)
# ============================================================================

from sqlalchemy import Boolean, Column, Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class BankReconciliationStatusTable(Base):
    __tablename__ = "bank_reconciliation_status"
    __table_args__ = (
        Index("idx_bank_recon_status_account", "bank_account_id"),
        Index("idx_bank_recon_status_period", "period_end_date"),
        Index("idx_bank_recon_status_reconciled", "reconciled"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    bank_account_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_end_date = Column(Date, nullable=False)
    reconciled = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False)
    statement_balance = Column(Numeric(20, 2), nullable=True)
    book_balance = Column(Numeric(20, 2), nullable=True)
    difference = Column(Numeric(20, 2), nullable=True)
    outstanding_deposits = Column(Numeric(20, 2), nullable=False, default=0)
    outstanding_checks = Column(Numeric(20, 2), nullable=False, default=0)
    last_reconciliation_date = Column(DateTime(timezone=True), nullable=True)
    reconciled_by = Column(PGUUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_bank_reconciliation_status: BankReconciliationStatus | None = None


async def get_bank_reconciliation_status() -> BankReconciliationStatus:
    """Get singleton instance of BankReconciliationStatus."""
    global _bank_reconciliation_status
    if _bank_reconciliation_status is None:
        _bank_reconciliation_status = BankReconciliationStatus()
    return _bank_reconciliation_status


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BankReconciliationStatus",
    "BankReconciliationStatusError",
    "get_bank_reconciliation_status",
]
