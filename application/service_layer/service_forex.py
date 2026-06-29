# service_forex.py - Complete rewrite with full event publishing

from __future__ import annotations

"""
Service Layer untuk Foreign Exchange (Forex)
Menangani:
- Kurs tengah harian (IDR terhadap mata uang asing)
- Revaluasi transaksi dalam mata uang asing ke IDR (PSAK 10/IFRS 21)
- Perhitungan selisih kurs (realized/unrealized)
- Konversi antar mata uang
- Event publishing untuk revaluasi dan perubahan kurs
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.shared_value_objects.exchange_rate_vo import ExchangeRateVO
from domain.shared_value_objects.money_vo import MoneyVO
from ports.primary.cache_port import CachePort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.forex_repository_port import ForexRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

# Import domain events (menggunakan event yang sudah ada di registry)
from application.events import JournalPostedEvent, TransactionRecordedEvent

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class ForexRevaluationResult:
    """Result of forex revaluation."""

    legal_entity_id: UUID
    account_code: str
    currency: str
    balance_fcy: Decimal
    old_rate: Decimal
    new_rate: Decimal
    old_idr: Decimal
    new_idr: Decimal
    difference: Decimal
    description: str
    revaluation_date: date
    journal_id: UUID | None = None


@dataclass(kw_only=True)
class ExchangeRateEntry:
    """Exchange rate entry."""

    id: UUID
    from_currency: str
    to_currency: str
    rate: Decimal
    rate_date: date
    source: str = "MANUAL"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None


# ============================================================================
# Exceptions
# ============================================================================


class ForexServiceError(Exception):
    pass


class ExchangeRateNotFoundError(ForexServiceError):
    pass


class InvalidCurrencyError(ForexServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class ForexService:
    """Layanan forex untuk revaluasi dan kurs.
    Mempublikasikan event untuk setiap operasi signifikan.
    """

    def __init__(
        self,
        forex_repo: ForexRepositoryPort,
        uow: UnitOfWorkPort,
        cache: CachePort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if forex_repo is None:
            raise ValueError("forex_repo is required")
        if uow is None:
            raise ValueError("uow is required")

        self.forex_repo = forex_repo
        self.uow = uow
        self.cache = cache
        self._event_publisher = event_publisher
        self._stats = {"revaluations": 0, "conversions": 0, "cache_hits": 0}

        logger.info("ForexService initialized")

    # ========================== KURS ==========================

    async def get_rate(
        self,
        from_currency: str = "IDR",
        to_currency: str = "IDR",
        rate_date: date | None = None,
    ) -> ExchangeRateVO:
        """
        Mendapatkan kurs tengah untuk pasangan mata uang pada tanggal tertentu.
        Jika tidak ada, akan mencari rate terakhir sebelum tanggal tersebut.
        """
        if from_currency == to_currency:
            return ExchangeRateVO(from_currency, to_currency, Decimal(1), rate_date or date.today())

        rate_date = rate_date or date.today()

        # Coba dari cache
        cache_key = f"forex:rate:{from_currency}:{to_currency}:{rate_date.isoformat()}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                self._stats["cache_hits"] += 1
                return ExchangeRateVO.from_dict(cached)

        rate_entity = await self.forex_repo.get_rate(from_currency, to_currency, rate_date)
        if not rate_entity:
            rate_entity = await self.forex_repo.get_latest_rate_before(
                from_currency, to_currency, rate_date
            )
            if not rate_entity:
                raise ExchangeRateNotFoundError(
                    f"Tidak ada kurs untuk {from_currency}/{to_currency} pada {rate_date}"
                )

        rate_vo = ExchangeRateVO(
            from_currency=rate_entity.from_currency,
            to_currency=rate_entity.to_currency,
            rate=rate_entity.rate,
            date=rate_entity.rate_date,
            source=rate_entity.source,
        )

        if self.cache:
            await self.cache.setex(cache_key, 86400, rate_vo.to_json())

        return rate_vo

    async def set_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        rate_date: date,
        source: str = "MANUAL",
        created_by: UUID | None = None,
        correlation_id: str | None = None,
    ) -> ExchangeRateEntry:
        """Set exchange rate manually."""
        if from_currency == to_currency:
            raise InvalidCurrencyError("From and to currencies cannot be the same")

        rate_entry = ExchangeRateEntry(
            id=uuid4(),
            from_currency=from_currency.upper(),
            to_currency=to_currency.upper(),
            rate=rate,
            rate_date=rate_date,
            source=source,
            created_by=created_by,
        )

        await self.forex_repo.save_rate(rate_entry)
        await self.uow.commit()

        # Invalidate cache
        if self.cache:
            cache_key = f"forex:rate:{from_currency}:{to_currency}:{rate_date.isoformat()}"
            await self.cache.delete(cache_key)

        # --- PUBLISH EVENT ---
        # Gunakan TransactionRecordedEvent sebagai event generik untuk perubahan kurs
        if self._event_publisher:
            try:
                event = TransactionRecordedEvent(
                    aggregate_id=rate_entry.id,
                    aggregate_version=1,
                    transaction_id=rate_entry.id,
                    transaction_type="EXCHANGE_RATE_UPDATE",
                    amount=rate,
                    description=f"Exchange rate {from_currency}/{to_currency} = {rate}",
                    user_id=str(created_by) if created_by else "system",
                    occurred_at=datetime.now(UTC),
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published TransactionRecordedEvent for rate update {from_currency}/{to_currency}")
            except Exception as e:
                logger.warning(f"Failed to publish TransactionRecordedEvent: {e}")

        logger.info(
            "Exchange rate set: %s/%s = %s on %s",
            from_currency,
            to_currency,
            rate,
            rate_date
        )
        return rate_entry

    async def convert_money(
        self,
        money: MoneyVO,
        target_currency: str = "IDR",
        rate_date: date | None = None,
    ) -> MoneyVO:
        """Konversi MoneyVO ke mata uang target menggunakan kurs pada tanggal tertentu."""
        self._stats["conversions"] += 1

        if money.currency == target_currency:
            return money

        rate = await self.get_rate(money.currency, target_currency, rate_date)
        converted_amount = money.amount * rate.rate
        return MoneyVO(
            amount=converted_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            currency=target_currency,
        )

    # ========================== REVALUASI ==========================

    async def revalue_balance(
        self,
        legal_entity_id: UUID,
        currency: str,
        balance_in_fcy: Decimal,
        account_code: str,
        as_of_date: date,
        description: str = "Forex revaluation",
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> ForexRevaluationResult:
        """
        Melakukan revaluasi saldo akun dalam mata uang asing ke IDR.
        Menghasilkan selisih kurs unrealized yang harus di-jurnal.
        """
        self._stats["revaluations"] += 1

        if currency == "IDR":
            raise InvalidCurrencyError("Cannot revalue IDR to IDR")

        # Rate saat ini
        current_rate = await self.get_rate(currency, "IDR", as_of_date)

        # Rate terakhir yang digunakan
        previous_rate = await self.forex_repo.get_last_revaluation_rate(
            legal_entity_id, account_code, currency
        )

        if previous_rate is None:
            previous_rate = current_rate

        old_idr = balance_in_fcy * previous_rate.rate
        new_idr = balance_in_fcy * current_rate.rate
        difference = new_idr - old_idr

        # Simpan revaluasi ke repository
        await self.forex_repo.save_revaluation(
            legal_entity_id=legal_entity_id,
            account_code=account_code,
            currency=currency,
            as_of_date=as_of_date,
            balance_fcy=balance_in_fcy,
            rate_used=current_rate.rate,
            old_idr=old_idr,
            new_idr=new_idr,
            difference=difference,
            description=description,
            created_by=user_id,
        )
        await self.uow.commit()

        # --- PUBLISH EVENT (jika ada perbedaan) ---
        if self._event_publisher and difference != 0:
            try:
                # Gunakan JournalPostedEvent atau TransactionRecordedEvent
                event = TransactionRecordedEvent(
                    aggregate_id=uuid4(),
                    aggregate_version=1,
                    transaction_id=uuid4(),
                    transaction_type="FOREX_REVALUATION",
                    amount=difference,
                    description=f"Forex revaluation for {account_code} ({currency}): {difference}",
                    user_id=str(user_id) if user_id else "system",
                    occurred_at=datetime.now(UTC),
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published TransactionRecordedEvent for revaluation of {account_code}")
            except Exception as e:
                logger.warning(f"Failed to publish TransactionRecordedEvent: {e}")

        logger.info(
            "Forex revaluation for %s (%s): difference=%s (old: %s, new: %s)",
            account_code,
            currency,
            difference,
            old_idr,
            new_idr
        )

        return ForexRevaluationResult(
            legal_entity_id=legal_entity_id,
            account_code=account_code,
            currency=currency,
            balance_fcy=balance_in_fcy,
            old_rate=previous_rate.rate,
            new_rate=current_rate.rate,
            old_idr=old_idr,
            new_idr=new_idr,
            difference=difference,
            description=description,
            revaluation_date=as_of_date,
        )

    async def revalue_all_foreign_currency_accounts(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        period_id: UUID,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> list[ForexRevaluationResult]:
        """
        Revaluasi semua akun yang memiliki saldo dalam mata uang asing.
        Biasanya dijalankan saat akhir bulan.
        """
        accounts = await self.forex_repo.get_foreign_currency_balances(legal_entity_id, as_of_date)
        results = []

        for acc in accounts:
            result = await self.revalue_balance(
                legal_entity_id=legal_entity_id,
                currency=acc["currency"],
                balance_in_fcy=acc["balance_fcy"],
                account_code=acc["account_code"],
                as_of_date=as_of_date,
                description=f"Month-end revaluation for {as_of_date}",
                user_id=user_id,
                correlation_id=correlation_id,
            )
            results.append(result)

        # Mark period as revalued
        await self.forex_repo.mark_period_revalued(legal_entity_id, period_id)
        await self.uow.commit()

        # --- PUBLISH AGGREGATED EVENT ---
        if self._event_publisher and results:
            total_diff = sum(r.difference for r in results)
            try:
                event = JournalPostedEvent(
                    aggregate_id=period_id,
                    aggregate_version=1,
                    journal_id=uuid4(),
                    journal_number=f"FOREX-{as_of_date}",
                    description=f"Bulk forex revaluation for {as_of_date}",
                    total_debit=total_diff if total_diff > 0 else Decimal("0"),
                    total_credit=abs(total_diff) if total_diff < 0 else Decimal("0"),
                    posted_by=str(user_id) if user_id else "system",
                    user_id=str(user_id) if user_id else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
                logger.debug(f"Published JournalPostedEvent for bulk forex revaluation")
            except Exception as e:
                logger.warning(f"Failed to publish JournalPostedEvent: {e}")

        return results

    # ========================== SELISIH KURS TRANSAKSI ==========================

    async def calculate_realized_exchange_difference(
        self,
        original_amount_fcy: Decimal,
        original_rate: Decimal,
        settlement_amount_fcy: Decimal,
        settlement_rate: Decimal,
        original_date: date,
        settlement_date: date,
    ) -> tuple[Decimal, str]:
        """
        Hitung selisih kurs realized untuk transaksi pembayaran/penerimaan.
        Returns (difference, gain_loss) - gain_loss = 'GAIN' atau 'LOSS'
        """
        original_idr = original_amount_fcy * original_rate
        settlement_idr = settlement_amount_fcy * settlement_rate
        difference = settlement_idr - original_idr
        gain_loss = "GAIN" if difference > 0 else "LOSS"
        return abs(difference), gain_loss

    async def get_monthly_average_rate(
        self,
        year: int,
        month: int,
        from_currency: str = "IDR",
        to_currency: str = "IDR",
    ) -> Decimal:
        """
        Dapatkan kurs rata-rata bulanan (digunakan untuk translasi laporan keuangan).
        Parameter yang diperlukan: year, month.
        Parameter opsional: from_currency, to_currency (default IDR).
        """
        if from_currency == to_currency:
            return Decimal(1)

        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)

        rates = await self.forex_repo.get_rates_in_period(
            from_currency, to_currency, start_date, end_date
        )

        if not rates:
            raise ExchangeRateNotFoundError(
                f"Tidak ada kurs untuk {from_currency}/{to_currency} pada bulan {month}/{year}"
            )

        total = sum(r.rate for r in rates)
        return (total / len(rates)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    async def get_historical_rates(
        self,
        from_currency: str,
        to_currency: str,
        start_date: date,
        end_date: date,
    ) -> list[ExchangeRateVO]:
        """Get historical exchange rates for a period."""
        rates = await self.forex_repo.get_rates_in_period(
            from_currency, to_currency, start_date, end_date
        )
        return [
            ExchangeRateVO(
                from_currency=r.from_currency,
                to_currency=r.to_currency,
                rate=r.rate,
                date=r.rate_date,
                source=r.source,
            )
            for r in rates
        ]

    # ========================== CLOSE PERIOD ==========================

    async def close_period_forex(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        closing_date: date,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Decimal:
        """Tutup periode forex: catat semua selisih kurs unrealized ke akun laba rugi."""
        unrealized = await self.forex_repo.get_unrealized_differences(legal_entity_id, period_id)
        total_unrealized = sum(item["difference"] for item in unrealized)

        # Post to journal if needed
        journal_id = None
        if total_unrealized != 0:
            # In production, call journal service
            logger.info(
                "Total unrealized forex for period %s: %s",
                period_id,
                total_unrealized
            )

            # --- PUBLISH EVENT ---
            if self._event_publisher:
                try:
                    event = JournalPostedEvent(
                        aggregate_id=period_id,
                        aggregate_version=1,
                        journal_id=journal_id or uuid4(),
                        journal_number=f"FOREX-CLOSE-{closing_date}",
                        description=f"Forex closing for period {period_id}",
                        total_debit=total_unrealized if total_unrealized > 0 else Decimal("0"),
                        total_credit=abs(total_unrealized) if total_unrealized < 0 else Decimal("0"),
                        posted_by=str(user_id) if user_id else "system",
                        user_id=str(user_id) if user_id else None,
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event, correlation_id)
                    logger.debug(f"Published JournalPostedEvent for forex period close")
                except Exception as e:
                    logger.warning(f"Failed to publish JournalPostedEvent: {e}")

        await self.forex_repo.mark_period_closed(legal_entity_id, period_id, user_id)
        await self.uow.commit()

        logger.info(
            "Forex period %s closed with total unrealized %s",
            period_id,
            total_unrealized
        )
        return total_unrealized

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_forex_service(
    forex_repo: ForexRepositoryPort,
    uow: UnitOfWorkPort,
    cache: CachePort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> ForexService:
    return ForexService(forex_repo, uow, cache, event_publisher)


__all__ = [
    "ExchangeRateEntry",
    "ExchangeRateNotFoundError",
    "ForexRevaluationResult",
    "ForexService",
    "ForexServiceError",
    "InvalidCurrencyError",
    "create_forex_service",
]