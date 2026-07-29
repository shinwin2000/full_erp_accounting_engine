# test_rate_registry_dynamic.py
# Comprehensive tests for policy_engine/tax_indonesia/rate_registry_dynamic.py

import json
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, mock_open, patch

import pytest

from policy_engine.tax_indonesia.rate_registry_dynamic import (
    DynamicRateRegistry,
    RateExpiredError,
    RateNotFoundError,
    RateRegistry,
    RateRegistryError,
    RateType,
    TaxRate,
    TaxType,
    get_dynamic_rate_registry,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def fixed_now():
    return datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("policy_engine.tax_indonesia.rate_registry_dynamic.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        mock_dt.combine = datetime.combine
        mock_dt.min = datetime.min
        yield mock_dt


@pytest.fixture
def sample_tax_rate():
    return TaxRate(
        rate_id="test_rate_001",
        tax_type=TaxType.PPN,
        rate_type=RateType.PERCENTAGE,
        rate_value=Decimal("11"),
        effective_from=datetime(2022, 4, 1, tzinfo=UTC),
        effective_to=datetime(2025, 12, 31, tzinfo=UTC),
        description="Test PPN rate",
        metadata={"source": "test"},
    )


@pytest.fixture
def registry():
    # Reset singleton before each test
    DynamicRateRegistry._instance = None
    with patch("policy_engine.tax_indonesia.rate_registry_dynamic.logger") as mock_logger:
        reg = DynamicRateRegistry()
        # Clear default rates for a clean slate
        reg._rates.clear()
        reg._index.clear()
        reg._history.clear()
        yield reg


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_tax_type(self):
        assert TaxType.PPN.value == "ppn"
        assert TaxType.PPH_21.value == "pph_21"
        assert TaxType.PPH_22.value == "pph_22"
        assert TaxType.PPH_23.value == "pph_23"
        assert TaxType.PPH_25.value == "pph_25"
        assert TaxType.PPH_26.value == "pph_26"
        assert TaxType.PPH_4_AYAT_2.value == "pph_4_ayat_2"
        assert TaxType.PPH_BADAN.value == "pph_badan"
        assert TaxType.BEA_METERAI.value == "bea_meterai"
        assert TaxType.PENALTY_INTEREST.value == "penalty_interest"

    def test_rate_type(self):
        assert RateType.PERCENTAGE.value == "percentage"
        assert RateType.NOMINAL.value == "nominal"


# -------------------- Tests for Exceptions --------------------
class TestExceptions:
    def test_rate_registry_error(self):
        with pytest.raises(RateRegistryError):
            raise RateRegistryError("error")

    def test_rate_not_found_error(self):
        with pytest.raises(RateNotFoundError):
            raise RateNotFoundError("not found")

    def test_rate_expired_error(self):
        with pytest.raises(RateExpiredError):
            raise RateExpiredError("expired")


# -------------------- Tests for TaxRate --------------------
class TestTaxRate:
    def test_construction(self, sample_tax_rate):
        assert sample_tax_rate.rate_id == "test_rate_001"
        assert sample_tax_rate.tax_type == TaxType.PPN
        assert sample_tax_rate.rate_type == RateType.PERCENTAGE
        assert sample_tax_rate.rate_value == Decimal("11")
        assert sample_tax_rate.effective_from == datetime(2022, 4, 1, tzinfo=UTC)
        assert sample_tax_rate.effective_to == datetime(2025, 12, 31, tzinfo=UTC)
        assert sample_tax_rate.hash_sha256 != ""

    def test_compute_hash_consistent(self, sample_tax_rate):
        h1 = sample_tax_rate.hash_sha256
        h2 = sample_tax_rate._compute_hash()
        assert h1 == h2

    def test_is_active(self, sample_tax_rate):
        # Inside range
        assert sample_tax_rate.is_active(datetime(2023, 6, 1, tzinfo=UTC)) is True
        # Before effective
        assert sample_tax_rate.is_active(datetime(2022, 3, 31, tzinfo=UTC)) is False
        # After effective_to
        assert sample_tax_rate.is_active(datetime(2026, 1, 1, tzinfo=UTC)) is False
        # No effective_to
        rate_no_end = TaxRate(
            rate_id="no_end",
            tax_type=TaxType.PPH_23,
            rate_type=RateType.PERCENTAGE,
            rate_value=Decimal("2"),
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert rate_no_end.is_active(datetime(2025, 1, 1, tzinfo=UTC)) is True

    def test_to_dict(self, sample_tax_rate):
        d = sample_tax_rate.to_dict()
        assert d["rate_id"] == "test_rate_001"
        assert d["tax_type"] == "ppn"
        assert d["rate_type"] == "percentage"
        assert d["rate_value"] == "11"
        assert d["effective_from"] == "2022-04-01T00:00:00+00:00"
        assert d["effective_to"] == "2025-12-31T00:00:00+00:00"
        assert d["description"] == "Test PPN rate"
        assert d["metadata"] == {"source": "test"}
        assert "hash" in d


# -------------------- Tests for DynamicRateRegistry --------------------
class TestDynamicRateRegistry:
    def test_singleton(self):
        r1 = DynamicRateRegistry()
        r2 = DynamicRateRegistry()
        assert r1 is r2

    def test_initialization_loads_default_rates(self):
        # Reset singleton
        DynamicRateRegistry._instance = None
        reg = DynamicRateRegistry()
        # Default rates should be loaded
        assert len(reg._rates) > 0
        # Check a specific default rate
        ppn_rate = reg.get_rate(TaxType.PPN, as_of=datetime(2023, 1, 1, tzinfo=UTC))
        assert ppn_rate is not None
        assert ppn_rate.rate_value == Decimal("11")

    def test_add_rate(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        assert len(registry._rates) == 1
        assert registry._rates["test_rate_001"] == sample_tax_rate
        # Check history
        history = registry.get_history()
        assert len(history) == 1
        assert history[0]["action"] == "ADD"
        assert history[0]["rate_id"] == "test_rate_001"

    def test_update_rate_existing(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        result = registry.update_rate(
            "test_rate_001",
            rate_value=Decimal("12"),
            description="Updated rate",
        )
        assert result is True
        updated = registry._rates["test_rate_001"]
        assert updated.rate_value == Decimal("12")
        assert updated.description == "Updated rate"
        assert updated.updated_at is not None
        # History
        history = registry.get_history()
        assert len(history) == 2
        assert history[1]["action"] == "UPDATE"

    def test_update_rate_not_existing(self, registry):
        result = registry.update_rate("nonexistent", rate_value=Decimal("10"))
        assert result is False

    def test_remove_rate(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        result = registry.remove_rate("test_rate_001")
        assert result is True
        # Rate should be soft-deleted (effective_to set to past)
        rate = registry._rates["test_rate_001"]
        assert rate.effective_to < datetime.now(UTC)
        # History
        history = registry.get_history()
        assert len(history) == 2
        assert history[1]["action"] == "REMOVE"

    def test_remove_rate_not_existing(self, registry):
        result = registry.remove_rate("nonexistent")
        assert result is False

    def test_get_rate_cached(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        # First call populates cache
        rate1 = registry.get_rate(TaxType.PPN, as_of=datetime(2023, 6, 1, tzinfo=UTC))
        assert rate1 is not None
        assert rate1.rate_id == "test_rate_001"
        # Cache key should be set
        cache_key = (TaxType.PPN, datetime(2023, 6, 1, tzinfo=UTC).date())
        assert cache_key in registry._index
        # Second call returns same object (from cache)
        rate2 = registry.get_rate(TaxType.PPN, as_of=datetime(2023, 6, 1, tzinfo=UTC))
        assert rate2 is rate1

    def test_get_rate_no_match(self, registry):
        rate = registry.get_rate(TaxType.PPN, as_of=datetime(1990, 1, 1, tzinfo=UTC))
        assert rate is None

    def test_get_rate_with_multiple_versions(self, registry):
        # Add two rates for same tax type with different effective dates
        rate1 = TaxRate(
            rate_id="ppn_old",
            tax_type=TaxType.PPN,
            rate_type=RateType.PERCENTAGE,
            rate_value=Decimal("10"),
            effective_from=datetime(2000, 1, 1, tzinfo=UTC),
            effective_to=datetime(2022, 3, 31, tzinfo=UTC),
        )
        rate2 = TaxRate(
            rate_id="ppn_new",
            tax_type=TaxType.PPN,
            rate_type=RateType.PERCENTAGE,
            rate_value=Decimal("11"),
            effective_from=datetime(2022, 4, 1, tzinfo=UTC),
        )
        registry.add_rate(rate1)
        registry.add_rate(rate2)
        # As of 2021, should return old rate
        rate_2021 = registry.get_rate(TaxType.PPN, as_of=datetime(2021, 6, 1, tzinfo=UTC))
        assert rate_2021.rate_id == "ppn_old"
        # As of 2023, should return new rate
        rate_2023 = registry.get_rate(TaxType.PPN, as_of=datetime(2023, 6, 1, tzinfo=UTC))
        assert rate_2023.rate_id == "ppn_new"
        # If multiple active, choose latest effective_from
        rate3 = TaxRate(
            rate_id="ppn_12",
            tax_type=TaxType.PPN,
            rate_type=RateType.PERCENTAGE,
            rate_value=Decimal("12"),
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
        registry.add_rate(rate3)
        # As of 2026, should return the 12% rate
        rate_2026 = registry.get_rate(TaxType.PPN, as_of=datetime(2026, 6, 1, tzinfo=UTC))
        assert rate_2026.rate_id == "ppn_12"

    def test_get_rate_value(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        value = registry.get_rate_value(TaxType.PPN, as_of=datetime(2023, 6, 1, tzinfo=UTC))
        assert value == Decimal("11")
        # Not found raises
        with pytest.raises(RateNotFoundError):
            registry.get_rate_value(TaxType.PPH_21, as_of=datetime(2023, 6, 1, tzinfo=UTC))

    def test_get_rate_by_id(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        rate = registry.get_rate_by_id("test_rate_001")
        assert rate is not None
        assert rate.rate_id == "test_rate_001"
        assert registry.get_rate_by_id("nonexistent") is None

    def test_get_all_rates(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        # Add another
        rate2 = TaxRate(
            rate_id="rate2",
            tax_type=TaxType.PPH_23,
            rate_type=RateType.PERCENTAGE,
            rate_value=Decimal("2"),
            effective_from=datetime(2000, 1, 1, tzinfo=UTC),
        )
        registry.add_rate(rate2)
        all_rates = registry.get_all_rates()
        assert len(all_rates) == 2
        # Filter by tax type
        ppn_rates = registry.get_all_rates(TaxType.PPN)
        assert len(ppn_rates) == 1
        assert ppn_rates[0].rate_id == "test_rate_001"

    def test_invalidate_cache(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        # Populate cache
        registry.get_rate(TaxType.PPN, as_of=datetime(2023, 6, 1, tzinfo=UTC))
        assert len(registry._index) == 1
        registry._invalidate_cache()
        assert len(registry._index) == 0

    def test_refresh(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        registry.get_rate(TaxType.PPN, as_of=datetime(2023, 6, 1, tzinfo=UTC))
        assert len(registry._index) == 1
        registry.refresh()
        assert len(registry._index) == 0

    def test_get_history(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        registry.update_rate("test_rate_001", rate_value=Decimal("12"))
        history = registry.get_history(limit=1)
        assert len(history) == 1
        assert history[0]["action"] == "UPDATE"
        # Full history
        full = registry.get_history()
        assert len(full) == 2

    def test_sync_from_api_success(self, registry):
        with patch("policy_engine.tax_indonesia.rate_registry_dynamic.HAS_REQUESTS", True):
            with patch("policy_engine.tax_indonesia.rate_registry_dynamic.requests") as mock_requests:
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "rates": [
                        {
                            "rate_id": "api_rate_1",
                            "tax_type": "ppn",
                            "rate_type": "percentage",
                            "rate_value": "11",
                            "effective_from": "2022-04-01T00:00:00+00:00",
                            "effective_to": None,
                            "description": "From API",
                        }
                    ]
                }
                mock_response.raise_for_status.return_value = None
                mock_requests.get.return_value = mock_response

                count = registry.sync_from_api("https://api.example.com/rates", api_key="test_key")
                assert count == 1
                rate = registry.get_rate(TaxType.PPN, as_of=datetime(2023, 6, 1, tzinfo=UTC))
                assert rate is not None
                assert rate.rate_value == Decimal("11")
                assert rate.rate_id == "api_rate_1"

    def test_sync_from_api_requests_not_available(self, registry):
        with patch("policy_engine.tax_indonesia.rate_registry_dynamic.HAS_REQUESTS", False):
            count = registry.sync_from_api("https://api.example.com", api_key="key")
            assert count == 0

    def test_sync_from_api_failure(self, registry):
        with patch("policy_engine.tax_indonesia.rate_registry_dynamic.HAS_REQUESTS", True):
            with patch("policy_engine.tax_indonesia.rate_registry_dynamic.requests") as mock_requests:
                mock_requests.get.side_effect = Exception("Network error")
                count = registry.sync_from_api("https://api.example.com")
                assert count == 0

    def test_sync_from_json_file_success(self, registry):
        json_data = {
            "rates": [
                {
                    "rate_id": "json_rate_1",
                    "tax_type": "pph_23",
                    "rate_type": "percentage",
                    "rate_value": "2",
                    "effective_from": "2009-01-01T00:00:00+00:00",
                    "effective_to": None,
                    "description": "From JSON",
                }
            ]
        }
        mock_file = mock_open(read_data=json.dumps(json_data))
        with patch("builtins.open", mock_file):
            count = registry.sync_from_json_file("/fake/path.json")
            assert count == 1
            rate = registry.get_rate(TaxType.PPH_23, as_of=datetime(2023, 6, 1, tzinfo=UTC))
            assert rate is not None
            assert rate.rate_value == Decimal("2")

    def test_sync_from_json_file_failure(self, registry):
        with patch("builtins.open", side_effect=Exception("File error")):
            count = registry.sync_from_json_file("/fake/path.json")
            assert count == 0

    def test_generate_report(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        report = registry.generate_report()
        assert report["total_rates"] == 1
        assert report["by_tax_type"]["ppn"] == 1
        assert report["cache_size"] == 0
        assert report["history_count"] == 1

    def test_export_to_json(self, registry, sample_tax_rate):
        registry.add_rate(sample_tax_rate)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            file_path = tmp.name
        try:
            registry.export_to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "report" in data
            assert "rates" in data
            assert len(data["rates"]) == 1
            assert data["rates"][0]["rate_id"] == "test_rate_001"
            assert "history" in data
        finally:
            import os
            os.unlink(file_path)


# -------------------- Tests for Singleton Accessor --------------------
def test_get_dynamic_rate_registry():
    r1 = get_dynamic_rate_registry()
    r2 = get_dynamic_rate_registry()
    assert r1 is r2
    assert isinstance(r1, DynamicRateRegistry)


# -------------------- Tests for RateRegistry Compatibility Class --------------------
class TestRateRegistry:
    def test_get_ppn_rate_default(self):
        # PPN rate as of default (2025) should be 11% (since 12% effective 2026)
        rate = RateRegistry.get_ppn_rate()
        # In decimal, 11% = 0.11
        assert rate == Decimal("0.11")

    def test_get_ppn_rate_with_date(self):
        # Before April 2022: should be 10%? Actually default rates only have 11% and 12%, no 10% in defaults.
        # We can test with a date in 2021, but there is no 10% rate, so it would raise RateNotFoundError.
        # Instead, test with a date in 2023 (should return 11% as decimal 0.11)
        rate = RateRegistry.get_ppn_rate(effective_date=date(2023, 6, 1))
        assert rate == Decimal("0.11")
        # After 2026: should return 12% as decimal 0.12
        rate_2026 = RateRegistry.get_ppn_rate(effective_date=date(2026, 2, 1))
        assert rate_2026 == Decimal("0.12")

    def test_get_ppn_rate_no_match(self):
        # If no rate found, get_rate_value raises RateNotFoundError, which propagates
        # We can mock the registry to return None for a tax type.
        with patch("policy_engine.tax_indonesia.rate_registry_dynamic.get_dynamic_rate_registry") as mock_get:
            mock_reg = MagicMock()
            mock_reg.get_rate_value.side_effect = RateNotFoundError("No rate")
            mock_get.return_value = mock_reg
            with pytest.raises(RateNotFoundError):
                RateRegistry.get_ppn_rate(effective_date=date(2000, 1, 1))

    def test_get_pph21_progressive_rates(self):
        brackets = RateRegistry.get_pph21_progressive_rates()
        assert len(brackets) == 5
        # Check first bracket
        assert brackets[0] == (Decimal("0"), Decimal("60000000"), Decimal("0.05"))
        # Check last bracket (upper bound is huge)
        assert brackets[4] == (Decimal("5000000000"), Decimal("999999999999"), Decimal("0.35"))
