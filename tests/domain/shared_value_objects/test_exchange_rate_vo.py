# tests/domain/shared_value_objects/test_exchange_rate_vo.py
"""
Unit tests for exchange_rate_vo.py.
Covers all public methods with strong assertions, using fixed datetime to avoid flakiness.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from domain.shared_value_objects.currency_vo import CurrencyCode, CurrencyVO
from domain.shared_value_objects.exchange_rate_vo import (
    ExchangeRateError,
    ExchangeRateVO,
    InvalidExchangeRateError,
    SameCurrencyError,
    average_rate,
    get_cross_rate,
)

# ============================================================================
# FIXED DATETIME
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_LATER = FIXED_NOW + timedelta(days=1)
FIXED_EARLIER = FIXED_NOW - timedelta(days=1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now(UTC) and datetime.now() to return FIXED_NOW."""
    with patch("domain.shared_value_objects.exchange_rate_vo.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        # Also patch the function directly for direct calls
        with patch("domain.shared_value_objects.exchange_rate_vo.datetime.now", return_value=FIXED_NOW):
            yield


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def idr():
    return CurrencyVO(CurrencyCode.IDR)


@pytest.fixture
def usd():
    return CurrencyVO(CurrencyCode.USD)


@pytest.fixture
def eur():
    return CurrencyVO(CurrencyCode.EUR)


# ============================================================================
# TESTS FOR EXCEPTIONS (parametrized to avoid duplication)
# ============================================================================

class TestExceptions:
    @pytest.mark.parametrize("exception_class,msg", [
        (ExchangeRateError, "test"),
        (InvalidExchangeRateError, "test"),
        (SameCurrencyError, "test"),
    ])
    def test_exceptions(self, exception_class, msg):
        with pytest.raises(exception_class, match=msg):
            raise exception_class(msg)


# ============================================================================
# TESTS FOR EXCHANGE RATE VO
# ============================================================================

class TestExchangeRateVO:
    # ------------------------------------------------------------------------
    # Construction and validation
    # ------------------------------------------------------------------------

    def test_construction(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert rate.from_currency == idr
        assert rate.to_currency == usd
        assert rate.rate == Decimal("0.00006400")
        assert rate.effective_date == FIXED_NOW
        assert rate.source == "System"
        assert rate.bid_rate is None
        assert rate.ask_rate is None
        assert rate.is_inverse is False

    def test_same_currency_raises(self, idr):
        with pytest.raises(SameCurrencyError, match="cannot be the same"):
            ExchangeRateVO(idr, idr, Decimal("1"), FIXED_NOW)

    @pytest.mark.parametrize("bad_rate", [Decimal("0"), Decimal("-1")])
    def test_zero_or_negative_rate_raises(self, idr, usd, bad_rate):
        with pytest.raises(InvalidExchangeRateError, match="positive"):
            ExchangeRateVO(idr, usd, bad_rate, FIXED_NOW)

    def test_bid_ask_validation(self, idr, usd):
        # Valid bid <= ask
        rate = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        assert rate.bid_rate == Decimal("0.00006300")
        assert rate.ask_rate == Decimal("0.00006500")

        # Invalid bid > ask
        with pytest.raises(InvalidExchangeRateError, match="Bid rate.*cannot exceed"):
            ExchangeRateVO(
                idr, usd, Decimal("0.000064"),
                FIXED_NOW,
                bid_rate=Decimal("0.000066"),
                ask_rate=Decimal("0.000065"),
            )

    def test_timezone_normalization(self, idr, usd):
        naive = datetime(2025, 1, 1)
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), naive)
        assert rate.effective_date.tzinfo is not None
        assert rate.effective_date.tzinfo == UTC
        assert rate.effective_date == naive.replace(tzinfo=UTC)

    def test_empty_source_raises(self, idr, usd):
        with pytest.raises(ValueError, match="Source cannot be empty"):
            ExchangeRateVO(idr, usd, Decimal("1"), FIXED_NOW, source="")

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    def test_create(self, idr, usd):
        rate = ExchangeRateVO.create(idr, usd, Decimal("0.000064"))
        assert rate.from_currency == idr
        assert rate.to_currency == usd
        assert rate.source == "System"
        assert rate.effective_date == FIXED_NOW

    def test_create_with_idempotency_key(self, idr, usd):
        # Idempotency key is a no-op in pure factory
        rate = ExchangeRateVO.create(idr, usd, Decimal("0.000064"), idempotency_key="key-123")
        assert rate.rate == Decimal("0.00006400")
        assert rate.source == "System"

    def test_from_string(self, idr, usd):
        rate = ExchangeRateVO.from_string("IDR", "USD", "0.000064")
        assert rate.from_currency == idr
        assert rate.to_currency == usd

        with pytest.raises(ValueError, match="Invalid from_currency"):
            ExchangeRateVO.from_string("XXX", "USD", "1")

        with pytest.raises(ValueError, match="Invalid to_currency"):
            ExchangeRateVO.from_string("IDR", "YYY", "1")

    def test_create_direct(self):
        rate = ExchangeRateVO.create_direct("IDR", "USD", Decimal("0.000064"))
        assert rate.from_currency.code == CurrencyCode.IDR
        assert rate.to_currency.code == CurrencyCode.USD
        assert rate.source == "Direct"

    def test_default_idr_to_usd(self):
        rate = ExchangeRateVO.default_idr_to_usd(Decimal("0.000064"))
        assert rate.from_currency.code == CurrencyCode.IDR
        assert rate.to_currency.code == CurrencyCode.USD
        assert rate.source == "System"

    def test_from_mid_rate(self, idr, usd):
        rate = ExchangeRateVO.from_mid_rate(idr, usd, Decimal("0.000064"), Decimal("0.01"))
        assert rate.rate == Decimal("0.00006400")
        assert rate.bid_rate is not None
        assert rate.ask_rate is not None
        assert rate.bid_rate < rate.rate < rate.ask_rate
        assert rate.source == "Mid+Spread"

        # With custom effective date
        rate2 = ExchangeRateVO.from_mid_rate(idr, usd, Decimal("0.000064"), Decimal("0.01"), FIXED_LATER)
        assert rate2.effective_date == FIXED_LATER

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    def test_rate_float(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert rate.rate_float == 0.000064

    def test_is_bid_ask_available(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert rate.is_bid_ask_available is False

        rate2 = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        assert rate2.is_bid_ask_available is True

    def test_spread(self, idr, usd):
        rate = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        assert rate.spread == Decimal("0.00000200")

        rate2 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert rate2.spread is None

    def test_spread_percentage(self, idr, usd):
        rate = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        # (0.000065 - 0.000063) / 0.000064 * 100 = 3.125%
        assert rate.spread_percentage == Decimal("3.1250")

        # Without bid/ask
        rate2 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert rate2.spread_percentage is None

    def test_mid_rate(self, idr, usd):
        rate = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        assert rate.mid_rate == Decimal("0.00006400")

        rate2 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert rate2.mid_rate == Decimal("0.00006400")

    # ------------------------------------------------------------------------
    # Conversion methods
    # ------------------------------------------------------------------------

    def test_convert(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        result = rate.convert(Decimal("15000000"))
        assert result == Decimal("960.00")

        # With bid rate
        rate2 = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        result_bid = rate2.convert(Decimal("15000000"), use_bid=True)
        assert result_bid == Decimal("945.00")  # 15000000 * 0.000063

        result_ask = rate2.convert(Decimal("15000000"), use_ask=True)
        assert result_ask == Decimal("975.00")  # 15000000 * 0.000065

        with pytest.raises(ValueError, match="Cannot convert negative"):
            rate.convert(Decimal("-100"))

        with pytest.raises(ValueError, match="Cannot use both bid and ask"):
            rate2.convert(Decimal("100"), use_bid=True, use_ask=True)

        with pytest.raises(ValueError, match="Bid rate not available"):
            rate.convert(Decimal("100"), use_bid=True)

    def test_convert_back(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        result = rate.convert_back(Decimal("960"))
        assert result == Decimal("15000000.00")

        # With bid/ask
        rate2 = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        # For reverse, use_bid uses inverse of ask, use_ask uses inverse of bid
        result_bid = rate2.convert_back(Decimal("1000"), use_bid=True)
        # 1000 / 0.000065 = 15,384,615.38 (rounded to 2 decimals)
        assert result_bid == Decimal("15384615.38")

        result_ask = rate2.convert_back(Decimal("1000"), use_ask=True)
        # 1000 / 0.000063 = 15,873,015.87
        assert result_ask == Decimal("15873015.87")

        with pytest.raises(ValueError, match="Ask rate not available"):
            rate.convert_back(Decimal("100"), use_bid=True)

    def test_invert(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        inverted = rate.invert()
        assert inverted.from_currency == usd
        assert inverted.to_currency == idr
        assert inverted.rate == Decimal("15625.00000000")
        assert inverted.is_inverse is True
        assert inverted.source == "inv(System)"

        # With bid/ask
        rate2 = ExchangeRateVO(
            idr, usd, Decimal("0.000064"),
            FIXED_NOW,
            bid_rate=Decimal("0.000063"),
            ask_rate=Decimal("0.000065"),
        )
        inv2 = rate2.invert()
        assert inv2.bid_rate is not None
        assert inv2.ask_rate is not None
        # bid becomes 1/ask, ask becomes 1/bid
        assert inv2.bid_rate == Decimal("15384.61538462")  # 1/0.000065
        assert inv2.ask_rate == Decimal("15873.01587302")  # 1/0.000063

    # ------------------------------------------------------------------------
    # Effective date checks
    # ------------------------------------------------------------------------

    def test_is_effective_on(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert rate.is_effective_on(FIXED_NOW) is True
        assert rate.is_effective_on(FIXED_EARLIER) is True
        assert rate.is_effective_on(FIXED_LATER) is False

        # Defaults to now (which is mocked to FIXED_NOW)
        assert rate.is_effective_on() is True

    def test_is_newer_than_is_older_than(self, idr, usd):
        rate1 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        rate2 = ExchangeRateVO(idr, usd, Decimal("0.000065"), FIXED_LATER)
        assert rate2.is_newer_than(rate1) is True
        assert rate1.is_older_than(rate2) is True
        assert rate1.is_newer_than(rate2) is False
        assert rate2.is_older_than(rate1) is False

    # ------------------------------------------------------------------------
    # with_* methods (immutable updates)
    # ------------------------------------------------------------------------

    def test_with_effective_date(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        new_rate = rate.with_effective_date(FIXED_LATER)
        assert new_rate.effective_date == FIXED_LATER
        assert new_rate.rate == rate.rate
        assert new_rate.from_currency == rate.from_currency
        assert new_rate.to_currency == rate.to_currency

    def test_with_rate(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        new_rate = rate.with_rate(Decimal("0.000070"))
        assert new_rate.rate == Decimal("0.00007000")
        assert new_rate.effective_date == rate.effective_date

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def test_to_dict(self, idr, usd):
        rate = ExchangeRateVO(
            idr, usd, Decimal("0.000064"), FIXED_NOW,
            bid_rate=Decimal("0.000063"), ask_rate=Decimal("0.000065")
        )
        d = rate.to_dict()
        assert d["from_currency"] == "IDR"
        assert d["to_currency"] == "USD"
        assert d["rate"] == "0.00006400"
        assert d["effective_date"] == FIXED_NOW.isoformat()
        assert d["source"] == "System"
        assert d["bid_rate"] == "0.00006300"
        assert d["ask_rate"] == "0.00006500"
        assert d["is_inverse"] is False
        assert d["mid_rate"] == "0.00006400"
        assert d["spread"] == "0.00000200"

    def test_from_dict(self, idr, usd):
        data = {
            "from_currency": "IDR",
            "to_currency": "USD",
            "rate": "0.00006400",
            "effective_date": FIXED_NOW.isoformat(),
            "source": "System",
            "bid_rate": "0.00006300",
            "ask_rate": "0.00006500",
            "is_inverse": False,
        }
        rate = ExchangeRateVO.from_dict(data)
        assert rate.from_currency == idr
        assert rate.to_currency == usd
        assert rate.rate == Decimal("0.00006400")
        assert rate.effective_date == FIXED_NOW
        assert rate.bid_rate == Decimal("0.00006300")
        assert rate.ask_rate == Decimal("0.00006500")

        # Missing bid/ask
        data2 = {
            "from_currency": "IDR",
            "to_currency": "USD",
            "rate": "0.00006400",
            "effective_date": FIXED_NOW.isoformat(),
        }
        rate2 = ExchangeRateVO.from_dict(data2)
        assert rate2.bid_rate is None
        assert rate2.ask_rate is None

        # Invalid currency
        data3 = data.copy()
        data3["from_currency"] = "XXX"
        with pytest.raises(ValueError, match="Invalid currency codes"):
            ExchangeRateVO.from_dict(data3)

    def test_to_db_format(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        rec = rate.to_db_format()
        assert rec["from_currency_code"] == "IDR"
        assert rec["to_currency_code"] == "USD"
        assert rec["rate"] == Decimal("0.00006400")
        assert rec["effective_date"] == FIXED_NOW
        assert rec["source"] == "System"
        assert rec["bid_rate"] is None
        assert rec["ask_rate"] is None

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def test_str_repr(self, idr, usd):
        rate = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        assert str(rate) == "1 IDR = 0.00006400 USD"
        assert repr(rate) == f"ExchangeRateVO(IDR -> USD, rate=0.00006400, effective={FIXED_NOW.date()})"

    def test_eq_hash(self, idr, usd):
        now = FIXED_NOW
        rate1 = ExchangeRateVO(idr, usd, Decimal("0.000064"), now)
        rate2 = ExchangeRateVO(idr, usd, Decimal("0.000064"), now)
        rate3 = ExchangeRateVO(idr, usd, Decimal("0.000065"), now)
        rate4 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_LATER)
        assert rate1 == rate2
        assert rate1 != rate3
        assert rate1 != rate4
        assert hash(rate1) == hash(rate2)
        assert rate1 != "not a rate"


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_get_cross_rate(self, idr, usd, eur):
        # IDR -> USD
        rate1 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        # EUR -> USD
        rate2 = ExchangeRateVO(eur, usd, Decimal("1.08"), FIXED_NOW)
        # Cross: IDR -> EUR
        cross = get_cross_rate(rate1, rate2, eur)
        assert cross.from_currency == idr
        assert cross.to_currency == eur
        assert cross.rate == Decimal("0.00005926")  # 0.000064 / 1.08

        # Same from currency: rate1: IDR->USD, rate3: IDR->EUR => cross USD->EUR = rate3/rate1
        rate3 = ExchangeRateVO(idr, eur, Decimal("0.000059"), FIXED_NOW)
        cross2 = get_cross_rate(rate1, rate3, eur)
        assert cross2.from_currency == usd
        assert cross2.to_currency == eur
        assert cross2.rate == Decimal("0.92187500")  # 0.000059 / 0.000064

        # Other combinations are covered by the code; we test one more:
        # rate1: USD->IDR, rate2: EUR->USD => cross EUR->IDR = rate1 * rate2
        rate4 = ExchangeRateVO(usd, idr, Decimal("15625"), FIXED_NOW)
        rate5 = ExchangeRateVO(eur, usd, Decimal("1.08"), FIXED_NOW)
        cross3 = get_cross_rate(rate4, rate5, idr)
        assert cross3.from_currency == eur
        assert cross3.to_currency == idr
        assert cross3.rate == Decimal("16875.00000000")  # 15625 * 1.08

        # rate1: USD->IDR, rate2: EUR->IDR => cross USD->EUR = rate1 / rate2
        rate6 = ExchangeRateVO(eur, idr, Decimal("16875"), FIXED_NOW)
        cross4 = get_cross_rate(rate4, rate6, idr)
        assert cross4.from_currency == usd
        assert cross4.to_currency == eur
        assert cross4.rate == Decimal("0.92592593")  # 15625 / 16875

    def test_get_cross_rate_no_common(self, idr, usd, eur):
        rate1 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        rate2 = ExchangeRateVO(eur, usd, Decimal("1.08"), FIXED_NOW)
        # Asking for a target that is not common will fail
        with pytest.raises(ValueError, match="No common currency"):
            get_cross_rate(rate1, rate2, usd)  # target is common, but the function picks based on common detection

        # But if we use a different combination where no common currency exists?
        # Actually the function detects common by checking from/to pairs; if it finds none it raises.
        # To force no common, we can pass rates that share no currency
        ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        ExchangeRateVO(eur, idr, Decimal("15625"), FIXED_NOW)  # shares IDR with rate3? Yes.
        # So we need two rates with no common: e.g., IDR->USD and EUR->GBP
        gbp = CurrencyVO(CurrencyCode.GBP)
        rate5 = ExchangeRateVO(idr, usd, Decimal("0.000064"), FIXED_NOW)
        rate6 = ExchangeRateVO(eur, gbp, Decimal("0.85"), FIXED_NOW)
        with pytest.raises(ValueError, match="No common currency"):
            get_cross_rate(rate5, rate6, gbp)

    def test_average_rate(self, idr, usd):
        now = FIXED_NOW
        rates = [
            ExchangeRateVO(idr, usd, Decimal("0.000064"), now),
            ExchangeRateVO(idr, usd, Decimal("0.000065"), now),
            ExchangeRateVO(idr, usd, Decimal("0.000063"), now),
        ]
        avg = average_rate(rates)
        assert avg.rate == Decimal("0.00006400")
        assert avg.source == "Average"
        assert avg.effective_date == now

        # Empty list
        with pytest.raises(ValueError, match="empty"):
            average_rate([])

        # Different pairs
        eur = CurrencyVO(CurrencyCode.EUR)
        rates2 = [
            ExchangeRateVO(idr, usd, Decimal("0.000064"), now),
            ExchangeRateVO(eur, usd, Decimal("1.08"), now),
        ]
        with pytest.raises(ValueError, match="same currency pair"):
            average_rate(rates2)
