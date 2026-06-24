#!/usr/bin/env python3
"""
Module: sqlalchemy_tax_transaction_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Tax Transaction menggunakan SQLAlchemy - LENGKAP.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.tax_transaction_table import TaxTransactionTable
from ports.primary.tax_transaction_repository_port import TaxTransactionRepositoryPort

logger = logging.getLogger(__name__)


class SQLAlchemyTaxTransactionRepository(TaxTransactionRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):  # <-- PERBAIKAN: default None
        self._session = session
        self._audit_log: List[Dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def _log_audit(self, action: str, transaction_id: UUID, details: Dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "transaction_id": str(transaction_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # CORE CRUD
    # ========================================================================

    async def add(self, transaction: TaxTransactionTable) -> TaxTransactionTable:
        """Alias untuk save."""
        return await self.save(transaction)

    async def save(self, transaction: TaxTransactionTable) -> TaxTransactionTable:
        session = await self._get_session()
        session.add(transaction)
        await session.flush()
        await self._log_audit("ADD", transaction.id, {"tax_type": transaction.tax_type})
        logger.info(f"Tax transaction saved: {transaction.id}")
        return transaction

    async def update(self, transaction: TaxTransactionTable) -> TaxTransactionTable:
        session = await self._get_session()
        await session.merge(transaction)
        await session.flush()
        await self._log_audit("UPDATE", transaction.id, {"tax_type": transaction.tax_type})
        logger.info(f"Tax transaction updated: {transaction.id}")
        return transaction

    async def delete(self, transaction_id: UUID, soft_delete: bool = True) -> bool:
        session = await self._get_session()
        if soft_delete:
            stmt = update(TaxTransactionTable).where(TaxTransactionTable.id == transaction_id).values(deleted_at=datetime.utcnow())
        else:
            stmt = delete(TaxTransactionTable).where(TaxTransactionTable.id == transaction_id)
        result = await session.execute(stmt)
        await session.flush()
        if result.rowcount > 0:
            await self._log_audit("DELETE", transaction_id, {"soft": soft_delete})
            logger.info(f"Tax transaction {transaction_id} deleted")
        return result.rowcount > 0

    async def get_by_id(self, transaction_id: UUID) -> TaxTransactionTable | None:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(TaxTransactionTable.id == transaction_id, TaxTransactionTable.deleted_at.is_(None))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_invoice(self, invoice_id: UUID, tax_type: str) -> TaxTransactionTable | None:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.source_document_id == invoice_id,
            TaxTransactionTable.source_document_type == "invoice",
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_reference(self, reference: str, legal_entity_id: UUID) -> List[TaxTransactionTable]:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.reference_number == reference,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========================================================================
    # PERIOD-BASED QUERIES
    # ========================================================================

    async def find_by_period(
        self, tax_type: str, period_year: int, period_month: int, legal_entity_id: UUID
    ) -> List[TaxTransactionTable]:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.period_year == period_year,
            TaxTransactionTable.period_month == period_month,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_period_range(
        self, tax_type: str, from_date: date, to_date: date, legal_entity_id: UUID
    ) -> List[TaxTransactionTable]:
        session = await self._get_session()
        from_year, from_month = from_date.year, from_date.month
        to_year, to_month = to_date.year, to_date.month
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.deleted_at.is_(None),
            or_(
                and_(
                    TaxTransactionTable.period_year == from_year,
                    TaxTransactionTable.period_month >= from_month,
                    TaxTransactionTable.period_month <= to_month
                ) if from_year == to_year else
                and_(
                    TaxTransactionTable.period_year >= from_year,
                    TaxTransactionTable.period_year <= to_year,
                )
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_spt_by_period(
        self, tax_type: str, period_year: int, period_month: int, legal_entity_id: UUID
    ) -> List[TaxTransactionTable]:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.period_year == period_year,
            TaxTransactionTable.period_month == period_month,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_submissions(
        self, tax_type: str, legal_entity_id: UUID
    ) -> List[TaxTransactionTable]:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.submission_status == "pending",
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========================================================================
    # SUBMISSION & SPT MANAGEMENT
    # ========================================================================

    async def submit_spt(self, transaction_id: UUID, submitted_by: UUID) -> bool:
        session = await self._get_session()
        transaction = await self.get_by_id(transaction_id)
        if not transaction:
            return False
        transaction.submission_status = "submitted"
        transaction.submitted_at = datetime.utcnow()
        transaction.submitted_by = submitted_by
        await session.flush()
        await self._log_audit("SUBMIT_SPT", transaction_id, {"submitted_by": str(submitted_by)})
        logger.info(f"SPT submitted for transaction {transaction_id}")
        return True

    async def approve_spt(self, transaction_id: UUID, approved_by: UUID) -> bool:
        session = await self._get_session()
        transaction = await self.get_by_id(transaction_id)
        if not transaction or transaction.submission_status != "submitted":
            return False
        transaction.submission_status = "approved"
        transaction.approved_at = datetime.utcnow()
        transaction.approved_by = approved_by
        await session.flush()
        await self._log_audit("APPROVE_SPT", transaction_id, {"approved_by": str(approved_by)})
        logger.info(f"SPT approved for transaction {transaction_id}")
        return True

    async def reject_spt(self, transaction_id: UUID, rejected_by: UUID, reason: str) -> bool:
        session = await self._get_session()
        transaction = await self.get_by_id(transaction_id)
        if not transaction or transaction.submission_status != "submitted":
            return False
        transaction.submission_status = "rejected"
        transaction.rejection_reason = reason
        transaction.rejected_at = datetime.utcnow()
        transaction.rejected_by = rejected_by
        await session.flush()
        await self._log_audit("REJECT_SPT", transaction_id, {"reason": reason, "rejected_by": str(rejected_by)})
        logger.info(f"SPT rejected for transaction {transaction_id}")
        return True

    async def create_spt_submission(
        self, transaction_ids: List[UUID], submitted_by: UUID
    ) -> List[TaxTransactionTable]:
        session = await self._get_session()
        updated = []
        for tid in transaction_ids:
            t = await self.get_by_id(tid)
            if t and t.submission_status is None:
                t.submission_status = "pending"
                t.submitted_by = submitted_by
                updated.append(t)
        await session.flush()
        for t in updated:
            await self._log_audit("CREATE_SPT_SUBMISSION", t.id, {"submitted_by": str(submitted_by)})
        logger.info(f"Created SPT submission for {len(updated)} transactions")
        return updated

    async def mark_transactions_reported(self, transaction_ids: List[UUID]) -> int:
        session = await self._get_session()
        count = 0
        for tid in transaction_ids:
            t = await self.get_by_id(tid)
            if t:
                t.reported = True
                t.reported_at = datetime.utcnow()
                count += 1
        await session.flush()
        logger.info(f"Marked {count} transactions as reported")
        return count

    async def update_submission_status(
        self, transaction_id: UUID, status: str, submission_id: str | None = None
    ) -> None:
        session = await self._get_session()
        values = {"submission_status": status, "submitted_at": datetime.utcnow()}
        if submission_id:
            values["submission_id"] = submission_id
        stmt = update(TaxTransactionTable).where(TaxTransactionTable.id == transaction_id).values(**values)
        await session.execute(stmt)
        await self._log_audit("UPDATE_SUBMISSION_STATUS", transaction_id, {"status": status})
        logger.info(f"Submission status updated for transaction {transaction_id} to {status}")

    # ========================================================================
    # ADJUSTMENT & PAYMENT
    # ========================================================================

    async def create_adjustment(
        self, original_transaction_id: UUID, adjustment_amount: Decimal, reason: str, created_by: UUID
    ) -> TaxTransactionTable:
        session = await self._get_session()
        original = await self.get_by_id(original_transaction_id)
        if not original:
            raise ValueError(f"Original transaction {original_transaction_id} not found")
        new_tx = TaxTransactionTable(
            id=uuid.uuid4(),
            tax_type=original.tax_type,
            tax_amount=adjustment_amount,
            period_year=original.period_year,
            period_month=original.period_month,
            legal_entity_id=original.legal_entity_id,
            source_document_id=original.source_document_id,
            source_document_type="adjustment",
            reference_number=f"ADJ-{original.reference_number}",
            adjustment_reason=reason,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        session.add(new_tx)
        await session.flush()
        await self._log_audit("CREATE_ADJUSTMENT", new_tx.id, {"original": str(original_transaction_id), "amount": str(adjustment_amount)})
        logger.info(f"Adjustment created for transaction {original_transaction_id}")
        return new_tx

    async def record_payment(self, transaction_id: UUID, payment_id: UUID, amount: Decimal) -> bool:
        session = await self._get_session()
        transaction = await self.get_by_id(transaction_id)
        if not transaction:
            return False
        transaction.payment_id = payment_id
        transaction.payment_amount = amount
        transaction.payment_date = datetime.utcnow().date()
        transaction.submission_status = "paid"
        await session.flush()
        await self._log_audit("RECORD_PAYMENT", transaction_id, {"payment_id": str(payment_id), "amount": str(amount)})
        logger.info(f"Payment recorded for transaction {transaction_id}")
        return True

    # ========================================================================
    # SUMMARY & STATISTICS
    # ========================================================================

    async def get_summary_by_period(
        self, tax_type: str, period_year: int, period_month: int, legal_entity_id: UUID
    ) -> Decimal:
        session = await self._get_session()
        stmt = select(TaxTransactionTable.tax_amount).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.period_year == period_year,
            TaxTransactionTable.period_month == period_month,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.submission_status == "submitted",
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        amounts = result.scalars().all()
        return sum(amounts, Decimal(0))

    async def get_total_tax_liability(self, legal_entity_id: UUID, tax_type: str | None = None) -> Decimal:
        session = await self._get_session()
        conditions = [
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.submission_status.in_(["submitted", "approved", "paid"]),
            TaxTransactionTable.deleted_at.is_(None),
            TaxTransactionTable.tax_amount > 0,
        ]
        if tax_type:
            conditions.append(TaxTransactionTable.tax_type == tax_type)
        stmt = select(func.coalesce(func.sum(TaxTransactionTable.tax_amount), 0)).where(and_(*conditions))
        result = await session.execute(stmt)
        return Decimal(str(result.scalar() or 0))

    async def get_total_tax_credit(self, legal_entity_id: UUID, tax_type: str | None = None) -> Decimal:
        session = await self._get_session()
        conditions = [
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.submission_status.in_(["submitted", "approved", "paid"]),
            TaxTransactionTable.deleted_at.is_(None),
            TaxTransactionTable.tax_amount < 0,
        ]
        if tax_type:
            conditions.append(TaxTransactionTable.tax_type == tax_type)
        stmt = select(func.coalesce(func.sum(TaxTransactionTable.tax_amount), 0)).where(and_(*conditions))
        result = await session.execute(stmt)
        return Decimal(str(abs(result.scalar() or 0)))

    async def get_statistics(self, legal_entity_id: UUID) -> Dict[str, Any]:
        session = await self._get_session()
        total = await session.execute(
            select(func.count()).where(
                TaxTransactionTable.legal_entity_id == legal_entity_id,
                TaxTransactionTable.deleted_at.is_(None)
            )
        )
        total_count = total.scalar() or 0

        pending = await session.execute(
            select(func.count()).where(
                TaxTransactionTable.legal_entity_id == legal_entity_id,
                TaxTransactionTable.submission_status == "pending",
                TaxTransactionTable.deleted_at.is_(None)
            )
        )
        pending_count = pending.scalar() or 0

        submitted = await session.execute(
            select(func.count()).where(
                TaxTransactionTable.legal_entity_id == legal_entity_id,
                TaxTransactionTable.submission_status == "submitted",
                TaxTransactionTable.deleted_at.is_(None)
            )
        )
        submitted_count = submitted.scalar() or 0

        approved = await session.execute(
            select(func.count()).where(
                TaxTransactionTable.legal_entity_id == legal_entity_id,
                TaxTransactionTable.submission_status == "approved",
                TaxTransactionTable.deleted_at.is_(None)
            )
        )
        approved_count = approved.scalar() or 0

        return {
            "total_transactions": total_count,
            "pending": pending_count,
            "submitted": submitted_count,
            "approved": approved_count,
            "total_liability": float(await self.get_total_tax_liability(legal_entity_id)),
            "total_credit": float(await self.get_total_tax_credit(legal_entity_id)),
        }

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    async def export_to_csv(self, legal_entity_id: UUID, period_year: int = None, period_month: int = None) -> str:
        session = await self._get_session()
        conditions = [
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.deleted_at.is_(None),
        ]
        if period_year:
            conditions.append(TaxTransactionTable.period_year == period_year)
        if period_month:
            conditions.append(TaxTransactionTable.period_month == period_month)
        stmt = select(TaxTransactionTable).where(and_(*conditions))
        result = await session.execute(stmt)
        transactions = result.scalars().all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "tax_type", "tax_amount", "period_year", "period_month",
            "source_document_id", "source_document_type", "reference_number",
            "submission_status", "legal_entity_id", "created_at"
        ])
        for t in transactions:
            writer.writerow([
                str(t.id),
                t.tax_type,
                float(t.tax_amount),
                t.period_year,
                t.period_month,
                str(t.source_document_id) if t.source_document_id else "",
                t.source_document_type or "",
                t.reference_number or "",
                t.submission_status or "",
                str(t.legal_entity_id),
                t.created_at.isoformat() if t.created_at else "",
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        session = await self._get_session()
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                tx = TaxTransactionTable(
                    id=uuid.uuid4(),
                    tax_type=row["tax_type"],
                    tax_amount=Decimal(row["tax_amount"]),
                    period_year=int(row["period_year"]),
                    period_month=int(row["period_month"]),
                    source_document_id=uuid.UUID(row["source_document_id"]) if row.get("source_document_id") else None,
                    source_document_type=row.get("source_document_type"),
                    reference_number=row.get("reference_number"),
                    legal_entity_id=legal_entity_id,
                    created_by=created_by,
                    created_at=datetime.utcnow(),
                )
                session.add(tx)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import row: {e}")
        await session.flush()
        logger.info(f"Imported {count} tax transactions")
        return count

    # ========================================================================
    # AUDIT
    # ========================================================================

    async def get_audit_log(self, transaction_id: UUID | None = None, limit: int = 100) -> List[Dict[str, Any]]:
        logs = self._audit_log
        if transaction_id:
            logs = [l for l in logs if l.get("transaction_id") == str(transaction_id)]
        return logs[-limit:]

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    async def health_check(self) -> Dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(select(1))
            total = await session.execute(select(func.count()).select_from(TaxTransactionTable))
            return {"status": "healthy", "repository": "TaxTransactionRepository", "total": total.scalar() or 0}
        except Exception as e:
            return {"status": "unhealthy", "repository": "TaxTransactionRepository", "error": str(e)}


__all__ = ["SQLAlchemyTaxTransactionRepository"]