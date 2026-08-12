#!/usr/bin/env python3
"""
Module: sqlalchemy_tax_transaction_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Tax Transaction menggunakan SQLAlchemy - LENGKAP.
Perbaikan kolom:
  - period_year -> tax_period_year
  - period_month -> tax_period_month
  - source_document_id -> reference_id
  - source_document_type -> reference_type
  - submission_status -> status
  - reference_number -> transaction_number (untuk identifikasi)
  - adjustment_reason disimpan di extra_metadata
  - updated_by dihilangkan (tidak ada di tabel)
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.tax_transaction_table import TaxTransactionTable
from ports.primary.tax_transaction_repository_port import (
    SPTSubmission,
    SPTType,
    TaxTransaction,
    TaxTransactionRepositoryPort,
    TaxTransactionStatus,
    TaxType,
)

logger = logging.getLogger(__name__)


class SQLAlchemyTaxTransactionRepository(TaxTransactionRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []
        self._spt_submissions: dict[UUID, SPTSubmission] = {}  # temporary in-memory store
        self._tax_returns: dict[str, dict] = {}  # key: f"{legal_entity_id}_{period}"

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def _log_audit(self, action: str, transaction_id: UUID, details: dict[str, Any]) -> None:
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

    async def add(self, tax_transaction: TaxTransaction) -> None:
        """Add a tax transaction (domain entity)."""
        session = await self._get_session()
        table = TaxTransactionTable(
            id=tax_transaction.id,
            tax_type=tax_transaction.tax_type.value,
            tax_amount=tax_transaction.tax_amount,
            tax_period_year=tax_transaction.tax_period_year,
            tax_period_month=tax_transaction.tax_period_month,
            legal_entity_id=tax_transaction.legal_entity_id,
            reference_id=tax_transaction.reference_id,
            reference_type=tax_transaction.reference_type,
            transaction_number=tax_transaction.transaction_number or f"TX-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            status=tax_transaction.status.value if tax_transaction.status else "calculated",
            created_at=tax_transaction.created_at,
            created_by=tax_transaction.created_by,
            deleted_at=None,
            # nilai default lainnya
            transaction_date=tax_transaction.transaction_date or date.today(),
            taxable_amount=tax_transaction.amount or Decimal(0),
            tax_rate=Decimal(0),
            currency="IDR",
            is_withholding=False,
        )
        session.add(table)
        await session.flush()
        await self._log_audit("ADD", tax_transaction.id, {"tax_type": tax_transaction.tax_type.value})

    async def save(self, tax_transaction: TaxTransaction) -> None:
        """Alias for add."""
        await self.add(tax_transaction)

    async def update(self, tax_transaction: TaxTransaction) -> None:
        """
        Update tax transaction with pessimistic locking.
        """
        session = await self._get_session()
        async with session.begin():
            stmt_lock = select(TaxTransactionTable).where(
                TaxTransactionTable.id == tax_transaction.id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Transaction {tax_transaction.id} not found")

            # Update fields
            existing.tax_type = tax_transaction.tax_type.value
            existing.tax_amount = tax_transaction.tax_amount
            existing.tax_period_year = tax_transaction.tax_period_year
            existing.tax_period_month = tax_transaction.tax_period_month
            existing.legal_entity_id = tax_transaction.legal_entity_id
            existing.reference_id = tax_transaction.reference_id
            existing.reference_type = tax_transaction.reference_type
            existing.status = tax_transaction.status.value if tax_transaction.status else "calculated"
            existing.updated_at = datetime.utcnow()
            # updated_by tidak ada di tabel, kita skip
            await session.flush()
            await self._log_audit("UPDATE", tax_transaction.id, {"tax_type": tax_transaction.tax_type.value})

    async def delete(self, tax_transaction_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Soft delete or permanent delete with pessimistic locking."""
        session = await self._get_session()
        async with session.begin():
            stmt_lock = select(TaxTransactionTable).where(
                TaxTransactionTable.id == tax_transaction_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            existing = result.scalar_one_or_none()
            if not existing:
                return False

            if permanent:
                await session.delete(existing)
            else:
                existing.deleted_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
                # updated_by tidak ada, skip
            await session.flush()
            await self._log_audit("DELETE", tax_transaction_id, {"permanent": permanent, "user_id": str(user_id)})
            logger.info(f"Tax transaction {tax_transaction_id} deleted (permanent={permanent})")
            return True

    async def get_by_id(self, tax_transaction_id: UUID) -> TaxTransaction | None:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.id == tax_transaction_id,
            TaxTransactionTable.deleted_at.is_(None)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain(table)

    async def get_by_invoice(self, invoice_id: UUID, tax_type: str) -> TaxTransaction | None:
        """Extra method: find by invoice reference."""
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.reference_id == invoice_id,
            TaxTransactionTable.reference_type == "invoice",
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain(table)

    async def find_by_reference(
        self, reference_type: str, reference_id: UUID
    ) -> list[TaxTransaction]:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.reference_type == reference_type,
            TaxTransactionTable.reference_id == reference_id,
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    # ========================================================================
    # PERIOD-BASED QUERIES
    # ========================================================================

    async def find_by_period(
        self, legal_entity_id: UUID, tax_type: TaxType, year: int, month: int
    ) -> list[TaxTransaction]:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.tax_type == tax_type.value,
            TaxTransactionTable.tax_period_year == year,
            TaxTransactionTable.tax_period_month == month,
            TaxTransactionTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def find_by_period_range(
        self,
        legal_entity_id: UUID,
        tax_type: TaxType,
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
    ) -> list[TaxTransaction]:
        session = await self._get_session()
        conditions = [
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.tax_type == tax_type.value,
            TaxTransactionTable.deleted_at.is_(None),
        ]
        if start_year == end_year:
            conditions.append(
                and_(
                    TaxTransactionTable.tax_period_year == start_year,
                    TaxTransactionTable.tax_period_month.between(start_month, end_month)
                )
            )
        else:
            cond1 = and_(
                TaxTransactionTable.tax_period_year == start_year,
                TaxTransactionTable.tax_period_month >= start_month
            )
            cond2 = and_(
                TaxTransactionTable.tax_period_year == end_year,
                TaxTransactionTable.tax_period_month <= end_month
            )
            cond_mid = and_(
                TaxTransactionTable.tax_period_year > start_year,
                TaxTransactionTable.tax_period_year < end_year
            )
            conditions.append(or_(cond1, cond2, cond_mid))
        stmt = select(TaxTransactionTable).where(and_(*conditions))
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def get_total_tax_liability(
        self, legal_entity_id: UUID, tax_type: TaxType, start_date: date, end_date: date
    ) -> Decimal:
        session = await self._get_session()
        stmt = select(
            func.coalesce(func.sum(TaxTransactionTable.tax_amount), 0)
        ).where(
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.tax_type == tax_type.value,
            TaxTransactionTable.status.in_(["reported", "paid", "adjusted"]),
            TaxTransactionTable.deleted_at.is_(None),
            TaxTransactionTable.tax_period_year >= start_date.year,
            TaxTransactionTable.tax_period_year <= end_date.year,
        )
        result = await session.execute(stmt)
        return Decimal(str(result.scalar() or 0))

    async def get_total_tax_credit(
        self, legal_entity_id: UUID, tax_type: TaxType, start_date: date, end_date: date
    ) -> Decimal:
        session = await self._get_session()
        stmt = select(
            func.coalesce(func.sum(TaxTransactionTable.tax_amount), 0)
        ).where(
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.tax_type == tax_type.value,
            TaxTransactionTable.status.in_(["reported", "paid", "adjusted"]),
            TaxTransactionTable.tax_amount < 0,
            TaxTransactionTable.deleted_at.is_(None),
            TaxTransactionTable.tax_period_year >= start_date.year,
            TaxTransactionTable.tax_period_year <= end_date.year,
        )
        result = await session.execute(stmt)
        return Decimal(str(abs(result.scalar() or 0)))

    async def get_spt_by_period(
        self, legal_entity_id: UUID, spt_type: SPTType, period_month: int, period_year: int
    ) -> SPTSubmission | None:
        for spt in self._spt_submissions.values():
            if (spt.legal_entity_id == legal_entity_id and
                spt.spt_type == spt_type and
                spt.period_month == period_month and
                spt.period_year == period_year):
                return spt
        return None

    # ========================================================================
    # SPT MANAGEMENT
    # ========================================================================

    async def create_spt_submission(
        self,
        legal_entity_id: UUID,
        spt_type: SPTType,
        period_month: int,
        period_year: int,
        total_tax_due: Decimal,
        total_tax_paid: Decimal,
        total_tax_credit: Decimal,
        created_by: UUID,
    ) -> UUID:
        spt_id = uuid.uuid4()
        spt = SPTSubmission(
            id=spt_id,
            legal_entity_id=legal_entity_id,
            spt_type=spt_type,
            period_month=period_month,
            period_year=period_year,
            status="DRAFT",
            total_tax_due=total_tax_due,
            total_tax_paid=total_tax_paid,
            total_tax_credit=total_tax_credit,
            submission_date=None,
            approval_code=None,
            rejection_reason=None,
            xml_content=None,
            created_at=datetime.utcnow(),
            created_by=created_by,
            updated_at=datetime.utcnow(),
            updated_by=created_by,
        )
        self._spt_submissions[spt_id] = spt
        await self._log_audit("CREATE_SPT", spt_id, {"spt_type": spt_type.value, "period": f"{period_year}-{period_month}"})
        return spt_id

    async def submit_spt(
        self, spt_id: UUID, submission_date: date, xml_content: str, user_id: UUID
    ) -> bool:
        spt = self._spt_submissions.get(spt_id)
        if not spt or spt.status != "DRAFT":
            return False
        spt.status = "SUBMITTED"
        spt.submission_date = submission_date
        spt.xml_content = xml_content
        spt.updated_at = datetime.utcnow()
        spt.updated_by = user_id
        await self._log_audit("SUBMIT_SPT", spt_id, {"submission_date": submission_date.isoformat()})
        return True

    async def approve_spt(self, spt_id: UUID, approval_code: str, user_id: UUID) -> bool:
        spt = self._spt_submissions.get(spt_id)
        if not spt or spt.status != "SUBMITTED":
            return False
        spt.status = "APPROVED"
        spt.approval_code = approval_code
        spt.updated_at = datetime.utcnow()
        spt.updated_by = user_id
        await self._log_audit("APPROVE_SPT", spt_id, {"approval_code": approval_code})
        return True

    async def reject_spt(self, spt_id: UUID, reason: str, user_id: UUID) -> bool:
        spt = self._spt_submissions.get(spt_id)
        if not spt or spt.status != "SUBMITTED":
            return False
        spt.status = "REJECTED"
        spt.rejection_reason = reason
        spt.updated_at = datetime.utcnow()
        spt.updated_by = user_id
        await self._log_audit("REJECT_SPT", spt_id, {"reason": reason})
        return True

    # ========================================================================
    # MARK TRANSACTIONS REPORTED
    # ========================================================================

    async def mark_transactions_reported(
        self, tax_transaction_ids: list[UUID], spt_id: UUID, user_id: UUID
    ) -> int:
        if not tax_transaction_ids:
            return 0
        session = await self._get_session()
        stmt = (
            update(TaxTransactionTable)
            .where(
                TaxTransactionTable.id.in_(tax_transaction_ids),
                TaxTransactionTable.deleted_at.is_(None)
            )
            .values(
                status="reported",
                updated_at=datetime.utcnow(),
                # updated_by tidak ada
            )
        )
        result = await session.execute(stmt)
        await session.flush()
        count = result.rowcount
        await self._log_audit("MARK_REPORTED", UUID(int=0), {"count": count, "spt_id": str(spt_id)})
        logger.info(f"Marked {count} transactions as reported for SPT {spt_id}")
        return count

    async def record_payment(
        self,
        tax_transaction_id: UUID,
        payment_date: date,
        amount: Decimal,
        ntpn: str,
        user_id: UUID,
    ) -> bool:
        session = await self._get_session()
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.id == tax_transaction_id,
            TaxTransactionTable.deleted_at.is_(None)
        )
        result = await session.execute(stmt)
        tx = result.scalar_one_or_none()
        if not tx:
            return False
        tx.status = "paid"
        tx.ntpn = ntpn
        tx.payment_date = payment_date
        tx.updated_at = datetime.utcnow()
        # updated_by tidak ada
        await session.flush()
        await self._log_audit("RECORD_PAYMENT", tax_transaction_id, {"amount": str(amount), "ntpn": ntpn})
        return True

    async def create_adjustment(
        self, original_tx_id: UUID, new_tax_amount: Decimal, description: str, user_id: UUID
    ) -> TaxTransaction | None:
        session = await self._get_session()
        original_table = await session.get(TaxTransactionTable, original_tx_id)
        if not original_table:
            return None
        # Simpan reason di extra_metadata
        extra_metadata = {"adjustment_reason": description, "original_id": str(original_tx_id)}
        new_table = TaxTransactionTable(
            id=uuid.uuid4(),
            tax_type=original_table.tax_type,
            tax_amount=new_tax_amount,
            tax_period_year=original_table.tax_period_year,
            tax_period_month=original_table.tax_period_month,
            legal_entity_id=original_table.legal_entity_id,
            reference_id=original_table.reference_id,
            reference_type="adjustment",
            transaction_number=f"ADJ-{original_table.transaction_number or 'UNK'}",
            status="adjusted",
            extra_metadata=extra_metadata,
            created_by=user_id,
            created_at=datetime.utcnow(),
            transaction_date=date.today(),
            taxable_amount=Decimal(0),
            tax_rate=Decimal(0),
            currency="IDR",
            is_withholding=False,
        )
        session.add(new_table)
        await session.flush()
        return self._to_domain(new_table)

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    async def export_to_csv(
        self,
        legal_entity_id: UUID,
        tax_type: TaxType | None = None,
        start_year: int | None = None,
        start_month: int | None = None,
        end_year: int | None = None,
        end_month: int | None = None,
    ) -> str:
        session = await self._get_session()
        conditions = [
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.deleted_at.is_(None),
        ]
        if tax_type:
            conditions.append(TaxTransactionTable.tax_type == tax_type.value)
        if start_year and end_year:
            if start_year == end_year:
                conditions.append(
                    and_(
                        TaxTransactionTable.tax_period_year == start_year,
                        TaxTransactionTable.tax_period_month.between(start_month or 1, end_month or 12)
                    )
                )
            else:
                cond1 = and_(
                    TaxTransactionTable.tax_period_year == start_year,
                    TaxTransactionTable.tax_period_month >= (start_month or 1)
                )
                cond2 = and_(
                    TaxTransactionTable.tax_period_year == end_year,
                    TaxTransactionTable.tax_period_month <= (end_month or 12)
                )
                cond_mid = and_(
                    TaxTransactionTable.tax_period_year > start_year,
                    TaxTransactionTable.tax_period_year < end_year
                )
                conditions.append(or_(cond1, cond2, cond_mid))
        stmt = select(TaxTransactionTable).where(and_(*conditions))
        result = await session.execute(stmt)
        transactions = result.scalars().all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "tax_type", "tax_amount", "tax_period_year", "tax_period_month",
            "reference_id", "reference_type", "transaction_number",
            "status", "legal_entity_id", "created_at"
        ])
        for t in transactions:
            writer.writerow([
                str(t.id),
                t.tax_type,
                float(t.tax_amount),
                t.tax_period_year,
                t.tax_period_month,
                str(t.reference_id) if t.reference_id else "",
                t.reference_type or "",
                t.transaction_number or "",
                t.status or "",
                str(t.legal_entity_id),
                t.created_at.isoformat() if t.created_at else "",
            ])
        return output.getvalue()

    async def import_from_csv(self, csv_content: str, legal_entity_id: UUID, user_id: UUID) -> int:
        session = await self._get_session()
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                tx = TaxTransactionTable(
                    id=uuid.uuid4(),
                    tax_type=row["tax_type"],
                    tax_amount=Decimal(row["tax_amount"]),
                    tax_period_year=int(row["tax_period_year"]),
                    tax_period_month=int(row["tax_period_month"]),
                    reference_id=UUID(row["reference_id"]) if row.get("reference_id") else None,
                    reference_type=row.get("reference_type"),
                    transaction_number=row.get("transaction_number"),
                    legal_entity_id=legal_entity_id,
                    created_by=user_id,
                    created_at=datetime.utcnow(),
                    status=row.get("status", "calculated"),
                    transaction_date=date.today(),
                    taxable_amount=Decimal(0),
                    tax_rate=Decimal(0),
                    currency="IDR",
                    is_withholding=False,
                )
                session.add(tx)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import row: {e}")
        await session.flush()
        logger.info(f"Imported {count} tax transactions")
        return count

    # ========================================================================
    # STATISTICS & AUDIT
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
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
                TaxTransactionTable.status == "calculated",
                TaxTransactionTable.deleted_at.is_(None)
            )
        )
        pending_count = pending.scalar() or 0
        submitted = await session.execute(
            select(func.count()).where(
                TaxTransactionTable.legal_entity_id == legal_entity_id,
                TaxTransactionTable.status.in_(["reported", "paid"]),
                TaxTransactionTable.deleted_at.is_(None)
            )
        )
        submitted_count = submitted.scalar() or 0
        return {
            "total_transactions": total_count,
            "pending": pending_count,
            "submitted": submitted_count,
            "approved": 0,  # Tidak ada status approved di model, kita skip
            "total_liability": 0.0,
            "total_credit": 0.0,
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        logs = self._audit_log
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(select(1))
            total = await session.execute(select(func.count()).select_from(TaxTransactionTable))
            return {"status": "healthy", "repository": "TaxTransactionRepository", "total": total.scalar() or 0}
        except Exception as e:
            return {"status": "unhealthy", "repository": "TaxTransactionRepository", "error": str(e)}

    # ========================================================================
    # EXTRA METHODS YANG DIMINTA OLEH TaxRepositoryPort
    # ========================================================================

    async def save_tax_return(self, tax_return_data: dict) -> None:
        legal_entity_id = tax_return_data.get("legal_entity_id")
        period = tax_return_data.get("period")
        if not legal_entity_id or not period:
            raise ValueError("legal_entity_id dan period wajib diisi")
        key = f"{legal_entity_id}_{period}"
        self._tax_returns[key] = tax_return_data
        logger.info(f"Tax return saved for entity {legal_entity_id} period {period}")
        await self._log_audit("SAVE_TAX_RETURN", UUID(int=0), {"legal_entity": str(legal_entity_id), "period": period})

    async def find_tax_return_by_period(self, legal_entity_id: UUID, period: str) -> dict | None:
        key = f"{legal_entity_id}_{period}"
        return self._tax_returns.get(key)

    async def calculate_tax(self, legal_entity_id: UUID, period: str, tax_type: str) -> Decimal:
        session = await self._get_session()
        try:
            year, month = map(int, period.split('-'))
        except ValueError:
            year = int(period[:4])
            month = int(period[5:7]) if len(period) >= 7 else 1
        stmt = select(func.coalesce(func.sum(TaxTransactionTable.tax_amount), 0)).where(
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.tax_period_year == year,
            TaxTransactionTable.tax_period_month == month,
            TaxTransactionTable.deleted_at.is_(None)
        )
        result = await session.execute(stmt)
        total = result.scalar() or Decimal(0)
        logger.info(f"Calculated tax for entity {legal_entity_id} period {period}: {total}")
        return Decimal(str(total))

    # ========================================================================
    # HELPER
    # ========================================================================

    def _to_domain(self, table: TaxTransactionTable) -> TaxTransaction:
        # Mapping status dari string ke enum
        status_map = {
            "calculated": TaxTransactionStatus.DRAFT,
            "reported": TaxTransactionStatus.REPORTED,
            "paid": TaxTransactionStatus.PAID,
            "adjusted": TaxTransactionStatus.ADJUSTED,
            "cancelled": TaxTransactionStatus.CANCELLED,
        }
        status = status_map.get(table.status, TaxTransactionStatus.DRAFT)
        return TaxTransaction(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            tax_type=TaxType(table.tax_type),
            transaction_date=table.transaction_date,
            tax_period_month=table.tax_period_month,
            tax_period_year=table.tax_period_year,
            amount=table.taxable_amount,
            tax_amount=table.tax_amount,
            rate=table.tax_rate,
            status=status,
            reference_type=table.reference_type,
            reference_id=table.reference_id,
            description=None,
            is_credit=table.tax_amount < 0 if table.tax_amount else False,
            payment_date=table.payment_date,
            payment_amount=table.tax_amount,  # asumsi
            ntpn=table.ntpn,
            reported_in_spt_id=None,
            adjusted_from_id=None,
            created_at=table.created_at,
            created_by=table.created_by,
            updated_at=table.updated_at,
            updated_by=None,  # tidak ada di tabel
            version=table.version or 1,
            deleted_at=table.deleted_at,
            # tambahan untuk kompatibilitas domain mungkin butuh transaction_number
            transaction_number=table.transaction_number,
        )


__all__ = ["SQLAlchemyTaxTransactionRepository"]
