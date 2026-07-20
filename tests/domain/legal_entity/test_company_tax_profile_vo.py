# test_company_tax_profile_vo.py
# Comprehensive tests for company_tax_profile_vo.py

from decimal import Decimal

import pytest

from domain.legal_entity.company_tax_profile_vo import (
    CompanyTaxProfileVO,
    TaxPaymentMethod,
    TaxRegime,
)
from domain.shared_value_objects.percentage_vo import Percentage


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_percentage_22():
    """Valid corporate tax rate 22%."""
    return Percentage(Decimal("22"))


@pytest.fixture
def valid_vat_rate_11():
    """Valid VAT rate 11%."""
    return Percentage(Decimal("11"))


@pytest.fixture
def valid_tax_profile(valid_percentage_22, valid_vat_rate_11):
    """Create a valid CompanyTaxProfileVO."""
    return CompanyTaxProfileVO(
        is_pkp=True,
        tax_regime=TaxRegime.GENERAL,
        corporate_income_tax_rate=valid_percentage_22,
        vat_rate=valid_vat_rate_11,
        vat_collection_method="output",
        income_tax_article="PPh 25",
        tax_bracket="Bracket 1",
        payment_method=TaxPaymentMethod.MONTHLY_INSTALLMENT,
        annual_return_deadline_month=4,
    )


@pytest.fixture
def non_pkp_profile(valid_percentage_22, valid_vat_rate_11):
    """Create a non-PKP profile."""
    return CompanyTaxProfileVO(
        is_pkp=False,
        tax_regime=TaxRegime.GENERAL,
        corporate_income_tax_rate=valid_percentage_22,
        vat_rate=valid_vat_rate_11,
    )


@pytest.fixture
def final_regime_profile(valid_percentage_22, valid_vat_rate_11):
    """Profile with FINAL tax regime."""
    return CompanyTaxProfileVO(
        is_pkp=True,
        tax_regime=TaxRegime.FINAL,
        corporate_income_tax_rate=valid_percentage_22,
        vat_rate=valid_vat_rate_11,
    )


@pytest.fixture
def gross_up_profile(valid_percentage_22, valid_vat_rate_11):
    """Profile with GROSS_UP tax regime."""
    return CompanyTaxProfileVO(
        is_pkp=True,
        tax_regime=TaxRegime.GROSS_UP,
        corporate_income_tax_rate=valid_percentage_22,
        vat_rate=valid_vat_rate_11,
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestTaxRegime:
    def test_members(self):
        assert TaxRegime.GENERAL.value == "general"
        assert TaxRegime.FINAL.value == "final"
        assert TaxRegime.GROSS_UP.value == "gross_up"
        assert TaxRegime.WITHHOLDING.value == "withholding"

    def test_from_string(self):
        assert TaxRegime.from_string("general") == TaxRegime.GENERAL
        assert TaxRegime.from_string("GENERAL") == TaxRegime.GENERAL
        assert TaxRegime.from_string("final") == TaxRegime.FINAL
        assert TaxRegime.from_string("gross_up") == TaxRegime.GROSS_UP
        assert TaxRegime.from_string("withholding") == TaxRegime.WITHHOLDING
        assert TaxRegime.from_string("invalid") == TaxRegime.GENERAL  # default


class TestTaxPaymentMethod:
    def test_members(self):
        assert TaxPaymentMethod.MONTHLY_INSTALLMENT.value == "monthly"
        assert TaxPaymentMethod.ANNUAL_LUMP_SUM.value == "annual"
        assert TaxPaymentMethod.WITHHOLDING.value == "withholding"

    def test_from_string(self):
        assert TaxPaymentMethod.from_string("monthly") == TaxPaymentMethod.MONTHLY_INSTALLMENT
        assert TaxPaymentMethod.from_string("MONTHLY") == TaxPaymentMethod.MONTHLY_INSTALLMENT
        assert TaxPaymentMethod.from_string("annual") == TaxPaymentMethod.ANNUAL_LUMP_SUM
        assert TaxPaymentMethod.from_string("withholding") == TaxPaymentMethod.WITHHOLDING
        assert TaxPaymentMethod.from_string("invalid") == TaxPaymentMethod.MONTHLY_INSTALLMENT  # default


# ============================================================================
# Tests for CompanyTaxProfileVO Construction and Validation
# ============================================================================

class TestCompanyTaxProfileVOConstruction:
    def test_construction_valid(self, valid_tax_profile):
        assert valid_tax_profile.is_pkp is True
        assert valid_tax_profile.tax_regime == TaxRegime.GENERAL
        assert valid_tax_profile.corporate_income_tax_rate.value == Decimal("22")
        assert valid_tax_profile.vat_rate.value == Decimal("11")
        assert valid_tax_profile.vat_collection_method == "output"
        assert valid_tax_profile.income_tax_article == "PPh 25"
        assert valid_tax_profile.tax_bracket == "Bracket 1"
        assert valid_tax_profile.payment_method == TaxPaymentMethod.MONTHLY_INSTALLMENT
        assert valid_tax_profile.annual_return_deadline_month == 4

    def test_validation_corporate_rate_negative(self, valid_vat_rate_11):
        with pytest.raises(ValueError, match="between 0 and 100"):
            CompanyTaxProfileVO(
                is_pkp=True,
                tax_regime=TaxRegime.GENERAL,
                corporate_income_tax_rate=Percentage(Decimal("-1")),
                vat_rate=valid_vat_rate_11,
            )

    def test_validation_corporate_rate_above_100(self, valid_vat_rate_11):
        with pytest.raises(ValueError, match="between 0 and 100"):
            CompanyTaxProfileVO(
                is_pkp=True,
                tax_regime=TaxRegime.GENERAL,
                corporate_income_tax_rate=Percentage(Decimal("101")),
                vat_rate=valid_vat_rate_11,
            )

    def test_validation_vat_rate_negative(self, valid_percentage_22):
        with pytest.raises(ValueError, match="between 0 and 100"):
            CompanyTaxProfileVO(
                is_pkp=True,
                tax_regime=TaxRegime.GENERAL,
                corporate_income_tax_rate=valid_percentage_22,
                vat_rate=Percentage(Decimal("-1")),
            )

    def test_validation_vat_rate_above_100(self, valid_percentage_22):
        with pytest.raises(ValueError, match="between 0 and 100"):
            CompanyTaxProfileVO(
                is_pkp=True,
                tax_regime=TaxRegime.GENERAL,
                corporate_income_tax_rate=valid_percentage_22,
                vat_rate=Percentage(Decimal("101")),
            )

    def test_validation_deadline_month_zero(self, valid_percentage_22, valid_vat_rate_11):
        with pytest.raises(ValueError, match="between 1 and 12"):
            CompanyTaxProfileVO(
                is_pkp=True,
                tax_regime=TaxRegime.GENERAL,
                corporate_income_tax_rate=valid_percentage_22,
                vat_rate=valid_vat_rate_11,
                annual_return_deadline_month=0,
            )

    def test_validation_deadline_month_13(self, valid_percentage_22, valid_vat_rate_11):
        with pytest.raises(ValueError, match="between 1 and 12"):
            CompanyTaxProfileVO(
                is_pkp=True,
                tax_regime=TaxRegime.GENERAL,
                corporate_income_tax_rate=valid_percentage_22,
                vat_rate=valid_vat_rate_11,
                annual_return_deadline_month=13,
            )


# ============================================================================
# Tests for Effective Rates
# ============================================================================

class TestCompanyTaxProfileVOEffectiveRates:
    def test_effective_income_tax_rate_general(self, valid_tax_profile):
        # For GENERAL, rate should be same as corporate_income_tax_rate
        assert valid_tax_profile.effective_income_tax_rate() == valid_tax_profile.corporate_income_tax_rate

    def test_effective_income_tax_rate_final(self, final_regime_profile):
        # For FINAL, rate should be 0.5%
        expected = Percentage(Decimal("0.5"))
        assert final_regime_profile.effective_income_tax_rate() == expected

    def test_effective_income_tax_rate_gross_up(self, gross_up_profile):
        # For GROSS_UP, rate should be corporate_rate + 10
        expected = Percentage(Decimal("32"))  # 22 + 10
        assert gross_up_profile.effective_income_tax_rate() == expected

    def test_effective_vat_rate_pkp(self, valid_tax_profile):
        # For PKP, effective VAT rate should be vat_rate
        assert valid_tax_profile.effective_vat_rate() == valid_tax_profile.vat_rate

    def test_effective_vat_rate_non_pkp(self, non_pkp_profile):
        # For non-PKP, effective VAT rate should be 0
        assert non_pkp_profile.effective_vat_rate() == Percentage(Decimal("0"))


# ============================================================================
# Tests for Serialization (to_dict / from_dict)
# ============================================================================

class TestCompanyTaxProfileVOSerialization:
    def test_to_dict(self, valid_tax_profile):
        d = valid_tax_profile.to_dict()
        assert d["is_pkp"] is True
        assert d["tax_regime"] == "general"
        # Ensure rates are strings (MNY-003 compliance)
        assert d["corporate_income_tax_rate"] == "22"
        assert d["vat_rate"] == "11"
        assert d["vat_collection_method"] == "output"
        assert d["income_tax_article"] == "PPh 25"
        assert d["tax_bracket"] == "Bracket 1"
        assert d["payment_method"] == "monthly"
        assert d["annual_return_deadline_month"] == 4

    def test_from_dict(self, valid_tax_profile):
        data = valid_tax_profile.to_dict()
        restored = CompanyTaxProfileVO.from_dict(data)
        assert restored.is_pkp == valid_tax_profile.is_pkp
        assert restored.tax_regime == valid_tax_profile.tax_regime
        assert restored.corporate_income_tax_rate == valid_tax_profile.corporate_income_tax_rate
        assert restored.vat_rate == valid_tax_profile.vat_rate
        assert restored.vat_collection_method == valid_tax_profile.vat_collection_method
        assert restored.income_tax_article == valid_tax_profile.income_tax_article
        assert restored.tax_bracket == valid_tax_profile.tax_bracket
        assert restored.payment_method == valid_tax_profile.payment_method
        assert restored.annual_return_deadline_month == valid_tax_profile.annual_return_deadline_month

    def test_from_dict_defaults(self):
        data = {
            "is_pkp": True,
            "tax_regime": "general",
            "corporate_income_tax_rate": "22",
            "vat_rate": "11",
        }
        restored = CompanyTaxProfileVO.from_dict(data)
        assert restored.vat_collection_method == "output"
        assert restored.income_tax_article is None
        assert restored.tax_bracket is None
        assert restored.payment_method == TaxPaymentMethod.MONTHLY_INSTALLMENT
        assert restored.annual_return_deadline_month == 4

    def test_from_dict_invalid_regime_fallback(self):
        data = {
            "is_pkp": True,
            "tax_regime": "invalid",
            "corporate_income_tax_rate": "22",
            "vat_rate": "11",
        }
        restored = CompanyTaxProfileVO.from_dict(data)
        assert restored.tax_regime == TaxRegime.GENERAL


# ============================================================================
# Tests for Normalize
# ============================================================================

class TestCompanyTaxProfileVONormalize:
    def test_normalize(self, valid_tax_profile):
        # Create a profile with non-normalized fields
        profile = CompanyTaxProfileVO(
            is_pkp=True,
            tax_regime=TaxRegime.GENERAL,
            corporate_income_tax_rate=Percentage(Decimal("22.0000")),
            vat_rate=Percentage(Decimal("11.0000")),
            vat_collection_method="  OUTPUT  ",
            income_tax_article="  pph 25  ",
            tax_bracket="  Bracket 1  ",
            payment_method=TaxPaymentMethod.MONTHLY_INSTALLMENT,
            annual_return_deadline_month=4,
        )
        normalized = profile.normalize()
        assert normalized.corporate_income_tax_rate.value == Decimal("22.00")
        assert normalized.vat_rate.value == Decimal("11.00")
        assert normalized.vat_collection_method == "output"
        assert normalized.income_tax_article == "PPH 25"
        assert normalized.tax_bracket == "Bracket 1"


# ============================================================================
# Tests for Equality and Hashing
# ============================================================================

class TestCompanyTaxProfileVOEquality:
    def test_equality(self, valid_tax_profile, valid_percentage_22, valid_vat_rate_11):
        same = CompanyTaxProfileVO(
            is_pkp=True,
            tax_regime=TaxRegime.GENERAL,
            corporate_income_tax_rate=valid_percentage_22,
            vat_rate=valid_vat_rate_11,
            vat_collection_method="output",
            income_tax_article="PPh 25",
            tax_bracket="Bracket 1",
            payment_method=TaxPaymentMethod.MONTHLY_INSTALLMENT,
            annual_return_deadline_month=4,
        )
        assert valid_tax_profile == same

        different = CompanyTaxProfileVO(
            is_pkp=False,
            tax_regime=TaxRegime.GENERAL,
            corporate_income_tax_rate=valid_percentage_22,
            vat_rate=valid_vat_rate_11,
        )
        assert valid_tax_profile != different

        # Different rate
        diff_rate = CompanyTaxProfileVO(
            is_pkp=True,
            tax_regime=TaxRegime.GENERAL,
            corporate_income_tax_rate=Percentage(Decimal("25")),
            vat_rate=valid_vat_rate_11,
        )
        assert valid_tax_profile != diff_rate

    def test_hash(self, valid_tax_profile):
        assert hash(valid_tax_profile) == hash(
            (True, TaxRegime.GENERAL, Percentage(Decimal("22")), Percentage(Decimal("11")))
        )