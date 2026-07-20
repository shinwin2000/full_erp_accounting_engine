# adapters/primary_api/v1/test_fastapi_forex_router.py
"""
Comprehensive unit tests for FastAPI Forex Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_forex_router import (
    BatchConversionRequestSchema,
    BatchConversionResponseSchema,
    CurrencyCode,
    CurrencyConversionRequestSchema,
    CurrencyConversionResponseSchema,
    ExchangeRateCreateSchema,
    ExchangeRateResponseSchema,
    ExchangeRateUpdateSchema,
    ForexDashboardResponseSchema,
    ForexPositionResponseSchema,
    ForexRevaluationRequestSchema,
    ForexRevaluationResponseSchema,
    HistoricalRateResponseSchema,
    IdempotencyManager,
    RateProvider,
    RateStatus,
    RateType,
    RevaluationStatus,
    batch_convert_currency,
    convert_currency,
    create_exchange_rate,
    deactivate_exchange_rate,
    export_exchange_rates,
    export_revaluation_history,
    get_current_rate,
    get_exchange_rate,
    get_forex_dashboard,
    get_forex_position,
    get_forex_revaluation,
    get_historical_rates,
    get_rate_history,
    get_rate_status,
    list_exchange_rates,
    list_forex_revaluations,
    lock_exchange_rate,
    reverse_forex_revaluation,
    run_forex_revaluation,
    sync_rates_from_provider,
    unlock_exchange_rate,
    update_exchange_rate,
)

# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_forex_service():
    svc = AsyncMock()

    # Rate responses
    svc.create_exchange_rate.return_value = MagicMock(
        id=uuid4(),
        from_currency="USD",
        to_currency="IDR",
        rate=Decimal("15500.00"),
        rate_type="mid",
        effective_date=date.today(),
        provider="manual",
        bid_rate=Decimal("15400.00"),
        ask_rate=Decimal("15600.00"),
        spread=Decimal("200.00"),
        spread_percent=1.29,
        status="active",
        is_locked=False,
        notes="Test rate",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_exchange_rate_by_id.return_value = svc.create_exchange_rate.return_value
    svc.get_current_rate.return_value = svc.create_exchange_rate.return_value
    svc.list_exchange_rates.return_value = [svc.create_exchange_rate.return_value]
    svc.update_exchange_rate.return_value = svc.create_exchange_rate.return_value
    svc.deactivate_exchange_rate.return_value = MagicMock(
        from_currency="USD",
        to_currency="IDR",
        effective_date=date.today(),
        status="inactive",
    )
    svc.lock_exchange_rate.return_value = svc.create_exchange_rate.return_value
    svc.unlock_exchange_rate.return_value = svc.create_exchange_rate.return_value

    # Conversion responses
    svc.convert_currency.return_value = MagicMock(
        from_currency="USD",
        to_currency="IDR",
        from_amount=Decimal("100"),
        to_amount=Decimal("1550000"),
        rate_used=Decimal("15500"),
        rate_type="mid",
        effective_date=date.today(),
        converted_at=datetime.now(UTC),
        rate_id=uuid4(),
    )

    # Historical rates
    svc.get_historical_rates.return_value = MagicMock(
        entries=[{"date": date.today(), "rate": 15500}],
        average_rate=Decimal("15500"),
        min_rate=Decimal("15400"),
        max_rate=Decimal("15600"),
        volatility=0.5,
    )

    # Revaluation responses
    svc.run_revaluation.return_value = MagicMock(
        revaluation_id=uuid4(),
        revaluation_number="REV-2025-001",
        revaluation_date=date.today(),
        functional_currency="IDR",
        total_foreign_currency_balance=Decimal("1000000"),
        total_gain=Decimal("10000"),
        total_loss=Decimal("5000"),
        net_gain_loss=Decimal("5000"),
        accounts_affected=[{"account": "1-1000", "amount": 5000}],
        journal_id=uuid4(),
        status="processed",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        posted_at=datetime.now(UTC),
        reversed_at=None,
    )
    svc.get_revaluation_by_id.return_value = svc.run_revaluation.return_value
    svc.list_revaluations.return_value = [svc.run_revaluation.return_value]
    svc.reverse_revaluation.return_value = svc.run_revaluation.return_value

    # Position & dashboard
    svc.get_forex_position.return_value = MagicMock(
        by_currency={"USD": {"balance": 10000, "unrealized_gain": 100}},
        total_foreign_currency_balance=Decimal("10000"),
        total_unrealized_gain=Decimal("100"),
        total_unrealized_loss=Decimal("0"),
        net_unrealized_position=Decimal("100"),
    )
    svc.get_forex_dashboard.return_value = MagicMock(
        latest_rates={"USD/IDR": 15500},
        month_to_date_gain_loss=Decimal("100"),
        year_to_date_gain_loss=Decimal("500"),
        open_positions={"USD": 10000},
        pending_revaluations=0,
        last_revaluation_date=date.today(),
        last_revaluation_result={"gain": 100, "loss": 0},
        rate_providers_status={"manual": "ok", "bank_indonesia": "ok"},
    )

    # Sync
    svc.sync_rates_from_provider.return_value = MagicMock(
        rates_synced=10,
        new_rates=5,
        updated_rates=5,
        failed_currencies=[],
        errors=[],
    )

    # History & status
    svc.get_rate_history.return_value = []
    svc.get_rate_status.return_value = MagicMock(
        from_currency="USD",
        to_currency="IDR",
        status="active",
        is_locked=False,
        can_edit=True,
        can_delete=True,
        can_lock=True,
        effective_date=date.today(),
        expiry_date=None,
        current_rate=Decimal("15500"),
        previous_rate=Decimal("15400"),
        change_percent=0.65,
        last_updated=datetime.now(UTC),
    )

    # Export
    svc.export_rates.return_value = b"csv data"
    svc.export_revaluation_history.return_value = b"csv data"

    return svc


@pytest.fixture
def mock_revaluation_use_case():
    uc = AsyncMock()
    uc.execute.return_value = MagicMock(
        revaluation_id=uuid4(),
        revaluation_number="REV-2025-001",
        revaluation_date=date.today(),
        functional_currency="IDR",
        total_foreign_currency_balance=Decimal("1000000"),
        total_gain=Decimal("10000"),
        total_loss=Decimal("5000"),
        net_gain_loss=Decimal("5000"),
        accounts_affected=[{"account": "1-1000", "amount": 5000}],
        journal_id=uuid4(),
        status="processed",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        posted_at=datetime.now(UTC),
        reversed_at=None,
    )
    return uc


# =============================================================================
# Tests for IdempotencyManager
# =============================================================================

class TestIdempotencyManager:
    def test_initialization(self):
        manager = IdempotencyManager()
        assert manager._storage == {}
        assert manager._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        manager = IdempotencyManager()
        result = manager.get_cached_result("key1", "method1")
        assert result is None

    def test_cache_and_retrieve(self):
        manager = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        manager.cache_result("key1", "method1", data)
        cached = manager.get_cached_result("key1", "method1")
        assert cached == data

    def test_cache_serializes_complex_types(self):
        manager = IdempotencyManager()
        data = {"date": date.today(), "decimal": Decimal("10.50")}
        manager.cache_result("key2", "method2", data)
        cached = manager.get_cached_result("key2", "method2")
        assert cached is not None
        assert "date" in cached

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0
        manager.cache_result("key3", "method3", {"foo": "bar"})
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "create_rate")
        key2 = manager._get_key("abc", "create_rate")
        key3 = manager._get_key("abc", "update_rate")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_currency_code_values(self):
        assert CurrencyCode.IDR.value == "IDR"
        assert CurrencyCode.USD.value == "USD"
        assert CurrencyCode.EUR.value == "EUR"
        assert CurrencyCode.SGD.value == "SGD"
        assert CurrencyCode.JPY.value == "JPY"
        assert CurrencyCode.CNY.value == "CNY"
        assert CurrencyCode.GBP.value == "GBP"
        assert CurrencyCode.AUD.value == "AUD"
        assert CurrencyCode.MYR.value == "MYR"
        assert CurrencyCode.THB.value == "THB"
        assert CurrencyCode.KRW.value == "KRW"
        assert CurrencyCode.HKD.value == "HKD"
        assert CurrencyCode.CHF.value == "CHF"
        assert CurrencyCode.CAD.value == "CAD"
        assert CurrencyCode.SAR.value == "SAR"
        assert CurrencyCode.INR.value == "INR"

    def test_rate_provider_values(self):
        assert RateProvider.MANUAL.value == "manual"
        assert RateProvider.BANK_INDONESIA.value == "bank_indonesia"
        assert RateProvider.BLOOMBERG.value == "bloomberg"
        assert RateProvider.REUTERS.value == "reuters"
        assert RateProvider.BANK_BCA.value == "bank_bca"
        assert RateProvider.BANK_MANDIRI.value == "bank_mandiri"
        assert RateProvider.BANK_BRI.value == "bank_bri"
        assert RateProvider.BANK_BNI.value == "bank_bni"
        assert RateProvider.CUSTOM.value == "custom"

    def test_rate_type_values(self):
        assert RateType.MID.value == "mid"
        assert RateType.BUY.value == "buy"
        assert RateType.SELL.value == "sell"
        assert RateType.SPOT.value == "spot"
        assert RateType.FORWARD.value == "forward"

    def test_rate_status_values(self):
        assert RateStatus.ACTIVE.value == "active"
        assert RateStatus.INACTIVE.value == "inactive"
        assert RateStatus.EXPIRED.value == "expired"
        assert RateStatus.LOCKED.value == "locked"
        assert RateStatus.PENDING.value == "pending"
        assert RateStatus.ARCHIVED.value == "archived"

    def test_revaluation_status_values(self):
        assert RevaluationStatus.DRAFT.value == "draft"
        assert RevaluationStatus.PROCESSED.value == "processed"
        assert RevaluationStatus.POSTED.value == "posted"
        assert RevaluationStatus.REVERSED.value == "reversed"
        assert RevaluationStatus.CANCELLED.value == "cancelled"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestExchangeRateCreateSchema:
    def test_valid_schema(self):
        data = {
            "from_currency": CurrencyCode.USD,
            "to_currency": CurrencyCode.IDR,
            "rate": Decimal("15500.00"),
            "rate_type": RateType.MID,
            "effective_date": date.today(),
            "provider": RateProvider.MANUAL,
            "bid_rate": Decimal("15400.00"),
            "ask_rate": Decimal("15600.00"),
            "notes": "Test",
        }
        schema = ExchangeRateCreateSchema(**data)
        assert schema.from_currency == CurrencyCode.USD
        assert schema.to_currency == CurrencyCode.IDR
        assert schema.rate == Decimal("15500.00")

    def test_same_currencies_invalid(self):
        with pytest.raises(ValueError, match="From and to currencies must be different"):
            ExchangeRateCreateSchema(
                from_currency=CurrencyCode.USD,
                to_currency=CurrencyCode.USD,
                rate=Decimal("1.0"),
            )

    def test_bid_less_than_ask(self):
        with pytest.raises(ValueError, match="Bid rate must be less than ask rate"):
            ExchangeRateCreateSchema(
                from_currency=CurrencyCode.USD,
                to_currency=CurrencyCode.IDR,
                rate=Decimal("15500"),
                bid_rate=Decimal("15600"),
                ask_rate=Decimal("15400"),
            )

    def test_rate_positive(self):
        with pytest.raises(ValueError, match="Rate must be greater than 0"):
            ExchangeRateCreateSchema(
                from_currency=CurrencyCode.USD,
                to_currency=CurrencyCode.IDR,
                rate=Decimal("0"),
            )


class TestExchangeRateUpdateSchema:
    def test_valid_schema(self):
        data = {
            "rate": Decimal("15600.00"),
            "bid_rate": Decimal("15500.00"),
            "ask_rate": Decimal("15700.00"),
            "provider": RateProvider.BANK_INDONESIA,
            "notes": "Updated",
            "status": RateStatus.ACTIVE,
        }
        schema = ExchangeRateUpdateSchema(**data)
        assert schema.rate == Decimal("15600.00")
        assert schema.provider == RateProvider.BANK_INDONESIA

    def test_partial_update(self):
        schema = ExchangeRateUpdateSchema(rate=Decimal("16000"))
        assert schema.rate == Decimal("16000")
        assert schema.bid_rate is None


class TestCurrencyConversionRequestSchema:
    def test_valid_schema(self):
        data = {
            "from_currency": CurrencyCode.USD,
            "to_currency": CurrencyCode.IDR,
            "amount": Decimal("100.00"),
            "as_of_date": date.today(),
            "rate_type": RateType.MID,
            "use_bank_rate": True,
        }
        schema = CurrencyConversionRequestSchema(**data)
        assert schema.amount == Decimal("100.00")


class TestForexRevaluationRequestSchema:
    def test_valid_schema(self):
        data = {
            "revaluation_date": date.today(),
            "functional_currency": CurrencyCode.IDR,
            "account_ids": [uuid4()],
            "post_to_ledger": True,
            "gain_account_code": "4-9300",
            "loss_account_code": "6-9300",
            "notes": "Test",
        }
        schema = ForexRevaluationRequestSchema(**data)
        assert schema.revaluation_date == date.today()


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestExchangeRateEndpoints:
    async def test_create_rate_success(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        request = ExchangeRateCreateSchema(
            from_currency=CurrencyCode.USD,
            to_currency=CurrencyCode.IDR,
            rate=Decimal("15500"),
        )
        result = await create_exchange_rate(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ExchangeRateResponseSchema)
        assert result.rate == Decimal("15500")
        mock_forex_service.create_exchange_rate.assert_called_once()

    async def test_create_rate_idempotency(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        request = ExchangeRateCreateSchema(
            from_currency=CurrencyCode.USD,
            to_currency=CurrencyCode.IDR,
            rate=Decimal("15500"),
        )
        with patch("adapters.primary_api.v1.fastapi_forex_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "from_currency": "USD",
                "to_currency": "IDR",
                "rate": "15500.00",
                "rate_type": "mid",
                "effective_date": date.today().isoformat(),
                "provider": "manual",
                "bid_rate": None,
                "ask_rate": None,
                "spread": None,
                "spread_percent": None,
                "status": "active",
                "is_locked": False,
                "notes": None,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_exchange_rate(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                forex_svc=mock_forex_service,
            )
            assert isinstance(result, ExchangeRateResponseSchema)
            mock_forex_service.create_exchange_rate.assert_not_called()

    async def test_get_rate_success(self, mock_forex_service, mock_legal_entity_id):
        rate_id = uuid4()
        result = await get_exchange_rate(
            rate_id=rate_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ExchangeRateResponseSchema)
        mock_forex_service.get_exchange_rate_by_id.assert_called_once_with(rate_id, mock_legal_entity_id)

    async def test_get_rate_not_found(self, mock_forex_service, mock_legal_entity_id):
        mock_forex_service.get_exchange_rate_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_exchange_rate(
                rate_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                forex_svc=mock_forex_service,
            )
        assert exc.value.status_code == 404

    async def test_get_current_rate_success(self, mock_forex_service, mock_legal_entity_id):
        result = await get_current_rate(
            from_currency=CurrencyCode.USD,
            to_currency=CurrencyCode.IDR,
            rate_type=RateType.MID,
            as_of_date=date.today(),
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ExchangeRateResponseSchema)
        mock_forex_service.get_current_rate.assert_called_once()

    async def test_get_current_rate_not_found(self, mock_forex_service, mock_legal_entity_id):
        mock_forex_service.get_current_rate.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_current_rate(
                from_currency=CurrencyCode.USD,
                to_currency=CurrencyCode.IDR,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                forex_svc=mock_forex_service,
            )
        assert exc.value.status_code == 404

    async def test_list_rates(self, mock_forex_service, mock_legal_entity_id):
        result = await list_exchange_rates(
            from_currency=CurrencyCode.USD,
            to_currency=CurrencyCode.IDR,
            rate_type=RateType.MID,
            effective_date=date.today(),
            provider=RateProvider.MANUAL,
            page=1,
            page_size=50,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ExchangeRateResponseSchema)
        mock_forex_service.list_exchange_rates.assert_called_once()

    async def test_update_rate_success(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        rate_id = uuid4()
        request = ExchangeRateUpdateSchema(rate=Decimal("16000"))
        result = await update_exchange_rate(
            rate_id=rate_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ExchangeRateResponseSchema)
        mock_forex_service.update_exchange_rate.assert_called_once()

    async def test_update_rate_not_found(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        mock_forex_service.update_exchange_rate.return_value = None
        with pytest.raises(HTTPException) as exc:
            await update_exchange_rate(
                rate_id=uuid4(),
                request=ExchangeRateUpdateSchema(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                forex_svc=mock_forex_service,
            )
        assert exc.value.status_code == 404

    async def test_deactivate_rate_success(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        rate_id = uuid4()
        result = await deactivate_exchange_rate(
            rate_id=rate_id,
            reason="Test reason",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert result["status"] == "inactive"
        mock_forex_service.deactivate_exchange_rate.assert_called_once()

    async def test_lock_rate_success(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        rate_id = uuid4()
        result = await lock_exchange_rate(
            rate_id=rate_id,
            reason="Audit",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert result.is_locked is True
        mock_forex_service.lock_exchange_rate.assert_called_once()

    async def test_unlock_rate_success(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        rate_id = uuid4()
        result = await unlock_exchange_rate(
            rate_id=rate_id,
            reason="Done",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert result.is_locked is False
        mock_forex_service.unlock_exchange_rate.assert_called_once()


@pytest.mark.asyncio
class TestCurrencyConversion:
    async def test_convert_success(self, mock_forex_service, mock_legal_entity_id):
        request = CurrencyConversionRequestSchema(
            from_currency=CurrencyCode.USD,
            to_currency=CurrencyCode.IDR,
            amount=Decimal("100"),
        )
        result = await convert_currency(
            request=request,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, CurrencyConversionResponseSchema)
        assert result.from_amount == Decimal("100")
        assert result.to_amount == Decimal("1550000")
        mock_forex_service.convert_currency.assert_called_once()

    async def test_convert_value_error(self, mock_forex_service, mock_legal_entity_id):
        mock_forex_service.convert_currency.side_effect = ValueError("Invalid currency")
        request = CurrencyConversionRequestSchema(
            from_currency=CurrencyCode.USD,
            to_currency=CurrencyCode.IDR,
            amount=Decimal("100"),
        )
        with pytest.raises(HTTPException) as exc:
            await convert_currency(
                request=request,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                forex_svc=mock_forex_service,
            )
        assert exc.value.status_code == 422

    async def test_batch_convert(self, mock_forex_service, mock_legal_entity_id):
        request = BatchConversionRequestSchema(
            conversions=[
                CurrencyConversionRequestSchema(
                    from_currency=CurrencyCode.USD,
                    to_currency=CurrencyCode.IDR,
                    amount=Decimal("100"),
                ),
                CurrencyConversionRequestSchema(
                    from_currency=CurrencyCode.EUR,
                    to_currency=CurrencyCode.IDR,
                    amount=Decimal("200"),
                ),
            ],
            as_of_date=date.today(),
        )
        # Make service return different results for each conversion
        mock_forex_service.convert_currency.side_effect = [
            MagicMock(
                from_currency="USD",
                to_currency="IDR",
                from_amount=Decimal("100"),
                to_amount=Decimal("1550000"),
                rate_used=Decimal("15500"),
                rate_type="mid",
                effective_date=date.today(),
                converted_at=datetime.now(UTC),
                rate_id=uuid4(),
            ),
            MagicMock(
                from_currency="EUR",
                to_currency="IDR",
                from_amount=Decimal("200"),
                to_amount=Decimal("3400000"),
                rate_used=Decimal("17000"),
                rate_type="mid",
                effective_date=date.today(),
                converted_at=datetime.now(UTC),
                rate_id=uuid4(),
            ),
        ]
        result = await batch_convert_currency(
            request=request,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, BatchConversionResponseSchema)
        assert len(result.results) == 2
        assert result.total_from_amount == Decimal("300")
        assert result.total_to_amount == Decimal("4950000")
        assert result.errors == []


@pytest.mark.asyncio
class TestHistoricalRates:
    async def test_get_historical_rates(self, mock_forex_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_historical_rates(
            from_currency=CurrencyCode.USD,
            to_currency=CurrencyCode.IDR,
            start_date=start,
            end_date=end,
            rate_type=RateType.MID,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, HistoricalRateResponseSchema)
        assert result.period_start == start
        assert result.period_end == end
        mock_forex_service.get_historical_rates.assert_called_once()


@pytest.mark.asyncio
class TestRevaluationEndpoints:
    async def test_run_revaluation_success(self, mock_revaluation_use_case, mock_token_payload, mock_legal_entity_id):
        request = ForexRevaluationRequestSchema(
            revaluation_date=date.today(),
            functional_currency=CurrencyCode.IDR,
        )
        result = await run_forex_revaluation(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            revaluation_use_case=mock_revaluation_use_case,
        )
        assert isinstance(result, ForexRevaluationResponseSchema)
        assert result.net_gain_loss == Decimal("5000")
        mock_revaluation_use_case.execute.assert_called_once()

    async def test_list_revaluations(self, mock_forex_service, mock_legal_entity_id):
        result = await list_forex_revaluations(
            start_date=None,
            end_date=None,
            status=None,
            page=1,
            page_size=20,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ForexRevaluationResponseSchema)

    async def test_get_revaluation_success(self, mock_forex_service, mock_legal_entity_id):
        reval_id = uuid4()
        result = await get_forex_revaluation(
            revaluation_id=reval_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ForexRevaluationResponseSchema)
        mock_forex_service.get_revaluation_by_id.assert_called_once_with(reval_id, mock_legal_entity_id)

    async def test_get_revaluation_not_found(self, mock_forex_service, mock_legal_entity_id):
        mock_forex_service.get_revaluation_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_forex_revaluation(
                revaluation_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                forex_svc=mock_forex_service,
            )
        assert exc.value.status_code == 404

    async def test_reverse_revaluation_success(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        reval_id = uuid4()
        result = await reverse_forex_revaluation(
            revaluation_id=reval_id,
            reason="Test reversal",
            reversal_date=date.today(),
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ForexRevaluationResponseSchema)
        mock_forex_service.reverse_revaluation.assert_called_once()


@pytest.mark.asyncio
class TestPositionAndDashboard:
    async def test_get_forex_position(self, mock_forex_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_forex_position(
            as_of_date=as_of,
            functional_currency=CurrencyCode.IDR,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ForexPositionResponseSchema)
        assert result.as_of_date == as_of
        mock_forex_service.get_forex_position.assert_called_once()

    async def test_get_forex_dashboard(self, mock_forex_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_forex_dashboard(
            as_of_date=as_of,
            functional_currency=CurrencyCode.IDR,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, ForexDashboardResponseSchema)
        assert result.as_of_date == as_of
        mock_forex_service.get_forex_dashboard.assert_called_once()


@pytest.mark.asyncio
class TestSyncAndHistory:
    async def test_sync_from_provider(self, mock_forex_service, mock_token_payload, mock_legal_entity_id):
        result = await sync_rates_from_provider(
            provider=RateProvider.BANK_INDONESIA,
            effective_date=date.today(),
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert result["rates_synced"] == 10
        mock_forex_service.sync_rates_from_provider.assert_called_once()

    async def test_get_rate_history(self, mock_forex_service, mock_legal_entity_id):
        rate_id = uuid4()
        result = await get_rate_history(
            rate_id=rate_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert isinstance(result, list)
        mock_forex_service.get_rate_history.assert_called_once_with(rate_id, mock_legal_entity_id)

    async def test_get_rate_status_success(self, mock_forex_service, mock_legal_entity_id):
        rate_id = uuid4()
        result = await get_rate_status(
            rate_id=rate_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert result["status"] == "active"
        assert result["can_edit"] is True
        mock_forex_service.get_rate_status.assert_called_once_with(rate_id, mock_legal_entity_id)

    async def test_get_rate_status_not_found(self, mock_forex_service, mock_legal_entity_id):
        mock_forex_service.get_rate_status.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_rate_status(
                rate_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                forex_svc=mock_forex_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestExportEndpoints:
    async def test_export_rates(self, mock_forex_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_exchange_rates(
            start_date=start,
            end_date=end,
            format="csv",
            from_currency=CurrencyCode.USD,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_forex_service.export_rates.assert_called_once()

    async def test_export_revaluation_history(self, mock_forex_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_revaluation_history(
            start_date=start,
            end_date=end,
            format="excel",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            forex_svc=mock_forex_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        mock_forex_service.export_revaluation_history.assert_called_once()
