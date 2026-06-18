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
