# tests/policy_engine/tax_indonesia/test_withholding_engine.py
"""
Comprehensive unit tests for policy_engine/tax_indonesia/withholding_engine.py.
Covers all enums, exceptions, WithholdingRecord, and WithholdingEngine methods.
Uses mocking to avoid external dependencies and ensure deterministic results.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from policy_engine.tax_indonesia.withholding_engine import (
    WithholdingEngine,
    WithholdingEngineError,
    WithholdingNotFoundError,
    WithholdingPeriod,
    WithholdingRecord,
    WithholdingStatus,
    WithholdingType,
    get_withholding_engine,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def mock_datetime_now(mocker):
    """Mock datetime.now in withholding_engine to fixed time."""
    fixed = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
    mocker.patch("policy_engine.tax_indonesia.withholding_engine.datetime.now", return_value=fixed)
    return fixed


@pytest.fixture
def fixed_datetime():
    return datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_taxpayer_id():
    return uuid4()


@pytest.fixture
def sample_transaction_id():
    return uuid4()


@pytest.fixture
def sample_record_data(sample_transaction_id, sample_taxpayer_id, fixed_datetime):
    return {
        "record_id": uuid4(),
        "withholding_type": WithholdingType.PPH_23,
        "transaction_id": sample_transaction_id,
        "taxpayer_id": sample_taxpayer_id,
        "taxpayer_name": "PT Test",
        "gross_amount": Decimal("10000000"),
        "tax_amount": Decimal("200000"),
        "tariff": Decimal("0.02"),
        "period": "2026-07",
        "transaction_date": fixed_datetime,
        "withholding_date": fixed_datetime,
        "status": WithholdingStatus.CALCULATED,
        "withholding_number": "2.1.1.23.2026.07.00001",
        "details": {"service": "consulting"},
        "cancelled_at": None,
        "cancelled_by": None,
        "hash_sha256": "",
    }


@pytest.fixture
def sample_record(sample_record_data):
    return WithholdingRecord(**sample_record_data)


@pytest.fixture
def engine_with_mocks(mocker):
    """Return WithholdingEngine with mocked calculators."""
    # Mock all calculators
    mock_pph21 = mocker.MagicMock()
    mock_pph22 = mocker.MagicMock()
    mock_pph23 = mocker.MagicMock()
    mock_pph25 = mocker.MagicMock()
    mock_pph26 = mocker.MagicMock()
    mock_pph42 = mocker.MagicMock()
    mock_pph_badan = mocker.MagicMock()
    mock_rate_registry = mocker.MagicMock()

    # Patch getters to return mocks
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_pph21_calculator",
        return_value=mock_pph21,
    )
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_pph22_calculator",
        return_value=mock_pph22,
    )
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_pph23_calculator",
        return_value=mock_pph23,
    )
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_pph25_calculator",
        return_value=mock_pph25,
    )
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_pph26_calculator",
        return_value=mock_pph26,
    )
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_pph4_ayat_2_calculator",
        return_value=mock_pph42,
    )
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_pph_badan_calculator",
        return_value=mock_pph_badan,
    )
    mocker.patch(
        "policy_engine.tax_indonesia.withholding_engine.get_dynamic_rate_registry",
        return_value=mock_rate_registry,
    )

    # Create engine with mocked dependencies
    engine = WithholdingEngine()
    # Override the internal references to mocks for easier assertion
    engine._pph21 = mock_pph21
    engine._pph22 = mock_pph22
    engine._pph23 = mock_pph23
    engine._pph25 = mock_pph25
    engine._pph26 = mock_pph26
    engine._pph42 = mock_pph42
    engine._pph_badan = mock_pph_badan
    engine._rate_registry = mock_rate_registry
    return engine


@pytest.fixture
def engine_with_calculator_mocks(engine_with_mocks):
    """Engine with calculator mocks configured to return predictable results."""
    # Configure mock calculators to return a simple result object
    class MockResult:
        def __init__(self, tax_amount, tariff, **kwargs):
            self.tax_amount = tax_amount
            self.tariff = tariff
            self.to_dict = lambda: {"tax_amount": str(tax_amount), "tariff": str(tariff)}

    # PPh 23 mock
    mock_pph23_result = MockResult(Decimal("200000"), Decimal("0.02"))
    engine_with_mocks._pph23.calculate_tax.return_value = mock_pph23_result

    # PPh 22 mocks for different methods
    mock_pph22_result = MockResult(Decimal("150000"), Decimal("0.015"))
    engine_with_mocks._pph22.calculate_import.return_value = mock_pph22_result
    engine_with_mocks._pph22.calculate_government_purchase.return_value = mock_pph22_result
    engine_with_mocks._pph22.calculate_producer_sales.return_value = mock_pph22_result
    engine_with_mocks._pph22.calculate_auction.return_value = mock_pph22_result

    # PPh 4(2) mocks
    mock_pph42_result = MockResult(Decimal("300000"), Decimal("0.03"))
    engine_with_mocks._pph42.calculate_land_building_rental.return_value = mock_pph42_result
    engine_with_mocks._pph42.calculate_construction_services.return_value = mock_pph42_result
    engine_with_mocks._pph42.calculate_umkm_turnover.return_value = mock_pph42_result
    engine_with_mocks._pph42.calculate_real_estate_sales.return_value = mock_pph42_result
    engine_with_mocks._pph42.calculate_lottery_prize.return_value = mock_pph42_result

    # PPh 26 mock
    mock_pph26_result = MockResult(Decimal("250000"), Decimal("0.025"))
    engine_with_mocks._pph26.calculate.return_value = mock_pph26_result

    # PPh 21 mock
    mock_pph21_result = MockResult(Decimal("100000"), Decimal("0.01"))
    engine_with_mocks._pph21.calculate_monthly_tax.return_value = mock_pph21_result

    return engine_with_mocks


# ============================================================================
# Tests for Enums
# ============================================================================

class TestWithholdingType:
    def test_members(self):
        assert WithholdingType.PPH_21.value == "pph21"
        assert WithholdingType.PPH_22.value == "pph22"
        assert WithholdingType.PPH_23.value == "pph23"
        assert WithholdingType.PPH_25.value == "pph25"
        assert WithholdingType.PPH_26.value == "pph26"
        assert WithholdingType.PPH_4_AYAT_2.value == "pph4_2"
        assert WithholdingType.PPH_BADAN.value == "pph_badan"


class TestWithholdingStatus:
    def test_members(self):
        assert WithholdingStatus.CALCULATED.value == "calculated"
        assert WithholdingStatus.WITHHELD.value == "withheld"
        assert WithholdingStatus.PAID.value == "paid"
        assert WithholdingStatus.REPORTED.value == "reported"
        assert WithholdingStatus.CANCELLED.value == "cancelled"


class TestWithholdingPeriod:
    def test_members(self):
        assert WithholdingPeriod.MONTHLY.value == "monthly"
        assert WithholdingPeriod.QUARTERLY.value == "quarterly"
        assert WithholdingPeriod.ANNUAL.value == "annual"


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_inheritance(self):
        assert issubclass(WithholdingNotFoundError, WithholdingEngineError)

    def test_instantiation(self):
        e = WithholdingEngineError("test")
        assert str(e) == "test"


# ============================================================================
# Tests for WithholdingRecord
# ============================================================================

class TestWithholdingRecord:
    def test_construction(self, sample_record_data):
        record = WithholdingRecord(**sample_record_data)
        assert record.record_id == sample_record_data["record_id"]
        assert record.withholding_type == sample_record_data["withholding_type"]
        assert record.tax_amount == sample_record_data["tax_amount"]
        # Hash should be computed
        assert record.hash_sha256 != ""
        assert len(record.hash_sha256) == 64

    def test_hash_changes_on_status_update(self, sample_record):
        old_hash = sample_record.hash_sha256
        sample_record.status = WithholdingStatus.WITHHELD
        # Recompute hash by calling _compute_hash
        sample_record.hash_sha256 = sample_record._compute_hash()
        assert sample_record.hash_sha256 != old_hash

    def test_to_dict(self, sample_record):
        d = sample_record.to_dict()
        assert d["record_id"] == str(sample_record.record_id)
        assert d["withholding_type"] == sample_record.withholding_type.value
        assert d["tax_amount"] == str(sample_record.tax_amount)
        assert "hash" in d


# ============================================================================
# Tests for WithholdingEngine
# ============================================================================

class TestWithholdingEngine:
    def test_singleton(self):
        e1 = WithholdingEngine()
        e2 = WithholdingEngine()
        assert e1 is e2

    def test_initialization(self, engine_with_mocks):
        assert engine_with_mocks._pph21 is not None
        assert engine_with_mocks._pph22 is not None
        assert engine_with_mocks._pph23 is not None
        assert engine_with_mocks._pph25 is not None
        assert engine_with_mocks._pph26 is not None
        assert engine_with_mocks._pph42 is not None
        assert engine_with_mocks._pph_badan is not None
        assert engine_with_mocks._rate_registry is not None

    # ---- calculate (main) ----
    def test_calculate(self, engine_with_mocks):
        result = engine_with_mocks.calculate(
            bruto=Decimal("10000000"),
            pph_type="23",
            rate=Decimal("0.02"),
            has_npwp=True,
        )
        expected = Decimal("200000")
        assert result == expected

        # Without NPWP => factor 2
        result2 = engine_with_mocks.calculate(
            bruto=Decimal("10000000"),
            pph_type="23",
            rate=Decimal("0.02"),
            has_npwp=False,
        )
        assert result2 == Decimal("400000")

    # ---- calculate_tax (compatibility) ----
    def test_calculate_tax(self, engine_with_mocks):
        tax = engine_with_mocks.calculate_tax(
            bruto=Decimal("5000000"),
            pph_type="23",
            rate=Decimal("0.02"),
            has_npwp=True,
        )
        assert tax == Decimal("100000")

    # ---- calculate_simple ----
    def test_calculate_simple(self, engine_with_mocks):
        result = engine_with_mocks.calculate_simple(
            bruto=Decimal("10000000"),
            pph_type="23",
            rate=Decimal("0.02"),
            has_npwp=True,
        )
        assert result.tax == Decimal("200000")
        assert result.npwp_factor == Decimal("1")

        result2 = engine_with_mocks.calculate_simple(
            bruto=Decimal("10000000"),
            pph_type="23",
            rate=Decimal("0.02"),
            has_npwp=False,
        )
        assert result2.tax == Decimal("400000")
        assert result2.npwp_factor == Decimal("2")

    # ---- get_rate ----
    def test_get_rate(self, engine_with_mocks):
        rate = engine_with_mocks.get_rate()
        assert rate == Decimal("0.02")  # default

    # ---- validate ----
    def test_validate(self, engine_with_mocks):
        assert engine_with_mocks.validate({}) is True

    # ---- _generate_withholding_number ----
    def test_generate_withholding_number_pph23(self, engine_with_mocks):
        with engine_with_mocks._lock:
            engine_with_mocks._withholding_counter = 5
        num = engine_with_mocks._generate_withholding_number(WithholdingType.PPH_23, "2026-07")
        assert num == "2.1.1.23.2026.07.00005"

    def test_generate_withholding_number_pph22(self, engine_with_mocks):
        with engine_with_mocks._lock:
            engine_with_mocks._withholding_counter = 10
        num = engine_with_mocks._generate_withholding_number(WithholdingType.PPH_22, "2026-08")
        assert num == "2.1.1.22.2026.08.00010"

    def test_generate_withholding_number_pph26(self, engine_with_mocks):
        num = engine_with_mocks._generate_withholding_number(WithholdingType.PPH_26, "2026-09")
        assert num.startswith("2.1.1.26.2026.09.")

    def test_generate_withholding_number_pph42(self, engine_with_mocks):
        num = engine_with_mocks._generate_withholding_number(WithholdingType.PPH_4_AYAT_2, "2026-10")
        assert num.startswith("2.1.1.42.2026.10.")

    def test_generate_withholding_number_other(self, engine_with_mocks):
        num = engine_with_mocks._generate_withholding_number(WithholdingType.PPH_21, "2026-11")
        assert num.startswith("WTH-PPH21-2026-11-")

    # ---- withhold_pph23 ----
    def test_withhold_pph23_success(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
            npwp_status="HAS_NPWP",
            service_subtype="consulting",
            is_exempt=False,
        )
        assert record.withholding_type == WithholdingType.PPH_23
        assert record.tax_amount == Decimal("200000")
        assert record.withholding_number.startswith("2.1.1.23")
        assert record.record_id in engine._records
        # Verify calculator called with correct parameters
        engine._pph23.calculate_tax.assert_called_once()

    def test_withhold_pph23_with_exemption(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
            is_exempt=True,
            exemption_reason="SKB",
        )
        assert record.tax_amount == Decimal("200000")  # Mock returns same
        # Verify exemption parameters passed
        call_args = engine._pph23.calculate_tax.call_args
        assert call_args[1]["is_exempted"] is True
        assert call_args[1]["exemption_reason"] == "SKB"

    # ---- withhold_pph22 ----
    def test_withhold_pph22_import(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Import",
            gross_amount=Decimal("10000000"),
            transaction_type="import",
            transaction_date=fixed_datetime,
            period="2026-07",
            importer_type="with_api",
            has_masterlist=False,
        )
        assert record.withholding_type == WithholdingType.PPH_22
        assert record.tax_amount == Decimal("150000")
        engine._pph22.calculate_import.assert_called_once()

    def test_withhold_pph22_government_purchase(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Gov",
            gross_amount=Decimal("10000000"),
            transaction_type="government_purchase",
            transaction_date=fixed_datetime,
            period="2026-07",
            purchaser_type="bumn",
            is_pkp=True,
            has_exemption=False,
        )
        assert record.tax_amount == Decimal("150000")
        engine._pph22.calculate_government_purchase.assert_called_once()

    def test_withhold_pph22_producer_sales(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Producer",
            gross_amount=Decimal("10000000"),
            transaction_type="producer_sales",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        assert record.tax_amount == Decimal("150000")
        engine._pph22.calculate_producer_sales.assert_called_once()

    def test_withhold_pph22_auction(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Auction",
            gross_amount=Decimal("10000000"),
            transaction_type="auction",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        assert record.tax_amount == Decimal("150000")
        engine._pph22.calculate_auction.assert_called_once()

    def test_withhold_pph22_unsupported(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        with pytest.raises(WithholdingEngineError, match="Unsupported PPh 22 type"):
            engine.withhold_pph22(
                transaction_id=sample_transaction_id,
                taxpayer_id=sample_taxpayer_id,
                taxpayer_name="PT Invalid",
                gross_amount=Decimal("10000000"),
                transaction_type="invalid",
                transaction_date=fixed_datetime,
                period="2026-07",
            )

    # ---- withhold_pph42 ----
    def test_withhold_pph42_land_rental(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph42(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Land",
            gross_amount=Decimal("10000000"),
            transaction_type="land_rental",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        assert record.withholding_type == WithholdingType.PPH_4_AYAT_2
        assert record.tax_amount == Decimal("300000")
        engine._pph42.calculate_land_building_rental.assert_called_once()

    def test_withhold_pph42_construction_services(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        from policy_engine.tax_indonesia.pph_4_ayat_2_calculator import ConstructionServiceType
        record = engine.withhold_pph42(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Konstruksi",
            gross_amount=Decimal("10000000"),
            transaction_type="construction_services",
            transaction_date=fixed_datetime,
            period="2026-07",
            construction_service_type=ConstructionServiceType.MEDIUM_SCALE,
            has_npwp=True,
        )
        assert record.tax_amount == Decimal("300000")
        engine._pph42.calculate_construction_services.assert_called_once()

    def test_withhold_pph42_umkm(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph42(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT UMKM",
            gross_amount=Decimal("10000000"),
            transaction_type="umkm",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        assert record.tax_amount == Decimal("300000")
        engine._pph42.calculate_umkm_turnover.assert_called_once()

    def test_withhold_pph42_real_estate(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph42(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Realty",
            gross_amount=Decimal("10000000"),
            transaction_type="real_estate",
            transaction_date=fixed_datetime,
            period="2026-07",
            is_subsidized=True,
        )
        assert record.tax_amount == Decimal("300000")
        engine._pph42.calculate_real_estate_sales.assert_called_once()

    def test_withhold_pph42_lottery(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph42(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Lucky",
            gross_amount=Decimal("10000000"),
            transaction_type="lottery",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        assert record.tax_amount == Decimal("300000")
        engine._pph42.calculate_lottery_prize.assert_called_once()

    def test_withhold_pph42_unsupported(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        with pytest.raises(WithholdingEngineError, match="Unsupported PPh 4(2) type"):
            engine.withhold_pph42(
                transaction_id=sample_transaction_id,
                taxpayer_id=sample_taxpayer_id,
                taxpayer_name="PT Invalid",
                gross_amount=Decimal("10000000"),
                transaction_type="invalid",
                transaction_date=fixed_datetime,
                period="2026-07",
            )

    # ---- withhold_pph26 ----
    def test_withhold_pph26(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph26(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="Foreign Ltd",
            gross_amount=Decimal("10000000"),
            income_type="royalty",
            country_code="SG",
            transaction_date=fixed_datetime,
            period="2026-07",
            has_treaty=True,
            treaty_rate_override=Decimal("0.15"),
            effective_date=fixed_datetime,
            is_exempt=False,
            exemption_reason="",
        )
        assert record.withholding_type == WithholdingType.PPH_26
        assert record.tax_amount == Decimal("250000")
        engine._pph26.calculate.assert_called_once()

    # ---- withhold_pph21 ----
    def test_withhold_pph21(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph21(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="Karyawan",
            monthly_gross=Decimal("10000000"),
            ptkp_status="TK/0",
            transaction_date=fixed_datetime,
            period="2026-07",
            position_allowance=Decimal("500000"),
            pension_contribution=Decimal("200000"),
            is_final_month=False,
        )
        assert record.withholding_type == WithholdingType.PPH_21
        assert record.tax_amount == Decimal("100000")
        engine._pph21.calculate_monthly_tax.assert_called_once()

    # ---- record management ----
    def test_get_record(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        retrieved = engine.get_record(record.record_id)
        assert retrieved is record
        assert engine.get_record(uuid4()) is None

    def test_update_status(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        old_hash = record.hash_sha256
        success = engine.update_status(record.record_id, WithholdingStatus.WITHHELD)
        assert success is True
        assert record.status == WithholdingStatus.WITHHELD
        assert record.hash_sha256 != old_hash
        # Non-existent record
        success2 = engine.update_status(uuid4(), WithholdingStatus.PAID)
        assert success2 is False

    def test_cancel_withholding(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        cancelled_by = uuid4()
        success = engine.cancel_withholding(record.record_id, cancelled_by, "Reason")
        assert success is True
        assert record.status == WithholdingStatus.CANCELLED
        assert record.cancelled_at is not None
        assert record.cancelled_by == cancelled_by
        assert record.details["cancellation_reason"] == "Reason"
        # Cancel again should fail
        success2 = engine.cancel_withholding(record.record_id, uuid4(), "Again")
        assert success2 is False
        # Non-existent record
        success3 = engine.cancel_withholding(uuid4(), uuid4(), "X")
        assert success3 is False

    def test_get_records_by_period(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        record1 = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        record2 = engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test2",
            gross_amount=Decimal("20000000"),
            transaction_type="import",
            transaction_date=fixed_datetime,
            period="2026-07",
            importer_type="with_api",
        )
        record3 = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test3",
            gross_amount=Decimal("30000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-08",
        )
        # Get all for 2026-07
        records_jul = engine.get_records_by_period("2026-07")
        assert len(records_jul) == 2
        # Filter by type
        records_jul_pph23 = engine.get_records_by_period("2026-07", WithholdingType.PPH_23)
        assert len(records_jul_pph23) == 1
        assert records_jul_pph23[0].record_id == record1.record_id
        # 2026-08
        records_aug = engine.get_records_by_period("2026-08")
        assert len(records_aug) == 1

    def test_get_records_by_taxpayer(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        taxpayer1 = uuid4()
        taxpayer2 = uuid4()
        record1 = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=taxpayer1,
            taxpayer_name="Taxpayer A",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        record2 = engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=taxpayer2,
            taxpayer_name="Taxpayer B",
            gross_amount=Decimal("20000000"),
            transaction_type="import",
            transaction_date=fixed_datetime,
            period="2026-07",
            importer_type="with_api",
        )
        records_a = engine.get_records_by_taxpayer(taxpayer1)
        assert len(records_a) == 1
        assert records_a[0].record_id == record1.record_id
        records_b = engine.get_records_by_taxpayer(taxpayer2)
        assert len(records_b) == 1
        assert records_b[0].record_id == record2.record_id
        records_empty = engine.get_records_by_taxpayer(uuid4())
        assert records_empty == []

    # ---- reporting ----
    def test_generate_monthly_report(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        # Create some records
        engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test2",
            gross_amount=Decimal("20000000"),
            transaction_type="import",
            transaction_date=fixed_datetime,
            period="2026-07",
            importer_type="with_api",
        )
        # Cancel one
        record_to_cancel = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Cancel",
            gross_amount=Decimal("15000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        engine.cancel_withholding(record_to_cancel.record_id, uuid4(), "Cancel")

        report = engine.generate_monthly_report("2026-07")
        assert report["period"] == "2026-07"
        # Only non-cancelled records counted
        assert report["total_records"] == 2  # Two active
        assert Decimal(report["total_gross"]) == Decimal("30000000")  # 10M + 20M
        assert Decimal(report["total_withholding"]) == Decimal("350000")  # 200k + 150k
        assert "pph23" in report["by_withholding_type"]
        assert "pph22" in report["by_withholding_type"]
        assert len(report["records"]) == 2

    def test_generate_monthly_report_filter_by_type(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        engine.withhold_pph22(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test2",
            gross_amount=Decimal("20000000"),
            transaction_type="import",
            transaction_date=fixed_datetime,
            period="2026-07",
            importer_type="with_api",
        )
        report = engine.generate_monthly_report("2026-07", WithholdingType.PPH_23)
        assert report["total_records"] == 1
        assert Decimal(report["total_withholding"]) == Decimal("200000")
        assert len(report["records"]) == 1

    def test_generate_spt_masa(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test2",
            gross_amount=Decimal("20000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        # Cancel one
        record_to_cancel = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Cancel",
            gross_amount=Decimal("15000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        engine.cancel_withholding(record_to_cancel.record_id, uuid4(), "Cancel")

        spt = engine.generate_spt_masa("2026-07", WithholdingType.PPH_23)
        assert spt["form_type"] == "SPT Masa PPh PPH23"
        assert spt["period"] == "2026-07"
        assert spt["number_of_withholding_slips"] == 2
        assert Decimal(spt["total_tax_withheld"]) == Decimal("400000")  # 200k + 200k
        assert len(spt["details"]) == 2

    # ---- export_to_json ----
    @patch("builtins.open")
    @patch("json.dump")
    def test_export_to_json(self, mock_json_dump, mock_open, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="services",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        engine.export_to_json("test.json")
        mock_open.assert_called_once_with("test.json", "w")
        # Check that json.dump was called with data
        call_args = mock_json_dump.call_args
        data = call_args[0][0]
        assert "records" in data
        assert "summary" in data
        assert data["summary"]["total_records"] == 1

    # ---- singleton getter ----
    def test_get_withholding_engine(self):
        e1 = get_withholding_engine()
        e2 = get_withholding_engine()
        assert e1 is e2

    # ---- negative: unsupported PPh 23 type ----
    def test_withhold_pph23_unsupported_type(self, engine_with_calculator_mocks, sample_transaction_id, sample_taxpayer_id, fixed_datetime):
        engine = engine_with_calculator_mocks
        # The type map will default to SERVICES for unknown, so no exception, but we can test with a non-existent key.
        # Actually the map uses get with default, so no exception. We'll just ensure it doesn't raise.
        record = engine.withhold_pph23(
            transaction_id=sample_transaction_id,
            taxpayer_id=sample_taxpayer_id,
            taxpayer_name="PT Test",
            gross_amount=Decimal("10000000"),
            transaction_type="unknown_type",
            transaction_date=fixed_datetime,
            period="2026-07",
        )
        assert record is not None  # should default to SERVICES

    # ---- test that calculate_simple returns SimpleNamespace ----
    def test_calculate_simple_return_type(self, engine_with_mocks):
        result = engine_with_mocks.calculate_simple(Decimal("1000"), "23", Decimal("0.02"), True)
        assert hasattr(result, "tax")
        assert hasattr(result, "npwp_factor")
