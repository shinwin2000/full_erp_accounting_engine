#!/usr/bin/env python3
"""
Module: sqlalchemy_journal_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk aggregate Journal menggunakan
               SQLAlchemy ORM. Menyediakan operasi CRUD untuk jurnal dengan
               dukungan optimistic locking, soft delete, dan mapping yang aman
               antara domain entity dan tabel database.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, delete, and_, or_
- ports.primary.journal_repository_port (JournalRepositoryPort)
- domain.journal.aggregate_root (JournalAggregate)
- infrastructure.persistence_orm.journal_header_table, journal_line_table
- domain.shared_value_objects.money_vo (Money)
Audit: Setiap operasi yang mengubah data jurnal dicatat di event store
       (diluar repository). Repository hanya fokus pada persistensi.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.journal.aggregate_root import JournalAggregate
from domain.journal.journal_entity import JournalLine, JournalStatus
from domain.shared_value_objects.document_number_vo import DocumentNumber

# Value objects
from domain.shared_value_objects.money_vo import Money

# Infrastructure ORM
from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
from infrastructure.persistence_orm.journal_line_table import JournalLineTable

# Ports
from ports.primary.journal_repository_port import JournalRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================


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


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyJournalRepository(JournalRepositoryPort):
    """
    Implementasi repository Journal dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise JournalRepositoryError("Session not set. Use UoW to get repository.")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain(
        self, header: JournalHeaderTable, lines: list[JournalLineTable]
    ) -> JournalAggregate:
        """
        Mapping dari ORM models ke domain aggregate.
        """
        journal_lines = []
        for line in lines:
            journal_lines.append(
                JournalLine(
                    id=line.id,
                    account_code=line.account_code,
                    account_name=line.account_name if hasattr(line, "account_name") else "",
                    debit_amount=Money(amount=line.debit_amount, currency=line.currency or "IDR"),
                    credit_amount=Money(amount=line.credit_amount, currency=line.currency or "IDR"),
                    cost_center=line.cost_center,
                    department=line.department,
                    description=line.description,
                    journal_id=line.journal_id,
                )
            )

        # Map status from string to enum
        status_map = {
            "draft": JournalStatus.DRAFT,
            "submitted": JournalStatus.SUBMITTED,
            "approved": JournalStatus.APPROVED,
            "posted": JournalStatus.POSTED,
            "reversed": JournalStatus.REVERSED,
            "cancelled": JournalStatus.CANCELLED,
        }
        status = status_map.get(header.status, JournalStatus.DRAFT)

        # Bangun aggregate
        aggregate = JournalAggregate(
            id=header.id,
            voucher_number=DocumentNumber(header.voucher_number),
            journal_date=header.journal_date,
            description=header.description,
            lines=journal_lines,
            status=status,
            total_debit=Money(amount=header.total_debit, currency=header.currency or "IDR"),
            total_credit=Money(amount=header.total_credit, currency=header.currency or "IDR"),
            created_by=header.created_by,
            created_at=header.created_at,
            approved_by=header.approved_by,
            approved_at=header.approved_at,
            posted_by=header.posted_by,
            posted_at=header.posted_at,
            reversed_by=header.reversed_by,
            reversed_at=header.reversed_at,
            reversed_journal_id=header.reversed_journal_id,
            original_journal_id=header.original_journal_id,
            reference_number=header.reference_number,
            source_type=header.source_type,
            source_id=header.source_id,
            version=header.version,
        )

        return aggregate

    async def _to_orm_header(self, aggregate: JournalAggregate) -> JournalHeaderTable:
        """Mapping dari domain ke ORM header."""
        header = JournalHeaderTable(
            id=aggregate.id,
            voucher_number=str(aggregate.voucher_number),
            journal_date=aggregate.journal_date,
            description=aggregate.description,
            status=aggregate.status.value
            if hasattr(aggregate.status, "value")
            else str(aggregate.status),
            total_debit=aggregate.total_debit.amount,
            total_credit=aggregate.total_credit.amount,
            currency=aggregate.total_debit.currency,
            created_by=aggregate.created_by,
            created_at=aggregate.created_at,
            approved_by=aggregate.approved_by,
            approved_at=aggregate.approved_at,
            posted_by=aggregate.posted_by,
            posted_at=aggregate.posted_at,
            reversed_by=aggregate.reversed_by,
            reversed_at=aggregate.reversed_at,
            reversed_journal_id=aggregate.reversed_journal_id,
            original_journal_id=aggregate.original_journal_id,
            reference_number=aggregate.reference_number,
            source_type=aggregate.source_type,
            source_id=aggregate.source_id,
            legal_entity_id=aggregate.legal_entity_id,
            version=aggregate.version,
            updated_at=datetime.utcnow(),
        )
        return header

    async def _to_orm_lines(self, aggregate: JournalAggregate) -> list[JournalLineTable]:
        """Mapping domain lines ke ORM lines."""
        lines = []
        for i, line in enumerate(aggregate.lines):
            line_table = JournalLineTable(
                id=line.id,
                journal_id=aggregate.id,
                line_number=i + 1,
                account_code=line.account_code,
                account_name=line.account_name,
                debit_amount=line.debit_amount.amount,
                credit_amount=line.credit_amount.amount,
                currency=line.debit_amount.currency,
                cost_center=line.cost_center,
                department=line.department,
                description=line.description,
                legal_entity_id=aggregate.legal_entity_id,
            )
            lines.append(line_table)
        return lines

    # ========================================================================
    # REPOSITORY METHODS
    # ========================================================================

    # --- NEW: save method (required by port) ---
    async def save(self, journal: JournalAggregate) -> None:
        """
        Simpan jurnal (insert jika baru, update jika sudah ada).
        Method ini memenuhi kontrak JournalRepositoryPort.save().
        """
        existing = await self.get_by_id(journal.id)
        if existing is None:
            await self.add(journal)
        else:
            await self.update(journal)

    async def add(self, journal: JournalAggregate) -> None:
        """
        Menambahkan jurnal baru ke database.
        """
        try:
            # Cek duplikasi voucher number
            exists = await self.exists_by_voucher_number(str(journal.voucher_number))
            if exists:
                raise DuplicateJournalNumberError(
                    f"Voucher number {journal.voucher_number} already exists"
                )

            # Mapping ke ORM
            header = await self._to_orm_header(journal)
            lines = await self._to_orm_lines(journal)

            # Add to session
            self.session.add(header)
            for line in lines:
                self.session.add(line)

            await self.session.flush()
            logger.info("Journal added: %s (id=%s)", journal.voucher_number, journal.id)

        except IntegrityError as e:
            await self.session.rollback()
            if "voucher_number" in str(e).lower():
                raise DuplicateJournalNumberError(
                    f"Duplicate voucher number: {journal.voucher_number}"
                ) from e
            raise JournalRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add journal: %s", e)
            raise JournalRepositoryError(f"Failed to add journal: {e}") from e

    async def get_by_id(self, journal_id: UUID) -> JournalAggregate | None:
        """
        Mengambil jurnal berdasarkan ID.
        """
        try:
            # Query header
            stmt = select(JournalHeaderTable).where(JournalHeaderTable.id == journal_id)
            result = await self.session.execute(stmt)
            header = result.scalar_one_or_none()

            if not header:
                return None

            # Query lines
            lines_stmt = (
                select(JournalLineTable)
                .where(JournalLineTable.journal_id == journal_id)
                .order_by(JournalLineTable.line_number)
            )
            lines_result = await self.session.execute(lines_stmt)
            lines = lines_result.scalars().all()

            return self._to_domain(header, lines)

        except Exception as e:
            logger.error("Failed to get journal by id %s: %s", journal_id, e)
            raise JournalRepositoryError(f"Failed to get journal: {e}") from e

    async def get_by_voucher_number(self, voucher_number: str) -> JournalAggregate | None:
        """
        Mengambil jurnal berdasarkan nomor voucher.
        """
        try:
            stmt = select(JournalHeaderTable).where(
                JournalHeaderTable.voucher_number == voucher_number
            )
            result = await self.session.execute(stmt)
            header = result.scalar_one_or_none()

            if not header:
                return None

            lines_stmt = (
                select(JournalLineTable)
                .where(JournalLineTable.journal_id == header.id)
                .order_by(JournalLineTable.line_number)
            )
            lines_result = await self.session.execute(lines_stmt)
            lines = lines_result.scalars().all()

            return self._to_domain(header, lines)

        except Exception as e:
            logger.error("Failed to get journal by voucher number %s: %s", voucher_number, e)
            raise JournalRepositoryError(f"Failed to get journal: {e}") from e

    async def update(self, journal: JournalAggregate) -> None:
        """
        Memperbarui jurnal yang sudah ada (hanya jika status draft).
        Menggunakan optimistic locking berdasarkan version.
        """
        try:
            # Get current version from database
            stmt = select(JournalHeaderTable.version).where(JournalHeaderTable.id == journal.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise JournalNotFoundError(f"Journal {journal.id} not found")

            # Check version match
            if current_version != journal.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {journal.version}, got {current_version}"
                )

            # Update header
            header = await self._to_orm_header(journal)
            header.version = journal.version + 1
            header.updated_at = datetime.utcnow()

            await self.session.merge(header)

            # Update lines: delete existing and insert new
            await self.session.execute(
                delete(JournalLineTable).where(JournalLineTable.journal_id == journal.id)
            )
            lines = await self._to_orm_lines(journal)
            for line in lines:
                self.session.add(line)

            await self.session.flush()
            logger.info(
                "Journal updated: %s (version %d -> %d)",
                journal.voucher_number,
                journal.version,
                journal.version + 1,
            )

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update journal %s: %s", journal.id, e)
            raise JournalRepositoryError(f"Failed to update journal: {e}") from e

    async def delete(self, journal_id: UUID) -> bool:
        """
        Soft delete jurnal (set deleted_at).
        """
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(JournalHeaderTable.id == journal_id)
                .values(deleted_at=datetime.utcnow(), status="cancelled")
            )
            result = await self.session.execute(stmt)
            await self.session.flush()

            deleted = result.rowcount > 0
            if deleted:
                logger.info("Journal %s soft deleted", journal_id)
            return deleted

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete journal %s: %s", journal_id, e)
            raise JournalRepositoryError(f"Failed to delete journal: {e}") from e

    async def find_by_status(
        self, status: str, limit: int = 100, offset: int = 0
    ) -> list[JournalAggregate]:
        """
        Mencari jurnal berdasarkan status.
        """
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(JournalHeaderTable.status == status)
                .where(JournalHeaderTable.deleted_at.is_(None))
                .order_by(JournalHeaderTable.created_at.desc())
                .limit(limit)
                .offset(offset)
            )

            result = await self.session.execute(stmt)
            headers = result.scalars().all()

            journals = []
            for header in headers:
                lines_stmt = select(JournalLineTable).where(
                    JournalLineTable.journal_id == header.id
                )
                lines_result = await self.session.execute(lines_stmt)
                lines = lines_result.scalars().all()
                journals.append(self._to_domain(header, lines))

            return journals

        except Exception as e:
            logger.error("Failed to find journals by status %s: %s", status, e)
            raise JournalRepositoryError(f"Failed to find journals: {e}") from e

    async def find_by_period(
        self, period_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[JournalAggregate]:
        """
        Mencari jurnal dalam periode akuntansi.
        """
        try:
            # Join dengan fiscal_period table
            stmt = (
                select(JournalHeaderTable)
                .join("fiscal_period", JournalHeaderTable.period_id == period_id)
                .where(JournalHeaderTable.deleted_at.is_(None))
                .order_by(JournalHeaderTable.journal_date)
                .limit(limit)
                .offset(offset)
            )

            result = await self.session.execute(stmt)
            headers = result.scalars().all()

            journals = []
            for header in headers:
                lines_stmt = select(JournalLineTable).where(
                    JournalLineTable.journal_id == header.id
                )
                lines_result = await self.session.execute(lines_stmt)
                lines = lines_result.scalars().all()
                journals.append(self._to_domain(header, lines))

            return journals

        except Exception as e:
            logger.error("Failed to find journals by period %s: %s", period_id, e)
            raise JournalRepositoryError(f"Failed to find journals: {e}") from e

    async def exists_by_voucher_number(self, voucher_number: str) -> bool:
        """
        Memeriksa apakah nomor voucher sudah ada.
        """
        try:
            stmt = (
                select(func.count())
                .select_from(JournalHeaderTable)
                .where(
                    JournalHeaderTable.voucher_number == voucher_number,
                    JournalHeaderTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            logger.error("Failed to check voucher number %s: %s", voucher_number, e)
            raise JournalRepositoryError(f"Failed to check voucher number: {e}") from e

    async def find_by_date_range(
        self, start_date: date, end_date: date, legal_entity_id: UUID, limit: int = 100
    ) -> list[JournalAggregate]:
        """
        Mencari jurnal dalam rentang tanggal.
        """
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.journal_date >= start_date,
                    JournalHeaderTable.journal_date <= end_date,
                    JournalHeaderTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .order_by(JournalHeaderTable.journal_date)
                .limit(limit)
            )

            result = await self.session.execute(stmt)
            headers = result.scalars().all()

            journals = []
            for header in headers:
                lines_stmt = select(JournalLineTable).where(
                    JournalLineTable.journal_id == header.id
                )
                lines_result = await self.session.execute(lines_stmt)
                lines = lines_result.scalars().all()
                journals.append(self._to_domain(header, lines))

            return journals

        except Exception as e:
            logger.error("Failed to find journals by date range: %s", e)
            raise JournalRepositoryError(f"Failed to find journals: {e}") from e

    async def get_next_voucher_number(self, prefix: str = "JRN", year: int = None) -> str:
        """
        Menghasilkan nomor voucher berikutnya.
        Format: {prefix}-{YYYY}-{seq:06d}
        """
        if year is None:
            year = date.today().year

        try:
            # Gunakan func.concat untuk menghindari f-string dalam SQL
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = (
                select(JournalHeaderTable.voucher_number)
                .where(
                    JournalHeaderTable.voucher_number.like(pattern),
                    JournalHeaderTable.deleted_at.is_(None),
                )
                .order_by(JournalHeaderTable.voucher_number.desc())
                .limit(1)
            )

            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            return f"{prefix}-{year}-{seq:06d}"

        except Exception as e:
            logger.error("Failed to generate next voucher number: %s", e)
            raise JournalRepositoryError(f"Failed to generate voucher number: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================
SqlAlchemyJournalRepository = SQLAlchemyJournalRepository
__all__ = [
    "DuplicateJournalNumberError",
    "JournalNotFoundError",
    "JournalRepositoryError",
    "OptimisticLockError",
    "SQLAlchemyJournalRepository",
    "SqlAlchemyJournalRepository",
]
