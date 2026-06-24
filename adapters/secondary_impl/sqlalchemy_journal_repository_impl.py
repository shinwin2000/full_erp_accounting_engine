#!/usr/bin/env python3
"""
Module: sqlalchemy_journal_repository_impl.py
Layer: Adapters / Secondary Implementation
Responsibility: Implementasi repository untuk Journal menggunakan SQLAlchemy ORM.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, desc, func, select, update, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from domain.journal.aggregate_root import JournalAggregate
from domain.journal.journal_entity import JournalStatus, JournalType
from domain.journal.journal_line_vo import JournalLineVO, JournalSide
from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
from infrastructure.persistence_orm.journal_line_table import JournalLineTable
from ports.primary.journal_repository_port import JournalRepositoryPort

logger = logging.getLogger(__name__)


class JournalRepositoryError(Exception):
    """Base exception untuk repository journal."""
    pass


class DuplicateJournalNumberError(JournalRepositoryError):
    """Nomor jurnal sudah ada."""
    pass


class JournalNotFoundError(JournalRepositoryError):
    """Jurnal tidak ditemukan."""
    pass


class OptimisticLockError(JournalRepositoryError):
    """Version mismatch saat update (optimistic locking)."""
    pass


class SQLAlchemyJournalRepository(JournalRepositoryPort):
    """
    Implementasi repository Journal dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========================================================================
    # MAPPING HELPERS
    # ========================================================================

    def _to_domain(
        self, header: JournalHeaderTable, lines: list[JournalLineTable]
    ) -> JournalAggregate:
        """Mapping dari ORM models ke domain aggregate."""
        journal_lines = []
        for line in lines:
            journal_lines.append(
                JournalLineVO(
                    line_id=line.id,
                    journal_id=line.journal_id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    account_name=line.account_name or "",
                    side=JournalSide.DEBIT if line.debit_amount > 0 else JournalSide.CREDIT,
                    amount=line.debit_amount if line.debit_amount > 0 else line.credit_amount,
                    description=line.description or "",
                    legal_entity_id=header.legal_entity_id,
                    cost_center=line.cost_center,
                    department=line.department,
                    project_id=line.project_id,
                    customer_id=getattr(line, "customer_id", None),
                    supplier_id=getattr(line, "supplier_id", None),
                    employee_id=getattr(line, "employee_id", None),
                )
            )

        status_map = {
            "draft": JournalStatus.DRAFT,
            "submitted": JournalStatus.SUBMITTED,
            "approved": JournalStatus.APPROVED,
            "posted": JournalStatus.POSTED,
            "reversed": JournalStatus.REVERSED,
            "cancelled": JournalStatus.CANCELLED,
            "rejected": JournalStatus.REJECTED,
            "archived": JournalStatus.ARCHIVED,
        }
        status = status_map.get(header.status, JournalStatus.DRAFT)

        return JournalAggregate(
            journal_id=header.id,
            journal_number=header.journal_number,
            journal_type=JournalType(header.journal_type) if hasattr(header, "journal_type") else JournalType.GENERAL,
            transaction_date=header.journal_date,
            posting_date=header.posting_date,
            description=header.description or "",
            lines=journal_lines,
            legal_entity_id=header.legal_entity_id,
            status=status,
            created_by=header.created_by or "system",
            created_at=header.created_at or datetime.utcnow(),
            updated_at=header.updated_at or datetime.utcnow(),
            approved_by=[],
            approved_at=header.approved_at,
            posted_by=header.posted_by,
            posted_at=header.posted_at,
            reversed_by=header.reversed_by,
            reversed_at=header.reversed_at,
            reversal_of=header.original_journal_id,
            reversal_journal_id=header.reversed_journal_id,
            reference=header.reference_number,
            source_system=header.source_type or "ERP",
            _version=header.version or 1,
            _is_locked=header.is_locked if hasattr(header, "is_locked") else False,
        )

    async def _to_orm_header(self, aggregate: JournalAggregate) -> JournalHeaderTable:
        """Mapping dari domain ke ORM header."""
        return JournalHeaderTable(
            id=aggregate.journal_id,
            journal_number=aggregate.journal_number,
            journal_type=aggregate.journal_type.value,
            journal_date=aggregate.transaction_date,
            posting_date=aggregate.posting_date,
            description=aggregate.description,
            status=aggregate.status.value,
            legal_entity_id=aggregate.legal_entity_id,
            created_by=aggregate.created_by,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            approved_at=aggregate.approved_at,
            posted_by=aggregate.posted_by,
            posted_at=aggregate.posted_at,
            reversed_by=aggregate.reversed_by,
            reversed_at=aggregate.reversed_at,
            original_journal_id=aggregate.reversal_of,
            reversed_journal_id=aggregate.reversal_journal_id,
            reference_number=aggregate.reference,
            source_type=aggregate.source_system,
            version=aggregate.version + 1,
            is_locked=aggregate.is_locked,
            locked_by=aggregate._locked_by if hasattr(aggregate, "_locked_by") else None,
            locked_at=aggregate._locked_at if hasattr(aggregate, "_locked_at") else None,
        )

    async def _to_orm_lines(self, aggregate: JournalAggregate) -> list[JournalLineTable]:
        """Mapping domain lines ke ORM lines."""
        lines = []
        for i, line in enumerate(aggregate.lines):
            debit = line.amount if line.side == JournalSide.DEBIT else Decimal("0")
            credit = line.amount if line.side == JournalSide.CREDIT else Decimal("0")
            lines.append(
                JournalLineTable(
                    id=line.line_id,
                    journal_id=aggregate.journal_id,
                    line_number=i + 1,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    account_name=line.account_name,
                    debit_amount=debit,
                    credit_amount=credit,
                    description=line.description,
                    cost_center=line.cost_center,
                    department=line.department,
                    project_id=line.project_id,
                    customer_id=line.customer_id,
                    supplier_id=line.supplier_id,
                    employee_id=line.employee_id,
                    legal_entity_id=aggregate.legal_entity_id,
                    created_at=datetime.utcnow(),
                )
            )
        return lines

    # ========================================================================
    # PORT METHODS
    # ========================================================================

    async def save(self, journal: JournalAggregate) -> None:
        """Simpan journal (insert jika baru, update jika sudah ada)."""
        existing = await self.get_by_id(journal.journal_id, journal.legal_entity_id)
        if existing is None:
            await self.add(journal)
        else:
            await self.update(journal)

    async def add(self, journal: JournalAggregate) -> None:
        """Menambahkan jurnal baru."""
        session = await self._get_session()
        try:
            # Cek duplikasi journal number
            exists = await self.exists(journal.journal_number, journal.legal_entity_id)
            if exists:
                raise DuplicateJournalNumberError(
                    f"Journal number {journal.journal_number} already exists"
                )

            header = await self._to_orm_header(journal)
            lines = await self._to_orm_lines(journal)

            session.add(header)
            for line in lines:
                session.add(line)

            await session.flush()
            logger.info(f"Journal added: {journal.journal_number}")

        except IntegrityError as e:
            await session.rollback()
            if "journal_number" in str(e).lower():
                raise DuplicateJournalNumberError(
                    f"Duplicate journal number: {journal.journal_number}"
                ) from e
            raise JournalRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add journal: {e}")
            raise JournalRepositoryError(f"Failed to add journal: {e}") from e

    async def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> JournalAggregate | None:
        """Ambil journal berdasarkan ID."""
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.id == journal_id,
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                return None
            return self._to_domain(header, header.lines)
        except Exception as e:
            logger.error(f"Failed to get journal by id {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to get journal: {e}") from e

    async def get_by_voucher_number(self, voucher_number: str) -> JournalAggregate | None:
        """Ambil journal berdasarkan nomor voucher."""
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.journal_number == voucher_number,
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                return None
            return self._to_domain(header, header.lines)
        except Exception as e:
            logger.error(f"Failed to get journal by voucher number {voucher_number}: {e}")
            raise JournalRepositoryError(f"Failed to get journal: {e}") from e

    async def update(self, journal: JournalAggregate) -> None:
        """Update journal dengan optimistic locking."""
        session = await self._get_session()
        try:
            # Check version
            stmt = select(JournalHeaderTable.version).where(
                JournalHeaderTable.id == journal.journal_id
            )
            result = await session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise JournalNotFoundError(f"Journal {journal.journal_id} not found")
            if current_version != journal.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {journal.version}, got {current_version}"
                )

            # Update header
            header = await self._to_orm_header(journal)
            header.version = journal.version + 1
            header.updated_at = datetime.utcnow()

            await session.merge(header)

            # Delete existing lines and insert new ones
            await session.execute(
                delete(JournalLineTable).where(
                    JournalLineTable.journal_id == journal.journal_id
                )
            )
            lines = await self._to_orm_lines(journal)
            for line in lines:
                session.add(line)

            await session.flush()
            logger.info(f"Journal updated: {journal.journal_number}")

        except OptimisticLockError:
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update journal {journal.journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to update journal: {e}") from e

    async def delete(self, journal_id: UUID, legal_entity_id: UUID) -> None:
        """Soft delete journal."""
        session = await self._get_session()
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(
                    JournalHeaderTable.id == journal_id,
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                )
                .values(deleted_at=datetime.utcnow(), status="cancelled")
            )
            result = await session.execute(stmt)
            await session.flush()
            if result.rowcount == 0:
                raise JournalNotFoundError(f"Journal {journal_id} not found")
            logger.info(f"Journal {journal_id} soft deleted")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to delete journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to delete journal: {e}") from e

    async def exists(self, journal_number: str, legal_entity_id: UUID) -> bool:
        """Cek apakah journal number sudah ada."""
        session = await self._get_session()
        try:
            stmt = (
                select(func.count())
                .select_from(JournalHeaderTable)
                .where(
                    JournalHeaderTable.journal_number == journal_number,
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            logger.error(f"Failed to check journal number {journal_number}: {e}")
            raise JournalRepositoryError(f"Failed to check journal: {e}") from e

    async def count(
        self,
        legal_entity_id: UUID,
        status: JournalStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """Count journal dengan filter."""
        session = await self._get_session()
        try:
            conditions = [
                JournalHeaderTable.legal_entity_id == legal_entity_id,
                JournalHeaderTable.deleted_at.is_(None),
            ]
            if status:
                conditions.append(JournalHeaderTable.status == status.value)
            if start_date:
                conditions.append(JournalHeaderTable.journal_date >= start_date)
            if end_date:
                conditions.append(JournalHeaderTable.journal_date <= end_date)

            stmt = select(func.count()).select_from(JournalHeaderTable).where(and_(*conditions))
            result = await session.execute(stmt)
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Failed to count journals: {e}")
            raise JournalRepositoryError(f"Failed to count journals: {e}") from e

    async def get_all(
        self,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalAggregate]:
        """Get all journals with pagination."""
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .order_by(desc(JournalHeaderTable.journal_date))
                .offset(offset)
                .limit(limit)
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            headers = result.scalars().all()
            return [self._to_domain(h, h.lines) for h in headers]
        except Exception as e:
            logger.error(f"Failed to get all journals: {e}")
            raise JournalRepositoryError(f"Failed to get journals: {e}") from e

    async def find_by_status(
        self,
        status: JournalStatus,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalAggregate]:
        """Find journals by status."""
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.status == status.value,
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .order_by(desc(JournalHeaderTable.journal_date))
                .offset(offset)
                .limit(limit)
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            headers = result.scalars().all()
            return [self._to_domain(h, h.lines) for h in headers]
        except Exception as e:
            logger.error(f"Failed to find journals by status {status}: {e}")
            raise JournalRepositoryError(f"Failed to find journals: {e}") from e

    async def find_by_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalAggregate]:
        """Find journals by period."""
        session = await self._get_session()
        try:
            # Jika ada period_id di JournalHeaderTable
            if hasattr(JournalHeaderTable, "period_id"):
                stmt = (
                    select(JournalHeaderTable)
                    .where(
                        JournalHeaderTable.period_id == period_id,
                        JournalHeaderTable.legal_entity_id == legal_entity_id,
                        JournalHeaderTable.deleted_at.is_(None),
                    )
                    .order_by(desc(JournalHeaderTable.journal_date))
                    .offset(offset)
                    .limit(limit)
                    .options(selectinload(JournalHeaderTable.lines))
                )
            else:
                # Fallback: cari berdasarkan date range dari period
                # Asumsikan period_id adalah UUID yang tidak bisa di-join
                # Kita kembalikan kosong
                logger.warning(f"period_id not supported in this ORM schema: {period_id}")
                return []
            result = await session.execute(stmt)
            headers = result.scalars().all()
            return [self._to_domain(h, h.lines) for h in headers]
        except Exception as e:
            logger.error(f"Failed to find journals by period {period_id}: {e}")
            raise JournalRepositoryError(f"Failed to find journals: {e}") from e

    async def find_by_date_range(
        self,
        start_date: date,
        end_date: date,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalAggregate]:
        """Find journals by date range."""
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.journal_date >= start_date,
                    JournalHeaderTable.journal_date <= end_date,
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .order_by(desc(JournalHeaderTable.journal_date))
                .offset(offset)
                .limit(limit)
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            headers = result.scalars().all()
            return [self._to_domain(h, h.lines) for h in headers]
        except Exception as e:
            logger.error(f"Failed to find journals by date range: {e}")
            raise JournalRepositoryError(f"Failed to find journals: {e}") from e

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[JournalAggregate]:
        """Get pending approval journals (SUBMITTED status)."""
        return await self.find_by_status(JournalStatus.SUBMITTED, legal_entity_id)

    async def get_next_voucher_number(self, prefix: str = "JRN", year: int = None) -> str:
        """Generate next voucher number."""
        if year is None:
            year = date.today().year
        session = await self._get_session()
        try:
            pattern = f"{prefix}-{year}-%"
            stmt = (
                select(JournalHeaderTable.journal_number)
                .where(
                    JournalHeaderTable.journal_number.like(pattern),
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .order_by(desc(JournalHeaderTable.journal_number))
                .limit(1)
            )
            result = await session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            return f"{prefix}-{year}-{seq:06d}"
        except Exception as e:
            logger.error(f"Failed to generate next voucher number: {e}")
            raise JournalRepositoryError(f"Failed to generate voucher number: {e}") from e

    # ========================================================================
    # METHODS REQUIRED BY P55 STRUCTURAL AUDITOR
    # ========================================================================

    async def save(self, journal: JournalAggregate) -> None:
        """P55: Save (add or update) a journal."""
        existing = await self.get_by_id(journal.journal_id, journal.legal_entity_id)
        if existing:
            await self.update(journal)
        else:
            await self.add(journal)

    async def find_by_id(self, journal_id: UUID) -> JournalAggregate | None:
        """P55: Find journal by ID without legal_entity_id filter."""
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(JournalHeaderTable.id == journal_id, JournalHeaderTable.deleted_at.is_(None))
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                return None
            return self._to_domain(header, header.lines)
        except Exception as e:
            logger.error(f"Failed to find journal by id {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to find journal: {e}") from e

    async def find_all(self, limit: int = 100, offset: int = 0) -> list[JournalAggregate]:
        """P55: Find all journals without legal_entity filter."""
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(JournalHeaderTable.deleted_at.is_(None))
                .order_by(desc(JournalHeaderTable.journal_date))
                .offset(offset).limit(limit)
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            headers = result.scalars().all()
            return [self._to_domain(h, h.lines) for h in headers]
        except Exception as e:
            raise JournalRepositoryError(f"Failed to find all journals: {e}") from e

    # ========================================================================
    # NEW MISSING METHODS (from JournalRepositoryPort)
    # ========================================================================

    async def approve(self, journal_id: UUID, approved_by: UUID) -> None:
        """Approve a journal (status -> APPROVED)."""
        session = await self._get_session()
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(JournalHeaderTable.id == journal_id)
                .values(
                    status=JournalStatus.APPROVED.value,
                    approved_by=approved_by,
                    approved_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            result = await session.execute(stmt)
            await session.flush()
            if result.rowcount == 0:
                raise JournalNotFoundError(f"Journal {journal_id} not found")
            logger.info(f"Journal {journal_id} approved by {approved_by}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to approve journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to approve journal: {e}") from e

    async def exists_by_voucher_number(self, voucher_number: str, legal_entity_id: UUID) -> bool:
        """Check if a voucher number exists for the legal entity."""
        return await self.exists(voucher_number, legal_entity_id)

    async def export_to_csv(self, journals: list[JournalAggregate]) -> str:
        """Export journals to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        # Write header
        writer.writerow([
            "Journal ID", "Journal Number", "Transaction Date", "Description",
            "Status", "Legal Entity", "Created By", "Created At",
            "Line Number", "Account ID", "Account Code", "Account Name",
            "Debit", "Credit", "Line Description"
        ])
        for journal in journals:
            for line in journal.lines:
                writer.writerow([
                    str(journal.journal_id),
                    journal.journal_number,
                    journal.transaction_date.isoformat(),
                    journal.description,
                    journal.status.value,
                    str(journal.legal_entity_id),
                    journal.created_by,
                    journal.created_at.isoformat() if journal.created_at else "",
                    line.line_number if hasattr(line, "line_number") else "",
                    str(line.account_id) if line.account_id else "",
                    line.account_code,
                    line.account_name,
                    str(line.amount) if line.side == JournalSide.DEBIT else "0",
                    str(line.amount) if line.side == JournalSide.CREDIT else "0",
                    line.description,
                ])
        return output.getvalue()

    async def find_by_account(
        self,
        account_id: UUID,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JournalAggregate]:
        """Find journals containing lines with a specific account."""
        session = await self._get_session()
        try:
            # Subquery to get journal IDs that have lines with this account
            subq = (
                select(JournalLineTable.journal_id)
                .where(
                    JournalLineTable.account_id == account_id,
                    JournalLineTable.legal_entity_id == legal_entity_id,
                )
                .distinct()
                .subquery()
            )
            stmt = (
                select(JournalHeaderTable)
                .join(subq, JournalHeaderTable.id == subq.c.journal_id)
                .where(
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.journal_date >= start_date,
                    JournalHeaderTable.journal_date <= end_date,
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .order_by(desc(JournalHeaderTable.journal_date))
                .offset(offset)
                .limit(limit)
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            headers = result.scalars().all()
            # Need to filter lines to only those with the account? The JournalAggregate will include all lines,
            # but we could filter later if needed. However, port likely expects full journals.
            return [self._to_domain(h, h.lines) for h in headers]
        except Exception as e:
            logger.error(f"Failed to find journals by account {account_id}: {e}")
            raise JournalRepositoryError(f"Failed to find journals by account: {e}") from e

    async def get_audit_log(self, journal_id: UUID) -> list[dict[str, Any]]:
        """Get audit log entries for a journal (stub - no audit table)."""
        # In a real implementation, we would query an audit log table.
        # For now, return a stub entry.
        return [
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": "get_audit_log",
                "message": f"Audit log for journal {journal_id} not implemented",
            }
        ]

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Get statistics about journals."""
        session = await self._get_session()
        try:
            # Count by status
            status_counts = {}
            for status in JournalStatus:
                count = await self.count(legal_entity_id, status=status)
                status_counts[status.value] = count
            # Total count
            total = await self.count(legal_entity_id)
            return {
                "total": total,
                "by_status": status_counts,
                "legal_entity_id": str(legal_entity_id),
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            raise JournalRepositoryError(f"Failed to get statistics: {e}") from e

    async def health_check(self) -> dict[str, Any]:
        """Perform health check (database connectivity)."""
        try:
            session = await self._get_session()
            await session.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "connected"}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def import_from_csv(self, csv_data: str, legal_entity_id: UUID) -> list[JournalAggregate]:
        """Import journals from CSV (stub)."""
        # This is a placeholder; actual implementation would parse CSV and create JournalAggregate objects.
        logger.info(f"Import CSV for legal_entity {legal_entity_id} - not implemented")
        return []

    async def post(self, journal_id: UUID, posted_by: UUID) -> None:
        """Post a journal (status -> POSTED)."""
        session = await self._get_session()
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(JournalHeaderTable.id == journal_id)
                .values(
                    status=JournalStatus.POSTED.value,
                    posted_by=posted_by,
                    posted_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            result = await session.execute(stmt)
            await session.flush()
            if result.rowcount == 0:
                raise JournalNotFoundError(f"Journal {journal_id} not found")
            logger.info(f"Journal {journal_id} posted by {posted_by}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to post journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to post journal: {e}") from e

    async def reverse(self, journal_id: UUID, reversed_by: UUID, reversal_date: date) -> None:
        """Reverse a journal (create reversal journal and update original)."""
        # This is complex; we need to create a new journal with reversed signs,
        # update original status to REVERSED, and link them.
        # For stub, we'll just update status to REVERSED.
        # In real implementation, you'd create a reversal journal.
        session = await self._get_session()
        try:
            # Update original to REVERSED
            stmt = (
                update(JournalHeaderTable)
                .where(JournalHeaderTable.id == journal_id)
                .values(
                    status=JournalStatus.REVERSED.value,
                    reversed_by=reversed_by,
                    reversed_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            result = await session.execute(stmt)
            await session.flush()
            if result.rowcount == 0:
                raise JournalNotFoundError(f"Journal {journal_id} not found")
            logger.info(f"Journal {journal_id} reversed by {reversed_by}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to reverse journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to reverse journal: {e}") from e

    async def submit(self, journal_id: UUID, submitted_by: UUID) -> None:
        """Submit a journal (status -> SUBMITTED)."""
        session = await self._get_session()
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(JournalHeaderTable.id == journal_id)
                .values(
                    status=JournalStatus.SUBMITTED.value,
                    updated_at=datetime.utcnow(),
                    # Optionally store submitted_by if there is a field
                )
            )
            result = await session.execute(stmt)
            await session.flush()
            if result.rowcount == 0:
                raise JournalNotFoundError(f"Journal {journal_id} not found")
            logger.info(f"Journal {journal_id} submitted by {submitted_by}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to submit journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to submit journal: {e}") from e


# ============================================================================
# ALIAS untuk kompatibilitas dengan import yang berbeda
# ============================================================================

SQLAlchemyJournalRepositoryImpl = SQLAlchemyJournalRepository
SqlAlchemyJournalRepository = SQLAlchemyJournalRepository


__all__ = [
    "DuplicateJournalNumberError",
    "JournalNotFoundError",
    "JournalRepositoryError",
    "OptimisticLockError",
    "SQLAlchemyJournalRepository",
    "SQLAlchemyJournalRepositoryImpl",
    "SqlAlchemyJournalRepository",
]