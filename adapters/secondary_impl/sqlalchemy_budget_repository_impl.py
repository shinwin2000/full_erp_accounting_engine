#!/usr/bin/env python3
"""
Module: sqlalchemy_budget_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Budget (anggaran) menggunakan SQLAlchemy.
Perbaikan:
  - [FIX] Race condition pada update dan update_budget_amount dengan pessimistic locking.
  - [FIX] get_budget_by_account menggunakan join dengan BudgetLineTable karena account_code ada di line, bukan header.
  - [FIX] update_budget_amount tidak lagi mengakses field amount yang tidak ada di header; sekarang raise NotImplementedError.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.budget_revision_history_table import BudgetRevisionHistoryTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable

from infrastructure.persistence_orm.budget_table import BudgetLineTable, BudgetTable
from infrastructure.telemetry import get_logger
from ports.primary.budget_repository_port import (
    BudgetEntity,
    BudgetLineEntity,
    BudgetRepositoryPort,
)

logger = get_logger(__name__)


class SQLAlchemyBudgetRepository(BudgetRepositoryPort):
    """Implementasi BudgetRepositoryPort dengan SQLAlchemy."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========================================================================
    # MAPPING HELPERS
    # ========================================================================

    def _entity_to_orm_header(self, entity: BudgetEntity) -> BudgetTable:
        return BudgetTable(
            id=entity.id,
            legal_entity_id=entity.legal_entity_id,
            budget_code=entity.budget_code,
            budget_name=entity.budget_name,
            budget_type=entity.budget_type,
            fiscal_year=entity.fiscal_year,
            period=entity.period,
            # [FIX] entity.version adalah label string budget (mis. "1.0"),
            # HARUS dipetakan ke kolom version_label -- bukan ke kolom
            # `version` milik VersionMixin (Integer, optimistic-lock counter,
            # yang bukan tanggung jawab repository untuk di-set manual).
            version_label=entity.version,
            version=entity.version_number,
            status=entity.status,
            effective_date=entity.effective_date,
            expiry_date=entity.expiry_date,
            currency=entity.currency,
            is_locked=entity.is_locked,
            notes=entity.notes,
            description=entity.description,
            tags=entity.tags,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            created_by=entity.created_by,
            updated_by=entity.updated_by,
            approved_at=entity.approved_at,
            approved_by=entity.approved_by,
            submitted_at=entity.submitted_at,
            submitted_by=entity.submitted_by,
            rejected_at=entity.rejected_at,
            rejected_by=entity.rejected_by,
            rejection_reason=entity.rejection_reason,
        )

    def _orm_header_to_entity(self, header: BudgetTable, lines: list[BudgetLineTable]) -> BudgetEntity:
        return BudgetEntity(
            id=header.id,
            legal_entity_id=header.legal_entity_id,
            budget_code=header.budget_code,
            budget_name=header.budget_name,
            budget_type=header.budget_type,
            fiscal_year=header.fiscal_year,
            period=header.period,
            # [FIX] Sebelumnya membaca kolom `version` (Integer, optimistic-lock
            # counter VersionMixin) ke field string `version`, dan menduplikasi
            # nilai yang sama ke version_number. Yang benar: label string dari
            # version_label, dan counter integer dari version.
            version=header.version_label,
            status=header.status,
            effective_date=header.effective_date,
            expiry_date=header.expiry_date,
            currency=header.currency,
            total_amount=sum(line.amount for line in lines),
            notes=header.notes,
            description=header.description,
            tags=header.tags,
            is_locked=header.is_locked,
            created_at=header.created_at,
            updated_at=header.updated_at,
            created_by=header.created_by,
            updated_by=header.updated_by,
            approved_at=header.approved_at,
            approved_by=header.approved_by,
            submitted_at=header.submitted_at,
            submitted_by=header.submitted_by,
            rejected_at=header.rejected_at,
            rejected_by=header.rejected_by,
            rejection_reason=header.rejection_reason,
            version_number=header.version,
            lines=[
                BudgetLineEntity(
                    id=line.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                )
                for line in lines
            ],
        )

    def _line_entity_to_orm(self, entity: BudgetLineEntity, budget_id: UUID) -> BudgetLineTable:
        return BudgetLineTable(
            id=entity.id,
            budget_id=budget_id,
            account_id=entity.account_id,
            account_code=entity.account_code,
            amount=entity.amount,
            note=entity.note,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    async def _log_audit(self, action: str, budget_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "budget_id": str(budget_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    async def _record_revision_history(self, budget: BudgetEntity, change_type: str) -> None:
        """
        [FITUR] Tulis satu snapshot ringkas ke `budget_revision_history`
        setiap kali budget dibuat/diperbarui, supaya tab "Versi Budget"
        punya riwayat sungguhan untuk ditampilkan (sebelumnya endpoint ini
        tidak ada sama sekali, dan tidak ada mekanisme persisten apapun
        yang menyimpan histori perubahan budget).
        """
        session = await self._get_session()
        changed_by = (
            budget.updated_by or budget.submitted_by or budget.approved_by
            or budget.rejected_by or budget.created_by
        )
        session.add(
            BudgetRevisionHistoryTable(
                id=uuid4(),
                budget_id=budget.id,
                legal_entity_id=budget.legal_entity_id,
                budget_code=budget.budget_code,
                version_label=budget.version,
                version_number=budget.version_number,
                status=budget.status,
                total_amount=budget.total_amount,
                effective_date=budget.effective_date,
                change_type=change_type,
                changed_by=changed_by,
                changed_at=datetime.utcnow(),
            )
        )
        await session.flush()

    async def get_revision_history(
        self, legal_entity_id: UUID, budget_code: str
    ) -> list[dict[str, Any]]:
        """[FITUR] Ambil riwayat versi budget untuk tab 'Versi Budget'."""
        session = await self._get_session()
        stmt = (
            select(BudgetRevisionHistoryTable)
            .where(
                BudgetRevisionHistoryTable.legal_entity_id == legal_entity_id,
                BudgetRevisionHistoryTable.budget_code == budget_code,
            )
            .order_by(BudgetRevisionHistoryTable.changed_at.desc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "version": row.version_label,
                "version_number": row.version_number,
                "status": row.status,
                "total_amount": str(row.total_amount),
                "effective_date": row.effective_date.isoformat(),
                "change_type": row.change_type,
                "changed_by": str(row.changed_by) if row.changed_by else None,
                "changed_at": row.changed_at.isoformat(),
            }
            for row in rows
        ]

    # ========================================================================
    # CRUD METHODS (dari port)
    # ========================================================================

    async def save(self, budget: BudgetEntity) -> None:
        """Simpan budget baru."""
        session = await self._get_session()
        header = self._entity_to_orm_header(budget)
        session.add(header)
        for line in budget.lines:
            line_orm = self._line_entity_to_orm(line, budget.id)
            session.add(line_orm)
        await session.flush()
        await self._record_revision_history(budget, "CREATE")
        await self._log_audit("SAVE", budget.id, {"budget_code": budget.budget_code})
        logger.info(f"Budget saved: {budget.budget_code}")

    async def update(self, budget: BudgetEntity) -> None:
        """Update budget yang sudah ada (dengan pessimistic locking)."""
        session = await self._get_session()
        # [FIX] Session ini request-scoped (dipakai bersama sepanjang satu
        # request lewat `get_async_session()`), dan AsyncSession SQLAlchemy
        # otomatis "autobegin" transaksi begitu statement pertama dijalankan
        # (mis. `get_by_id` yang dipanggil `_get_aggregate()` sebelum
        # `update()` ini). `async with session.begin():` di sini mencoba
        # memulai transaksi BARU di atas transaksi yang sudah otomatis aktif
        # -> selalu meledak "A transaction is already begun on this Session"
        # begitu update dipanggil dalam request yang sebelumnya sudah
        # membaca data lain lewat session yang sama (yang mana SELALU
        # terjadi, karena workflow update/submit/approve/dst. semuanya
        # baca dulu lewat `_get_aggregate()` sebelum menulis). Perbaikan:
        # jangan buka transaksi baru -- langsung pakai transaksi yang sudah
        # otomatis aktif, sama seperti pola yang dipakai `save()`. Commit
        # sesungguhnya tetap ditangani oleh `get_async_session()` di akhir
        # request.
        # Lock header untuk mencegah race condition
        stmt = select(BudgetTable).where(BudgetTable.id == budget.id).with_for_update()
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            raise ValueError(f"Budget {budget.id} not found")

        # Update header fields
        header.budget_code = budget.budget_code
        header.budget_name = budget.budget_name
        header.budget_type = budget.budget_type
        header.fiscal_year = budget.fiscal_year
        header.period = budget.period
        # [FIX] Baris ini sebelumnya menulis label string ke kolom
        # `version` (int, langsung ditimpa oleh baris di bawah), dan
        # `version_label` tidak pernah di-update sama sekali.
        header.version_label = budget.version
        header.status = budget.status
        header.effective_date = budget.effective_date
        header.expiry_date = budget.expiry_date
        header.currency = budget.currency
        header.is_locked = budget.is_locked
        header.notes = budget.notes
        header.description = budget.description
        header.tags = budget.tags
        header.updated_at = budget.updated_at
        header.updated_by = budget.updated_by
        header.approved_at = budget.approved_at
        header.approved_by = budget.approved_by
        header.submitted_at = budget.submitted_at
        header.submitted_by = budget.submitted_by
        header.rejected_at = budget.rejected_at
        header.rejected_by = budget.rejected_by
        header.rejection_reason = budget.rejection_reason
        header.version = budget.version_number

        # Update lines: delete old, insert new
        await session.execute(
            BudgetLineTable.__table__.delete().where(BudgetLineTable.budget_id == budget.id)
        )
        for line in budget.lines:
            line_orm = self._line_entity_to_orm(line, budget.id)
            session.add(line_orm)

        await session.flush()
        await self._record_revision_history(budget, f"UPDATE ({budget.status})")
        await self._log_audit("UPDATE", budget.id, {"budget_code": budget.budget_code})
        logger.info(f"Budget updated: {budget.budget_code}")

    # ========================================================================
    # [FITUR] REALISASI (ACTUAL) DARI GENERAL LEDGER
    # ========================================================================
    # Sebelumnya `get_budget_alerts()` dan `get_budget_vs_actual()` di
    # service layer selalu hardcode `actual = Decimal(0)` (placeholder,
    # komentar aslinya: "Ganti dengan query nyata"). Method ini
    # menggantikannya dengan query sungguhan ke `ledger_entry` (tabel yang
    # benar-benar diisi oleh posting jurnal -- `general_ledger_table.py`
    # ternyata tidak dipakai di manapun / tabel yatim, jadi TIDAK dipakai
    # di sini).
    #
    # Arah (sign) realisasi disesuaikan dengan `normal_balance` akun
    # (debit/credit) dari `AccountTable`, supaya akun expense (normal
    # debit) dan akun revenue (normal credit) sama-sama menghasilkan angka
    # "realisasi" yang position (bukan negatif) ketika aktivitasnya sesuai
    # arah normalnya.
    async def get_actual_amounts_by_account(
        self,
        legal_entity_id: UUID,
        account_ids: list[UUID],
        fiscal_year: int,
        period_month: int,
        ytd: bool = False,
    ) -> dict[UUID, Decimal]:
        """
        Hitung realisasi (actual) per account_id dari `ledger_entry` yang
        sudah diposting, untuk satu bulan (`ytd=False`) atau akumulasi
        Januari..`period_month` (`ytd=True`) pada `fiscal_year` tertentu.

        Return dict {account_id: Decimal} -- account yang tidak punya
        aktivitas sama sekali tidak akan muncul sebagai key (biarkan
        caller default-kan ke 0).
        """
        if not account_ids:
            return {}

        period_filter = (
            LedgerEntryTable.period_month <= period_month
            if ytd
            else LedgerEntryTable.period_month == period_month
        )
        stmt = (
            select(
                LedgerEntryTable.account_id,
                AccountTable.normal_balance,
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("total_credit"),
            )
            .join(AccountTable, AccountTable.id == LedgerEntryTable.account_id)
            .where(
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.account_id.in_(account_ids),
                LedgerEntryTable.fiscal_year == fiscal_year,
                period_filter,
            )
            .group_by(LedgerEntryTable.account_id, AccountTable.normal_balance)
        )
        session = await self._get_session()
        rows = (await session.execute(stmt)).all()

        actuals: dict[UUID, Decimal] = {}
        for account_id, normal_balance, total_debit, total_credit in rows:
            total_debit = Decimal(str(total_debit))
            total_credit = Decimal(str(total_credit))
            if normal_balance == "debit":
                actuals[account_id] = total_debit - total_credit
            else:
                actuals[account_id] = total_credit - total_debit
        return actuals

    async def get_by_id(self, budget_id: UUID) -> BudgetEntity | None:
        """Ambil budget berdasarkan ID."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(BudgetTable.id == budget_id, BudgetTable.deleted_at.is_(None))
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            return None

        lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == budget_id)
        lines_result = await session.execute(lines_stmt)
        lines = lines_result.scalars().all()

        return self._orm_header_to_entity(header, lines)

    async def get_by_code_and_year(
        self, legal_entity_id: UUID, budget_code: str, fiscal_year: int
    ) -> BudgetEntity | None:
        """Ambil budget berdasarkan kode dan tahun fiskal."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.budget_code == budget_code,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            return None

        lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == header.id)
        lines_result = await session.execute(lines_stmt)
        lines = lines_result.scalars().all()

        return self._orm_header_to_entity(header, lines)

    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> BudgetEntity | None:
        """Ambil budget berdasarkan nama dan tahun fiskal."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.budget_name == budget_name,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            return None

        lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == header.id)
        lines_result = await session.execute(lines_stmt)
        lines = lines_result.scalars().all()

        return self._orm_header_to_entity(header, lines)

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None, status: str | None = None
    ) -> list[BudgetEntity]:
        """Daftar budget untuk entitas legal."""
        session = await self._get_session()
        conditions = [
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.deleted_at.is_(None),
        ]
        if fiscal_year:
            conditions.append(BudgetTable.fiscal_year == fiscal_year)
        if status:
            conditions.append(BudgetTable.status == status)

        stmt = select(BudgetTable).where(and_(*conditions)).order_by(BudgetTable.created_at.desc())
        result = await session.execute(stmt)
        headers = result.scalars().all()

        entities = []
        for header in headers:
            lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == header.id)
            lines_result = await session.execute(lines_stmt)
            lines = lines_result.scalars().all()
            entities.append(self._orm_header_to_entity(header, lines))

        return entities

    async def get_last_budget_code(self, legal_entity_id: UUID) -> str | None:
        """Dapatkan kode budget terakhir yang digunakan."""
        session = await self._get_session()
        stmt = select(BudgetTable.budget_code).where(
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.deleted_at.is_(None),
        ).order_by(BudgetTable.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, budget_id: UUID) -> bool:
        """Hapus budget (soft delete)."""
        session = await self._get_session()
        # [FIX] Sama seperti `update()` -- jangan buka transaksi baru di atas
        # transaksi yang sudah autobegin pada session request-scoped ini.
        stmt = select(BudgetTable).where(BudgetTable.id == budget_id).with_for_update()
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            return False

        header.deleted_at = datetime.utcnow()
        await session.flush()
        await self._log_audit("DELETE", budget_id, {})
        logger.info(f"Budget {budget_id} soft deleted")
        return True

    # ========================================================================
    # METODE TAMBAHAN (untuk kompatibilitas dengan kode lama)
    # ========================================================================

    async def save_budget(self, budget: BudgetTable) -> BudgetTable:
        """Simpan budget ORM langsung (untuk kompatibilitas)."""
        session = await self._get_session()
        session.add(budget)
        await session.flush()
        return budget

    async def get_budget_by_id(self, budget_id: UUID) -> BudgetTable | None:
        """Ambil budget ORM langsung (untuk kompatibilitas)."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(BudgetTable.id == budget_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_budgets_by_fiscal_year(self, fiscal_year: int, legal_entity_id: UUID) -> list[BudgetTable]:
        """Ambil budget berdasarkan tahun fiskal (ORM)."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_budget_by_account(self, account_code: str, fiscal_year: int, legal_entity_id: UUID) -> BudgetTable | None:
        """
        Ambil budget berdasarkan akun.
        Perbaikan: menggunakan join dengan BudgetLineTable karena account_code ada di line, bukan header.
        """
        session = await self._get_session()
        stmt = select(BudgetTable).join(
            BudgetLineTable, BudgetLineTable.budget_id == BudgetTable.id
        ).where(
            BudgetLineTable.account_code == account_code,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.deleted_at.is_(None),
        ).distinct()  # Hindari duplikat jika ada multiple lines dengan account_code yang sama
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_budget_amount(self, budget_id: UUID, amount: Decimal) -> None:
        """
        Update amount total budget - tidak didukung karena amount dihitung dari lines.
        Gunakan metode update lines untuk mengubah alokasi.
        """
        raise NotImplementedError(
            "Budget amount is derived from lines; use update lines instead"
        )

    # ========================================================================
    # BUDGET ACTUAL (untuk actual tracking)
    # ========================================================================

    async def save_budget_actual(self, actual: Any) -> Any:
        """Simpan actual budget."""
        session = await self._get_session()
        session.add(actual)
        await session.flush()
        return actual

    async def get_actuals_by_budget(self, budget_id: UUID, from_date: date, to_date: date) -> list[Any]:
        """Ambil actuals berdasarkan budget dan range tanggal."""
        from infrastructure.persistence_orm.budget_actual_table import BudgetActualTable
        session = await self._get_session()
        stmt = select(BudgetActualTable).where(
            BudgetActualTable.budget_id == budget_id,
            BudgetActualTable.transaction_date.between(from_date, to_date)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_actual_for_budget(self, budget_id: UUID) -> Decimal:
        """Total actual untuk budget."""
        from infrastructure.persistence_orm.budget_actual_table import BudgetActualTable
        session = await self._get_session()
        stmt = select(func.sum(BudgetActualTable.amount)).where(BudgetActualTable.budget_id == budget_id)
        result = await session.execute(stmt)
        return result.scalar() or Decimal(0)

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset:offset + limit]


# ============================================================================
# EKSPOR
# ============================================================================

__all__ = ["SQLAlchemyBudgetRepository"]
