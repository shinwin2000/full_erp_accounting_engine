#!/usr/bin/env python3

"""

Module: fastapi_forex_router.py

Layer: Adapters (Primary API - v1)

Responsibility: Menyediakan REST API endpoint untuk manajemen kurs valuta asing:

               CRUD kurs harian, konversi mata uang, revaluasi bulanan,

               laporan selisih kurs (realized & unrealized), historis kurs,

               rate provider integration (Bank Indonesia, Bloomberg, etc.).



Method Standards (ERP):

- create_exchange_rate() / update_exchange_rate() / delete_exchange_rate()

- get_exchange_rate() / get_latest_rates() / get_historical_rates()

- convert_currency() / convert_batch()

- run_revaluation() / reverse_revaluation()

- get_revaluation_history() / get_revaluation_summary()

- get_forex_position() / get_forex_gain_loss()

- get_exchange_rate_providers() / sync_from_provider()

- get_forex_dashboard() / get_forex_analytics()

- lock_rate() / unlock_rate()

- get_rate_status() / get_rate_history()

- audit_trail_rate() / can_transition_rate()

- register_rate_event() / get_rate_events()

- version_rate()

"""





from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession 

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

from app.main import get_db_session  

logger = logging.getLogger(__name__)



# ============================================================================

# IDEMPOTENCY MANAGER (for write operations)

# ============================================================================



class IdempotencyManager:

    """

    Simple in-memory idempotency manager untuk FastAPI endpoints.

    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.

    TTL 24 jam.

    """



    def __init__(self):

        self._storage: dict[str, tuple[str, datetime]] = {}

        self._ttl_seconds = 86400



    def _get_key(self, idempotency_key: str, method_name: str) -> str:

        raw = f"{method_name}:{idempotency_key}"

        return hashlib.sha256(raw.encode()).hexdigest()



    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:

        storage_key = self._get_key(idempotency_key, method_name)

        entry = self._storage.get(storage_key)

        if entry is None:

            return None

        result_json, timestamp = entry

        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:

            del self._storage[storage_key]

            return None

        try:

            return json.loads(result_json)

        except json.JSONDecodeError:

            return None



    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:

        storage_key = self._get_key(idempotency_key, method_name)

        try:

            result_json = json.dumps(result, default=str)

        except TypeError:

            result_json = json.dumps({"result": str(result)}, default=str)

        self._storage[storage_key] = (result_json, datetime.now())





# Global instance

_idempotency_manager = IdempotencyManager()





# ============================================================================

# CONSTANTS & ENUMS

# ============================================================================





class CurrencyCode(str, Enum):

    """Kode mata uang yang didukung."""



    IDR = "IDR"  # Indonesian Rupiah

    USD = "USD"  # US Dollar

    EUR = "EUR"  # Euro

    SGD = "SGD"  # Singapore Dollar

    JPY = "JPY"  # Japanese Yen

    CNY = "CNY"  # Chinese Yuan

    GBP = "GBP"  # British Pound

    AUD = "AUD"  # Australian Dollar

    MYR = "MYR"  # Malaysian Ringgit

    THB = "THB"  # Thai Baht

    KRW = "KRW"  # Korean Won

    HKD = "HKD"  # Hong Kong Dollar

    CHF = "CHF"  # Swiss Franc

    CAD = "CAD"  # Canadian Dollar

    SAR = "SAR"  # Saudi Riyal

    INR = "INR"  # Indian Rupee





class RateProvider(str, Enum):

    """Provider kurs."""



    MANUAL = "manual"

    BANK_INDONESIA = "bank_indonesia"

    BLOOMBERG = "bloomberg"

    REUTERS = "reuters"

    BANK_BCA = "bank_bca"

    BANK_MANDIRI = "bank_mandiri"

    BANK_BRI = "bank_bri"

    BANK_BNI = "bank_bni"

    CUSTOM = "custom"





class RateType(str, Enum):

    """Jenis kurs."""



    MID = "mid"  # Kurs tengah

    BUY = "buy"  # Kurs beli

    SELL = "sell"  # Kurs jual

    SPOT = "spot"  # Kurs spot

    FORWARD = "forward"  # Kurs forward





class RateStatus(str, Enum):

    """Status kurs."""



    ACTIVE = "active"

    INACTIVE = "inactive"

    EXPIRED = "expired"

    LOCKED = "locked"

    PENDING = "pending"

    ARCHIVED = "archived"





class RevaluationStatus(str, Enum):

    """Status revaluasi."""



    DRAFT = "draft"

    PROCESSED = "processed"

    POSTED = "posted"

    REVERSED = "reversed"

    CANCELLED = "cancelled"





# Default forex settings

DEFAULT_BASE_CURRENCY = CurrencyCode.IDR

DEFAULT_REVALUATION_ACCOUNT_GAIN = "4-9300"  # Pendapatan selisih kurs

DEFAULT_REVALUATION_ACCOUNT_LOSS = "6-9300"  # Beban selisih kurs

SUPPORTED_CURRENCIES = [c.value for c in CurrencyCode]





# Bank Indonesia rates (IDR against major currencies)

BI_RATE_CURRENCIES = [

    "USD",

    "EUR",

    "SGD",

    "JPY",

    "CNY",

    "GBP",

    "AUD",

    "MYR",

    "THB",

    "KRW",

    "HKD",

    "CHF",

    "CAD",

    "SAR",

    "INR",

]





# ============================================================================

# PYDANTIC SCHEMAS

# ============================================================================





class ExchangeRateCreateSchema(BaseModel):

    """Schema untuk membuat kurs baru."""



    model_config = ConfigDict(from_attributes=True)



    from_currency: CurrencyCode = Field(..., description="Mata uang sumber")

    to_currency: CurrencyCode = Field(..., description="Mata uang target")

    rate: Decimal = Field(..., gt=0, decimal_places=6, description="Nilai tukar")

    rate_type: RateType = Field(RateType.MID, description="Jenis kurs")

    effective_date: date = Field(default_factory=date.today, description="Tanggal berlaku")

    provider: RateProvider = Field(RateProvider.MANUAL, description="Sumber kurs")

    bid_rate: Decimal | None = Field(

        None, gt=0, decimal_places=6, description="Kurs bid (harga beli)"

    )

    ask_rate: Decimal | None = Field(

        None, gt=0, decimal_places=6, description="Kurs ask (harga jual)"

    )

    notes: str | None = Field(None, max_length=500, description="Catatan")



    @field_validator("rate")

    @classmethod

    def validate_rate(cls, v: Decimal) -> Decimal:

        if v <= 0:

            raise ValueError("Rate must be greater than 0")

        return v



    @model_validator(mode="after")

    def validate_currencies(self) -> ExchangeRateCreateSchema:

        if self.from_currency == self.to_currency:

            raise ValueError("From and to currencies must be different")

        # Validate bid/ask if provided

        if self.bid_rate and self.ask_rate:

            if self.bid_rate >= self.ask_rate:

                raise ValueError("Bid rate must be less than ask rate")

        return self





class ExchangeRateUpdateSchema(BaseModel):

    """Schema untuk update kurs."""



    model_config = ConfigDict(from_attributes=True)



    rate: Decimal | None = Field(None, gt=0, decimal_places=6)

    bid_rate: Decimal | None = Field(None, gt=0, decimal_places=6)

    ask_rate: Decimal | None = Field(None, gt=0, decimal_places=6)

    provider: RateProvider | None = None

    notes: str | None = Field(None, max_length=500)

    status: RateStatus | None = None





class CurrencyCreateSchema(BaseModel):

    """Request tambah mata uang baru ke currency_master."""

    code: str = Field(..., min_length=3, max_length=3, description="Kode ISO 4217, mis. AUD")

    name: str = Field(..., min_length=1, max_length=100)

    symbol: str | None = Field(None, max_length=10)

    decimal_places: int = Field(2, ge=0, le=6)

    @field_validator("code")

    @classmethod

    def _upper_code(cls, v: str) -> str:

        return v.strip().upper()


class CurrencyResponseSchema(BaseModel):

    """Response satu mata uang dari currency_master."""

    model_config = ConfigDict(from_attributes=True)

    code: str

    name: str

    symbol: str | None

    decimal_places: int

    is_active: bool

    created_by: str | None = None

    created_at: datetime

    updated_at: datetime


class ExchangeRateResponseSchema(BaseModel):

    """Response kurs."""



    model_config = ConfigDict(from_attributes=True)



    id: UUID

    from_currency: CurrencyCode

    to_currency: CurrencyCode

    rate: Decimal

    rate_type: RateType

    effective_date: date

    provider: RateProvider

    bid_rate: Decimal | None

    ask_rate: Decimal | None

    spread: Decimal | None

    spread_percent: float | None

    status: RateStatus

    is_locked: bool = False

    notes: str | None

    created_at: datetime

    updated_at: datetime

    created_by: UUID

    created_by_name: str | None = None

    version: int = 1





class CurrencyConversionRequestSchema(BaseModel):

    """Schema untuk konversi mata uang."""



    model_config = ConfigDict(from_attributes=True)



    from_currency: CurrencyCode = Field(..., description="Mata uang sumber")

    to_currency: CurrencyCode = Field(..., description="Mata uang target")

    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Jumlah yang dikonversi")

    as_of_date: date | None = Field(None, description="Tanggal kurs (default: hari ini)")

    rate_type: RateType = Field(RateType.MID, description="Jenis kurs yang digunakan")

    use_bank_rate: bool = Field(False, description="Gunakan kurs bank (bid/ask)")





class CurrencyConversionResponseSchema(BaseModel):

    """Response konversi mata uang."""



    model_config = ConfigDict(from_attributes=True)



    from_currency: CurrencyCode

    to_currency: CurrencyCode

    from_amount: Decimal

    to_amount: Decimal

    rate_used: Decimal

    rate_type: RateType

    effective_date: date

    converted_at: datetime

    rate_id: UUID | None = None





class BatchConversionRequestSchema(BaseModel):

    """Schema untuk batch konversi mata uang."""



    model_config = ConfigDict(from_attributes=True)



    conversions: list[CurrencyConversionRequestSchema] = Field(..., min_length=1, max_length=100)

    as_of_date: date | None = Field(None, description="Tanggal kurs seragam")





class BatchConversionResponseSchema(BaseModel):

    """Response batch konversi."""



    model_config = ConfigDict(from_attributes=True)



    results: list[CurrencyConversionResponseSchema]

    total_from_amount: Decimal

    total_to_amount: Decimal

    errors: list[dict[str, Any]] = []





class ForexRevaluationRequestSchema(BaseModel):

    """Schema untuk revaluasi mata uang asing."""



    model_config = ConfigDict(from_attributes=True)



    revaluation_date: date = Field(..., description="Tanggal revaluasi")

    functional_currency: CurrencyCode = Field(

        DEFAULT_BASE_CURRENCY, description="Mata uang fungsional"

    )

    account_ids: list[UUID] | None = Field(

        None, description="Akun yang direvaluasi (kosong = semua)"

    )

    post_to_ledger: bool = Field(True, description="Posting ke general ledger")

    gain_account_code: str | None = Field(DEFAULT_REVALUATION_ACCOUNT_GAIN, description="Akun gain")

    loss_account_code: str | None = Field(DEFAULT_REVALUATION_ACCOUNT_LOSS, description="Akun loss")

    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")

    def _apply_account_code_defaults(self) -> "ForexRevaluationRequestSchema":

        """

        CATATAN: gain_account_code/loss_account_code sudah punya default

        string di Field(...) di atas, TAPI Pydantic cuma pakai default itu

        kalau key-nya memang tidak ada di body request - kalau frontend

        kirim eksplisit "gain_account_code": null, validasi tetap gagal

        (Input should be a valid string) karena None-nya dianggap nilai

        yang benar-benar dikirim, bukan "tidak diisi". Frontend memang

        mengirim null eksplisit untuk 2 field ini, jadi fallback-kan ke

        default di sini supaya tidak 422 lagi.

        """

        if self.gain_account_code is None:

            self.gain_account_code = DEFAULT_REVALUATION_ACCOUNT_GAIN

        if self.loss_account_code is None:

            self.loss_account_code = DEFAULT_REVALUATION_ACCOUNT_LOSS

        return self





class ForexRevaluationResponseSchema(BaseModel):

    """Response revaluasi mata uang asing."""



    model_config = ConfigDict(from_attributes=True)



    revaluation_id: UUID

    revaluation_number: str

    revaluation_date: date

    functional_currency: CurrencyCode

    total_foreign_currency_balance: Decimal

    total_gain: Decimal

    total_loss: Decimal

    net_gain_loss: Decimal

    accounts_affected: list[dict[str, Any]]

    journal_id: UUID | None = None

    status: RevaluationStatus

    created_at: datetime

    created_by: UUID

    created_by_name: str | None = None

    posted_at: datetime | None = None

    reversed_at: datetime | None = None





class ForexPositionResponseSchema(BaseModel):

    """Response posisi mata uang asing."""



    model_config = ConfigDict(from_attributes=True)



    as_of_date: date

    functional_currency: CurrencyCode

    by_currency: dict[str, dict[str, Any]]

    total_foreign_currency_balance: Decimal

    total_unrealized_gain: Decimal

    total_unrealized_loss: Decimal

    net_unrealized_position: Decimal

    generated_at: datetime





class HistoricalRateResponseSchema(BaseModel):

    """Response historis kurs."""



    model_config = ConfigDict(from_attributes=True)



    from_currency: CurrencyCode

    to_currency: CurrencyCode

    rate_type: RateType

    entries: list[dict[str, Any]]

    period_start: date

    period_end: date

    average_rate: Decimal

    min_rate: Decimal

    max_rate: Decimal

    volatility: float

    generated_at: datetime





class ForexDashboardResponseSchema(BaseModel):

    """Response dashboard forex."""



    model_config = ConfigDict(from_attributes=True)



    as_of_date: date

    functional_currency: CurrencyCode

    latest_rates: dict[str, dict[str, Any]]

    month_to_date_gain_loss: Decimal

    year_to_date_gain_loss: Decimal

    open_positions: dict[str, Decimal]

    pending_revaluations: int

    last_revaluation_date: date | None = None

    last_revaluation_result: dict[str, Any] | None = None

    rate_providers_status: dict[str, str]

    generated_at: datetime





# ============================================================================

# DEPENDENCY INJECTION

# ============================================================================





async def get_forex_svc(request: Request) -> Any:

    """

    Get Forex Service instance.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    from application.service_layer.service_forex import ForexService



    container = request.app.state.container

    return await container.resolve_async(ForexService)





async def get_forex_revaluation_use_case(request: Request) -> Any:

    """Get Forex Revaluation Use Case instance."""

    from application.use_cases.forex_revaluation import ForexRevaluationUseCase



    container = request.app.state.container

    return await container.resolve_async(ForexRevaluationUseCase)





# ============================================================================

# ROUTER

# ============================================================================



router = APIRouter(prefix="/forex", tags=["Foreign Exchange"])





# ----------------------------------------------------------------------------

# EXCHANGE RATE CRUD

# ----------------------------------------------------------------------------





@router.post(

    "/rates",

    response_model=ExchangeRateResponseSchema,

    status_code=status.HTTP_201_CREATED,

    summary="Create exchange rate",

    operation_id="forex_create_exchange_rate",

)

async def create_exchange_rate(

    request: ExchangeRateCreateSchema,

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:create")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ExchangeRateResponseSchema:

    """

    Create a new exchange rate.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "create_exchange_rate"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return ExchangeRateResponseSchema(**cached)



    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.create_exchange_rate(

            from_currency=request.from_currency.value,

            to_currency=request.to_currency.value,

            rate=request.rate,

            rate_type=request.rate_type.value,

            effective_date=request.effective_date,

            provider=request.provider.value,

            bid_rate=request.bid_rate,

            ask_rate=request.ask_rate,

            notes=request.notes,

            created_by=current_user.user_id,

            legal_entity_id=legal_entity_id,

        )



        response = ExchangeRateResponseSchema(

            id=result.id,

            from_currency=CurrencyCode(result.from_currency),

            to_currency=CurrencyCode(result.to_currency),

            rate=result.rate,

            rate_type=RateType(result.rate_type),

            effective_date=result.effective_date,

            provider=RateProvider(result.provider),

            bid_rate=result.bid_rate,

            ask_rate=result.ask_rate,

            spread=result.spread,

            spread_percent=result.spread_percent,

            status=RateStatus(result.status),

            is_locked=result.is_locked,

            notes=result.notes,

            created_at=result.created_at,

            updated_at=result.updated_at,

            created_by=result.created_by,

            created_by_name=result.created_by_name,

            version=result.version,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to create exchange rate: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/rates/{rate_id}",

    response_model=ExchangeRateResponseSchema,

    summary="Get exchange rate by ID",

    operation_id="forex_get_exchange_rate",

)

async def get_exchange_rate(

    rate_id: UUID,

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ExchangeRateResponseSchema:

    """Get exchange rate by ID."""

    forex_svc.set_context(legal_entity_id)

    try:

        rate = await forex_svc.get_exchange_rate_by_id(rate_id, legal_entity_id)



        if not rate:

            raise HTTPException(status_code=404, detail="Exchange rate not found")



        return ExchangeRateResponseSchema(

            id=rate.id,

            from_currency=CurrencyCode(rate.from_currency),

            to_currency=CurrencyCode(rate.to_currency),

            rate=rate.rate,

            rate_type=RateType(rate.rate_type),

            effective_date=rate.effective_date,

            provider=RateProvider(rate.provider),

            bid_rate=rate.bid_rate,

            ask_rate=rate.ask_rate,

            spread=rate.spread,

            spread_percent=rate.spread_percent,

            status=RateStatus(rate.status),

            is_locked=rate.is_locked,

            notes=rate.notes,

            created_at=rate.created_at,

            updated_at=rate.updated_at,

            created_by=rate.created_by,

            created_by_name=rate.created_by_name,

            version=rate.version,

        )

    except HTTPException:

        raise

    except Exception as e:

        logger.exception(f"Failed to get exchange rate: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/rates/current/{from_currency}/{to_currency}",

    response_model=ExchangeRateResponseSchema,

    summary="Get current exchange rate",

    operation_id="forex_get_current_rate",

)

async def get_current_rate(

    from_currency: CurrencyCode,

    to_currency: CurrencyCode,

    rate_type: RateType = Query(RateType.MID, description="Rate type"),

    as_of_date: date | None = Query(None, description="As of date (default: today)"),

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ExchangeRateResponseSchema:

    """Get current exchange rate for currency pair."""

    forex_svc.set_context(legal_entity_id)

    try:

        rate = await forex_svc.get_current_rate(

            from_currency=from_currency.value,

            to_currency=to_currency.value,

            rate_type=rate_type.value,

            as_of_date=as_of_date or date.today(),

            legal_entity_id=legal_entity_id,

        )



        if not rate:

            raise HTTPException(

                status_code=404,

                detail=f"Exchange rate not found for {from_currency.value}/{to_currency.value}",

            )



        return ExchangeRateResponseSchema(

            id=rate.id,

            from_currency=CurrencyCode(rate.from_currency),

            to_currency=CurrencyCode(rate.to_currency),

            rate=rate.rate,

            rate_type=RateType(rate.rate_type),

            effective_date=rate.effective_date,

            provider=RateProvider(rate.provider),

            bid_rate=rate.bid_rate,

            ask_rate=rate.ask_rate,

            spread=rate.spread,

            spread_percent=rate.spread_percent,

            status=RateStatus(rate.status),

            is_locked=rate.is_locked,

            notes=rate.notes,

            created_at=rate.created_at,

            updated_at=rate.updated_at,

            created_by=rate.created_by,

            created_by_name=rate.created_by_name,

            version=rate.version,

        )

    except HTTPException:

        raise

    except Exception as e:

        logger.exception(f"Failed to get current rate: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/rates",

    response_model=list[ExchangeRateResponseSchema],

    summary="List exchange rates",

    operation_id="forex_list_exchange_rates",

)

async def list_exchange_rates(

    from_currency: CurrencyCode | None = Query(None, description="Filter by from currency"),

    to_currency: CurrencyCode | None = Query(None, description="Filter by to currency"),

    rate_type: RateType | None = Query(None, description="Filter by rate type"),

    effective_date: date | None = Query(None, description="Filter by effective date"),

    provider: RateProvider | None = Query(None, description="Filter by provider"),

    page: int = Query(1, ge=1),

    page_size: int = Query(50, ge=1, le=500),

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> list[ExchangeRateResponseSchema]:

    """List exchange rates with filters."""

    forex_svc.set_context(legal_entity_id)

    try:

        rates = await forex_svc.list_exchange_rates(

            legal_entity_id=legal_entity_id,

            from_currency=from_currency.value if from_currency else None,

            to_currency=to_currency.value if to_currency else None,

            rate_type=rate_type.value if rate_type else None,

            effective_date=effective_date,

            provider=provider.value if provider else None,

            page=page,

            page_size=page_size,

        )



        return [

            ExchangeRateResponseSchema(

                id=r.id,

                from_currency=CurrencyCode(r.from_currency),

                to_currency=CurrencyCode(r.to_currency),

                rate=r.rate,

                rate_type=RateType(r.rate_type),

                effective_date=r.effective_date,

                provider=RateProvider(r.provider),

                bid_rate=r.bid_rate,

                ask_rate=r.ask_rate,

                spread=r.spread,

                spread_percent=r.spread_percent,

                status=RateStatus(r.status),

                is_locked=r.is_locked,

                notes=r.notes,

                created_at=r.created_at,

                updated_at=r.updated_at,

                created_by=r.created_by,

                created_by_name=r.created_by_name,

                version=r.version,

            )

            for r in rates

        ]

    except Exception as e:

        logger.exception(f"Failed to list exchange rates: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.put(

    "/rates/{rate_id}",

    response_model=ExchangeRateResponseSchema,

    summary="Update exchange rate",

    operation_id="forex_update_exchange_rate",

)

async def update_exchange_rate(

    rate_id: UUID,

    request: ExchangeRateUpdateSchema,

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:update")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ExchangeRateResponseSchema:

    """

    Update an exchange rate.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "update_exchange_rate"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return ExchangeRateResponseSchema(**cached)



    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.update_exchange_rate(

            rate_id=rate_id,

            legal_entity_id=legal_entity_id,

            rate=request.rate,

            bid_rate=request.bid_rate,

            ask_rate=request.ask_rate,

            provider=request.provider.value if request.provider else None,

            notes=request.notes,

            status=request.status.value if request.status else None,

            updated_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(status_code=404, detail="Exchange rate not found")



        response = ExchangeRateResponseSchema(

            id=result.id,

            from_currency=CurrencyCode(result.from_currency),

            to_currency=CurrencyCode(result.to_currency),

            rate=result.rate,

            rate_type=RateType(result.rate_type),

            effective_date=result.effective_date,

            provider=RateProvider(result.provider),

            bid_rate=result.bid_rate,

            ask_rate=result.ask_rate,

            spread=result.spread,

            spread_percent=result.spread_percent,

            status=RateStatus(result.status),

            is_locked=result.is_locked,

            notes=result.notes,

            created_at=result.created_at,

            updated_at=result.updated_at,

            created_by=result.created_by,

            created_by_name=result.created_by_name,

            version=result.version,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to update exchange rate: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.delete(

    "/rates/{rate_id}",

    response_model=dict[str, Any],

    summary="Deactivate exchange rate",

    operation_id="forex_deactivate_exchange_rate",

)

async def deactivate_exchange_rate(

    rate_id: UUID,

    reason: str = Query("", description="Reason for deactivation"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:delete")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> dict[str, Any]:

    """

    Deactivate an exchange rate.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "deactivate_exchange_rate"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return cached



    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.deactivate_exchange_rate(

            rate_id=rate_id,

            legal_entity_id=legal_entity_id,

            reason=reason,

            deactivated_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(status_code=404, detail="Exchange rate not found")



        response = {

            "rate_id": str(rate_id),

            "from_currency": result.from_currency,

            "to_currency": result.to_currency,

            "effective_date": result.effective_date.isoformat(),

            "status": result.status,

            "message": "Exchange rate deactivated",

        }



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response)



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to deactivate exchange rate: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/rates/{rate_id}/lock",

    response_model=ExchangeRateResponseSchema,

    summary="Lock exchange rate",

    operation_id="forex_lock_exchange_rate",

)

async def lock_exchange_rate(

    rate_id: UUID,

    reason: str = Query("", description="Lock reason"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:lock")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ExchangeRateResponseSchema:

    """

    Lock an exchange rate to prevent modifications.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "lock_exchange_rate"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return ExchangeRateResponseSchema(**cached)



    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.lock_exchange_rate(

            rate_id=rate_id,

            legal_entity_id=legal_entity_id,

            reason=reason,

            locked_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(status_code=404, detail="Exchange rate not found")



        response = ExchangeRateResponseSchema(

            id=result.id,

            from_currency=CurrencyCode(result.from_currency),

            to_currency=CurrencyCode(result.to_currency),

            rate=result.rate,

            rate_type=RateType(result.rate_type),

            effective_date=result.effective_date,

            provider=RateProvider(result.provider),

            bid_rate=result.bid_rate,

            ask_rate=result.ask_rate,

            spread=result.spread,

            spread_percent=result.spread_percent,

            status=RateStatus(result.status),

            is_locked=True,

            notes=result.notes,

            created_at=result.created_at,

            updated_at=result.updated_at,

            created_by=result.created_by,

            created_by_name=result.created_by_name,

            version=result.version,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to lock exchange rate: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/rates/{rate_id}/unlock",

    response_model=ExchangeRateResponseSchema,

    summary="Unlock exchange rate",

    operation_id="forex_unlock_exchange_rate",

)

async def unlock_exchange_rate(

    rate_id: UUID,

    reason: str = Query("", description="Unlock reason"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:lock")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ExchangeRateResponseSchema:

    """

    Unlock a locked exchange rate.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "unlock_exchange_rate"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return ExchangeRateResponseSchema(**cached)



    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.unlock_exchange_rate(

            rate_id=rate_id,

            legal_entity_id=legal_entity_id,

            reason=reason,

            unlocked_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(status_code=404, detail="Exchange rate not found")



        response = ExchangeRateResponseSchema(

            id=result.id,

            from_currency=CurrencyCode(result.from_currency),

            to_currency=CurrencyCode(result.to_currency),

            rate=result.rate,

            rate_type=RateType(result.rate_type),

            effective_date=result.effective_date,

            provider=RateProvider(result.provider),

            bid_rate=result.bid_rate,

            ask_rate=result.ask_rate,

            spread=result.spread,

            spread_percent=result.spread_percent,

            status=RateStatus(result.status),

            is_locked=False,

            notes=result.notes,

            created_at=result.created_at,

            updated_at=result.updated_at,

            created_by=result.created_by,

            created_by_name=result.created_by_name,

            version=result.version,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to unlock exchange rate: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# CURRENCY CONVERSION

# ----------------------------------------------------------------------------





@router.post(

    "/convert",

    response_model=CurrencyConversionResponseSchema,

    summary="Convert currency",

    operation_id="forex_convert_currency",

)

async def convert_currency(

    request: CurrencyConversionRequestSchema,

    _permission: None = Depends(require_permission("forex:convert")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> CurrencyConversionResponseSchema:

    """Convert amount from one currency to another."""

    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.convert_currency(

            from_currency=request.from_currency.value,

            to_currency=request.to_currency.value,

            amount=request.amount,

            as_of_date=request.as_of_date,

            rate_type=request.rate_type.value,

            use_bank_rate=request.use_bank_rate,

            legal_entity_id=legal_entity_id,

        )



        return CurrencyConversionResponseSchema(

            from_currency=CurrencyCode(result.from_currency),

            to_currency=CurrencyCode(result.to_currency),

            from_amount=result.from_amount,

            to_amount=result.to_amount,

            rate_used=result.rate_used,

            rate_type=RateType(result.rate_type),

            effective_date=result.effective_date,

            converted_at=result.converted_at,

            rate_id=result.rate_id,

        )

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to convert currency: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/convert/batch",

    response_model=BatchConversionResponseSchema,

    summary="Batch convert currencies",

    operation_id="forex_batch_convert_currency",

)

async def batch_convert_currency(

    request: BatchConversionRequestSchema,

    _permission: None = Depends(require_permission("forex:convert")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> BatchConversionResponseSchema:

    """Convert multiple amounts in batch."""

    forex_svc.set_context(legal_entity_id)

    try:

        results = []

        total_from = Decimal(0)

        total_to = Decimal(0)

        errors = []



        for conv in request.conversions:

            try:

                result = await forex_svc.convert_currency(

                    from_currency=conv.from_currency.value,

                    to_currency=conv.to_currency.value,

                    amount=conv.amount,

                    as_of_date=request.as_of_date or conv.as_of_date,

                    rate_type=conv.rate_type.value,

                    use_bank_rate=conv.use_bank_rate,

                    legal_entity_id=legal_entity_id,

                )

                results.append(

                    CurrencyConversionResponseSchema(

                        from_currency=CurrencyCode(result.from_currency),

                        to_currency=CurrencyCode(result.to_currency),

                        from_amount=result.from_amount,

                        to_amount=result.to_amount,

                        rate_used=result.rate_used,

                        rate_type=RateType(result.rate_type),

                        effective_date=result.effective_date,

                        converted_at=result.converted_at,

                        rate_id=result.rate_id,

                    )

                )

                total_from += result.from_amount

                total_to += result.to_amount

            except Exception as e:

                errors.append({"conversion": conv.dict(), "error": str(e)})



        return BatchConversionResponseSchema(

            results=results,

            total_from_amount=total_from,

            total_to_amount=total_to,

            errors=errors,

        )

    except Exception as e:

        logger.exception("Failed to batch convert currency: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# HISTORICAL RATES

# ----------------------------------------------------------------------------





@router.get(

    "/history/{from_currency}/{to_currency}",

    response_model=HistoricalRateResponseSchema,

    summary="Get historical exchange rates",

    operation_id="forex_get_historical_rates",

)

async def get_historical_rates(

    from_currency: CurrencyCode,

    to_currency: CurrencyCode,

    start_date: date = Query(..., description="Start date"),

    end_date: date = Query(..., description="End date"),

    rate_type: RateType = Query(RateType.MID, description="Rate type"),

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> HistoricalRateResponseSchema:

    """Get historical exchange rates for a period."""

    forex_svc.set_context(legal_entity_id)

    try:

        history = await forex_svc.get_historical_rates(

            from_currency=from_currency.value,

            to_currency=to_currency.value,

            start_date=start_date,

            end_date=end_date,

            rate_type=rate_type.value,

            legal_entity_id=legal_entity_id,

        )



        return HistoricalRateResponseSchema(

            from_currency=from_currency,

            to_currency=to_currency,

            rate_type=rate_type,

            entries=history.entries,

            period_start=start_date,

            period_end=end_date,

            average_rate=history.average_rate,

            min_rate=history.min_rate,

            max_rate=history.max_rate,

            volatility=history.volatility,

            generated_at=datetime.now(),

        )

    except Exception as e:

        logger.exception("Failed to get historical rates: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# FOREX REVALUATION

# ----------------------------------------------------------------------------





@router.post(

    "/revaluation",

    response_model=ForexRevaluationResponseSchema,

    status_code=status.HTTP_201_CREATED,

    summary="Run forex revaluation",

    operation_id="forex_run_forex_revaluation",

)

async def run_forex_revaluation(

    request: ForexRevaluationRequestSchema,

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:revaluate")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    revaluation_use_case: Any = Depends(get_forex_revaluation_use_case),

) -> ForexRevaluationResponseSchema:

    """

    Run forex revaluation for monetary items.



    - Revaluates foreign currency balances to functional currency

    - Calculates unrealized gain/loss

    - Creates journal entry if post_to_ledger is true

    - LOCKING: Use case layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "run_forex_revaluation"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return ForexRevaluationResponseSchema(**cached)



    try:

        result = await revaluation_use_case.execute(

            legal_entity_id=legal_entity_id,

            revaluation_date=request.revaluation_date,

            functional_currency=request.functional_currency.value,

            account_ids=request.account_ids,

            post_to_ledger=request.post_to_ledger,

            gain_account_code=request.gain_account_code,

            loss_account_code=request.loss_account_code,

            notes=request.notes,

            performed_by=current_user.user_id,

        )



        response = ForexRevaluationResponseSchema(

            revaluation_id=result.revaluation_id,

            revaluation_number=result.revaluation_number,

            revaluation_date=request.revaluation_date,

            functional_currency=CurrencyCode(result.functional_currency),

            total_foreign_currency_balance=result.total_foreign_currency_balance,

            total_gain=result.total_gain,

            total_loss=result.total_loss,

            net_gain_loss=result.net_gain_loss,

            accounts_affected=result.accounts_affected,

            journal_id=result.journal_id,

            status=RevaluationStatus(result.status),

            created_at=result.created_at,

            created_by=result.created_by,

            created_by_name=result.created_by_name,

            posted_at=result.posted_at,

            reversed_at=result.reversed_at,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to run forex revaluation: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/revaluation",

    response_model=list[ForexRevaluationResponseSchema],

    summary="List forex revaluations",

    operation_id="forex_list_forex_revaluations",

)

async def list_forex_revaluations(

    start_date: date | None = Query(None, description="Start date"),

    end_date: date | None = Query(None, description="End date"),

    status: RevaluationStatus | None = Query(None, description="Filter by status"),

    page: int = Query(1, ge=1),

    page_size: int = Query(20, ge=1, le=100),

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> list[ForexRevaluationResponseSchema]:

    """List forex revaluation runs."""

    forex_svc.set_context(legal_entity_id)

    try:

        revaluations = await forex_svc.list_revaluations(

            legal_entity_id=legal_entity_id,

            start_date=start_date,

            end_date=end_date,

            status=status.value if status else None,

            page=page,

            page_size=page_size,

        )



        return [

            ForexRevaluationResponseSchema(

                revaluation_id=r.id,

                revaluation_number=r.revaluation_number,

                revaluation_date=r.revaluation_date,

                functional_currency=CurrencyCode(r.functional_currency),

                total_foreign_currency_balance=r.total_foreign_currency_balance,

                total_gain=r.total_gain,

                total_loss=r.total_loss,

                net_gain_loss=r.net_gain_loss,

                accounts_affected=r.accounts_affected,

                journal_id=r.journal_id,

                status=RevaluationStatus(r.status),

                created_at=r.created_at,

                created_by=r.created_by,

                created_by_name=r.created_by_name,

                posted_at=r.posted_at,

                reversed_at=r.reversed_at,

            )

            for r in revaluations

        ]

    except Exception as e:

        logger.exception("Failed to list forex revaluations: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/revaluation/{revaluation_id}",

    response_model=ForexRevaluationResponseSchema,

    summary="Get forex revaluation by ID",

    operation_id="forex_get_forex_revaluation",

)

async def get_forex_revaluation(

    revaluation_id: UUID,

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ForexRevaluationResponseSchema:

    """Get forex revaluation by ID."""

    forex_svc.set_context(legal_entity_id)

    try:

        revaluation = await forex_svc.get_revaluation_by_id(revaluation_id, legal_entity_id)



        if not revaluation:

            raise HTTPException(status_code=404, detail="Revaluation not found")



        return ForexRevaluationResponseSchema(

            revaluation_id=revaluation.id,

            revaluation_number=revaluation.revaluation_number,

            revaluation_date=revaluation.revaluation_date,

            functional_currency=CurrencyCode(revaluation.functional_currency),

            total_foreign_currency_balance=revaluation.total_foreign_currency_balance,

            total_gain=revaluation.total_gain,

            total_loss=revaluation.total_loss,

            net_gain_loss=revaluation.net_gain_loss,

            accounts_affected=revaluation.accounts_affected,

            journal_id=revaluation.journal_id,

            status=RevaluationStatus(revaluation.status),

            created_at=revaluation.created_at,

            created_by=revaluation.created_by,

            created_by_name=revaluation.created_by_name,

            posted_at=revaluation.posted_at,

            reversed_at=revaluation.reversed_at,

        )

    except HTTPException:

        raise

    except Exception as e:

        logger.exception("Failed to get forex revaluation: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/revaluation/{revaluation_id}/reverse",

    response_model=ForexRevaluationResponseSchema,

    summary="Reverse forex revaluation",

    operation_id="forex_reverse_forex_revaluation",

)

async def reverse_forex_revaluation(

    revaluation_id: UUID,

    reason: str = Query(..., min_length=5, description="Reversal reason"),

    reversal_date: date = Query(default_factory=date.today, description="Reversal date"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:revaluate")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ForexRevaluationResponseSchema:

    """

    Reverse a forex revaluation entry.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "reverse_forex_revaluation"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return ForexRevaluationResponseSchema(**cached)



    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.reverse_revaluation(

            revaluation_id=revaluation_id,

            legal_entity_id=legal_entity_id,

            reversal_date=reversal_date,

            reason=reason,

            reversed_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(

                status_code=404, detail="Revaluation not found or cannot be reversed"

            )



        response = ForexRevaluationResponseSchema(

            revaluation_id=result.id,

            revaluation_number=result.revaluation_number,

            revaluation_date=result.revaluation_date,

            functional_currency=CurrencyCode(result.functional_currency),

            total_foreign_currency_balance=result.total_foreign_currency_balance,

            total_gain=result.total_gain,

            total_loss=result.total_loss,

            net_gain_loss=result.net_gain_loss,

            accounts_affected=result.accounts_affected,

            journal_id=result.journal_id,

            status=RevaluationStatus(result.status),

            created_at=result.created_at,

            created_by=result.created_by,

            created_by_name=result.created_by_name,

            posted_at=result.posted_at,

            reversed_at=result.reversed_at,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to reverse revaluation: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# FOREX POSITION & DASHBOARD

# ----------------------------------------------------------------------------





@router.get(

    "/position",

    response_model=ForexPositionResponseSchema,

    summary="Get forex position",

    operation_id="forex_get_forex_position",

)

async def get_forex_position(

    as_of_date: date = Query(

        default_factory=date.today,

        description="As of date (default: hari ini kalau tidak dikirim)",

    ),

    functional_currency: CurrencyCode = Query(

        DEFAULT_BASE_CURRENCY, description="Functional currency"

    ),

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ForexPositionResponseSchema:

    """Get foreign currency position (open positions, unrealized gain/loss)."""

    forex_svc.set_context(legal_entity_id)

    try:

        position = await forex_svc.get_forex_position(

            legal_entity_id=legal_entity_id,

            as_of_date=as_of_date,

            functional_currency=functional_currency.value,

        )



        return ForexPositionResponseSchema(

            as_of_date=as_of_date,

            functional_currency=functional_currency,

            by_currency=position.by_currency,

            total_foreign_currency_balance=position.total_foreign_currency_balance,

            total_unrealized_gain=position.total_unrealized_gain,

            total_unrealized_loss=position.total_unrealized_loss,

            net_unrealized_position=position.net_unrealized_position,

            generated_at=datetime.now(),

        )

    except Exception as e:

        logger.exception("Failed to get forex position: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/dashboard",

    response_model=ForexDashboardResponseSchema,

    summary="Get forex dashboard",

    operation_id="forex_get_forex_dashboard",

)

async def get_forex_dashboard(

    as_of_date: date = Query(

        default_factory=date.today,

        description="As of date (default: hari ini kalau tidak dikirim)",

    ),

    functional_currency: CurrencyCode = Query(

        DEFAULT_BASE_CURRENCY, description="Functional currency"

    ),

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> ForexDashboardResponseSchema:

    """Get forex dashboard with latest rates and summary."""

    forex_svc.set_context(legal_entity_id)

    try:

        dashboard = await forex_svc.get_forex_dashboard(

            legal_entity_id=legal_entity_id,

            as_of_date=as_of_date,

            functional_currency=functional_currency.value,

        )



        return ForexDashboardResponseSchema(

            as_of_date=as_of_date,

            functional_currency=functional_currency,

            latest_rates=dashboard.latest_rates,

            month_to_date_gain_loss=dashboard.month_to_date_gain_loss,

            year_to_date_gain_loss=dashboard.year_to_date_gain_loss,

            open_positions=dashboard.open_positions,

            pending_revaluations=dashboard.pending_revaluations,

            last_revaluation_date=dashboard.last_revaluation_date,

            last_revaluation_result=dashboard.last_revaluation_result,

            rate_providers_status=dashboard.rate_providers_status,

            generated_at=datetime.now(),

        )

    except Exception as e:

        logger.exception("Failed to get forex dashboard: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# CURRENCY MASTER

# ----------------------------------------------------------------------------

# CATATAN: endpoint2 ini SEBELUMNYA TIDAK ADA SAMA SEKALI (fitur "Tambah

# Mata Uang Baru" di UI selalu 404). Daftar mata uang sekarang datang dari

# tabel currency_master (migrasi b2c3d4e5f6a7), bukan CurrencyCode Enum

# yang di-hardcode lagi untuk endpoint2 ini secara khusus - supaya benar2

# bisa menambah mata uang baru di luar daftar lama.


@router.get(

    "/currencies",

    response_model=list[CurrencyResponseSchema],

    summary="List mata uang",

    operation_id="forex_list_currencies",

)

async def list_currencies(

    is_active: bool | None = Query(True, description="Filter status aktif"),

    _permission: None = Depends(require_permission("forex:read")),

    forex_svc: Any = Depends(get_forex_svc),

    session: AsyncSession = Depends(get_db_session),

) -> list[CurrencyResponseSchema]:

    """List semua mata uang di currency_master."""

    forex_svc.set_context(None)

    try:

        rows = await forex_svc.list_currencies(is_active=is_active)

        return [CurrencyResponseSchema(**row) for row in rows]

    except Exception as e:

        logger.exception("Failed to list currencies: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(

    "/currencies",

    response_model=CurrencyResponseSchema,

    status_code=status.HTTP_201_CREATED,

    summary="Tambah mata uang baru",

    operation_id="forex_create_currency",

)

async def create_currency(

    request: CurrencyCreateSchema,

    _permission: None = Depends(require_permission("forex:create")),

    current_user: TokenPayload = Depends(get_current_user),

    forex_svc: Any = Depends(get_forex_svc),

    session: AsyncSession = Depends(get_db_session),

) -> CurrencyResponseSchema:

    """Tambah mata uang baru ke currency_master."""

    forex_svc.set_context(None)

    try:

        row = await forex_svc.create_currency(

            code=request.code,

            name=request.name,

            symbol=request.symbol,

            decimal_places=request.decimal_places,

            created_by=current_user.user_id,

        )

        return CurrencyResponseSchema(**row)

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to create currency: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(

    "/currencies/{code}",

    response_model=CurrencyResponseSchema,

    summary="Nonaktifkan mata uang",

    operation_id="forex_deactivate_currency",

)

async def deactivate_currency(

    code: str,

    _permission: None = Depends(require_permission("forex:delete")),

    current_user: TokenPayload = Depends(get_current_user),

    forex_svc: Any = Depends(get_forex_svc),

    session: AsyncSession = Depends(get_db_session),

) -> CurrencyResponseSchema:

    """Nonaktifkan mata uang (soft-deactivate, bukan hapus permanen)."""

    forex_svc.set_context(None)

    try:

        row = await forex_svc.deactivate_currency(code, current_user.user_id)

        if not row:

            raise HTTPException(status_code=404, detail="Mata uang tidak ditemukan")

        return CurrencyResponseSchema(**row)

    except HTTPException:

        raise

    except Exception as e:

        logger.exception("Failed to deactivate currency: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------

# RATE PROVIDER SYNC

# ----------------------------------------------------------------------------





@router.post(

    "/sync/{provider}",

    response_model=dict[str, Any],

    summary="Sync rates from provider",

    operation_id="forex_sync_rates_from_provider",

)

async def sync_rates_from_provider(

    provider: RateProvider,

    effective_date: date = Query(default_factory=date.today, description="Effective date"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("forex:sync")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> dict[str, Any]:

    """

    Sync exchange rates from external provider (Bank Indonesia, Bloomberg, etc.).

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "sync_rates_from_provider"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return cached



    forex_svc.set_context(legal_entity_id)

    try:

        result = await forex_svc.sync_rates_from_provider(

            legal_entity_id=legal_entity_id,

            provider=provider.value,

            effective_date=effective_date,

            synced_by=current_user.user_id,

        )



        response = {

            "provider": provider.value,

            "effective_date": effective_date.isoformat(),

            "rates_synced": result.rates_synced,

            "new_rates": result.new_rates,

            "updated_rates": result.updated_rates,

            "failed_currencies": result.failed_currencies,

            "errors": result.errors,

            "message": f"Successfully synced {result.rates_synced} rates",

        }



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response)



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to sync rates from provider: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# RATE HISTORY & AUDIT

# ----------------------------------------------------------------------------





@router.get(

    "/rates/{rate_id}/history",

    response_model=list[dict[str, Any]],

    summary="Get rate change history",

    operation_id="forex_get_rate_history",

)

async def get_rate_history(

    rate_id: UUID,

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> list[dict[str, Any]]:

    """Get exchange rate change history (audit trail)."""

    forex_svc.set_context(legal_entity_id)

    try:

        history = await forex_svc.get_rate_history(rate_id, legal_entity_id)



        return [

            {

                "timestamp": h.timestamp.isoformat(),

                "action": h.action,

                "field": h.field,

                "old_value": h.old_value,

                "new_value": h.new_value,

                "actor_id": str(h.actor_id),

                "actor_name": h.actor_name,

                "reason": h.reason,

            }

            for h in history

        ]

    except Exception as e:

        logger.exception("Failed to get rate history: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/rates/{rate_id}/status",

    response_model=dict[str, Any],

    summary="Get rate status",

    operation_id="forex_get_rate_status",

)

async def get_rate_status(

    rate_id: UUID,

    _permission: None = Depends(require_permission("forex:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> dict[str, Any]:

    """Get detailed exchange rate status."""

    forex_svc.set_context(legal_entity_id)

    try:

        status_info = await forex_svc.get_rate_status(rate_id, legal_entity_id)



        if not status_info:

            raise HTTPException(status_code=404, detail="Exchange rate not found")



        return {

            "rate_id": str(rate_id),

            "from_currency": status_info.from_currency,

            "to_currency": status_info.to_currency,

            "status": status_info.status,

            "is_locked": status_info.is_locked,

            "can_edit": status_info.can_edit,

            "can_delete": status_info.can_delete,

            "can_lock": status_info.can_lock,

            "effective_date": status_info.effective_date.isoformat(),

            "expiry_date": status_info.expiry_date.isoformat() if status_info.expiry_date else None,

            "current_rate": float(status_info.current_rate),

            "previous_rate": float(status_info.previous_rate)

            if status_info.previous_rate

            else None,

            "change_percent": status_info.change_percent,

            "last_updated": status_info.last_updated.isoformat()

            if status_info.last_updated

            else None,

        }

    except HTTPException:

        raise

    except Exception as e:

        logger.exception("Failed to get rate status: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# EXPORT

# ----------------------------------------------------------------------------





@router.get(

    "/export/rates",

    summary="Export exchange rates",

    operation_id="forex_export_exchange_rates",

)

async def export_exchange_rates(

    start_date: date = Query(..., description="Start date"),

    end_date: date = Query(..., description="End date"),

    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),

    from_currency: CurrencyCode | None = Query(None, description="Filter by from currency"),

    _permission: None = Depends(require_permission("forex:export")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> Response:

    """Export exchange rates to CSV or Excel."""

    forex_svc.set_context(legal_entity_id)

    try:

        data = await forex_svc.export_rates(

            legal_entity_id=legal_entity_id,

            start_date=start_date,

            end_date=end_date,

            format=format,

            from_currency=from_currency.value if from_currency else None,

        )



        media_type = (

            "text/csv"

            if format == "csv"

            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        )

        filename = f"exchange_rates_{legal_entity_id}_{start_date}_{end_date}.{format}"



        return Response(

            content=data,

            media_type=media_type,

            headers={"Content-Disposition": f"attachment; filename={filename}"},

        )

    except Exception as e:

        logger.exception("Failed to export exchange rates: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/export/revaluations",

    summary="Export revaluation history",

    operation_id="forex_export_revaluation_history",

)

async def export_revaluation_history(

    start_date: date = Query(..., description="Start date"),

    end_date: date = Query(..., description="End date"),

    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),

    _permission: None = Depends(require_permission("forex:export")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    forex_svc: Any = Depends(get_forex_svc),

) -> Response:

    """Export revaluation history to CSV or Excel."""

    forex_svc.set_context(legal_entity_id)

    try:

        data = await forex_svc.export_revaluation_history(

            legal_entity_id=legal_entity_id,

            start_date=start_date,

            end_date=end_date,

            format=format,

        )



        media_type = (

            "text/csv"

            if format == "csv"

            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        )

        filename = f"revaluation_history_{legal_entity_id}_{start_date}_{end_date}.{format}"



        return Response(

            content=data,

            media_type=media_type,

            headers={"Content-Disposition": f"attachment; filename={filename}"},

        )

    except Exception as e:

        logger.exception("Failed to export revaluation history: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# EXPORTS

# ----------------------------------------------------------------------------



__all__ = ["router"]

