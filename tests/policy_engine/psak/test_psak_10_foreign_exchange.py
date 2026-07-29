# tests/policy_engine/psak/test_psak_10_foreign_exchange.py
"""
Comprehensive tests for policy_engine/psak/psak_10_foreign_exchange.py.
Covers all enums, data classes, services, rules, validator methods,
edge cases, negative paths, and exceptions.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_10_foreign_exchange import (
    ExchangeDifferenceTreatment,
    ExchangeRate,
    ForeignCurrencyTransaction,
    ForeignExchangeDisclosure,
    ForeignOperation,
    FunctionalCurrencyAssessment,
    FunctionalCurrencyIndicator,
    FunctionalCurrencyNotDeterminedError,
    PSAK10ComplianceLevel,
    PSAK10Error,
    PSAK10FunctionalCurrencyService,
    PSAK10Rules,
    PSAK10TranslationService,
    PSAK10ValidationResult,
    PSAK10Validator,
    TranslationMethod,
    get_psak10_validator,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_assessment() -> FunctionalCurrencyAssessment:
    return FunctionalCurrencyAssessment(
        assessment_id=uuid4(),
        entity_id=uuid4(),
        assessment_date=datetime(2025, 1, 1, tzinfo=UTC),
        primary_sales_currency="IDR",
        labor_material_currency="IDR",
        financing_currency="USD",
        operating_currency="IDR",
        regulatory_currency="IDR",
        determined_currency="IDR",
        indicators_used=[FunctionalCurrencyIndicator.SALES_PRICE_SETTING],
        reasoning="Majority sales and costs in IDR",
    )


@pytest.fixture
def sample_transaction() -> ForeignCurrencyTransaction:
    return ForeignCurrencyTransaction(
        transaction_id=uuid4(),
        date=datetime(2025, 6, 15, tzinfo=UTC),
        foreign_currency="USD",
        amount_fcy=Decimal("10000"),
        functional_currency="IDR",
        spot_rate=Decimal("15200"),
        amount_functional=Decimal("152000000"),  # 10000 * 15200
        settlement_date=datetime(2025, 12, 15, tzinfo=UTC),
        settlement_rate=Decimal("15300"),
        exchange_difference=Decimal("0"),
        recognized_in=ExchangeDifferenceTreatment.RECOGNIZED_IN_PL,
    )


@pytest.fixture
def sample_operation() -> ForeignOperation:
    return ForeignOperation(
        operation_id=uuid4(),
        entity_id=uuid4(),
        name="Singapore Subsidiary",
        functional_currency="SGD",
        reporting_currency="IDR",
        net_assets_beginning=Decimal("500000"),
        net_assets_end=Decimal("550000"),
        cumulative_translation_adjustment=Decimal("0"),
        opening_rate=Decimal("10500"),
        closing_rate=Decimal("10600"),
        average_rate=Decimal("10550"),
    )


@pytest.fixture
def sample_disclosure(sample_assessment) -> ForeignExchangeDisclosure:
    return ForeignExchangeDisclosure(
        disclosure_id=uuid4(),
        entity_id=uuid4(),
        entity_name="PT Ekspor Impor",
        reporting_period_end=datetime(2025, 12, 31, tzinfo=UTC),
        functional_currency="IDR",
        presentation_currency="IDR",
        functional_currency_assessment=sample_assessment,
        transactions=[],
        foreign_operations=[],
        total_exchange_differences_pl=Decimal("0"),
        total_exchange_differences_oci=Decimal("0"),
    )


@pytest.fixture
def validator() -> PSAK10Validator:
    return PSAK10Validator()


# =============================================================================
# Tests for Enums
# =============================================================================

class TestFunctionalCurrencyIndicator:
    def test_members(self):
        assert FunctionalCurrencyIndicator.SALES_PRICE_SETTING.value == "penentuan_harga_jual"
        assert FunctionalCurrencyIndicator.COMPETITIVE_FORCES.value == "kekuatan_persaingan"
        assert FunctionalCurrencyIndicator.LABOR_MATERIAL_COSTS.value == "biaya_tenaga_kerja_dan_bahan"
        assert FunctionalCurrencyIndicator.FINANCING_CURRENCY.value == "mata_uang_pendanaan"
        assert FunctionalCurrencyIndicator.OPERATING_ACTIVITIES.value == "aktivitas_operasi"
        assert FunctionalCurrencyIndicator.REGULATORY_ENVIRONMENT.value == "lingkungan_regulasi"


class TestTranslationMethod:
    def test_members(self):
        assert TranslationMethod.CLOSING_RATE.value == "kurs_penutup"
        assert TranslationMethod.TEMPORAL.value == "temporal"


class TestExchangeDifferenceTreatment:
    def test_members(self):
        assert ExchangeDifferenceTreatment.RECOGNIZED_IN_PL.value == "diakui_di_laba_rugi"
        assert ExchangeDifferenceTreatment.RECOGNIZED_IN_OCI.value == "diakui_di_penghasilan_komprehensif_lain"


class TestPSAK10ComplianceLevel:
    def test_members(self):
        assert PSAK10ComplianceLevel.FULL.value == "penuh"
        assert PSAK10ComplianceLevel.SUBSTANTIAL.value == "substansial"
        assert PSAK10ComplianceLevel.PARTIAL.value == "sebagian"
        assert PSAK10ComplianceLevel.NON_COMPLIANT.value == "tidak_patuh"


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_psak10_error_is_base(self):
        assert issubclass(FunctionalCurrencyNotDeterminedError, PSAK10Error)

    def test_exceptions_can_be_raised(self):
        with pytest.raises(PSAK10Error):
            raise PSAK10Error("Test error")
        with pytest.raises(FunctionalCurrencyNotDeterminedError):
            raise FunctionalCurrencyNotDeterminedError("Not determined")


# =============================================================================
# Tests for ExchangeRate
# =============================================================================

class TestExchangeRate:
    def test_to_dict(self):
        rate = ExchangeRate(
            currency_code="USD",
            rate=Decimal("15200"),
            effective_date=date(2025, 1, 1),
        )
        d = rate.to_dict()
        assert d["currency"] == "USD"
        assert d["rate"] == "15200"
        assert d["effective_date"] == "2025-01-01"


# =============================================================================
# Tests for ForeignCurrencyTransaction
# =============================================================================

class TestForeignCurrencyTransaction:
    def test_post_init_calculates_amount_functional_if_zero(self):
        tx = ForeignCurrencyTransaction(
            transaction_id=uuid4(),
            date=datetime.now(UTC),
            foreign_currency="USD",
            amount_fcy=Decimal("1000"),
            functional_currency="IDR",
            spot_rate=Decimal("15000"),
            amount_functional=Decimal(0),  # should be auto-calculated
        )
        assert tx.amount_functional == Decimal("15000000")

    def test_calculate_settlement_difference(self, sample_transaction):
        # settlement_rate is 15300, spot was 15200, difference = 10000 * (15300-15200) = 1000000 IDR
        diff = sample_transaction.calculate_settlement_difference()
        assert diff == Decimal("1000000")

    def test_calculate_settlement_difference_raises_if_no_settlement_data(self):
        tx = ForeignCurrencyTransaction(
            transaction_id=uuid4(),
            date=datetime.now(UTC),
            foreign_currency="USD",
            amount_fcy=Decimal("1000"),
            functional_currency="IDR",
            spot_rate=Decimal("15000"),
            amount_functional=Decimal("15000000"),
            settlement_date=None,
            settlement_rate=None,
        )
        with pytest.raises(PSAK10Error, match="Settlement date and rate required"):
            tx.calculate_settlement_difference()

    def test_to_dict(self, sample_transaction):
        d = sample_transaction.to_dict()
        assert d["transaction_id"] == str(sample_transaction.transaction_id)
        assert d["amount_fcy"] == "10000"
        assert d["spot_rate"] == "15200"
        assert d["exchange_difference"] == "0"


# =============================================================================
# Tests for FunctionalCurrencyAssessment
# =============================================================================

class TestFunctionalCurrencyAssessment:
    def test_to_dict(self, sample_assessment):
        d = sample_assessment.to_dict()
        assert d["entity_id"] == str(sample_assessment.entity_id)
        assert d["determined"] == "IDR"
        assert d["indicators"] == ["penentuan_harga_jual"]


# =============================================================================
# Tests for ForeignOperation
# =============================================================================

class TestForeignOperation:
    def test_translation_adjustment_for_period(self, sample_operation):
        # Using formula from source:
        # opening_translated = net_assets_beginning * opening_rate = 500000 * 10500 = 5,250,000,000
        # closing_translated = net_assets_end * closing_rate = 550000 * 10600 = 5,830,000,000
        # average_translated = net_assets_end * average_rate = 550000 * 10550 = 5,802,500,000
        # prior = opening_translated - (net_assets_beginning * average_rate) = 5,250,000,000 - (500000 * 10550) = 5,250,000,000 - 5,275,000,000 = -25,000,000
        # adjustment = closing_translated - average_translated - prior = 5,830,000,000 - 5,802,500,000 - (-25,000,000) = 52,500,000
        adjustment = sample_operation.translation_adjustment_for_period()
        expected = Decimal("52500000")
        assert adjustment == expected

    def test_translation_adjustment_zero_if_rates_equal(self):
        op = ForeignOperation(
            operation_id=uuid4(),
            entity_id=uuid4(),
            name="Test",
            functional_currency="USD",
            reporting_currency="IDR",
            net_assets_beginning=Decimal("1000"),
            net_assets_end=Decimal("1000"),
            opening_rate=Decimal("1"),
            closing_rate=Decimal("1"),
            average_rate=Decimal("1"),
        )
        assert op.translation_adjustment_for_period() == Decimal(0)

    def test_to_dict(self, sample_operation):
        d = sample_operation.to_dict()
        assert d["operation_id"] == str(sample_operation.operation_id)
        assert d["net_assets_beginning"] == "500000"
        assert d["closing_rate"] == "10600"


# =============================================================================
# Tests for ForeignExchangeDisclosure
# =============================================================================

class TestForeignExchangeDisclosure:
    def test_total_net_exchange_difference(self, sample_disclosure):
        sample_disclosure.total_exchange_differences_pl = Decimal("100")
        sample_disclosure.total_exchange_differences_oci = Decimal("50")
        assert sample_disclosure.total_net_exchange_difference() == Decimal("150")

    def test_to_dict(self, sample_disclosure, sample_assessment):
        d = sample_disclosure.to_dict()
        assert d["entity_name"] == "PT Ekspor Impor"
        assert d["functional_currency"] == "IDR"
        assert d["functional_currency_assessment"] is not None


# =============================================================================
# Tests for PSAK10ValidationResult
# =============================================================================

class TestPSAK10ValidationResult:
    def test_add_error(self):
        result = PSAK10ValidationResult(
            is_compliant=True,
            compliance_level=PSAK10ComplianceLevel.FULL,
        )
        result.add_error("Test error")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK10ComplianceLevel.NON_COMPLIANT
        assert "Test error" in result.errors

    def test_add_warning(self):
        result = PSAK10ValidationResult(
            is_compliant=True,
            compliance_level=PSAK10ComplianceLevel.FULL,
        )
        result.add_warning("Test warning")
        assert result.compliance_level == PSAK10ComplianceLevel.SUBSTANTIAL
        assert "Test warning" in result.warnings

    def test_hash_changes_on_modification(self):
        result = PSAK10ValidationResult(is_compliant=True, compliance_level=PSAK10ComplianceLevel.FULL)
        old_hash = result.hash_sha256
        result.add_error("Error")
        assert result.hash_sha256 != old_hash

    def test_to_dict(self):
        result = PSAK10ValidationResult(
            is_compliant=False,
            compliance_level=PSAK10ComplianceLevel.PARTIAL,
            errors=["e1"],
            warnings=["w1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "sebagian"
        assert d["errors"] == ["e1"]
        assert "hash" in d


# =============================================================================
# Tests for PSAK10FunctionalCurrencyService
# =============================================================================

class TestPSAK10FunctionalCurrencyService:
    def test_determine_functional_currency_most_common(self):
        currency, indicators = PSAK10FunctionalCurrencyService.determine_functional_currency(
            primary_sales_currency="IDR",
            labor_material_currency="IDR",
            financing_currency="USD",
            operating_currency="EUR",
            regulatory_currency="IDR",
        )
        assert currency == "IDR"
        # Indicators: SALES_PRICE_SETTING, LABOR_MATERIAL_COSTS, REGULATORY_ENVIRONMENT
        indicator_values = {i.value for i in indicators}
        assert "penentuan_harga_jual" in indicator_values
        assert "biaya_tenaga_kerja_dan_bahan" in indicator_values
        assert "lingkungan_regulasi" in indicator_values

    def test_determine_functional_currency_tie_break(self):
        # When all currencies different, first one (primary sales) wins
        currency, indicators = PSAK10FunctionalCurrencyService.determine_functional_currency(
            primary_sales_currency="A",
            labor_material_currency="B",
            financing_currency="C",
            operating_currency="D",
            regulatory_currency="E",
        )
        assert currency == "A"
        # Indicator list should contain SALES_PRICE_SETTING
        assert FunctionalCurrencyIndicator.SALES_PRICE_SETTING in indicators

    def test_can_change_functional_currency(self):
        # Can change only if significant change and different currency
        assert PSAK10FunctionalCurrencyService.can_change_functional_currency(
            old_currency="IDR", new_currency="USD", has_significant_change=True
        ) is True
        assert PSAK10FunctionalCurrencyService.can_change_functional_currency(
            old_currency="IDR", new_currency="IDR", has_significant_change=True
        ) is False
        assert PSAK10FunctionalCurrencyService.can_change_functional_currency(
            old_currency="IDR", new_currency="USD", has_significant_change=False
        ) is False


# =============================================================================
# Tests for PSAK10TranslationService
# =============================================================================

class TestPSAK10TranslationService:
    def test_translate_balance_sheet(self):
        bs = {"Cash": Decimal("100"), "Inventory": Decimal("200")}
        translated = PSAK10TranslationService.translate_balance_sheet(
            bs, closing_rate=Decimal("2"), reporting_currency="USD"
        )
        assert translated["Cash"] == Decimal("200")
        assert translated["Inventory"] == Decimal("400")

    def test_translate_income_statement(self):
        is_ = {"Revenue": Decimal("500"), "Expense": Decimal("300")}
        translated = PSAK10TranslationService.translate_income_statement(
            is_, average_rate=Decimal("1.5"), reporting_currency="USD"
        )
        assert translated["Revenue"] == Decimal("750")
        assert translated["Expense"] == Decimal("450")

    def test_calculate_cta(self):
        # Use provided formula
        cta = PSAK10TranslationService.calculate_cta(
            opening_net_assets=Decimal("1000"),
            closing_net_assets=Decimal("1200"),
            opening_rate=Decimal("1.0"),
            closing_rate=Decimal("1.1"),
            average_rate=Decimal("1.05"),
        )
        # current_period = 1200 * (1.1 - 1.05) = 1200 * 0.05 = 60
        # prior_period = 1000 * (1.0 - 1.05) = 1000 * (-0.05) = -50
        # CTA = 60 - (-50) = 110
        assert cta == Decimal("110")


# =============================================================================
# Tests for PSAK10Rules
# =============================================================================

class TestPSAK10Rules:
    def test_validate_functional_currency_assessment_valid(self, sample_assessment):
        result = PSAK10Rules.validate_functional_currency_assessment(sample_assessment)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK10ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_functional_currency_assessment_no_currency(self, sample_assessment):
        sample_assessment.determined_currency = ""
        result = PSAK10Rules.validate_functional_currency_assessment(sample_assessment)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK10ComplianceLevel.NON_COMPLIANT
        assert "Mata uang fungsional tidak ditentukan" in result.errors

    def test_validate_functional_currency_assessment_warning(self, sample_assessment):
        sample_assessment.determined_currency = "XYZ"
        result = PSAK10Rules.validate_functional_currency_assessment(sample_assessment)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK10ComplianceLevel.SUBSTANTIAL
        assert any("tidak sesuai dengan indikator dominan" in w for w in result.warnings)

    def test_validate_transaction_classification_valid(self, sample_transaction):
        result = PSAK10Rules.validate_transaction_classification([sample_transaction])
        assert result.is_compliant is True
        assert result.errors == []

    def test_validate_transaction_classification_zero_amount(self, sample_transaction):
        sample_transaction.amount_functional = Decimal(0)
        result = PSAK10Rules.validate_transaction_classification([sample_transaction])
        assert result.is_compliant is False
        assert any("nilai fungsional nol" in e for e in result.errors)

    def test_validate_transaction_classification_negative_spot(self, sample_transaction):
        sample_transaction.spot_rate = Decimal("-1")
        result = PSAK10Rules.validate_transaction_classification([sample_transaction])
        assert result.is_compliant is False
        assert any("Kurs spot" in e for e in result.errors)

    def test_validate_foreign_operation_translation_valid(self, sample_operation):
        result = PSAK10Rules.validate_foreign_operation_translation([sample_operation])
        assert result.is_compliant is True
        assert result.errors == []

    def test_validate_foreign_operation_translation_invalid_rate(self, sample_operation):
        sample_operation.closing_rate = Decimal("0")
        result = PSAK10Rules.validate_foreign_operation_translation([sample_operation])
        assert result.is_compliant is False
        assert any("Kurs untuk operasi luar negeri" in e for e in result.errors)

    def test_validate_foreign_operation_translation_warning_same_currency(self, sample_operation):
        sample_operation.reporting_currency = "SGD"
        result = PSAK10Rules.validate_foreign_operation_translation([sample_operation])
        assert result.is_compliant is True
        assert result.compliance_level == PSAK10ComplianceLevel.SUBSTANTIAL
        assert any("mata uang fungsional sama dengan mata uang penyajian" in w for w in result.warnings)


# =============================================================================
# Tests for PSAK10Validator
# =============================================================================

class TestPSAK10Validator:
    def test_assess_functional_currency(self, validator):
        assessment = validator.assess_functional_currency(
            entity_id=uuid4(),
            primary_sales_currency="IDR",
            labor_material_currency="IDR",
            financing_currency="USD",
            operating_currency="IDR",
            regulatory_currency="IDR",
            reasoning="Test reasoning",
        )
        assert assessment.determined_currency == "IDR"
        assert assessment.assessment_id is not None
        assert assessment.reasoning == "Test reasoning"
        # Check indicators include appropriate ones
        indicator_values = [i.value for i in assessment.indicators_used]
        assert "penentuan_harga_jual" in indicator_values

    def test_assess_functional_currency_generates_reasoning_if_empty(self, validator):
        assessment = validator.assess_functional_currency(
            entity_id=uuid4(),
            primary_sales_currency="USD",
            labor_material_currency="EUR",
            financing_currency="USD",
            operating_currency="GBP",
            regulatory_currency="IDR",
        )
        assert assessment.reasoning.startswith("Berdasarkan indikator dominan:")

    def test_create_transaction(self, validator):
        tx = validator.create_transaction(
            foreign_currency="USD",
            amount_fcy=Decimal("1000"),
            functional_currency="IDR",
            spot_rate=Decimal("15000"),
            date=datetime(2025, 1, 1, tzinfo=UTC),
            settlement_date=datetime(2025, 2, 1, tzinfo=UTC),
            settlement_rate=Decimal("15100"),
            recognized_in=ExchangeDifferenceTreatment.RECOGNIZED_IN_OCI,
        )
        assert tx.transaction_id is not None
        assert tx.foreign_currency == "USD"
        assert tx.amount_functional == Decimal("15000000")
        assert tx.recognized_in == ExchangeDifferenceTreatment.RECOGNIZED_IN_OCI

    def test_create_foreign_operation(self, validator):
        op = validator.create_foreign_operation(
            entity_id=uuid4(),
            name="Test Op",
            functional_currency="SGD",
            reporting_currency="IDR",
            net_assets_beginning=Decimal("100"),
            net_assets_end=Decimal("200"),
            opening_rate=Decimal("1"),
            closing_rate=Decimal("1.1"),
            average_rate=Decimal("1.05"),
        )
        assert op.operation_id is not None
        assert op.functional_currency == "SGD"
        assert op.net_assets_end == Decimal("200")

    def test_create_disclosure(self, validator, sample_assessment):
        disclosure = validator.create_disclosure(
            entity_id=uuid4(),
            entity_name="Test Entity",
            reporting_period_end=datetime(2025, 12, 31, tzinfo=UTC),
            functional_currency="IDR",
            presentation_currency="USD",
            assessment=sample_assessment,
        )
        assert disclosure.disclosure_id is not None
        assert disclosure.functional_currency == "IDR"
        assert disclosure.presentation_currency == "USD"
        assert disclosure.functional_currency_assessment is sample_assessment

    def test_add_transaction(self, validator, sample_disclosure, sample_transaction):
        new_disclosure = validator.add_transaction(sample_disclosure, sample_transaction)
        assert len(new_disclosure.transactions) == 1
        assert new_disclosure.transactions[0] is sample_transaction
        # Total PL should be sum of exchange differences of PL transactions
        # For sample_transaction, exchange_difference=0, so total remains 0
        assert new_disclosure.total_exchange_differences_pl == Decimal(0)
        # Add another transaction with non-zero diff
        tx2 = ForeignCurrencyTransaction(
            transaction_id=uuid4(),
            date=datetime.now(UTC),
            foreign_currency="USD",
            amount_fcy=Decimal("100"),
            functional_currency="IDR",
            spot_rate=Decimal("15000"),
            amount_functional=Decimal("1500000"),
            exchange_difference=Decimal("1000"),
            recognized_in=ExchangeDifferenceTreatment.RECOGNIZED_IN_PL,
        )
        new_disclosure2 = validator.add_transaction(new_disclosure, tx2)
        assert new_disclosure2.total_exchange_differences_pl == Decimal("1000")

    def test_add_foreign_operation(self, validator, sample_disclosure, sample_operation):
        new_disclosure = validator.add_foreign_operation(sample_disclosure, sample_operation)
        assert len(new_disclosure.foreign_operations) == 1
        assert new_disclosure.foreign_operations[0] is sample_operation

    def test_update_exchange_difference(self, validator, sample_transaction):
        # Set settlement rate to new value
        new_rate = Decimal("15400")
        updated_tx = validator.update_exchange_difference(sample_transaction, new_rate)
        # Difference = 10000 * (15400 - 15200) = 2000000
        assert updated_tx.exchange_difference == Decimal("2000000")
        assert updated_tx.settlement_rate == new_rate

    def test_update_exchange_difference_raises_if_no_settlement_data(self, validator):
        tx = ForeignCurrencyTransaction(
            transaction_id=uuid4(),
            date=datetime.now(UTC),
            foreign_currency="USD",
            amount_fcy=Decimal("100"),
            functional_currency="IDR",
            spot_rate=Decimal("15000"),
            amount_functional=Decimal("1500000"),
            settlement_date=None,
            settlement_rate=None,
        )
        with pytest.raises(PSAK10Error, match="Settlement date and rate required"):
            validator.update_exchange_difference(tx, Decimal("15100"))

    def test_validate_disclosure_full_compliance(self, validator, sample_disclosure, sample_transaction, sample_operation):
        # Add valid transaction and operation
        sample_disclosure = validator.add_transaction(sample_disclosure, sample_transaction)
        sample_disclosure = validator.add_foreign_operation(sample_disclosure, sample_operation)
        result = validator.validate_disclosure(sample_disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK10ComplianceLevel.FULL

    def test_validate_disclosure_inconsistent_functional_currency(self, validator, sample_disclosure, sample_transaction):
        # Make transaction functional currency different from disclosure
        sample_transaction.functional_currency = "USD"
        sample_disclosure = validator.add_transaction(sample_disclosure, sample_transaction)
        result = validator.validate_disclosure(sample_disclosure)
        assert result.is_compliant is False
        assert any("berbeda dari" in e for e in result.errors)

    def test_validate_disclosure_merges_results(self, validator, sample_disclosure):
        # Create a disclosure with an assessment that will generate a warning and a transaction that generates an error
        # We'll mutate assessment to trigger warning: determined_currency not among indicators
        assessment = sample_disclosure.functional_currency_assessment
        assessment.determined_currency = "XYZ"
        tx = ForeignCurrencyTransaction(
            transaction_id=uuid4(),
            date=datetime.now(UTC),
            foreign_currency="USD",
            amount_fcy=Decimal("100"),
            functional_currency="IDR",
            spot_rate=Decimal("15000"),
            amount_functional=Decimal(0),  # will cause error
        )
        sample_disclosure = validator.add_transaction(sample_disclosure, tx)
        result = validator.validate_disclosure(sample_disclosure)
        # Should have warning from assessment and error from transaction
        assert result.is_compliant is False
        assert any("tidak sesuai" in w for w in result.warnings)
        assert any("nilai fungsional nol" in e for e in result.errors)
        # Compliance level should be NON_COMPLIANT because of error
        assert result.compliance_level == PSAK10ComplianceLevel.NON_COMPLIANT

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "functional_currency" in summary
        assert "initial_recognition" in summary
        assert isinstance(summary, dict)

    def test_merge_results(self, validator):
        main = PSAK10ValidationResult(is_compliant=True, compliance_level=PSAK10ComplianceLevel.FULL)
        other = PSAK10ValidationResult(
            is_compliant=False,
            compliance_level=PSAK10ComplianceLevel.NON_COMPLIANT,
            errors=["e"],
            warnings=["w"],
        )
        merged = validator._merge_results(main, other)
        assert merged.is_compliant is False
        assert merged.compliance_level == PSAK10ComplianceLevel.NON_COMPLIANT
        assert merged.errors == ["e"]
        assert merged.warnings == ["w"]


# =============================================================================
# Tests for Singleton Accessor
# =============================================================================

class TestSingleton:
    def test_get_psak10_validator_returns_same_instance(self):
        v1 = get_psak10_validator()
        v2 = get_psak10_validator()
        assert v1 is v2
        assert isinstance(v1, PSAK10Validator)
