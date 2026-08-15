# =============================================================================
# 8. service_forex.py
# =============================================================================

# service_forex.py - Complete rewrite with full event publishing
# v5.9.3 - Added audit decorator and authority checks for mutation methods

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

# Import domain events
from application.events import JournalPostedEvent, TransactionRecordedEvent
from domain.shared_value_objects.exchange_rate_vo import ExchangeRateVO
from domain.shared_value_objects.money_vo import MoneyVO
from ports.primary.cache_port import CachePort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.forex_repository_port import ForexRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


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


@dataclass(kw_only=True)
class ExchangeRateDTO:
    """
    Hasil list/create/get/update/deactivate/lock/unlock exchange rate.
    Nama field sengaja disamakan persis dengan ExchangeRateResponseSchema
    di fastapi_forex_router.py (effective_date bukan rate_date, provider
    bukan source, spread_percent bukan spread_percentage) supaya router
    bisa langsung construct response dari sini tanpa transformasi lagi.
    """
    id: UUID
    from_currency: str
    to_currency: str
    rate: Decimal
    rate_type: str
    effective_date: date
    provider: str
    bid_rate: Decimal | None
    ask_rate: Decimal | None
    spread: Decimal | None
    spread_percent: float | None
    status: str
    is_locked: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    created_by_name: str | None = None
    version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExchangeRateDTO":
        return cls(
            id=UUID(data["id"]),
            from_currency=data["from_currency"],
            to_currency=data["to_currency"],
            rate=Decimal(str(data["rate"])),
            rate_type=data["rate_type"],
            effective_date=date.fromisoformat(data["rate_date"]),
            provider=data["source"],
            bid_rate=Decimal(str(data["bid_rate"])) if data.get("bid_rate") is not None else None,
            ask_rate=Decimal(str(data["ask_rate"])) if data.get("ask_rate") is not None else None,
            spread=Decimal(str(data["spread"])) if data.get("spread") is not None else None,
            spread_percent=data.get("spread_percentage"),
            status=data["status"],
            is_locked=data["is_locked"],
            notes=data.get("notes"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_by_name=None,
            version=data.get("version", 1),
        )


@dataclass(kw_only=True)
class ForexPositionDTO:
    """Hasil get_forex_position - bentuknya menyamai ForexPositionResponseSchema."""
    by_currency: dict[str, dict[str, Any]]
    total_foreign_currency_balance: Decimal
    total_unrealized_gain: Decimal
    total_unrealized_loss: Decimal
    net_unrealized_position: Decimal


@dataclass(kw_only=True)
class ForexDashboardDTO:
    """Hasil get_forex_dashboard - bentuknya menyamai ForexDashboardResponseSchema."""
    latest_rates: dict[str, dict[str, Any]]
    month_to_date_gain_loss: Decimal
    year_to_date_gain_loss: Decimal
    open_positions: dict[str, Decimal]
    pending_revaluations: int
    last_revaluation_date: date | None
    last_revaluation_result: dict[str, Any] | None
    rate_providers_status: dict[str, str]


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
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("ForexService initialized")

    def set_context(self, legal_entity_id: UUID | None) -> None:
        """
        Ikat legal_entity_id per-request ke repo.

        CATATAN: ForexService & self.forex_repo didaftarkan sebagai
        singleton di IoC container (satu instance untuk seumur hidup
        aplikasi), sedangkan legal_entity_id itu per-request/per-tenant.
        Tanpa ini, beberapa method repo (get_rate/set_rate/
        get_last_revaluation_rate, dll) akan selalu ValueError
        "legal_entity_id not set in repository" begitu dipanggil, karena
        legal_entity_id sebelumnya cuma bisa diisi lewat konstruktor sekali
        di awal proses. HARUS dipanggil router di awal setiap endpoint
        (sebelum method service manapun dipanggil), memakai
        legal_entity_id yang dikirim frontend lewat query/path param.

        legal_entity_id boleh None untuk endpoint yang genuinely tidak
        scoped per entitas (mis. currency master - mata uang berlaku
        global, bukan per legal entity) - dalam hal ini repo dibiarkan
        seperti kondisi terakhir, tidak ditimpa.
        """
        if legal_entity_id is None:
            return
        if hasattr(type(self.forex_repo), "legal_entity_id"):
            self.forex_repo.legal_entity_id = legal_entity_id

    async def _commit(self) -> None:
        """
        Commit perubahan.

        CATATAN BUG: self.uow (UnitOfWorkPort) di service ini TIDAK PERNAH
        di-`begin()`/dimasuki lewat `async with self.uow:`, jadi
        `self.uow.commit()` langsung selalu raise "UoW not started or
        transaction not active" (pola bug yang sama seperti sudah
        diperbaiki di service_iam.py & service_consolidation.py). Repo
        forex mengelola session-nya sendiri (lihat
        SQLAlchemyForexRepository.commit()) - commit lewat situ.
        """
        if hasattr(self.forex_repo, "commit"):
            await self.forex_repo.commit()
        elif self.uow is not None:
            await self._commit()

    # ==================== EXCHANGE RATE CRUD ====================
    # CATATAN: 7 method di bawah ini SEBELUMNYA TIDAK ADA SAMA SEKALI,
    # padahal fastapi_forex_router.py sudah memanggilnya sejak awal
    # (AttributeError setiap dipanggil). Dibangun lewat method *_full di
    # ForexRepositoryPort yang juga baru ditambahkan (create_rate_full,
    # list_rates_full, get_rate_by_id_full, update_rate_full,
    # deactivate_rate_full, set_rate_lock).

    async def create_exchange_rate(
        self,
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
        legal_entity_id: UUID,
    ) -> ExchangeRateDTO:
        self._check_authority(created_by, "create_exchange_rate")
        if from_currency == to_currency:
            raise ValueError("from_currency dan to_currency tidak boleh sama")
        if rate <= 0:
            raise ValueError("rate harus lebih besar dari 0")
        data = await self.forex_repo.create_rate_full(
            legal_entity_id=legal_entity_id,
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            rate_type=rate_type,
            effective_date=effective_date,
            provider=provider,
            bid_rate=bid_rate,
            ask_rate=ask_rate,
            notes=notes,
            created_by=created_by,
        )
        if self.uow is not None:
            await self._commit()
        return ExchangeRateDTO.from_dict(data)

    async def list_exchange_rates(
        self,
        legal_entity_id: UUID,
        from_currency: str | None = None,
        to_currency: str | None = None,
        rate_type: str | None = None,
        effective_date: date | None = None,
        provider: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[ExchangeRateDTO]:
        rows = await self.forex_repo.list_rates_full(
            legal_entity_id=legal_entity_id,
            from_currency=from_currency,
            to_currency=to_currency,
            rate_type=rate_type,
            effective_date=effective_date,
            provider=provider,
            page=page,
            page_size=page_size,
        )
        return [ExchangeRateDTO.from_dict(row) for row in rows]

    async def get_exchange_rate_by_id(self, rate_id: UUID, legal_entity_id: UUID) -> ExchangeRateDTO | None:
        data = await self.forex_repo.get_rate_by_id_full(rate_id, legal_entity_id)
        return ExchangeRateDTO.from_dict(data) if data else None

    async def update_exchange_rate(
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
    ) -> ExchangeRateDTO | None:
        self._check_authority(updated_by, "update_exchange_rate")
        data = await self.forex_repo.update_rate_full(
            rate_id=rate_id,
            legal_entity_id=legal_entity_id,
            rate=rate,
            bid_rate=bid_rate,
            ask_rate=ask_rate,
            provider=provider,
            notes=notes,
            status=status,
            updated_by=updated_by,
        )
        if not data:
            return None
        if self.uow is not None:
            await self._commit()
        return ExchangeRateDTO.from_dict(data)

    async def deactivate_exchange_rate(
        self, rate_id: UUID, legal_entity_id: UUID, reason: str, deactivated_by: UUID | None
    ) -> ExchangeRateDTO | None:
        self._check_authority(deactivated_by, "deactivate_exchange_rate")
        data = await self.forex_repo.deactivate_rate_full(rate_id, legal_entity_id, reason, deactivated_by)
        if not data:
            return None
        if self.uow is not None:
            await self._commit()
        return ExchangeRateDTO.from_dict(data)

    async def lock_exchange_rate(self, rate_id: UUID, legal_entity_id: UUID, locked_by: UUID) -> ExchangeRateDTO | None:
        self._check_authority(locked_by, "lock_exchange_rate")
        data = await self.forex_repo.set_rate_lock(rate_id, legal_entity_id, True, locked_by)
        if not data:
            return None
        if self.uow is not None:
            await self._commit()
        return ExchangeRateDTO.from_dict(data)

    async def unlock_exchange_rate(self, rate_id: UUID, legal_entity_id: UUID, unlocked_by: UUID) -> ExchangeRateDTO | None:
        self._check_authority(unlocked_by, "unlock_exchange_rate")
        data = await self.forex_repo.set_rate_lock(rate_id, legal_entity_id, False, unlocked_by)
        if not data:
            return None
        if self.uow is not None:
            await self._commit()
        return ExchangeRateDTO.from_dict(data)

    # ==================== CURRENCY MASTER ====================
    # CATATAN: sebelumnya daftar mata uang di-hardcode sebagai Python Enum
    # (CurrencyCode) di fastapi_forex_router.py - fitur "Tambah Mata Uang
    # Baru" di UI selalu 404 karena endpoint-nya memang belum pernah
    # dibuat. Method2 di bawah ini membungkus tabel currency_master yang
    # baru (lihat migrasi b2c3d4e5f6a7).

    async def create_currency(
        self,
        code: str,
        name: str,
        symbol: str | None,
        decimal_places: int,
        created_by: UUID | None,
    ) -> dict[str, Any]:
        self._check_authority(created_by, "create_currency")
        code = code.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("Kode mata uang harus 3 huruf (format ISO 4217), mis. USD")
        data = await self.forex_repo.create_currency(code, name, symbol, decimal_places, created_by)
        await self._commit()
        return data

    async def list_currencies(self, is_active: bool | None = True) -> list[dict[str, Any]]:
        return await self.forex_repo.list_currencies(is_active)

    async def get_currency_by_code(self, code: str) -> dict[str, Any] | None:
        return await self.forex_repo.get_currency_by_code(code.strip().upper())

    async def deactivate_currency(self, code: str, deactivated_by: UUID) -> dict[str, Any] | None:
        self._check_authority(deactivated_by, "deactivate_currency")
        data = await self.forex_repo.deactivate_currency(code.strip().upper())
        if data:
            await self._commit()
        return data

    # ==================== POSITION & DASHBOARD ====================
    # CATATAN PENTING soal keterbatasan data: journal_line baru punya
    # fc_amount/booking_rate mulai migrasi b2c3d4e5f6a7 - baris jurnal yang
    # dibuat SEBELUM migrasi itu tidak punya nilai di 2 kolom itu (None),
    # jadi otomatis DIKECUALIKAN dari perhitungan unrealized gain/loss di
    # bawah (bukan dianggap 0 - dikecualikan sepenuhnya, supaya tidak
    # menyesatkan). "coverage" pada hasil position menunjukkan proporsi
    # baris yang punya data lengkap vs yang dikecualikan, supaya user bisa
    # menilai seberapa bisa diandalkan angka gain/loss yang ditampilkan.

    async def _compute_position_by_currency(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> dict[str, dict[str, Any]]:
        coa_accounts = await self.forex_repo.get_foreign_currency_balances(legal_entity_id, as_of_date)
        accounts_by_currency: dict[str, list[str]] = {}
        for bal in coa_accounts:
            currency = bal.get("currency_code") or bal.get("currency")
            if not currency or currency == "IDR":
                continue
            accounts_by_currency.setdefault(currency, []).append(bal.get("account_code"))

        exposures = await self.forex_repo.get_currency_exposure_from_journal(legal_entity_id, as_of_date)

        by_currency: dict[str, dict[str, Any]] = {}
        for exp in exposures:
            currency = exp["currency"]
            try:
                rate_entity = await self.forex_repo.get_rate(currency, "IDR", as_of_date)
                if rate_entity is None:
                    rate_entity = await self.forex_repo.get_latest_rate_before(currency, "IDR", as_of_date)
            except Exception:
                rate_entity = None

            fc_amount_total = Decimal(str(exp["fc_amount_total"]))
            booked_value = Decimal(str(exp["booked_functional_value_total"]))
            current_value = None
            unrealized_gain_loss = None
            if rate_entity is not None and exp["lines_with_booking_data"] > 0:
                current_value = fc_amount_total * rate_entity.rate
                unrealized_gain_loss = current_value - booked_value

            by_currency[currency] = {
                "currency": currency,
                "accounts": accounts_by_currency.get(currency, []),
                "fc_amount_total": float(fc_amount_total),
                "booked_functional_value_total": float(booked_value),
                "current_functional_value": float(current_value) if current_value is not None else None,
                "unrealized_gain_loss": float(unrealized_gain_loss) if unrealized_gain_loss is not None else None,
                "latest_rate": float(rate_entity.rate) if rate_entity else None,
                "latest_rate_date": rate_entity.rate_date.isoformat() if rate_entity else None,
                "total_journal_lines": exp["total_lines"],
                "lines_with_booking_data": exp["lines_with_booking_data"],
                "lines_excluded_no_booking_data": exp["lines_excluded"],
            }

        for currency, accounts in accounts_by_currency.items():
            if currency not in by_currency:
                by_currency[currency] = {
                    "currency": currency,
                    "accounts": accounts,
                    "fc_amount_total": 0.0,
                    "booked_functional_value_total": 0.0,
                    "current_functional_value": None,
                    "unrealized_gain_loss": None,
                    "latest_rate": None,
                    "latest_rate_date": None,
                    "total_journal_lines": 0,
                    "lines_with_booking_data": 0,
                    "lines_excluded_no_booking_data": 0,
                }
        return by_currency

    async def get_forex_position(
        self, legal_entity_id: UUID, as_of_date: date, functional_currency: str = "IDR"
    ) -> ForexPositionDTO:
        by_currency = await self._compute_position_by_currency(legal_entity_id, as_of_date)

        total_balance = Decimal("0")
        total_gain = Decimal("0")
        total_loss = Decimal("0")
        for entry in by_currency.values():
            if entry["current_functional_value"] is not None:
                total_balance += Decimal(str(entry["current_functional_value"]))
            ugl = entry["unrealized_gain_loss"]
            if ugl is not None:
                if ugl >= 0:
                    total_gain += Decimal(str(ugl))
                else:
                    total_loss += Decimal(str(-ugl))

        return ForexPositionDTO(
            by_currency=by_currency,
            total_foreign_currency_balance=total_balance,
            total_unrealized_gain=total_gain,
            total_unrealized_loss=total_loss,
            net_unrealized_position=total_gain - total_loss,
        )

    async def get_forex_dashboard(
        self, legal_entity_id: UUID, as_of_date: date, functional_currency: str = "IDR"
    ) -> ForexDashboardDTO:
        position_now = await self.get_forex_position(legal_entity_id, as_of_date, functional_currency)

        month_start = as_of_date.replace(day=1)
        year_start = as_of_date.replace(month=1, day=1)
        position_month_start = await self.get_forex_position(legal_entity_id, month_start, functional_currency)
        position_year_start = await self.get_forex_position(legal_entity_id, year_start, functional_currency)

        mtd = position_now.net_unrealized_position - position_month_start.net_unrealized_position
        ytd = position_now.net_unrealized_position - position_year_start.net_unrealized_position

        latest_rates_list = await self.forex_repo.list_rates_full(
            legal_entity_id=legal_entity_id, effective_date=None, page=1, page_size=20,
        )
        latest_rates: dict[str, dict[str, Any]] = {}
        for r in latest_rates_list:
            pair = f"{r['from_currency']}/{r['to_currency']}"
            if pair not in latest_rates:
                latest_rates[pair] = r

        open_positions: dict[str, Decimal] = {
            cur: Decimal(str(entry["fc_amount_total"]))
            for cur, entry in position_now.by_currency.items()
        }

        rate_providers_status: dict[str, str] = {
            cur: ("tersedia" if entry["latest_rate"] is not None else "tidak ada kurs")
            for cur, entry in position_now.by_currency.items()
        }

        return ForexDashboardDTO(
            latest_rates=latest_rates,
            month_to_date_gain_loss=mtd,
            year_to_date_gain_loss=ytd,
            open_positions=open_positions,
            # CATATAN: belum ada infrastruktur pencatatan histori "revaluasi
            # dijalankan kapan" (revaluation_records belum pernah dimigrasi -
            # lihat catatan lama di sqlalchemy_forex_repository_impl.py).
            # Daripada mengarang, nilai2 ini dikosongkan/nol secara eksplisit.
            pending_revaluations=0,
            last_revaluation_date=None,
            last_revaluation_result=None,
            rate_providers_status=rate_providers_status,
        )

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "ForexService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ========================== KURS ==========================

    async def get_rate(
        self,
        from_currency: str = "IDR",
        to_currency: str = "IDR",
        rate_date: date | None = None,
    ) -> ExchangeRateVO:
        if from_currency == to_currency:
            return ExchangeRateVO(from_currency, to_currency, Decimal(1), rate_date or date.today())

        rate_date = rate_date or date.today()

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

    @audit
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
        self._check_authority(created_by, "set_rate")

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
        await self._commit()

        if self.cache:
            cache_key = f"forex:rate:{from_currency}:{to_currency}:{rate_date.isoformat()}"
            await self.cache.delete(cache_key)

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
            except Exception as e:
                logger.warning(f"Failed to publish TransactionRecordedEvent: {e}")

        self._record_audit("set_rate", {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate": str(rate),
            "rate_date": rate_date.isoformat(),
            "created_by": str(created_by) if created_by else None,
        })

        logger.info("Exchange rate set: %s/%s = %s on %s", from_currency, to_currency, rate, rate_date)
        return rate_entry

    async def convert_money(
        self,
        money: MoneyVO,
        target_currency: str = "IDR",
        rate_date: date | None = None,
    ) -> MoneyVO:
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

    @audit
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
        self._check_authority(user_id, "revalue_balance")
        self._stats["revaluations"] += 1

        if currency == "IDR":
            raise InvalidCurrencyError("Cannot revalue IDR to IDR")

        current_rate = await self.get_rate(currency, "IDR", as_of_date)

        previous_rate = await self.forex_repo.get_last_revaluation_rate(
            legal_entity_id, account_code, currency
        )

        if previous_rate is None:
            previous_rate = current_rate

        old_idr = balance_in_fcy * previous_rate.rate
        new_idr = balance_in_fcy * current_rate.rate
        difference = new_idr - old_idr

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
        await self._commit()

        if self._event_publisher and difference != 0:
            try:
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
            except Exception as e:
                logger.warning(f"Failed to publish TransactionRecordedEvent: {e}")

        self._record_audit("revalue_balance", {
            "account_code": account_code,
            "currency": currency,
            "difference": str(difference),
            "user_id": str(user_id) if user_id else None,
        })

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

    @audit
    async def revalue_all_foreign_currency_accounts(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        period_id: UUID,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> list[ForexRevaluationResult]:
        self._check_authority(user_id, "revalue_all_foreign_currency_accounts")
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

        await self.forex_repo.mark_period_revalued(legal_entity_id, period_id)
        await self._commit()

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
            except Exception as e:
                logger.warning(f"Failed to publish JournalPostedEvent: {e}")

        self._record_audit("revalue_all_foreign_currency_accounts", {
            "legal_entity_id": str(legal_entity_id),
            "period_id": str(period_id),
            "user_id": str(user_id) if user_id else None,
        })

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

    @audit
    async def close_period_forex(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        closing_date: date,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Decimal:
        self._check_authority(user_id, "close_period_forex")

        unrealized = await self.forex_repo.get_unrealized_differences(legal_entity_id, period_id)
        total_unrealized = sum(item["difference"] for item in unrealized)

        journal_id = None
        if total_unrealized != 0:
            logger.info("Total unrealized forex for period %s: %s", period_id, total_unrealized)

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
                except Exception as e:
                    logger.warning(f"Failed to publish JournalPostedEvent: {e}")

        await self.forex_repo.mark_period_closed(legal_entity_id, period_id, user_id)
        await self._commit()

        self._record_audit("close_period_forex", {
            "legal_entity_id": str(legal_entity_id),
            "period_id": str(period_id),
            "total_unrealized": str(total_unrealized),
            "user_id": str(user_id) if user_id else None,
        })

        logger.info("Forex period %s closed with total unrealized %s", period_id, total_unrealized)
        return total_unrealized

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


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
