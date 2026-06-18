#!/usr/bin/env python3
"""
Module: effective_date_vo.py
Layer: 5 - Reality, Intent, Causality / Reality
Responsibility: Value object tanggal efektif (kapan dampak ekonomi terjadi).
               Mendefinisikan aturan dan validasi untuk tanggal efektif
               transaksi, termasuk hubungannya dengan tanggal posting,
               periode akuntansi, dan batasan backdating/future dating.

Dependencies:
- standard library (datetime, logging, enum, dataclass, typing)
- kernel.context_holder (get_current_user) [optional]

Audit: Setiap penggunaan tanggal efektif yang tidak biasa dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class EffectiveDateType(Enum):
    """Jenis tanggal efektif."""

    TRANSACTION_DATE = auto()  # Tanggal transaksi terjadi
    RECOGNITION_DATE = auto()  # Tanggal pengakuan akuntansi
    SETTLEMENT_DATE = auto()  # Tanggal settlement (pembayaran)
    DELIVERY_DATE = auto()  # Tanggal penyerahan barang/jasa
    CONTRACT_DATE = auto()  # Tanggal kontrak
    INVOICE_DATE = auto()  # Tanggal faktur
    DUE_DATE = auto()  # Tanggal jatuh tempo
    PERIOD_START = auto()  # Awal periode akuntansi
    PERIOD_END = auto()  # Akhir periode akuntansi


class EffectiveDateConstraint(Enum):
    """Batasan untuk tanggal efektif."""

    NO_CONSTRAINT = auto()  # Tidak ada batasan
    NOT_IN_FUTURE = auto()  # Tidak boleh di masa depan
    NOT_IN_PAST = auto()  # Tidak boleh di masa lalu
    WITHIN_PERIOD = auto()  # Harus dalam periode saat ini
    WITHIN_FISCAL_YEAR = auto()  # Harus dalam tahun fiskal saat ini
    AFTER_LAST_TRANSACTION = auto()  # Harus setelah transaksi terakhir


# === 2. EFFECTIVE DATE VALUE OBJECT ===


@dataclass(frozen=True)
class EffectiveDate:
    """
    Value object untuk tanggal efektif.

    Business context: Tanggal kapan dampak ekonomi suatu transaksi
    benar-benar terjadi. Berbeda dengan tanggal posting yang mencatat
    kapan transaksi dicatat ke sistem.
    """

    date: datetime
    date_type: EffectiveDateType
    source: str  # Sumber tanggal (user_input, system, api, etc.)
    justification: str | None = None

    def __post_init__(self) -> None:
        # Ensure timezone-aware
        if self.date.tzinfo is None:
            object.__setattr__(self, "date", self.date.replace(tzinfo=UTC))
        # Validate source tidak kosong
        if not self.source:
            raise ValueError("Source cannot be empty")

    @classmethod
    def from_user_input(
        cls,
        date_input: datetime,
        date_type: EffectiveDateType,
        justification: str | None = None,
    ) -> EffectiveDate:
        """
        Membuat EffectiveDate dari input user.

        Args:
            date_input: Tanggal dari user
            date_type: Jenis tanggal
            justification: Justifikasi jika tanggal tidak biasa

        Returns:
            EffectiveDate
        """
        return cls(
            date=date_input,
            date_type=date_type,
            source="user_input",
            justification=justification,
        )

    @classmethod
    def from_system(cls, date_type: EffectiveDateType) -> EffectiveDate:
        """
        Membuat EffectiveDate dari sistem (current time).

        Args:
            date_type: Jenis tanggal

        Returns:
            EffectiveDate
        """
        return cls(
            date=datetime.now(UTC),
            date_type=date_type,
            source="system",
        )

    @classmethod
    def from_api(
        cls, date_input: datetime, date_type: EffectiveDateType, source_api: str
    ) -> EffectiveDate:
        """
        Membuat EffectiveDate dari API eksternal.

        Args:
            date_input: Tanggal dari API
            date_type: Jenis tanggal
            source_api: Nama sumber API

        Returns:
            EffectiveDate
        """
        return cls(
            date=date_input,
            date_type=date_type,
            source=f"api:{source_api}",
        )

    def validate(
        self,
        constraint: EffectiveDateConstraint,
        reference_date: datetime | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        fiscal_year_start: datetime | None = None,
        fiscal_year_end: datetime | None = None,
        tolerance_days: int = 7,
    ) -> tuple[bool, str | None]:
        """
        Memvalidasi tanggal efektif terhadap constraint.

        Args:
            constraint: Batasan yang berlaku
            reference_date: Tanggal referensi (default: sekarang)
            period_start: Awal periode akuntansi
            period_end: Akhir periode akuntansi
            fiscal_year_start: Awal tahun fiskal
            fiscal_year_end: Akhir tahun fiskal
            tolerance_days: Toleransi hari untuk backdating/future dating

        Returns:
            (is_valid, message_if_invalid)
        """
        now = reference_date or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        if constraint == EffectiveDateConstraint.NOT_IN_FUTURE:
            if self.date > now:
                days_future = (self.date - now).days
                if days_future > tolerance_days:
                    return (
                        False,
                        f"Effective date {self.date.date()} is {days_future} days in the future (max tolerance {tolerance_days} days)",
                    )
                elif days_future > 0:
                    logger.warning(
                        f"Future effective date within tolerance: {self.date.date()} (source: {self.source})"
                    )

        elif constraint == EffectiveDateConstraint.NOT_IN_PAST:
            if self.date < now:
                days_past = (now - self.date).days
                if days_past > tolerance_days:
                    return (
                        False,
                        f"Effective date {self.date.date()} is {days_past} days in the past (max tolerance {tolerance_days} days)",
                    )
                elif days_past > 0:
                    logger.warning(
                        f"Past effective date within tolerance: {self.date.date()} (source: {self.source})"
                    )

        elif constraint == EffectiveDateConstraint.WITHIN_PERIOD:
            if period_start is None or period_end is None:
                raise ValueError(
                    "period_start and period_end are required for WITHIN_PERIOD constraint"
                )
            if self.date < period_start:
                return (
                    False,
                    f"Effective date {self.date.date()} is before period start {period_start.date()}",
                )
            if self.date > period_end:
                return (
                    False,
                    f"Effective date {self.date.date()} is after period end {period_end.date()}",
                )

        elif constraint == EffectiveDateConstraint.WITHIN_FISCAL_YEAR:
            if fiscal_year_start is None or fiscal_year_end is None:
                raise ValueError(
                    "fiscal_year_start and fiscal_year_end are required for WITHIN_FISCAL_YEAR constraint"
                )
            if self.date < fiscal_year_start:
                return (
                    False,
                    f"Effective date {self.date.date()} is before fiscal year start {fiscal_year_start.date()}",
                )
            if self.date > fiscal_year_end:
                return (
                    False,
                    f"Effective date {self.date.date()} is after fiscal year end {fiscal_year_end.date()}",
                )

        elif constraint == EffectiveDateConstraint.AFTER_LAST_TRANSACTION:
            if reference_date is None:
                raise ValueError("reference_date is required for AFTER_LAST_TRANSACTION constraint")
            if self.date < reference_date:
                days_back = (reference_date - self.date).days
                return (
                    False,
                    f"Effective date {self.date.date()} is before last transaction date {reference_date.date()} (backdated by {days_back} days)",
                )

        return True, None

    def to_period_key(self) -> str:
        """Mengkonversi tanggal ke key periode akuntansi (YYYY-MM)."""
        return self.date.strftime("%Y-%m")

    def to_fiscal_year_key(self) -> str:
        """Mengkonversi tanggal ke key tahun fiskal (YYYY)."""
        return str(self.date.year)

    def to_quarter_key(self) -> str:
        """Mengkonversi tanggal ke key kuartal (YYYY-Q1)."""
        quarter = (self.date.month - 1) // 3 + 1
        return f"{self.date.year}-Q{quarter}"

    def is_weekend(self) -> bool:
        """Memeriksa apakah tanggal efektif jatuh pada weekend."""
        return self.date.weekday() >= 5  # 5=Saturday, 6=Sunday

    def is_public_holiday(self, holiday_calendar: set | None = None) -> bool:
        """Memeriksa apakah tanggal efektif jatuh pada hari libur."""
        if holiday_calendar:
            return self.date.date() in holiday_calendar
        return False

    def adjust_to_business_day(self, holiday_calendar: set | None = None) -> EffectiveDate:
        """
        Menyesuaikan tanggal ke hari kerja berikutnya jika jatuh pada weekend/libur.

        Returns:
            EffectiveDate yang sudah disesuaikan
        """
        adjusted = self.date
        while adjusted.weekday() >= 5 or (holiday_calendar and adjusted.date() in holiday_calendar):
            adjusted = adjusted + timedelta(days=1)

        if adjusted != self.date:
            return EffectiveDate(
                date=adjusted,
                date_type=self.date_type,
                source=f"adjusted_from_{self.source}",
                justification=f"Adjusted from {self.date.date()} to next business day",
            )
        return self

    def days_until(self, target_date: datetime) -> int:
        """Menghitung jumlah hari sampai tanggal target."""
        target = target_date if target_date.tzinfo else target_date.replace(tzinfo=UTC)
        return (target - self.date).days

    def days_since(self, past_date: datetime) -> int:
        """Menghitung jumlah hari sejak tanggal lampau."""
        past = past_date if past_date.tzinfo else past_date.replace(tzinfo=UTC)
        return (self.date - past).days

    def is_before(self, other: EffectiveDate) -> bool:
        """Memeriksa apakah tanggal efektif ini sebelum tanggal efektif lain."""
        return self.date < other.date

    def is_after(self, other: EffectiveDate) -> bool:
        """Memeriksa apakah tanggal efektif ini setelah tanggal efektif lain."""
        return self.date > other.date

    def is_same_day(self, other: EffectiveDate) -> bool:
        """Memeriksa apakah tanggal efektif ini sama hari dengan tanggal efektif lain."""
        return self.date.date() == other.date.date()

    def to_iso(self) -> str:
        return self.date.isoformat()

    def to_date_string(self) -> str:
        return self.date.strftime("%Y-%m-%d")

    def to_datetime(self) -> datetime:
        return self.date

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "date_type": self.date_type.name,
            "source": self.source,
            "justification": self.justification,
        }

    def __repr__(self) -> str:
        return (
            f"EffectiveDate({self.date.isoformat()}, {self.date_type.name}, source={self.source})"
        )


# === 3. EFFECTIVE DATE FACTORY ===


class EffectiveDateFactory:
    """
    Factory untuk membuat EffectiveDate dengan konteks yang tepat.
    """

    @staticmethod
    def for_transaction(
        transaction_date: datetime,
        user_input: datetime | None = None,
    ) -> EffectiveDate:
        """
        Membuat EffectiveDate untuk transaksi umum.

        Prioritas: user_input > transaction_date > current_time
        """
        if user_input:
            return EffectiveDate.from_user_input(user_input, EffectiveDateType.TRANSACTION_DATE)
        return EffectiveDate.from_system(EffectiveDateType.TRANSACTION_DATE)

    @staticmethod
    def for_invoice(invoice_date: datetime) -> EffectiveDate:
        """Membuat EffectiveDate untuk faktur."""
        return EffectiveDate.from_user_input(invoice_date, EffectiveDateType.INVOICE_DATE)

    @staticmethod
    def for_payment(payment_date: datetime, source: str = "user_input") -> EffectiveDate:
        """Membuat EffectiveDate untuk pembayaran."""
        if source == "user_input":
            return EffectiveDate.from_user_input(payment_date, EffectiveDateType.SETTLEMENT_DATE)
        else:
            return EffectiveDate.from_api(payment_date, EffectiveDateType.SETTLEMENT_DATE, source)

    @staticmethod
    def for_delivery(delivery_date: datetime, source: str = "system") -> EffectiveDate:
        """Membuat EffectiveDate untuk pengiriman barang."""
        if source == "user_input":
            return EffectiveDate.from_user_input(delivery_date, EffectiveDateType.DELIVERY_DATE)
        return EffectiveDate.from_api(delivery_date, EffectiveDateType.DELIVERY_DATE, source)

    @staticmethod
    def for_due_date(due_date: datetime, source: str = "contract") -> EffectiveDate:
        """Membuat EffectiveDate untuk tanggal jatuh tempo."""
        return EffectiveDate.from_api(due_date, EffectiveDateType.DUE_DATE, source)

    @staticmethod
    def for_recognition(recognition_date: datetime, source: str = "accounting") -> EffectiveDate:
        """Membuat EffectiveDate untuk tanggal pengakuan akuntansi."""
        return EffectiveDate.from_api(recognition_date, EffectiveDateType.RECOGNITION_DATE, source)


# === 4. EXPORTS ===

__all__ = [
    "EffectiveDate",
    "EffectiveDateConstraint",
    "EffectiveDateFactory",
    "EffectiveDateType",
]
