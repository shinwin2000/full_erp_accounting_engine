#!/usr/bin/env python3
"""
Module: sqlalchemy_forex_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Forex (nilai tukar) menggunakan SQLAlchemy.
Perbaikan:
  - [FIX] AccountTable.currency → currency_code
  - [FIX] AccountTable.balance dihapus (tidak ada di model)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Numeric,
    String,
    Text,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.forex_repository_port import (
    ExchangeRateEntity,
    ForexRepositoryPort,
    RevaluationRecord,
)

# CATATAN PENTING: ExchangeRateTable REAL (dipakai migrasi & seluruh app)
# ada di infrastructure.persistence_orm.exchange_rate_table, tabelnya
# "exchange_rate" (tunggal). Sebelumnya file ini mendeklarasikan model ORM
# DUPLIKAT secara lokal (declarative_base() sendiri, __tablename__ =
# "exchange_rates" - JAMAK) yang TIDAK PERNAH dibuat oleh migrasi manapun -
# setiap query lewat model duplikat itu akan gagal "relation exchange_rates
# does not exist" begitu benar-benar dieksekusi. Sekarang pakai model asli.
from infrastructure.persistence_orm.exchange_rate_table import ExchangeRateTable

logger = logging.getLogger(__name__)

# ============================================================================
# ORM MODELS (RevaluationRecordTable & PeriodStatusTable MASIH lokal/belum
# pernah di-migrasi - lihat catatan di save_revaluation/mark_period_closed/
# is_period_closed/get_last_revaluation_rate/get_foreign_currency_balances/
# get_unrealized_differences di bawah. Di luar scope perbaikan CRUD
# exchange rate kali ini; method2 itu akan tetap gagal kalau dipanggil.)
# ============================================================================

Base = declarative_base()


class RevaluationRecordTable(Base):
    __tablename__ = "revaluation_records"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    account_code = Column(String(50), nullable=False)
    currency = Column(String(3), nullable=False)
    as_of_date = Column(Date, nullable=False)
    balance_fcy = Column(Numeric(20, 2), nullable=False)
    rate_used = Column(Numeric(20, 6), nullable=False)
    old_idr = Column(Numeric(20, 2), nullable=False)
    new_idr = Column(Numeric(20, 2), nullable=False)
    difference = Column(Numeric(20, 2), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)


class PeriodStatusTable(Base):
    __tablename__ = "forex_period_status"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_id = Column(String(50), nullable=False)  # e.g., "2024-01"
    is_closed = Column(Boolean, default=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by = Column(PGUUID(as_uuid=True), nullable=True)


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================

class SQLAlchemyForexRepository(ForexRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    @property
    def legal_entity_id(self) -> UUID | None:
        return self._legal_entity_id

    @legal_entity_id.setter
    def legal_entity_id(self, value: UUID) -> None:
        """
        CATATAN: repo ini didaftarkan sebagai singleton di IoC container
        (satu instance untuk seumur hidup aplikasi), sedangkan
        legal_entity_id itu per-request. Tanpa setter ini, legal_entity_id
        cuma bisa diisi lewat konstruktor sekali di awal - method manapun
        yang mengandalkan self._get_legal_entity_id() (get_rate, set_rate,
        get_last_revaluation_rate, dll) akan selalu ValueError "not set" di
        request kedua dan seterusnya. Service (ForexService.set_context)
        HARUS memanggil ini di awal setiap request.
        """
        self._legal_entity_id = value

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            # FIX: get_async_session() itu AsyncGenerator (dipakai via
            # `async with`/`async for`, mis. sebagai FastAPI dependency),
            # BUKAN sesuatu yang bisa langsung di-`await` untuk dapat
            # AsyncSession - itu penyebab "TypeError: object async_generator
            # can't be used in 'await' expression". get_async_session_direct()
            # memang didesain untuk kasus repo yang mengelola session sendiri
            # seperti di sini.
            from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct
            self._session = await get_async_session_direct()
        return self._session

    async def commit(self) -> None:
        """
        Commit session yang dipegang repo ini.

        CATATAN BUG (sama persis dengan yang sudah diperbaiki di
        service_iam.py & service_consolidation.py): ForexService dulunya
        selalu manggil self.uow.commit() langsung, padahal self.uow
        (UnitOfWorkPort) di service ini TIDAK PERNAH di-`begin()`/dimasuki
        lewat `async with self.uow:` - jadi commit() selalu raise "UoW not
        started or transaction not active". Repo ini sudah mengelola
        session-nya sendiri secara lazy (_get_session), jadi commit
        langsung lewat session itu, bukan lewat UoW yang tidak pernah aktif.
        """
        if self._session is not None:
            await self._session.commit()

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========================================================================
    # MAPPING: ORM ↔ Domain
    # ========================================================================

    def _to_domain_rate(self, table: ExchangeRateTable) -> ExchangeRateEntity:
        return ExchangeRateEntity(
            id=table.id,
            from_currency=table.from_currency,
            to_currency=table.to_currency,
            rate=table.rate,
            rate_date=table.rate_date,
            source=table.source or "BI",
            created_at=table.created_at,
        )

    def _from_domain_rate(self, entity: ExchangeRateEntity) -> ExchangeRateTable:
        return ExchangeRateTable(
            id=entity.id,
            from_currency=entity.from_currency,
            to_currency=entity.to_currency,
            rate=entity.rate,
            rate_date=entity.rate_date,
            source=entity.source,
            legal_entity_id=self._get_legal_entity_id(),
            created_at=entity.created_at or datetime.utcnow(),
        )

    def _to_domain_revaluation(self, table: RevaluationRecordTable) -> RevaluationRecord:
        return RevaluationRecord(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            account_code=table.account_code,
            currency=table.currency,
            as_of_date=table.as_of_date,
            balance_fcy=table.balance_fcy,
            rate_used=table.rate_used,
            old_idr=table.old_idr,
            new_idr=table.new_idr,
            difference=table.difference,
            description=table.description,
            created_at=table.created_at,
        )

    # ========================================================================
    # PORT METHODS (signature sesuai port)
    # ========================================================================

    async def get_rate(
        self, from_currency: str, to_currency: str, rate_date: date
    ) -> ExchangeRateEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.from_currency == from_currency,
            ExchangeRateTable.to_currency == to_currency,
            ExchangeRateTable.rate_date == rate_date,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain_rate(table)

    async def get_latest_rate_before(
        self, from_currency: str, to_currency: str, rate_date: date
    ) -> ExchangeRateEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(ExchangeRateTable)
            .where(
                ExchangeRateTable.from_currency == from_currency,
                ExchangeRateTable.to_currency == to_currency,
                ExchangeRateTable.legal_entity_id == legal_entity_id,
                ExchangeRateTable.rate_date < rate_date,
            )
            .order_by(ExchangeRateTable.rate_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain_rate(table)

    async def get_rates_in_period(
        self, from_currency: str, to_currency: str, start_date: date, end_date: date
    ) -> list[ExchangeRateEntity]:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.from_currency == from_currency,
            ExchangeRateTable.to_currency == to_currency,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
            ExchangeRateTable.rate_date.between(start_date, end_date),
        ).order_by(ExchangeRateTable.rate_date)
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain_rate(t) for t in tables]

    async def save_rate(self, rate: ExchangeRateEntity) -> None:
        session = await self._get_session()
        table = self._from_domain_rate(rate)
        existing = await session.execute(
            select(ExchangeRateTable).where(ExchangeRateTable.id == rate.id)
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row:
            for key, value in table.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing_row, key, value)
            existing_row.updated_at = datetime.utcnow()
        else:
            session.add(table)
        await session.flush()

    async def save_revaluation(self, record: RevaluationRecord) -> None:
        session = await self._get_session()
        table = RevaluationRecordTable(
            id=record.id,
            legal_entity_id=record.legal_entity_id,
            account_code=record.account_code,
            currency=record.currency,
            as_of_date=record.as_of_date,
            balance_fcy=record.balance_fcy,
            rate_used=record.rate_used,
            old_idr=record.old_idr,
            new_idr=record.new_idr,
            difference=record.difference,
            description=record.description,
            created_at=record.created_at or datetime.utcnow(),
        )
        existing = await session.execute(
            select(RevaluationRecordTable).where(RevaluationRecordTable.id == record.id)
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row:
            for key, value in table.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing_row, key, value)
        else:
            session.add(table)
        await session.flush()

    async def get_last_revaluation_rate(
        self, legal_entity_id: UUID, account_code: str, currency: str
    ) -> ExchangeRateEntity | None:
        """Ambil rate terakhir yang digunakan untuk revaluasi akun tertentu."""
        session = await self._get_session()
        stmt = (
            select(RevaluationRecordTable)
            .where(
                RevaluationRecordTable.legal_entity_id == legal_entity_id,
                RevaluationRecordTable.account_code == account_code,
                RevaluationRecordTable.currency == currency,
            )
            .order_by(RevaluationRecordTable.as_of_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None
        rate = await self.get_rate(record.currency, "IDR", record.as_of_date)
        if not rate:
            return ExchangeRateEntity(
                id=uuid.uuid4(),
                from_currency=record.currency,
                to_currency="IDR",
                rate=record.rate_used,
                rate_date=record.as_of_date,
                source="Revaluation",
            )
        return rate

    async def get_foreign_currency_balances(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """
        Dapatkan semua akun yang memiliki mata uang asing.
        PERBAIKAN: gunakan currency_code, hapus filter balance (tidak ada di model).
        """
        session = await self._get_session()
        try:
            from infrastructure.persistence_orm.account_table import AccountTable
            stmt = select(AccountTable.account_code, AccountTable.currency_code).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.currency_code != "IDR",
            )
            result = await session.execute(stmt)
            rows = result.all()
            balances = []
            for row in rows:
                # Untuk balance_fcy, perlu dihitung dari ledger entries.
                # Sebagai fallback, kita set 0 dan serahkan ke pemanggil untuk mengisi.
                balances.append({
                    "account_code": row.account_code,
                    "currency": row.currency_code,
                    "balance_fcy": Decimal(0),
                })
            return balances
        except ImportError:
            logger.warning("AccountTable not available, returning empty foreign currency balances")
            return []

    async def get_unrealized_differences(
        self, legal_entity_id: UUID, period_id: UUID
    ) -> list[dict[str, Any]]:
        """Dapatkan selisih kurs unrealized untuk suatu periode."""
        session = await self._get_session()
        stmt = select(RevaluationRecordTable).where(
            RevaluationRecordTable.legal_entity_id == legal_entity_id,
            RevaluationRecordTable.difference != 0,
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        differences = []
        for rec in records:
            differences.append({
                "account_code": rec.account_code,
                "currency": rec.currency,
                "as_of_date": rec.as_of_date,
                "balance_fcy": float(rec.balance_fcy),
                "rate_used": float(rec.rate_used),
                "difference": float(rec.difference),
            })
        return differences

    async def mark_period_closed(self, legal_entity_id: UUID, period_id: UUID) -> None:
        """Tandai periode forex sebagai tertutup."""
        session = await self._get_session()
        period_str = str(period_id)
        stmt = select(PeriodStatusTable).where(
            PeriodStatusTable.legal_entity_id == legal_entity_id,
            PeriodStatusTable.period_id == period_str,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.is_closed = True
            existing.closed_at = datetime.utcnow()
        else:
            new_status = PeriodStatusTable(
                id=uuid.uuid4(),
                legal_entity_id=legal_entity_id,
                period_id=period_str,
                is_closed=True,
                closed_at=datetime.utcnow(),
            )
            session.add(new_status)
        await session.flush()

    async def is_period_closed(self, legal_entity_id: UUID, period_id: UUID) -> bool:
        """Cek apakah periode forex sudah tertutup."""
        session = await self._get_session()
        period_str = str(period_id)
        stmt = select(PeriodStatusTable).where(
            PeriodStatusTable.legal_entity_id == legal_entity_id,
            PeriodStatusTable.period_id == period_str,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return row.is_closed if row else False

    # ========================================================================
    # INTERNAL/LEGACY METHODS (untuk kompatibilitas)
    # ========================================================================

    async def get_rate_by_id(self, rate_id: UUID) -> ExchangeRateEntity | None:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(ExchangeRateTable.id == rate_id)
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain_rate(table)

    async def get_latest_rate(
        self, from_currency: str, to_currency: str
    ) -> ExchangeRateEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(ExchangeRateTable)
            .where(
                ExchangeRateTable.from_currency == from_currency,
                ExchangeRateTable.to_currency == to_currency,
                ExchangeRateTable.legal_entity_id == legal_entity_id,
            )
            .order_by(ExchangeRateTable.rate_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain_rate(table)

    async def bulk_save_rates(self, rates: list[ExchangeRateEntity]) -> None:
        session = await self._get_session()
        for rate in rates:
            table = self._from_domain_rate(rate)
            session.add(table)
        await session.flush()

    async def find_rate(self, rate_id: UUID) -> ExchangeRateEntity | None:
        return await self.get_rate_by_id(rate_id)

    # ========================================================================
    # EXCHANGE RATE CRUD LENGKAP (dict-based - dipakai ForexService)
    # ========================================================================

    async def create_rate_full(
        self,
        legal_entity_id: UUID,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        rate_type: str,
        effective_date: date,
        provider: str,
        bid_rate: Decimal | None,
        ask_rate: Decimal | None,
        notes: str | None,
        created_by: UUID | None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        table = ExchangeRateTable(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            rate_type=rate_type,
            rate_date=effective_date,
            source=provider,
            bid_rate=bid_rate if bid_rate is not None else Decimal("0"),
            ask_rate=ask_rate if ask_rate is not None else Decimal("0"),
            notes=notes,
            status="active",
            is_active=True,
            created_by=created_by,
            version=1,
        )
        session.add(table)
        await session.flush()
        await session.refresh(table)
        return table.to_dict()

    async def list_rates_full(
        self,
        legal_entity_id: UUID,
        from_currency: str | None = None,
        to_currency: str | None = None,
        rate_type: str | None = None,
        effective_date: date | None = None,
        provider: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.legal_entity_id == legal_entity_id,
            ExchangeRateTable.deleted_at.is_(None),
        )
        if from_currency:
            stmt = stmt.where(ExchangeRateTable.from_currency == from_currency)
        if to_currency:
            stmt = stmt.where(ExchangeRateTable.to_currency == to_currency)
        if rate_type:
            stmt = stmt.where(ExchangeRateTable.rate_type == rate_type)
        if effective_date:
            stmt = stmt.where(ExchangeRateTable.rate_date == effective_date)
        if provider:
            stmt = stmt.where(ExchangeRateTable.source == provider)
        stmt = (
            stmt.order_by(ExchangeRateTable.rate_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def get_rate_by_id_full(self, rate_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.id == rate_id,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
            ExchangeRateTable.deleted_at.is_(None),
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return row.to_dict() if row else None

    async def update_rate_full(
        self,
        rate_id: UUID,
        legal_entity_id: UUID,
        rate: Decimal | None = None,
        bid_rate: Decimal | None = None,
        ask_rate: Decimal | None = None,
        provider: str | None = None,
        notes: str | None = None,
        status: str | None = None,
        updated_by: UUID | None = None,
    ) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.id == rate_id,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
            ExchangeRateTable.deleted_at.is_(None),
        ).with_for_update()
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        if row.is_locked:
            raise ValueError(f"Exchange rate {rate_id} is locked and cannot be updated")
        if rate is not None:
            row.rate = rate
        if bid_rate is not None:
            row.bid_rate = bid_rate
        if ask_rate is not None:
            row.ask_rate = ask_rate
        if provider is not None:
            row.source = provider
        if notes is not None:
            row.notes = notes
        if status is not None:
            row.status = status
            row.is_active = status == "active"
        row.updated_by = updated_by
        await session.flush()
        await session.refresh(row)
        return row.to_dict()

    async def deactivate_rate_full(
        self, rate_id: UUID, legal_entity_id: UUID, reason: str, deactivated_by: UUID | None
    ) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.id == rate_id,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
            ExchangeRateTable.deleted_at.is_(None),
        ).with_for_update()
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        row.deactivate()
        row.status = "inactive"
        if reason:
            row.notes = f"{row.notes or ''}\n[deactivated: {reason}]".strip()
        row.updated_by = deactivated_by
        await session.flush()
        await session.refresh(row)
        return row.to_dict()

    async def set_rate_lock(
        self, rate_id: UUID, legal_entity_id: UUID, is_locked: bool, actor_id: UUID | None
    ) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.id == rate_id,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
            ExchangeRateTable.deleted_at.is_(None),
        ).with_for_update()
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return None
        row.is_locked = is_locked
        row.locked_by = actor_id if is_locked else None
        row.locked_at = datetime.utcnow() if is_locked else None
        await session.flush()
        await session.refresh(row)
        return row.to_dict()


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemyForexRepositoryImpl = SQLAlchemyForexRepository

__all__ = ["SQLAlchemyForexRepository", "SQLAlchemyForexRepositoryImpl"]
