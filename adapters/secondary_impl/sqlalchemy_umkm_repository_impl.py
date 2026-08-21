#!/usr/bin/env python3
"""
Module: sqlalchemy_umkm_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository UMKM (simplified accounting) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import logging
import uuid
from calendar import monthrange
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.umkm_business_profile_table import UMKMProfileTable
from infrastructure.persistence_orm.umkm_journal_table import UmkmJournalTable
from infrastructure.persistence_orm.umkm_transaction_table import UMKMTransactionTable
from ports.primary.umkm_repository_port import (
    UMKMJournalEntity,
    UMKMJournalHistoryEntry,
    UMKMRepositoryPort,
    UMKMRevenueSummary,
    UMKMTransactionEntity,
)

logger = logging.getLogger(__name__)


class SQLAlchemyUMKMRepository(UMKMRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        # `session` di sini hanya untuk kasus caller yang SENGAJA ingin
        # mengelola siklus hidup session sendiri (mis. unit test / Unit of
        # Work eksplisit). Untuk pemakaian normal (lewat IoC container),
        # biarkan None.
        self._injected_session = session
        self._legal_entity_id = legal_entity_id

    @asynccontextmanager
    async def _session_scope(self):
        """Selalu membuka AsyncSession BARU per pemanggilan (via
        `get_async_session_direct()`) dan selalu menutupnya di akhir -
        KECUALI session sudah di-inject eksplisit lewat konstruktor, di
        mana lifecycle-nya jadi tanggung jawab caller.

        PENTING (fix 2026-08-18): sebelumnya method ini (`_get_session`)
        meng-cache SATU AsyncSession di `self._session` dan memakainya
        ulang di semua pemanggilan berikutnya. Ini berbahaya karena
        `UMKMRepositoryPort`/`SQLAlchemyUMKMRepository` didaftarkan sebagai
        SINGLETON di IoC container (lihat AdapterRegistry -
        `register_singleton`) - satu AsyncSession yang sama akan dipakai
        bersamaan oleh SEMUA request yang datang selama server hidup.
        `AsyncSession` SQLAlchemy tidak aman dipakai oleh beberapa
        coroutine/request secara bersamaan; ini bisa menyebabkan data salah
        nyasar ke request lain atau error acak di bawah beban. Bug inilah
        juga penyebab error `TypeError: object async_generator can't be
        used in 'await' expression` - `get_async_session()` (tanpa
        `_direct`) adalah FastAPI dependency generator (dipakai lewat
        `Depends(...)`, bukan untuk di-`await` langsung).
        Perbaikannya memakai `get_async_session_direct()`, yang memang
        didesain untuk dipakai oleh repository yang mengurus siklus hidup
        session-nya sendiri - pola yang identik dengan
        SQLAlchemyEmployeeRepository, SQLAlchemyForexRepository,
        SQLAlchemyApprovalRepository, dll.

        Konsekuensi lain: dulu `get_async_session()` (generator FastAPI)
        otomatis commit setelah `yield`. Karena sekarang pakai
        `get_async_session_direct()` (tidak auto-commit), SETIAP method
        yang menulis data WAJIB memanggil `await session.commit()` sendiri
        di titik yang tepat - lihat masing-masing method di bawah.
        """
        if self._injected_session is not None:
            yield self._injected_session
            return

        from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct

        session = await get_async_session_direct()
        try:
            yield session
        finally:
            await session.close()

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    async def _get_profile_id(self, legal_entity_id: UUID) -> UUID | None:
        async with self._session_scope() as session:
            stmt = select(UMKMProfileTable.id).where(UMKMProfileTable.legal_entity_id == legal_entity_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    # ========================================================================
    # MAPPING: ORM ↔ Domain
    # ========================================================================

    def _to_domain_transaction(self, table: UMKMTransactionTable) -> UMKMTransactionEntity:
        return UMKMTransactionEntity(
            id=table.id,
            legal_entity_id=table.legal_entity_id,  # assuming table has legal_entity_id or from profile
            transaction_date=table.transaction_date,
            description=table.description,
            amount=table.amount,
            transaction_type=table.transaction_type,
            category=table.category,
            payment_method=table.payment_method,
            reference_number=table.reference_number,
            attachment_ids=[],
            created_by=table.created_by,
            created_at=table.created_at,
        )

    def _from_domain_transaction(self, entity: UMKMTransactionEntity, profile_id: UUID) -> UMKMTransactionTable:
        return UMKMTransactionTable(
            id=entity.id,
            profile_id=profile_id,
            transaction_date=entity.transaction_date,
            description=entity.description,
            amount=entity.amount,
            transaction_type=entity.transaction_type,
            category=entity.category,
            payment_method=entity.payment_method,
            reference_number=entity.reference_number,
            legal_entity_id=entity.legal_entity_id,
            created_by=entity.created_by,
            created_at=entity.created_at or datetime.utcnow(),
        )

    def _to_domain_summary(self, legal_entity_id: UUID, year: int, month: int, revenue: Decimal, expense: Decimal) -> UMKMRevenueSummary:
        net_income = revenue - expense
        pph_final_due = revenue * Decimal("0.005")  # 0.5%
        # Assume we can check if submitted status from some flag; for now set DRAFT
        return UMKMRevenueSummary(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            year=year,
            month=month,
            total_revenue=revenue,
            total_expenses=expense,
            net_income=net_income,
            pph_final_due=pph_final_due,
            pph_paid=Decimal(0),
            status="DRAFT",
            submitted_at=None,
        )

    def _to_domain_journal(self, table: UmkmJournalTable) -> UMKMJournalEntity:
        return UMKMJournalEntity(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            journal_number=table.journal_number,
            journal_date=table.journal_date,
            description=table.description,
            debit_account_code=table.debit_account_code,
            debit_account_name=table.debit_account_name,
            credit_account_code=table.credit_account_code,
            credit_account_name=table.credit_account_name,
            amount=table.debit_amount,
            status=table.status,
            category=getattr(table, "category", None),
            tax_id=table.tax_id,
            attachment_url=table.attachment_url,
            notes=getattr(table, "notes", None),
            posted_at=getattr(table, "posted_at", None) or table.approved_at,
            posted_by=getattr(table, "posted_by", None) or table.approved_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            updated_by=table.updated_by,
            created_by_name=None,
            version=table.version or 1,
        )

    # ========================================================================
    # SIMPLIFIED JOURNAL (double-entry)
    # ========================================================================

    async def next_journal_number(self, legal_entity_id: UUID, journal_date: date) -> str:
        async with self._session_scope() as session:
            prefix = f"JU-{journal_date.strftime('%Y%m')}"
            stmt = select(func.count()).select_from(UmkmJournalTable).where(
                UmkmJournalTable.legal_entity_id == legal_entity_id,
                UmkmJournalTable.journal_number.like(f"{prefix}-%"),
            )
            result = await session.execute(stmt)
            seq = (result.scalar() or 0) + 1
            return f"{prefix}-{seq:04d}"

    async def create_journal(self, journal: UMKMJournalEntity) -> UMKMJournalEntity:
        async with self._session_scope() as session:
            orm = UmkmJournalTable(
                id=journal.id,
                legal_entity_id=journal.legal_entity_id,
                journal_number=journal.journal_number,
                journal_date=journal.journal_date,
                description=journal.description,
                debit_account_code=journal.debit_account_code,
                debit_account_name=journal.debit_account_name,
                debit_amount=journal.amount,
                credit_account_code=journal.credit_account_code,
                credit_account_name=journal.credit_account_name,
                credit_amount=journal.amount,
                tax_id=journal.tax_id,
                attachment_url=journal.attachment_url,
                category=journal.category,
                notes=journal.notes,
                status=journal.status,
                created_by=journal.created_by,
                version=1,
            )
            session.add(orm)
            await session.flush()
            await session.commit()
            await session.refresh(orm)
            return self._to_domain_journal(orm)

    async def get_journal_by_id(
        self, journal_id: UUID, legal_entity_id: UUID
    ) -> UMKMJournalEntity | None:
        async with self._session_scope() as session:
            stmt = select(UmkmJournalTable).where(
                UmkmJournalTable.id == journal_id,
                UmkmJournalTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_journal(table) if table else None

    async def list_journals(
        self,
        legal_entity_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
        unpaginated: bool = False,
    ) -> tuple[list[UMKMJournalEntity], int]:
        async with self._session_scope() as session:
            conditions = [UmkmJournalTable.legal_entity_id == legal_entity_id]
            if start_date:
                conditions.append(UmkmJournalTable.journal_date >= start_date)
            if end_date:
                conditions.append(UmkmJournalTable.journal_date <= end_date)
            if status:
                conditions.append(UmkmJournalTable.status == status)
            if category:
                conditions.append(UmkmJournalTable.category == category)

            count_stmt = select(func.count()).select_from(UmkmJournalTable).where(*conditions)
            total = (await session.execute(count_stmt)).scalar() or 0

            stmt = select(UmkmJournalTable).where(*conditions).order_by(
                UmkmJournalTable.journal_date.desc(), UmkmJournalTable.created_at.desc()
            )
            if not unpaginated:
                stmt = stmt.limit(page_size).offset((page - 1) * page_size)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_journal(t) for t in tables], total

    async def update_journal(
        self, journal_id: UUID, legal_entity_id: UUID, **fields
    ) -> UMKMJournalEntity | None:
        async with self._session_scope() as session:
            stmt = select(UmkmJournalTable).where(
                UmkmJournalTable.id == journal_id,
                UmkmJournalTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            if table.status != "draft":
                raise ValueError("Only draft journal entries can be updated")

            if "amount" in fields and fields["amount"] is not None:
                table.debit_amount = fields["amount"]
                table.credit_amount = fields["amount"]
            for key in (
                "journal_date", "description", "debit_account_code", "debit_account_name",
                "credit_account_code", "credit_account_name", "tax_id", "attachment_url",
                "category", "notes",
            ):
                if key in fields and fields[key] is not None:
                    setattr(table, key, fields[key])
            if "updated_by" in fields:
                table.updated_by = fields["updated_by"]
            table.updated_at = datetime.utcnow()
            table.version = (table.version or 1) + 1
            await session.flush()
            await session.commit()
            await session.refresh(table)
            return self._to_domain_journal(table)

    async def cancel_journal(
        self, journal_id: UUID, legal_entity_id: UUID, cancelled_by: UUID, reason: str
    ) -> UMKMJournalEntity | None:
        async with self._session_scope() as session:
            stmt = select(UmkmJournalTable).where(
                UmkmJournalTable.id == journal_id,
                UmkmJournalTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            if table.status != "draft":
                raise ValueError("Only draft journal entries can be cancelled")
            table.status = "cancelled"
            table.updated_by = cancelled_by
            table.updated_at = datetime.utcnow()
            note = f"Cancelled: {reason}" if reason else "Cancelled"
            table.notes = f"{table.notes}\n{note}" if getattr(table, "notes", None) else note
            table.version = (table.version or 1) + 1
            await session.flush()
            await session.commit()
            await session.refresh(table)
            return self._to_domain_journal(table)

    async def post_journal(
        self, journal_id: UUID, legal_entity_id: UUID, posted_by: UUID
    ) -> UMKMJournalEntity | None:
        async with self._session_scope() as session:
            stmt = select(UmkmJournalTable).where(
                UmkmJournalTable.id == journal_id,
                UmkmJournalTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            if table.status != "draft":
                raise ValueError("Only draft journal entries can be posted")
            table.status = "posted"
            now = datetime.utcnow()
            table.posted_at = now
            table.posted_by = posted_by
            table.approved_at = now
            table.approved_by = posted_by
            table.updated_by = posted_by
            table.updated_at = now
            table.version = (table.version or 1) + 1
            await session.flush()
            await session.commit()
            await session.refresh(table)
            return self._to_domain_journal(table)

    async def reverse_journal(
        self, journal_id: UUID, legal_entity_id: UUID, reversed_by: UUID, reason: str
    ) -> UMKMJournalEntity | None:
        async with self._session_scope() as session:
            stmt = select(UmkmJournalTable).where(
                UmkmJournalTable.id == journal_id,
                UmkmJournalTable.legal_entity_id == legal_entity_id,
            )
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            if table.status != "posted":
                raise ValueError("Only posted journal entries can be reversed")

            # Buat entri pembalik: debit/kredit ditukar, mengacu ke jurnal asal via notes.
            # Catatan: next_journal_number() membuka session scope-nya sendiri
            # (read-only, SELECT COUNT) - aman dipanggil dari dalam scope ini.
            reversing = UmkmJournalTable(
                id=uuid.uuid4(),
                legal_entity_id=legal_entity_id,
                journal_number=await self.next_journal_number(legal_entity_id, date.today()),
                journal_date=date.today(),
                description=f"Reversal of {table.journal_number}: {reason}",
                debit_account_code=table.credit_account_code,
                debit_account_name=table.credit_account_name,
                debit_amount=table.debit_amount,
                credit_account_code=table.debit_account_code,
                credit_account_name=table.debit_account_name,
                credit_amount=table.credit_amount,
                tax_id=table.tax_id,
                category=table.category,
                notes=f"Reversal of {table.journal_number}. Reason: {reason}",
                status="posted",
                created_by=reversed_by,
                version=1,
            )
            now = datetime.utcnow()
            reversing.posted_at = now
            reversing.posted_by = reversed_by
            reversing.approved_at = now
            reversing.approved_by = reversed_by
            session.add(reversing)

            table.status = "reversed"
            table.updated_by = reversed_by
            table.updated_at = now
            note = f"Reversed by {reversing.journal_number}. Reason: {reason}"
            table.notes = f"{table.notes}\n{note}" if getattr(table, "notes", None) else note
            table.version = (table.version or 1) + 1

            await session.flush()
            await session.commit()
            await session.refresh(table)
            return self._to_domain_journal(table)

    async def get_journal_history(
        self, journal_id: UUID, legal_entity_id: UUID
    ) -> list[UMKMJournalHistoryEntry]:
        journal = await self.get_journal_by_id(journal_id, legal_entity_id)
        if not journal:
            return []
        history: list[UMKMJournalHistoryEntry] = [
            UMKMJournalHistoryEntry(
                timestamp=journal.created_at,
                action="created",
                from_status=None,
                to_status="draft",
                actor_id=journal.created_by,
                reason=None,
                notes="Journal entry created",
            )
        ]
        if journal.status == "posted" and journal.posted_at:
            history.append(
                UMKMJournalHistoryEntry(
                    timestamp=journal.posted_at,
                    action="posted",
                    from_status="draft",
                    to_status="posted",
                    actor_id=journal.posted_by or journal.created_by,
                    notes="Journal entry posted to ledger",
                )
            )
        elif journal.status == "cancelled" and journal.updated_at:
            history.append(
                UMKMJournalHistoryEntry(
                    timestamp=journal.updated_at,
                    action="cancelled",
                    from_status="draft",
                    to_status="cancelled",
                    actor_id=journal.updated_by or journal.created_by,
                    notes=journal.notes,
                )
            )
        elif journal.status == "reversed" and journal.updated_at:
            history.append(
                UMKMJournalHistoryEntry(
                    timestamp=journal.updated_at,
                    action="reversed",
                    from_status="posted",
                    to_status="reversed",
                    actor_id=journal.updated_by or journal.created_by,
                    notes=journal.notes,
                )
            )
        elif journal.updated_at and journal.version > 1:
            history.append(
                UMKMJournalHistoryEntry(
                    timestamp=journal.updated_at,
                    action="updated",
                    from_status="draft",
                    to_status="draft",
                    actor_id=journal.updated_by or journal.created_by,
                    notes="Journal entry updated",
                )
            )
        return history

    # ========================================================================
    # PORT METHODS
    # ========================================================================

    async def save_transaction(self, transaction: UMKMTransactionEntity) -> None:
        profile_id = await self._get_profile_id(transaction.legal_entity_id)
        if not profile_id:
            raise ValueError(f"UMKM profile not found for legal_entity {transaction.legal_entity_id}")
        async with self._session_scope() as session:
            orm = self._from_domain_transaction(transaction, profile_id)
            existing = await session.get(UMKMTransactionTable, transaction.id)
            if existing:
                # Update
                for key, value in orm.__dict__.items():
                    if not key.startswith("_") and key != "id":
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
            else:
                session.add(orm)
            await session.flush()
            await session.commit()

    async def get_transaction(self, transaction_id: UUID) -> UMKMTransactionEntity | None:
        async with self._session_scope() as session:
            stmt = select(UMKMTransactionTable).where(UMKMTransactionTable.id == transaction_id)
            result = await session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return None
            return self._to_domain_transaction(table)

    async def list_transactions_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        transaction_type: str | None = None,
    ) -> list[UMKMTransactionEntity]:
        profile_id = await self._get_profile_id(legal_entity_id)
        if not profile_id:
            return []
        async with self._session_scope() as session:
            stmt = select(UMKMTransactionTable).where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_date.between(from_date, to_date),
            )
            if transaction_type:
                stmt = stmt.where(UMKMTransactionTable.transaction_type == transaction_type)
            stmt = stmt.order_by(UMKMTransactionTable.transaction_date)
            result = await session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_transaction(t) for t in tables]

    async def get_monthly_revenue_summary(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> UMKMRevenueSummary | None:
        profile_id = await self._get_profile_id(legal_entity_id)
        if not profile_id:
            return None
        async with self._session_scope() as session:
            # Get total revenue
            rev_stmt = select(func.coalesce(func.sum(UMKMTransactionTable.amount), 0)).where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_type == "revenue",
                UMKMTransactionTable.transaction_date.between(date(year, month, 1), date(year, month, monthrange(year, month)[1])),
            )
            rev_result = await session.execute(rev_stmt)
            revenue = rev_result.scalar() or Decimal(0)
            # Get total expenses
            exp_stmt = select(func.coalesce(func.sum(UMKMTransactionTable.amount), 0)).where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_type == "expense",
                UMKMTransactionTable.transaction_date.between(date(year, month, 1), date(year, month, monthrange(year, month)[1])),
            )
            exp_result = await session.execute(exp_stmt)
            expense = exp_result.scalar() or Decimal(0)
            return self._to_domain_summary(legal_entity_id, year, month, revenue, expense)

    async def save_revenue_summary(self, summary: UMKMRevenueSummary) -> None:
        # In a real implementation, you would have a table for revenue summaries.
        # Since we don't have one, we just log or store in memory.
        logger.info(f"Saving revenue summary for {summary.year}-{summary.month}: net_income={summary.net_income}")
        # Optionally store in a temporary dict or create table later.

    async def submit_tax_report(
        self, legal_entity_id: UUID, year: int, month: int, submitted_by: UUID
    ) -> None:
        # Mark tax report as submitted. We could store this status in a separate table or update profile.
        logger.info(f"Submitting tax report for {year}-{month} by {submitted_by} for legal_entity {legal_entity_id}")
        # For demo, we could update a status flag on profile or store a submission record.
        # If we had a table for monthly tax submissions, we would insert/update here.
        # For now, just log and maybe set a flag on profile (if we add a field).
        # Since we don't have a field, we'll just pass.
        pass

    async def get_total_revenue_ytd(self, legal_entity_id: UUID, year: int) -> Decimal:
        profile_id = await self._get_profile_id(legal_entity_id)
        if not profile_id:
            return Decimal(0)
        async with self._session_scope() as session:
            stmt = select(func.coalesce(func.sum(UMKMTransactionTable.amount), 0)).where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_type == "revenue",
                UMKMTransactionTable.transaction_date.between(date(year, 1, 1), date(year, 12, 31)),
            )
            result = await session.execute(stmt)
            return result.scalar() or Decimal(0)

    # ========================================================================
    # INTERNAL/LEGACY METHODS (untuk kompatibilitas)
    # ========================================================================

    async def save_profile(self, profile: UMKMProfileTable) -> UMKMProfileTable:
        async with self._session_scope() as session:
            session.add(profile)
            await session.flush()
            await session.commit()
            await session.refresh(profile)
            return profile

    async def get_profile_by_id(self, profile_id: UUID) -> UMKMProfileTable | None:
        async with self._session_scope() as session:
            stmt = select(UMKMProfileTable).where(UMKMProfileTable.id == profile_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_profile_by_legal_entity(self, legal_entity_id: UUID) -> UMKMProfileTable | None:
        async with self._session_scope() as session:
            stmt = select(UMKMProfileTable).where(UMKMProfileTable.legal_entity_id == legal_entity_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_profile_tax_status(self, profile_id: UUID, uses_umkm_tax: bool) -> None:
        """
        Update UMKM tax status with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        async with self._session_scope() as session:
            async with session.begin():
                # 1. Lock the row with SELECT FOR UPDATE
                stmt_lock = select(UMKMProfileTable).where(
                    UMKMProfileTable.id == profile_id
                ).with_for_update()
                result = await session.execute(stmt_lock)
                profile = result.scalar_one_or_none()
                if not profile:
                    raise ValueError(f"UMKM profile {profile_id} not found")

                # 2. Update the locked row
                profile.uses_umkm_tax = uses_umkm_tax
                await session.flush()
                logger.info(f"UMKM profile {profile_id} tax status updated to {uses_umkm_tax}")
            # `session.begin()` di atas sudah commit otomatis saat blok
            # `async with` selesai tanpa exception.

    async def get_transaction_by_id(self, transaction_id: UUID) -> UMKMTransactionTable | None:
        async with self._session_scope() as session:
            stmt = select(UMKMTransactionTable).where(UMKMTransactionTable.id == transaction_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_transactions_by_period(
        self, profile_id: UUID, from_date: date, to_date: date
    ) -> list[UMKMTransactionTable]:
        async with self._session_scope() as session:
            stmt = (
                select(UMKMTransactionTable)
                .where(
                    UMKMTransactionTable.profile_id == profile_id,
                    UMKMTransactionTable.transaction_date.between(from_date, to_date),
                )
                .order_by(UMKMTransactionTable.transaction_date)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_total_revenue_by_period(
        self, profile_id: UUID, from_date: date, to_date: date
    ) -> Decimal:
        async with self._session_scope() as session:
            stmt = select(UMKMTransactionTable.amount).where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_type == "revenue",
                UMKMTransactionTable.transaction_date.between(from_date, to_date),
            )
            result = await session.execute(stmt)
            amounts = result.scalars().all()
            return sum(amounts, Decimal(0))

    async def get_monthly_summary(
        self, profile_id: UUID, year: int, month: int
    ) -> dict[str, Decimal]:
        from_date = date(year, month, 1)
        last_day = monthrange(year, month)[1]
        to_date = date(year, month, last_day)

        revenue = await self.get_total_revenue_by_period(profile_id, from_date, to_date)
        async with self._session_scope() as session:
            stmt = select(UMKMTransactionTable.amount).where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_type == "expense",
                UMKMTransactionTable.transaction_date.between(from_date, to_date),
            )
            result = await session.execute(stmt)
            expenses = result.scalars().all()
            total_expense = sum(expenses, Decimal(0))
            return {"revenue": revenue, "expense": total_expense, "net": revenue - total_expense}


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================
SQLAlchemyUmkmRepository = SQLAlchemyUMKMRepository
SQLAlchemyUmkmRepositoryImpl = SQLAlchemyUMKMRepository

__all__ = [
    "SQLAlchemyUMKMRepository",
    "SQLAlchemyUmkmRepository",
    "SQLAlchemyUmkmRepositoryImpl",
]
