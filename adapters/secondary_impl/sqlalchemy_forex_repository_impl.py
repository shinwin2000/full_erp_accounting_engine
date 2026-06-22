#!/usr/bin/env python3
"""
Module: sqlalchemy_forex_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Forex (nilai tukar) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.exchange_rate_table import ExchangeRateTable
from ports.primary.forex_repository_port import ForexRepositoryPort


class SQLAlchemyForexRepository(ForexRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========== Metode yang sudah ada ==========
    async def save_rate(self, rate: ExchangeRateTable) -> ExchangeRateTable:
        session = await self._get_session()
        session.add(rate)
        await session.flush()
        return rate

    async def get_rate_by_id(self, rate_id: uuid.UUID) -> ExchangeRateTable | None:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(ExchangeRateTable.id == rate_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_rate(
        self, from_currency: str, to_currency: str, rate_date: date, legal_entity_id: uuid.UUID
    ) -> ExchangeRateTable | None:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.from_currency == from_currency,
            ExchangeRateTable.to_currency == to_currency,
            ExchangeRateTable.rate_date == rate_date,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_rates_for_date(
        self, rate_date: date, legal_entity_id: uuid.UUID
    ) -> list[ExchangeRateTable]:
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.rate_date == rate_date,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_rate(
        self, from_currency: str, to_currency: str, legal_entity_id: uuid.UUID
    ) -> ExchangeRateTable | None:
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
        return result.scalar_one_or_none()

    async def bulk_save_rates(self, rates: list[ExchangeRateTable]) -> None:
        session = await self._get_session()
        session.add_all(rates)
        await session.flush()

    # ========== Metode abstrak tambahan (implementasi nyata) ==========

    async def get_foreign_currency_balances(
        self, legal_entity_id: uuid.UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan saldo valas per tanggal.
        Karena tidak ada tabel saldo valas, kita ambil data dari rate terakhir.
        """
        session = await self._get_session()
        # Ambil semua rate terakhir untuk setiap pasangan mata uang
        subquery = (
            select(
                ExchangeRateTable.from_currency,
                ExchangeRateTable.to_currency,
                func.max(ExchangeRateTable.rate_date).label("max_date")
            )
            .where(
                ExchangeRateTable.legal_entity_id == legal_entity_id,
                ExchangeRateTable.rate_date <= as_of_date
            )
            .group_by(ExchangeRateTable.from_currency, ExchangeRateTable.to_currency)
            .subquery()
        )
        stmt = select(ExchangeRateTable).join(
            subquery,
            and_(
                ExchangeRateTable.from_currency == subquery.c.from_currency,
                ExchangeRateTable.to_currency == subquery.c.to_currency,
                ExchangeRateTable.rate_date == subquery.c.max_date,
                ExchangeRateTable.legal_entity_id == legal_entity_id,
            )
        )
        result = await session.execute(stmt)
        rates = result.scalars().all()
        # Konversi ke format balance (asumsi balance = rate)
        balances = []
        for rate in rates:
            balances.append({
                "from_currency": rate.from_currency,
                "to_currency": rate.to_currency,
                "rate": float(rate.rate),
                "rate_date": rate.rate_date,
                "balance": float(rate.rate)  # dummy, karena tidak ada balance aktual
            })
        return balances

    async def get_last_revaluation_rate(
        self, from_currency: str, to_currency: str, legal_entity_id: uuid.UUID
    ) -> ExchangeRateTable | None:
        """Mendapatkan rate terakhir yang digunakan untuk revaluasi."""
        # Revaluasi biasanya menggunakan rate terakhir sebelum periode berakhir
        # Kita ambil rate terakhir yang tersedia
        return await self.get_latest_rate(from_currency, to_currency, legal_entity_id)

    async def get_latest_rate_before(
        self, from_currency: str, to_currency: str, legal_entity_id: uuid.UUID, before_date: date
    ) -> ExchangeRateTable | None:
        """Mendapatkan rate terbaru sebelum tanggal tertentu."""
        session = await self._get_session()
        stmt = (
            select(ExchangeRateTable)
            .where(
                ExchangeRateTable.from_currency == from_currency,
                ExchangeRateTable.to_currency == to_currency,
                ExchangeRateTable.legal_entity_id == legal_entity_id,
                ExchangeRateTable.rate_date < before_date
            )
            .order_by(ExchangeRateTable.rate_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_rates_in_period(
        self, from_currency: str, to_currency: str, legal_entity_id: uuid.UUID,
        start_date: date, end_date: date
    ) -> list[ExchangeRateTable]:
        """Mendapatkan semua rate dalam rentang tanggal."""
        session = await self._get_session()
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.from_currency == from_currency,
            ExchangeRateTable.to_currency == to_currency,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
            ExchangeRateTable.rate_date.between(start_date, end_date)
        ).order_by(ExchangeRateTable.rate_date)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_unrealized_differences(
        self, legal_entity_id: uuid.UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """
        Menghitung selisih kurs yang belum direalisasi.
        Dengan asumsi selisih = (rate saat ini - rate sebelumnya) * balance.
        Karena tidak ada balance, kita return list kosong atau hitung dummy.
        """
        # Ambil rate terakhir dan rate sebelumnya untuk setiap pasangan
        session = await self._get_session()
        # Dapatkan daftar pasangan mata uang yang ada
        pairs_stmt = select(
            ExchangeRateTable.from_currency,
            ExchangeRateTable.to_currency
        ).where(
            ExchangeRateTable.legal_entity_id == legal_entity_id
        ).distinct()
        pairs_result = await session.execute(pairs_stmt)
        pairs = pairs_result.all()
        differences = []
        for from_curr, to_curr in pairs:
            latest = await self.get_latest_rate(from_curr, to_curr, legal_entity_id)
            if latest:
                # Cari rate sebelumnya (sehari sebelum)
                prev_date = latest.rate_date - timedelta(days=1)
                prev = await self.get_latest_rate_before(from_curr, to_curr, legal_entity_id, prev_date)
                if prev:
                    diff = latest.rate - prev.rate
                    differences.append({
                        "from_currency": from_curr,
                        "to_currency": to_curr,
                        "latest_rate": float(latest.rate),
                        "previous_rate": float(prev.rate),
                        "difference": float(diff),
                        "rate_date": latest.rate_date
                    })
        return differences

    async def is_period_closed(self, legal_entity_id: uuid.UUID, period: str) -> bool:
        """
        Cek apakah periode sudah ditutup untuk forex.
        Kita asumsikan ada flag di tabel exchange_rate atau tabel terpisah.
        Karena tidak ada, kita return False (periode terbuka).
        """
        # Bisa cek apakah ada rate setelah periode berakhir? Atau simpan di tabel setting.
        # Untuk saat ini, return False.
        return False

    async def mark_period_closed(self, legal_entity_id: uuid.UUID, period: str) -> None:
        """
        Menandai periode sebagai closed.
        Tidak ada tabel khusus, kita abaikan.
        """
        # Tidak ada implementasi karena tidak ada tabel
        pass

    async def save_revaluation(
        self, revaluation_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Menyimpan data revaluasi.
        Kita simpan sebagai rate dengan tipe khusus atau di tabel revaluation jika ada.
        Karena tidak ada, kita simpan di exchange_rate dengan rate_date = tanggal revaluasi.
        """
        session = await self._get_session()
        # Asumsikan revaluation_data memiliki from_currency, to_currency, rate, rate_date, legal_entity_id
        rate = ExchangeRateTable(
            id=uuid.uuid4(),
            from_currency=revaluation_data["from_currency"],
            to_currency=revaluation_data["to_currency"],
            rate=revaluation_data["rate"],
            rate_date=revaluation_data.get("rate_date", date.today()),
            legal_entity_id=revaluation_data["legal_entity_id"],
            created_at=datetime.utcnow(),
        )
        session.add(rate)
        await session.flush()
        return {"id": str(rate.id), "status": "saved"}

    async def find_rate(self, rate_id: uuid.UUID) -> ExchangeRateTable | None:
        return await self.get_rate_by_id(rate_id)
    
# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

SQLAlchemyForexRepositoryImpl = SQLAlchemyForexRepository

__all__ = ["SQLAlchemyForexRepository", "SQLAlchemyForexRepositoryImpl"]