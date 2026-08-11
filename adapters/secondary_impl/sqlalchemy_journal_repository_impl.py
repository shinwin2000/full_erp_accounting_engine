#!/usr/bin/env python3
"""
Module: sqlalchemy_journal_repository_impl.py
Layer: Adapters / Secondary Implementation
Responsibility: Implementasi repository Journal dengan SQLAlchemy.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, desc, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from domain.journal.journal_entity import JournalStatus, JournalType
from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
from infrastructure.persistence_orm.journal_line_table import JournalLineTable
from ports.primary.journal_repository_port import (
    Journal,
    JournalLine,
    JournalListResult,
    JournalRepositoryPort,
)

logger = logging.getLogger(__name__)


class JournalRepositoryError(Exception):
    pass


class DuplicateJournalNumberError(JournalRepositoryError):
    pass


class JournalNotFoundError(JournalRepositoryError):
    pass


class OptimisticLockError(JournalRepositoryError):
    pass


class SQLAlchemyJournalRepository(JournalRepositoryPort):
    """Implementasi repository Journal dengan SQLAlchemy."""

    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct
            self._session = await get_async_session_direct()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========================================================================
    # MAPPING HELPERS (Domain ↔ ORM)
    # ========================================================================

    def _to_domain(
        self, header: JournalHeaderTable, lines: list[JournalLineTable]
    ) -> Journal:
        """Konversi ORM ke domain Journal."""
        journal_lines = []
        for line in lines:
            journal_lines.append(
                JournalLine(
                    account_id=line.account_code,  # ORM tidak punya account_id, pakai code
                    account_code=line.account_code,
                    debit_amount=line.debit_amount or Decimal(0),
                    credit_amount=line.credit_amount or Decimal(0),
                    description=line.description,
                    cost_center=line.cost_center,
                    department_id=line.department,  # string, bukan UUID
                    project_id=None,  # tidak ada project_id di ORM
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

        journal_type_map = {t.value: t for t in JournalType}
        journal_type = journal_type_map.get(
            getattr(header, "journal_type", None), JournalType.GENERAL
        )

        return Journal(
            id=header.id,
            voucher_number=header.voucher_number,
            journal_type=journal_type,
            status=status,
            journal_date=header.journal_date,
            posting_date=header.posted_at.date() if header.posted_at else None,
            period_id=header.period_id if hasattr(header, "period_id") else UUID(int=0),
            legal_entity_id=header.legal_entity_id,
            description=header.description or "",
            lines=journal_lines,
            total_debit=header.total_debit or Decimal(0),
            total_credit=header.total_credit or Decimal(0),
            created_by=header.created_by or UUID(int=0),
            created_at=header.created_at or datetime.now(UTC),
            updated_by=UUID(int=0),  # tidak ada di ORM
            updated_at=header.updated_at or datetime.now(UTC),
            submitted_by=getattr(header, "submitted_by", None),
            submitted_at=getattr(header, "submitted_at", None),
            approved_by=header.approved_by,
            approved_at=header.approved_at,
            posted_by=header.posted_by,
            posted_at=header.posted_at,
            reversed_by=header.reversed_by,
            reversed_at=header.reversed_at,
            reversed_journal_id=header.reversed_journal_id,
            original_journal_id=header.original_journal_id,
            cancellation_reason=getattr(header, "cancellation_reason", None),
            attachment_ids=getattr(header, "attachment_ids", None) or [],
            version=header.version or 1,
            reference_number=header.reference_number,
            source_type=getattr(header, "source_type", "manual"),
            source_id=getattr(header, "source_id", None),
            notes=getattr(header, "notes", None),
            is_locked=getattr(header, "is_locked", False),
            created_by_name=getattr(header, "created_by_name", None),
            approved_by_name=getattr(header, "approved_by_name", None),
            posted_by_name=getattr(header, "posted_by_name", None),
            rejected_by=getattr(header, "rejected_by", None),
            rejected_at=getattr(header, "rejected_at", None),
            rejection_reason=getattr(header, "rejection_reason", None),
            reversal_reason=getattr(header, "reversal_reason", None),
            cancelled_by=getattr(header, "cancelled_by", None),
            cancelled_at=getattr(header, "cancelled_at", None),
        )

    async def _to_orm_header(self, journal: Journal) -> JournalHeaderTable:
        """Konversi domain Journal ke ORM Header."""
        posted_at = None
        if journal.posting_date:
            posted_at = datetime.combine(journal.posting_date, datetime.min.time(), tzinfo=UTC)

        return JournalHeaderTable(
            id=journal.id,
            voucher_number=journal.voucher_number,
            journal_date=journal.journal_date,
            posted_at=posted_at,
            description=journal.description,
            status=journal.status.value,
            legal_entity_id=journal.legal_entity_id,
            period_id=journal.period_id,
            total_debit=journal.total_debit,
            total_credit=journal.total_credit,
            created_by=journal.created_by,
            created_at=journal.created_at,
            updated_at=datetime.now(UTC),
            approved_by=journal.approved_by,
            approved_at=journal.approved_at,
            posted_by=journal.posted_by,
            reversed_by=journal.reversed_by,
            reversed_at=journal.reversed_at,
            original_journal_id=journal.original_journal_id,
            reversed_journal_id=journal.reversed_journal_id,
            version=journal.version + 1,
            journal_type=journal.journal_type.value if journal.journal_type else "general",
            reference_number=journal.reference_number,
            source_type=journal.source_type or "manual",
            source_id=journal.source_id,
            notes=journal.notes,
            attachment_ids=journal.attachment_ids or [],
            is_locked=journal.is_locked,
            created_by_name=journal.created_by_name,
            approved_by_name=journal.approved_by_name,
            posted_by_name=journal.posted_by_name,
            submitted_by=journal.submitted_by,
            submitted_at=journal.submitted_at,
            rejected_by=journal.rejected_by,
            rejected_at=journal.rejected_at,
            rejection_reason=journal.rejection_reason,
            reversal_reason=journal.reversal_reason,
            cancelled_by=journal.cancelled_by,
            cancelled_at=journal.cancelled_at,
            cancellation_reason=journal.cancellation_reason,
        )

    async def _to_orm_lines(self, journal: Journal) -> list[JournalLineTable]:
        """Konversi domain Journal lines ke ORM Lines.

        BUGFIX: baris sebelumnya selalu memakai `id=UUID(int=0)` untuk SEMUA
        baris — artinya jurnal dengan lebih dari satu baris akan tabrakan
        primary key (baris kedua akan gagal INSERT atau, lebih buruk,
        menimpa baris pertama tergantung strategi flush). Sekarang setiap
        baris mendapat `uuid4()` baru.

        SNAPSHOT: `account_name`, `account_type_snapshot`, dan
        `normal_balance_snapshot` diisi dari kondisi akun SAAT INI di COA,
        satu query untuk semua baris (hindari N+1). Ini "membekukan" atribut
        akun pada momen jurnal dibuat, supaya laporan historis tidak
        berubah kalau akun diedit belakangan — lihat catatan di
        journal_line_table.py.
        """
        from infrastructure.persistence_orm.account_table import AccountTable

        session = await self._get_session()
        account_codes = list({line.account_code for line in journal.lines})
        account_info: dict[str, tuple[str, str, str]] = {}
        if account_codes:
            result = await session.execute(
                select(
                    AccountTable.account_code,
                    AccountTable.account_name,
                    AccountTable.account_type,
                    AccountTable.normal_balance,
                ).where(
                    AccountTable.legal_entity_id == journal.legal_entity_id,
                    AccountTable.account_code.in_(account_codes),
                )
            )
            for code, name, acc_type, normal_balance in result.all():
                account_info[code] = (name, acc_type, normal_balance)

        lines = []
        for i, line in enumerate(journal.lines):
            snap_name, snap_type, snap_normal_balance = account_info.get(
                line.account_code, (None, None, None)
            )
            lines.append(
                JournalLineTable(
                    id=uuid4(),
                    journal_id=journal.id,
                    line_number=i + 1,
                    account_code=line.account_code,
                    debit_amount=line.debit_amount,
                    credit_amount=line.credit_amount,
                    description=line.description,
                    cost_center=line.cost_center,
                    department=line.department_id,  # ORM pakai string, simpan sebagai string
                    legal_entity_id=journal.legal_entity_id,
                    created_at=datetime.now(UTC),
                    account_name=snap_name,
                    account_type_snapshot=snap_type,
                    normal_balance_snapshot=snap_normal_balance,
                    # currency, audit_metadata tidak diisi di sini (di luar cakupan perbaikan ini)
                )
            )
        return lines

    # ========================================================================
    # CRUD (sesuai port)
    # ========================================================================

    async def save(self, journal: Journal) -> None:
        existing = await self.get_by_id(journal.id)
        if existing:
            await self.update(journal)
        else:
            await self.add(journal)

    async def add(self, journal: Journal) -> None:
        session = await self._get_session()
        try:
            exists = await self.exists_by_voucher_number(journal.voucher_number)
            if exists:
                raise DuplicateJournalNumberError(
                    f"Journal number {journal.voucher_number} already exists"
                )

            header = await self._to_orm_header(journal)
            lines = await self._to_orm_lines(journal)

            session.add(header)
            for line in lines:
                session.add(line)

            await session.flush()
            logger.info(f"Journal added: {journal.voucher_number}")

        except IntegrityError as e:
            await session.rollback()
            raise DuplicateJournalNumberError(
                f"Duplicate journal number: {journal.voucher_number}"
            ) from e
        except DuplicateJournalNumberError:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to add journal: {e}")
            raise JournalRepositoryError(f"Failed to add journal: {e}") from e

    async def update(self, journal: Journal) -> None:
        session = await self._get_session()
        try:
            stmt = select(JournalHeaderTable.version).where(
                JournalHeaderTable.id == journal.id
            )
            result = await session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise JournalNotFoundError(f"Journal {journal.id} not found")
            if current_version != journal.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {journal.version}, got {current_version}"
                )

            header = await self._to_orm_header(journal)
            header.version = journal.version + 1
            header.updated_at = datetime.now(UTC)

            await session.merge(header)

            await session.execute(
                delete(JournalLineTable).where(
                    JournalLineTable.journal_id == journal.id
                )
            )
            lines = await self._to_orm_lines(journal)
            for line in lines:
                session.add(line)

            await session.flush()
            logger.info(f"Journal updated: {journal.voucher_number}")

        except (JournalNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to update journal {journal.id}: {e}")
            raise JournalRepositoryError(f"Failed to update journal: {e}") from e

    async def delete(self, journal_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        session = await self._get_session()
        try:
            async with session.begin():
                stmt_lock = select(JournalHeaderTable).where(
                    JournalHeaderTable.id == journal_id
                ).with_for_update()
                result = await session.execute(stmt_lock)
                header = result.scalar_one_or_none()
                if not header:
                    return False

                if header.status != JournalStatus.DRAFT.value:
                    raise ValueError(
                        f"Only DRAFT journal can be deleted (current status: {header.status})"
                    )

                if permanent:
                    await session.execute(
                        delete(JournalLineTable).where(
                            JournalLineTable.journal_id == journal_id
                        )
                    )
                    await session.delete(header)
                else:
                    header.deleted_at = datetime.now(UTC)
                    header.status = JournalStatus.CANCELLED.value
                    header.updated_at = datetime.now(UTC)
                    header.version = (header.version or 0) + 1

                await session.flush()
                logger.info(f"Journal {journal_id} deleted by {user_id} (permanent={permanent})")
                return True

        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to delete journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to delete journal: {e}") from e

    # ========================================================================
    # QUERY (sesuai port)
    # ========================================================================

    async def get_by_id(self, journal_id: UUID) -> Journal | None:
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.id == journal_id,
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

    async def get_by_voucher_number(self, voucher_number: str) -> Journal | None:
        session = await self._get_session()
        try:
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.voucher_number == voucher_number,
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

    async def exists_by_voucher_number(self, voucher_number: str) -> bool:
        session = await self._get_session()
        try:
            stmt = (
                select(func.count())
                .select_from(JournalHeaderTable)
                .where(
                    JournalHeaderTable.voucher_number == voucher_number,
                    JournalHeaderTable.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            logger.error(f"Failed to check journal number {voucher_number}: {e}")
            raise JournalRepositoryError(f"Failed to check journal: {e}") from e

    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
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
    ) -> list[Journal]:
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
        self, period_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        session = await self._get_session()
        try:
            if not hasattr(JournalHeaderTable, "period_id"):
                logger.warning("period_id not supported in ORM schema")
                return []
            stmt = (
                select(JournalHeaderTable)
                .where(
                    JournalHeaderTable.period_id == period_id,
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
            logger.error(f"Failed to find journals by period {period_id}: {e}")
            raise JournalRepositoryError(f"Failed to find journals: {e}") from e

    async def find_by_date_range(
        self,
        start_date: date,
        end_date: date,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Journal]:
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

    async def find_by_account(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Journal]:
        session = await self._get_session()
        try:
            # ORM menggunakan account_code, bukan account_id
            subq = (
                select(JournalLineTable.account_code)
                .where(JournalLineTable.account_code == account_id)
                .distinct()
                .subquery()
            )
            stmt = (
                select(JournalHeaderTable)
                .join(subq, JournalHeaderTable.id == subq.c.journal_id)
                .where(
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
            return [self._to_domain(h, h.lines) for h in headers]
        except Exception as e:
            logger.error(f"Failed to find journals by account {account_id}: {e}")
            raise JournalRepositoryError(f"Failed to find journals by account: {e}") from e

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[Journal]:
        return await self.find_by_status(JournalStatus.SUBMITTED, legal_entity_id)

    async def list(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        journal_type: str | None = None,
        source_type: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        journal_number: str | None = None,
        reference_number: str | None = None,
        account_code: str | None = None,
        created_by: UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> JournalListResult:
        """List jurnal dengan filter dan paginasi (dipakai endpoint GET /journals)."""
        session = await self._get_session()
        try:
            conditions = [
                JournalHeaderTable.legal_entity_id == legal_entity_id,
                JournalHeaderTable.deleted_at.is_(None),
            ]
            if status:
                conditions.append(JournalHeaderTable.status == status)
            if journal_type:
                conditions.append(JournalHeaderTable.journal_type == journal_type)
            if source_type:
                conditions.append(JournalHeaderTable.source_type == source_type)
            if start_date:
                start_date_only = start_date.date() if hasattr(start_date, "date") else start_date
                conditions.append(JournalHeaderTable.journal_date >= start_date_only)
            if end_date:
                end_date_only = end_date.date() if hasattr(end_date, "date") else end_date
                conditions.append(JournalHeaderTable.journal_date <= end_date_only)
            if journal_number:
                conditions.append(JournalHeaderTable.voucher_number.ilike(f"%{journal_number}%"))
            if reference_number:
                conditions.append(JournalHeaderTable.reference_number.ilike(f"%{reference_number}%"))
            if created_by:
                conditions.append(JournalHeaderTable.created_by == created_by)

            base_query = select(JournalHeaderTable).where(*conditions)

            if account_code:
                account_journal_ids = (
                    select(JournalLineTable.journal_id)
                    .where(JournalLineTable.account_code == account_code)
                    .distinct()
                    .subquery()
                )
                base_query = base_query.join(
                    account_journal_ids,
                    JournalHeaderTable.id == account_journal_ids.c.journal_id,
                )

            base_query_subq = base_query.subquery()

            count_stmt = select(func.count()).select_from(base_query_subq)
            total = (await session.execute(count_stmt)).scalar() or 0

            sum_stmt = select(
                func.coalesce(func.sum(base_query_subq.c.total_debit), 0),
                func.coalesce(func.sum(base_query_subq.c.total_credit), 0),
            )
            sum_debit, sum_credit = (await session.execute(sum_stmt)).one()

            page = max(page, 1)
            page_size = max(min(page_size, 200), 1)

            stmt = (
                base_query.order_by(desc(JournalHeaderTable.journal_date), desc(JournalHeaderTable.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .options(selectinload(JournalHeaderTable.lines))
            )
            result = await session.execute(stmt)
            headers = result.scalars().unique().all()

            items = [self._to_domain(h, h.lines) for h in headers]

            return JournalListResult(
                items=items,
                total=total,
                total_debit=Decimal(str(sum_debit)),
                total_credit=Decimal(str(sum_credit)),
            )
        except Exception as e:
            logger.error(f"Failed to list journals: {e}")
            raise JournalRepositoryError(f"Failed to list journals: {e}") from e

    # ========================================================================
    # WORKFLOW (sesuai port)
    # ========================================================================

    async def submit(self, journal_id: UUID, user_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(
                    JournalHeaderTable.id == journal_id,
                    JournalHeaderTable.status == JournalStatus.DRAFT.value,
                )
                .values(
                    status=JournalStatus.SUBMITTED.value,
                    submitted_by=user_id,       # kolom ini ADA di JournalHeaderTable?
                    submitted_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            await session.flush()
            return result.rowcount > 0
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to submit journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to submit journal: {e}") from e

    async def approve(self, journal_id: UUID, approver_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(
                    JournalHeaderTable.id == journal_id,
                    JournalHeaderTable.status == JournalStatus.SUBMITTED.value,
                )
                .values(
                    status=JournalStatus.APPROVED.value,
                    approved_by=approver_id,
                    approved_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            await session.flush()
            return result.rowcount > 0
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to approve journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to approve journal: {e}") from e

    async def post(self, journal_id: UUID, user_id: UUID) -> bool:
        session = await self._get_session()
        try:
            stmt = (
                update(JournalHeaderTable)
                .where(
                    JournalHeaderTable.id == journal_id,
                    JournalHeaderTable.status == JournalStatus.APPROVED.value,
                )
                .values(
                    status=JournalStatus.POSTED.value,
                    posted_by=user_id,
                    posted_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            await session.flush()
            return result.rowcount > 0
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to post journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to post journal: {e}") from e

    async def reverse(
        self, journal_id: UUID, user_id: UUID, reversal_date: date, reason: str
    ) -> Journal | None:
        session = await self._get_session()
        try:
            original = await self.get_by_id(journal_id)
            if not original:
                raise JournalNotFoundError(f"Journal {journal_id} not found")
            if original.status != JournalStatus.POSTED:
                raise ValueError("Only POSTED journal can be reversed")
            if original.reversed_journal_id:
                raise ValueError("Journal already reversed")

            reversal_lines = []
            for line in original.lines:
                reversal_lines.append(
                    JournalLine(
                        account_id=line.account_id,
                        account_code=line.account_code,
                        debit_amount=line.credit_amount,
                        credit_amount=line.debit_amount,
                        description=f"Reversal of {original.voucher_number}: {line.description}",
                        cost_center=line.cost_center,
                        department_id=line.department_id,
                        project_id=line.project_id,
                    )
                )

            reversal_journal = Journal(
                id=UUID(int=0),
                voucher_number=f"REV-{original.voucher_number}",
                journal_type=original.journal_type,
                status=JournalStatus.DRAFT,
                journal_date=reversal_date,
                posting_date=None,
                period_id=original.period_id,
                legal_entity_id=original.legal_entity_id,
                description=f"Reversal of {original.voucher_number}: {reason}",
                lines=reversal_lines,
                total_debit=original.total_credit,
                total_credit=original.total_debit,
                created_by=user_id,
                created_at=datetime.now(UTC),
                updated_by=user_id,
                updated_at=datetime.now(UTC),
                submitted_by=None,
                submitted_at=None,
                approved_by=None,
                approved_at=None,
                posted_by=None,
                posted_at=None,
                reversed_by=None,
                reversed_at=None,
                reversed_journal_id=None,
                original_journal_id=journal_id,
                cancellation_reason=reason,
                attachment_ids=[],
                version=1,
            )

            await self.add(reversal_journal)

            stmt = (
                update(JournalHeaderTable)
                .where(JournalHeaderTable.id == journal_id)
                .values(
                    status=JournalStatus.REVERSED.value,
                    reversed_by=user_id,
                    reversed_at=datetime.now(UTC),
                    reversed_journal_id=reversal_journal.id,
                    updated_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            await session.flush()

            if result.rowcount == 0:
                raise JournalRepositoryError(f"Failed to update original journal {journal_id}")

            logger.info(f"Journal {journal_id} reversed by {user_id}, reversal id: {reversal_journal.id}")
            return reversal_journal

        except ValueError:
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to reverse journal {journal_id}: {e}")
            raise JournalRepositoryError(f"Failed to reverse journal: {e}") from e

    # ========================================================================
    # EXPORT / IMPORT (sesuai port)
    # ========================================================================

    async def export_to_csv(self, legal_entity_id: UUID) -> str:
        journals = await self.get_all(legal_entity_id, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "voucher_number", "journal_date", "type", "status", "description",
            "total_debit", "total_credit", "account_code", "debit", "credit"
        ])
        for j in journals:
            for line in j.lines:
                writer.writerow([
                    j.voucher_number,
                    j.journal_date.isoformat(),
                    j.journal_type.value,
                    j.status.value,
                    j.description,
                    str(j.total_debit),
                    str(j.total_credit),
                    line.account_code,
                    str(line.debit_amount),
                    str(line.credit_amount),
                ])
        return output.getvalue()

    async def import_from_csv(
        self, csv_content: str, legal_entity_id: UUID, period_id: UUID, user_id: UUID
    ) -> int:
        logger.warning("import_from_csv not fully implemented")
        return 0

    # ========================================================================
    # STATISTICS & AUDIT (sesuai port)
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        session = await self._get_session()
        try:
            total = await self.count(legal_entity_id)
            by_status = {}
            for status in JournalStatus:
                count = await self.count(legal_entity_id, status=status)
                by_status[status.value] = count
            return {
                "total": total,
                "by_status": by_status,
                "legal_entity_id": str(legal_entity_id),
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            raise JournalRepositoryError(f"Failed to get statistics: {e}") from e

    async def count(
        self,
        legal_entity_id: UUID,
        status: JournalStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        session = await self._get_session()
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

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return [
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "get_audit_log",
                "message": "Audit log not implemented",
            }
        ]

    async def health_check(self) -> dict[str, Any]:
        try:
            session = await self._get_session()
            await session.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "connected"}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}


SQLAlchemyJournalRepositoryImpl = SQLAlchemyJournalRepository

__all__ = [
    "DuplicateJournalNumberError",
    "JournalNotFoundError",
    "JournalRepositoryError",
    "OptimisticLockError",
    "SQLAlchemyJournalRepository",
    "SQLAlchemyJournalRepositoryImpl",
]
