# test_tax_rate_vo.py
# ===================
# Comprehensive tests for domain/shared_value_objects/tax_rate_vo.py.
# Covers all public methods, enums, exceptions, factory methods, properties,
# business logic, serialization, comparison, and helper functions.

from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from unittest.mock import patch

import pytest

from domain.shared_value_objects.tax_rate_vo import (
    InvalidTaxRateError,
    TaxRateError,
    TaxRateVO,
    TaxType,
    add_audit,
    calculate_tax_for_amount,
    find_active_tax_rate,
    get_tax_rate_at_date,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def vat_rate() -> TaxRateVO:
    """Create a VAT 11% rate effective from 2025-01-01."""
    return TaxRateVO(
        rate=PercentageVO.of(11),
        tax_type=TaxType.VAT,
        effective_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        description="PPN 11%",
        code="VAT-11",
        created_by="system",
    )


@pytest.fixture
def vat_rate_old() -> TaxRateVO:
    """Create a VAT 10% rate effective from 2024-01-01 to 2024-12-31."""
    return TaxRateVO(
        rate=PercentageVO.of(10),
        tax_type=TaxType.VAT,
        effective_date=datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
        expiry_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        description="PPN 10% (old)",
        code="VAT-10",
        created_by="system",
    )


@pytest.fixture
def income_tax_rate() -> TaxRateVO:
    """Create an income tax 22% rate effective from 2025-01-01."""
    return TaxRateVO(
        rate=PercentageVO.of(22),
        tax_type=TaxType.INCOME_TAX,
        effective_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        description="PPh Badan 22%",
        code="PPh-22",
        created_by="system",
    )


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestTaxType:
    def test_members_exist(self):
        assert hasattr(TaxType, "VAT")
        assert hasattr(TaxType, "INCOME_TAX")
        assert hasattr(TaxType, "WITHHOLDING")
        assert hasattr(TaxType, "FINAL")
        assert hasattr(TaxType, "SALES_TAX")
        assert hasattr(TaxType, "CUSTOMS")
        assert hasattr(TaxType, "LOCAL_TAX")
        assert hasattr(TaxType, "PROPERTY_TAX")
        assert hasattr(TaxType, "EXCISE")

    def test_member_is_instance(self):
        assert isinstance(TaxType.VAT, TaxType)

    def test_from_string_valid(self):
        assert TaxType.from_string("vat") == TaxType.VAT
        assert TaxType.from_string("VAT") == TaxType.VAT
        assert TaxType.from_string("income") == TaxType.INCOME_TAX
        assert TaxType.from_string("INCOME") == TaxType.INCOME_TAX
        assert TaxType.from_string("withholding") == TaxType.WITHHOLDING
        assert TaxType.from_string("final") == TaxType.FINAL
        assert TaxType.from_string("sales") == TaxType.SALES_TAX
        assert TaxType.from_string("customs") == TaxType.CUSTOMS
        assert TaxType.from_string("local") == TaxType.LOCAL_TAX
        assert TaxType.from_string("property") == TaxType.PROPERTY_TAX
        assert TaxType.from_string("excise") == TaxType.EXCISE

    def test_from_string_unknown_returns_none(self):
        assert TaxType.from_string("unknown") is None
        assert TaxType.from_string("") is None

    def test_display_name(self):
        assert TaxType.VAT.display_name() == "PPN"
        assert TaxType.INCOME_TAX.display_name() == "PPh"
        assert TaxType.WITHHOLDING.display_name() == "PPh Potong/Pungut"
        assert TaxType.FINAL.display_name() == "PPh Final"
        assert TaxType.SALES_TAX.display_name() == "PPnBM"
        assert TaxType.CUSTOMS.display_name() == "Bea Masuk"
        assert TaxType.LOCAL_TAX.display_name() == "Pajak Daerah"
        assert TaxType.PROPERTY_TAX.display_name() == "PBB"
        assert TaxType.EXCISE.display_name() == "Cukai"


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class TestExceptions:
    def test_tax_rate_error(self):
        err = TaxRateError("test")
        assert isinstance(err, ValueError)
        assert str(err) == "test"

    def test_invalid_tax_rate_error(self):
        err = InvalidTaxRateError("test")
        assert isinstance(err, TaxRateError)


# ----------------------------------------------------------------------
# TaxRateVO - Construction & Validation
# ----------------------------------------------------------------------
class TestTaxRateVOConstruction:
    def test_construction_valid(self, vat_rate):
        assert vat_rate.rate.value == Decimal("11")
        assert vat_rate.tax_type == TaxType.VAT
        assert vat_rate.effective_date == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert vat_rate.expiry_date is None
        assert vat_rate.description == "PPN 11%"
        assert vat_rate.code == "VAT-11"
        assert vat_rate.created_by == "system"

    def test_construction_naive_dates_auto_utc(self):
        rate = TaxRateVO(
            rate=PercentageVO.of(11),
            tax_type=TaxType.VAT,
            effective_date=datetime(2025, 1, 1, 0, 0, 0),  # naive
            expiry_date=datetime(2026, 1, 1, 0, 0, 0),  # naive
        )
        assert rate.effective_date.tzinfo == UTC
        assert rate.expiry_date.tzinfo == UTC

    def test_construction_expiry_must_be_after_effective(self):
        with pytest.raises(InvalidTaxRateError, match="expiry_date.*must be after"):
            TaxRateVO(
                rate=PercentageVO.of(11),
                tax_type=TaxType.VAT,
                effective_date=datetime(2025, 1, 1, tzinfo=UTC),
                expiry_date=datetime(2025, 1, 1, tzinfo=UTC),  # equal
            )

    def test_construction_description_too_long_raises(self):
        long_desc = "x" * 501
        with pytest.raises(InvalidTaxRateError, match="Description must not exceed 500"):
            TaxRateVO(
                rate=PercentageVO.of(11),
                tax_type=TaxType.VAT,
                effective_date=datetime.now(UTC),
                description=long_desc,
            )

    def test_construction_code_too_long_raises(self):
        long_code = "x" * 51
        with pytest.raises(InvalidTaxRateError, match="Code must not exceed 50"):
            TaxRateVO(
                rate=PercentageVO.of(11),
                tax_type=TaxType.VAT,
                effective_date=datetime.now(UTC),
                code=long_code,
            )

    def test_construction_created_by_too_long_raises(self):
        long_name = "x" * 101
        with pytest.raises(InvalidTaxRateError, match="created_by must not exceed 100"):
            TaxRateVO(
                rate=PercentageVO.of(11),
                tax_type=TaxType.VAT,
                effective_date=datetime.now(UTC),
                created_by=long_name,
            )

    def test_construction_empty_code_becomes_none(self):
        rate = TaxRateVO(
            rate=PercentageVO.of(11),
            tax_type=TaxType.VAT,
            effective_date=datetime.now(UTC),
            code="   ",
        )
        assert rate.code is None

    def test_construction_empty_created_by_becomes_none(self):
        rate = TaxRateVO(
            rate=PercentageVO.of(11),
            tax_type=TaxType.VAT,
            effective_date=datetime.now(UTC),
            created_by="   ",
        )
        assert rate.created_by is None


# ----------------------------------------------------------------------
# TaxRateVO - Factory Methods
# ----------------------------------------------------------------------
class TestTaxRateVOFactory:
    def test_create_vat(self):
        eff = datetime(2025, 4, 1, tzinfo=UTC)
        with patch("domain.shared_value_objects.tax_rate_vo.add_audit") as mock_audit:
            rate = TaxRateVO.create_vat(
                rate_percent=11,
                effective_date=eff,
                description="PPN 11%",
                code="VAT-11",
                idempotency_key="key-123",
            )
        assert rate.tax_type == TaxType.VAT
        assert rate.rate.value == Decimal("11")
        assert rate.effective_date == eff
        assert rate.description == "PPN 11%"
        assert rate.code == "VAT-11"
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args[1]
        assert call_args["rate_percent"] == "11"
        assert call_args["idempotency_key"] == "key-123"

    def test_create_vat_defaults(self):
        eff = datetime(2025, 4, 1, tzinfo=UTC)
        rate = TaxRateVO.create_vat(12, eff)
        assert rate.description == "VAT 12%"
        assert rate.code == "VAT-12"

    def test_create_income_tax(self):
        eff = datetime(2025, 1, 1, tzinfo=UTC)
        with patch("domain.shared_value_objects.tax_rate_vo.add_audit") as mock_audit:
            rate = TaxRateVO.create_income_tax(
                rate_percent=22,
                effective_date=eff,
                description="PPh Badan",
                code="PPh-22",
                idempotency_key="key-456",
            )
        assert rate.tax_type == TaxType.INCOME_TAX
        assert rate.rate.value == Decimal("22")
        assert rate.effective_date == eff
        assert rate.description == "PPh Badan"
        assert rate.code == "PPh-22"
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args[1]
        assert call_args["rate_percent"] == "22"
        assert call_args["idempotency_key"] == "key-456"

    def test_create_withholding(self):
        eff = datetime(2025, 1, 1, tzinfo=UTC)
        with patch("domain.shared_value_objects.tax_rate_vo.add_audit") as mock_audit:
            rate = TaxRateVO.create_withholding(
                rate_percent=5,
                effective_date=eff,
                description="WHT 5%",
                code="WHT-5",
                idempotency_key="key-789",
            )
        assert rate.tax_type == TaxType.WITHHOLDING
        assert rate.rate.value == Decimal("5")
        assert rate.effective_date == eff
        assert rate.description == "WHT 5%"
        assert rate.code == "WHT-5"
        mock_audit.assert_called_once()


# ----------------------------------------------------------------------
# TaxRateVO - Properties
# ----------------------------------------------------------------------
class TestTaxRateVOProperties:
    def test_rate_percent(self, vat_rate):
        assert vat_rate.rate_percent == Decimal("11")

    def test_rate_factor(self, vat_rate):
        assert vat_rate.rate_factor == Decimal("0.11")

    def test_display_name(self, vat_rate):
        assert vat_rate.display_name == "PPN 11%"


# ----------------------------------------------------------------------
# TaxRateVO - Business Logic (is_active, calculate, calculate_inclusive, apply, expire)
# ----------------------------------------------------------------------
class TestTaxRateVOBusiness:
    def test_is_active_active(self, vat_rate):
        # Effective 2025-01-01, check in 2025-06-01 -> active
        as_of = datetime(2025, 6, 1, tzinfo=UTC)
        assert vat_rate.is_active(as_of) is True

    def test_is_active_before_effective(self, vat_rate):
        as_of = datetime(2024, 12, 31, tzinfo=UTC)
        assert vat_rate.is_active(as_of) is False

    def test_is_active_after_expiry(self, vat_rate_old):
        as_of = datetime(2025, 1, 1, tzinfo=UTC)  # expiry is 2025-01-01 (not inclusive)
        assert vat_rate_old.is_active(as_of) is False
        as_of = datetime(2024, 12, 31, tzinfo=UTC)
        assert vat_rate_old.is_active(as_of) is True

    def test_is_active_defaults_to_now(self, vat_rate):
        # Patch datetime.now to a time within active period
        with patch("domain.shared_value_objects.tax_rate_vo.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 1, tzinfo=UTC)
            assert vat_rate.is_active() is True

    def test_calculate_normal(self, vat_rate):
        amount = Decimal("1000000")
        tax = vat_rate.calculate(amount)
        assert tax == Decimal("110000.00")

    def test_calculate_with_rounding(self, vat_rate):
        amount = Decimal("1000.005")
        tax = vat_rate.calculate(amount, rounding=2)
        # 1000.005 * 0.11 = 110.00055 -> quantized to 110.00
        assert tax == Decimal("110.00")
        # with rounding to 3 decimal places
        tax = vat_rate.calculate(amount, rounding=3)
        assert tax == Decimal("110.001")  # 110.00055 rounded to 3 decimals = 110.001

    def test_calculate_negative_amount_raises(self, vat_rate):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            vat_rate.calculate(Decimal("-100"))

    def test_calculate_inclusive(self, vat_rate):
        total = Decimal("111000")
        tax = vat_rate.calculate_inclusive(total)
        # 111000 * 0.11 / 1.11 = 111000 * 0.099099... = 11000.0
        assert tax == Decimal("11000.00")

    def test_calculate_inclusive_negative_raises(self, vat_rate):
        with pytest.raises(ValueError, match="Total amount cannot be negative"):
            vat_rate.calculate_inclusive(Decimal("-100"))

    def test_apply_exclusive(self, vat_rate):
        amount = Decimal("1000000")
        total = vat_rate.apply(amount, inclusive=False)
        assert total == Decimal("1110000.00")  # 1,000,000 + 110,000

    def test_apply_inclusive(self, vat_rate):
        amount = Decimal("1000000")
        total = vat_rate.apply(amount, inclusive=True)
        # amount is total including tax, we need to compute tax from it
        # Actually apply with inclusive=True uses calculate_inclusive, which computes tax from total,
        # then adds to amount (which is total). So total = amount + tax.
        # For amount=1,000,000, tax = 1,000,000 * 0.11 / 1.11 = 99,099.10, total = 1,099,099.10
        expected_tax = amount * Decimal("0.11") / Decimal("1.11")
        expected_total = amount + expected_tax
        expected_total = expected_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        assert total == expected_total

    def test_expire_success(self, vat_rate):
        new_expiry = datetime(2026, 1, 1, tzinfo=UTC)
        expired = vat_rate.expire(new_expiry, expired_by="admin")
        assert expired.expiry_date == new_expiry
        assert expired.created_by == "admin"
        assert expired.rate == vat_rate.rate
        assert expired.tax_type == vat_rate.tax_type
        assert expired.effective_date == vat_rate.effective_date

    def test_expire_already_expired_raises(self, vat_rate_old):
        new_expiry = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(TaxRateError, match="already expires at"):
            vat_rate_old.expire(new_expiry)

    def test_expire_naive_date_converted(self, vat_rate):
        naive = datetime(2026, 1, 1, 0, 0, 0)
        expired = vat_rate.expire(naive)
        assert expired.expiry_date.tzinfo == UTC
        assert expired.expiry_date == naive.replace(tzinfo=UTC)

    def test_expire_date_before_effective_raises(self, vat_rate):
        bad_expiry = datetime(2024, 12, 31, tzinfo=UTC)
        with pytest.raises(InvalidTaxRateError, match="Expiry date must be after effective date"):
            vat_rate.expire(bad_expiry)


# ----------------------------------------------------------------------
# TaxRateVO - Comparison & Serialization
# ----------------------------------------------------------------------
class TestTaxRateVOComparison:
    def test_equality(self, vat_rate):
        same = TaxRateVO(
            rate=PercentageVO.of(11),
            tax_type=TaxType.VAT,
            effective_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        diff_rate = TaxRateVO(
            rate=PercentageVO.of(12),
            tax_type=TaxType.VAT,
            effective_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        diff_type = TaxRateVO(
            rate=PercentageVO.of(11),
            tax_type=TaxType.INCOME_TAX,
            effective_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        assert vat_rate == same
        assert vat_rate != diff_rate
        assert vat_rate != diff_type
        assert vat_rate != "not a tax rate"

    def test_hash(self, vat_rate):
        same = TaxRateVO(
            rate=PercentageVO.of(11),
            tax_type=TaxType.VAT,
            effective_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        assert hash(vat_rate) == hash(same)

    def test_less_than(self, vat_rate, vat_rate_old):
        # vat_rate_old effective 2024-01-01, vat_rate effective 2025-01-01
        assert vat_rate_old < vat_rate
        assert not (vat_rate < vat_rate_old)
        # Compare to same returns False
        assert not (vat_rate < vat_rate)

    def test_str(self, vat_rate):
        assert str(vat_rate) == "PPN 11%"

    def test_repr(self, vat_rate):
        assert repr(vat_rate).startswith("TaxRateVO(11%")
        assert "effective=2025-01-01" in repr(vat_rate)


class TestTaxRateVOSerialization:
    def test_to_dict(self, vat_rate):
        d = vat_rate.to_dict()
        assert d["rate"] == "11"
        assert d["rate_percent"] == "11"
        assert d["tax_type"] == "vat"
        assert d["tax_type_display"] == "PPN"
        assert d["effective_date"] == "2025-01-01T00:00:00+00:00"
        assert d["expiry_date"] is None
        assert d["description"] == "PPN 11%"
        assert d["code"] == "VAT-11"
        assert d["display_name"] == "PPN 11%"

    def test_to_db_record(self, vat_rate):
        rec = vat_rate.to_db_record()
        assert rec["rate"] == Decimal("11")
        assert rec["tax_type"] == "vat"
        assert rec["effective_date"] == vat_rate.effective_date
        assert rec["expiry_date"] is None
        assert rec["description"] == "PPN 11%"
        assert rec["code"] == "VAT-11"
        assert rec["created_by"] == "system"

    def test_from_dict(self):
        data = {
            "rate": "11",
            "tax_type": "vat",
            "effective_date": "2025-01-01T00:00:00+00:00",
            "expiry_date": None,
            "description": "Test",
            "code": "VAT-TEST",
            "created_by": "admin",
        }
        rate = TaxRateVO.from_dict(data)
        assert rate.rate.value == Decimal("11")
        assert rate.tax_type == TaxType.VAT
        assert rate.effective_date == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert rate.expiry_date is None
        assert rate.description == "Test"
        assert rate.code == "VAT-TEST"
        assert rate.created_by == "admin"

    def test_from_dict_invalid_tax_type_raises(self):
        data = {
            "rate": "11",
            "tax_type": "invalid",
            "effective_date": "2025-01-01T00:00:00+00:00",
        }
        with pytest.raises(InvalidTaxRateError, match="Invalid tax_type"):
            TaxRateVO.from_dict(data)


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelperFunctions:
    def test_find_active_tax_rate_found(self, vat_rate, vat_rate_old):
        rates = [vat_rate_old, vat_rate]
        as_of = datetime(2024, 6, 1, tzinfo=UTC)
        found = find_active_tax_rate(rates, TaxType.VAT, as_of)
        assert found == vat_rate_old
        as_of = datetime(2025, 6, 1, tzinfo=UTC)
        found = find_active_tax_rate(rates, TaxType.VAT, as_of)
        assert found == vat_rate

    def test_find_active_tax_rate_not_found(self, vat_rate):
        rates = [vat_rate]
        as_of = datetime(2024, 12, 31, tzinfo=UTC)
        found = find_active_tax_rate(rates, TaxType.VAT, as_of)
        assert found is None

    def test_find_active_tax_rate_defaults_to_now(self, vat_rate):
        with patch("domain.shared_value_objects.tax_rate_vo.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 1, tzinfo=UTC)
            found = find_active_tax_rate([vat_rate], TaxType.VAT)
            assert found == vat_rate

    def test_get_tax_rate_at_date_alias(self, vat_rate):
        rates = [vat_rate]
        as_of = datetime(2025, 6, 1, tzinfo=UTC)
        found = get_tax_rate_at_date(rates, TaxType.VAT, as_of)
        assert found == vat_rate

    def test_calculate_tax_for_amount_success(self, vat_rate):
        rates = [vat_rate]
        amount = Decimal("1000000")
        as_of = datetime(2025, 6, 1, tzinfo=UTC)
        tax = calculate_tax_for_amount(rates, amount, TaxType.VAT, as_of)
        assert tax == Decimal("110000.00")

    def test_calculate_tax_for_amount_no_rate_raises(self):
        rates = []
        with pytest.raises(TaxRateError, match="No active tax rate found"):
            calculate_tax_for_amount(rates, Decimal("1000"), TaxType.VAT)


# ----------------------------------------------------------------------
# add_audit function (just logs)
# ----------------------------------------------------------------------
def test_add_audit_logs(caplog):
    import logging
    caplog.set_level(logging.INFO)
    add_audit("TEST_ACTION", {"key": "value"})
    assert "AUDIT: TEST_ACTION - {'key': 'value'}" in caplog.text