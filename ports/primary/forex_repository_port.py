#!/usr/bin/env python3
"""
Module: forex_repository_port.py
Layer: 7 - Ports / Primary
Responsibility: Port untuk repository foreign exchange (forex).

Mendefinisikan kontrak untuk:
- Menyimpan dan mengambil kurs (exchange rates)
- Revaluasi mata uang asing
- Saldo akun dalam mata uang asing
- Penutupan periode forex
"""

from __future__ import annotations

import abc
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


class ExchangeRateEntity:
    """Entity untuk kurs mata uang."""

    def __init__(
        self,
        id: UUID,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        rate_date: date,
        source: str = "BI",
        created_at: datetime | None = None,
    ):
        self.id = id
        self.from_currency = from_currency
        self.to_currency = to_currency
        self.rate = rate
        self.rate_date = rate_date
        self.source = source
        self.created_at = created_at or datetime.utcnow()


class RevaluationRecord:
    """Record hasil revaluasi."""

    def __init__(
        self,
        id: UUID,
        legal_entity_id: UUID,
        account_code: str,
        currency: str,
        as_of_date: date,
        balance_fcy: Decimal,
        rate_used: Decimal,
        old_idr: Decimal,
        new_idr: Decimal,
        difference: Decimal,
        description: str,
        created_at: datetime | None = None,
    ):
        self.id = id
        self.legal_entity_id = legal_entity_id
        self.account_code = account_code
        self.currency = currency
        self.as_of_date = as_of_date
        self.balance_fcy = balance_fcy
        self.rate_used = rate_used
        self.old_idr = old_idr
        self.new_idr = new_idr
        self.difference = difference
        self.description = description
        self.created_at = created_at or datetime.utcnow()


class ForexRepositoryPort(abc.ABC):
    """
    Port untuk repository forex.
    Semua method harus diimplementasikan oleh adapter konkret.
    """

    # --------------------------------------------------------------------
    # Exchange Rate Operations
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def get_rate(
        self, from_currency: str, to_currency: str, rate_date: date
    ) -> ExchangeRateEntity | None:
        """Dapatkan kurs pada tanggal tertentu."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_latest_rate_before(
        self, from_currency: str, to_currency: str, rate_date: date
    ) -> ExchangeRateEntity | None:
        """Dapatkan kurs terakhir sebelum tanggal tertentu."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_rates_in_period(
        self, from_currency: str, to_currency: str, start_date: date, end_date: date
    ) -> list[ExchangeRateEntity]:
        """Dapatkan semua kurs dalam rentang tanggal."""
        raise NotImplementedError

    @abc.abstractmethod
    async def save_rate(self, rate: ExchangeRateEntity) -> None:
        """Simpan kurs baru."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Revaluation Operations
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def save_revaluation(self, record: RevaluationRecord) -> None:
        """Simpan record revaluasi."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_last_revaluation_rate(
        self, legal_entity_id: UUID, account_code: str, currency: str
    ) -> ExchangeRateEntity | None:
        """Dapatkan kurs terakhir yang digunakan untuk revaluasi akun tertentu."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_foreign_currency_balances(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """
        Dapatkan semua akun yang memiliki saldo dalam mata uang asing.
        Return list of dict: {'account_code', 'currency', 'balance_fcy'}
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def get_unrealized_differences(
        self, legal_entity_id: UUID, period_id: UUID
    ) -> list[dict[str, Any]]:
        """Dapatkan selisih kurs unrealized untuk suatu periode."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Period Management
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def mark_period_closed(self, legal_entity_id: UUID, period_id: UUID) -> None:
        """Tandai periode forex sebagai tertutup."""
        raise NotImplementedError

    @abc.abstractmethod
    async def is_period_closed(self, legal_entity_id: UUID, period_id: UUID) -> bool:
        """Cek apakah periode forex sudah tertutup."""
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Exchange Rate CRUD lengkap (dict-based - dipakai ForexService untuk
    # list/create/get/update/deactivate/lock/unlock, beda dari
    # get_rate/save_rate di atas yang cuma pakai ExchangeRateEntity minim
    # dan dipakai jalur revaluasi/konversi lama).
    # --------------------------------------------------------------------
    @abc.abstractmethod
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
        raise NotImplementedError

    @abc.abstractmethod
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
        raise NotImplementedError

    @abc.abstractmethod
    async def get_rate_by_id_full(self, rate_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        raise NotImplementedError

    @abc.abstractmethod
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
        raise NotImplementedError

    @abc.abstractmethod
    async def deactivate_rate_full(
        self, rate_id: UUID, legal_entity_id: UUID, reason: str, deactivated_by: UUID | None
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def set_rate_lock(
        self, rate_id: UUID, legal_entity_id: UUID, is_locked: bool, actor_id: UUID | None
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    # --------------------------------------------------------------------
    # Currency Master (sebelumnya di-hardcode sebagai Python Enum
    # CurrencyCode - lihat migrasi
    # b2c3d4e5f6a7_add_fx_booking_rate_and_currency_master.py)
    # --------------------------------------------------------------------
    @abc.abstractmethod
    async def create_currency(
        self,
        code: str,
        name: str,
        symbol: str | None,
        decimal_places: int,
        created_by: UUID | None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    async def list_currencies(self, is_active: bool | None = True) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_currency_by_code(self, code: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def deactivate_currency(self, code: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_currency_exposure_from_journal(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """
        Agregat per currency dari journal_line yang currency != IDR, sampai
        as_of_date: total fc_amount, total nilai IDR yang dibukukan
        (fc_amount * booking_rate per baris), jumlah baris yang punya data
        booking_rate lengkap vs yang tidak (baris lama sebelum migrasi
        b2c3d4e5f6a7 tidak punya booking_rate/fc_amount, dikecualikan).
        """
        raise NotImplementedError



class ForexRepositoryPortProtocol(Protocol):
    """Protocol version for structural typing."""

    async def get_rate(
        self, from_currency: str, to_currency: str, rate_date: date
    ) -> ExchangeRateEntity | None: ...
    async def get_latest_rate_before(
        self, from_currency: str, to_currency: str, rate_date: date
    ) -> ExchangeRateEntity | None: ...
    async def get_rates_in_period(
        self, from_currency: str, to_currency: str, start_date: date, end_date: date
    ) -> list[ExchangeRateEntity]: ...
    async def save_rate(self, rate: ExchangeRateEntity) -> None: ...
    async def save_revaluation(self, record: RevaluationRecord) -> None: ...
    async def get_last_revaluation_rate(
        self, legal_entity_id: UUID, account_code: str, currency: str
    ) -> ExchangeRateEntity | None: ...
    async def get_foreign_currency_balances(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict[str, Any]]: ...
    async def get_unrealized_differences(
        self, legal_entity_id: UUID, period_id: UUID
    ) -> list[dict[str, Any]]: ...
    async def mark_period_closed(self, legal_entity_id: UUID, period_id: UUID) -> None: ...
    async def is_period_closed(self, legal_entity_id: UUID, period_id: UUID) -> bool: ...


__all__ = [
    "ExchangeRateEntity",
    "ForexRepositoryPort",
    "ForexRepositoryPortProtocol",
    "RevaluationRecord",
]
