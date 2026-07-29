# tests/policy_engine/psak/test_psak_23_revenue_legacy.py
"""
Comprehensive tests for policy_engine/psak/psak_23_revenue_legacy.py

Covers:
- All enums
- All exceptions
- PSAK23GoodsSale: construction, meets_criteria, gross_profit, to_dict
- PSAK23ServiceContract: properties (estimated_profit, current_progress, revenue_to_recognize, profit_to_recognize), to_dict
- PSAK23PassiveIncome: to_dict
- PSAK23RevenueSummary: totals, to_dict, add methods
- PSAK23ValidationResult: add_error, add_warning, to_dict, hash
- PSAK23RevenueService: recognize_goods_sale, recognize_service_revenue, record_actual_cost
- PSAK23Rules: validate_service_contract, validate_goods_sale, validate_passive_income
- PSAK23Validator: all factory methods, add methods, record_service_cost, recognize_service_revenue, validate_summary, _merge_results, get_requirements_summary
- Singleton accessor
- Aliases
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from policy_engine.psak.psak_23_revenue_legacy import (
    PSAK23ComplianceLevel,
    PSAK23Error,
    PSAK23GoodsSale,
    PSAK23PassiveIncome,
    PSAK23RevenueRecognitionTiming,
    PSAK23RevenueService,
    PSAK23RevenueSummary,
    PSAK23RevenueType,
    PSAK23Rules,
    PSAK23ServiceCompletionMethod,
    PSAK23ServiceContract,
    PSAK23ValidationResult,
    PSAK23Validator,
    RevenueRecognitionError,
    RevenueRecognitionLegacy,
    RevenueTransaction,
    ServiceContractNotFoundError,
    get_psak23_validator,
)

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def fixed_now():
    return datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_past():
    return datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_future():
    return datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)


@pytest.fixture
def sample_goods_sale(fixed_now):
    return PSAK23GoodsSale(
        sale_id=uuid4(),
        customer_name="PT Pelanggan",
        invoice_number="INV-001",
        sale_date=fixed_now,
        revenue_amount=Decimal("1000000"),
        cost_of_goods_sold=Decimal("600000"),
        delivery_date=fixed_now + timedelta(days=1),
        transfer_of_risks_rewards=True,
        no_managerial_involvement=True,
        revenue_reliably_measurable=True,
        probable_economic_benefits=True,
        costs_reliably_measurable=True,
        recognition_timing=PSAK23RevenueRecognitionTiming.AT_POINT_OF_SALE,
        notes="Test",
    )


@pytest.fixture
def sample_service_contract(fixed_now, fixed_future):
    return PSAK23ServiceContract(
        contract_id=uuid4(),
        contract_number="CONT-001",
        customer_name="PT Jasa",
        contract_value=Decimal("10000000"),
        start_date=fixed_now,
        estimated_completion_date=fixed_future,
        estimated_total_cost=Decimal("7000000"),
        actual_costs_incurred=Decimal("3500000"),
        progress_percentage=Decimal("0"),
        revenue_recognized_to_date=Decimal("0"),
        completion_method=PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION,
        notes="Test",
    )


@pytest.fixture
def sample_passive_income(fixed_now):
    return PSAK23PassiveIncome(
        income_id=uuid4(),
        income_type=PSAK23RevenueType.INTEREST,
        amount=Decimal("500000"),
        accrual_date=fixed_now,
        description="Bunga deposito",
        effective_interest_rate=Decimal("0.06"),
        royalty_rate=None,
        declaration_date=None,
        is_recognized=True,
    )


@pytest.fixture
def sample_summary(sample_goods_sale, sample_service_contract, sample_passive_income, fixed_past, fixed_future):
    return PSAK23RevenueSummary(
        summary_id=uuid4(),
        entity_id=uuid4(),
        entity_name="PT Abadi",
        period_start=fixed_past,
        period_end=fixed_future,
        goods_sales=[sample_goods_sale],
        service_contracts=[sample_service_contract],
        passive_incomes=[sample_passive_income],
    )


@pytest.fixture
def validator():
    return PSAK23Validator()


# ============================================================================
# ENUM TESTS
# ============================================================================

class TestPSAK23RevenueType:
    def test_members(self):
        assert PSAK23RevenueType.SALE_OF_GOODS.value == "penjualan_barang"
        assert PSAK23RevenueType.RENDERING_OF_SERVICES.value == "pemberian_jasa"
        assert PSAK23RevenueType.INTEREST.value == "bunga"
        assert PSAK23RevenueType.ROYALTIES.value == "royalti"
        assert PSAK23RevenueType.DIVIDENDS.value == "dividen"


class TestPSAK23ServiceCompletionMethod:
    def test_members(self):
        assert PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION.value == "persentase_penyelesaian"
        assert PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT.value == "kontrak_selesai"


class TestPSAK23RevenueRecognitionTiming:
    def test_members(self):
        assert PSAK23RevenueRecognitionTiming.AT_POINT_OF_SALE.value == "saat_penjualan"
        assert PSAK23RevenueRecognitionTiming.UPON_DELIVERY.value == "saat_pengiriman"
        assert PSAK23RevenueRecognitionTiming.OVER_TIME.value == "sepanjang_waktu"
        assert PSAK23RevenueRecognitionTiming.UPON_COLLECTION.value == "saat_penerimaan_kas"


class TestPSAK23ComplianceLevel:
    def test_members(self):
        assert PSAK23ComplianceLevel.FULL.value == "penuh"
        assert PSAK23ComplianceLevel.SUBSTANTIAL.value == "substansial"
        assert PSAK23ComplianceLevel.PARTIAL.value == "sebagian"
        assert PSAK23ComplianceLevel.NON_COMPLIANT.value == "tidak_patuh"


# ============================================================================
# EXCEPTION TESTS
# ============================================================================

class TestExceptions:
    def test_psak23_error(self):
        with pytest.raises(PSAK23Error):
            raise PSAK23Error("test")

    def test_revenue_recognition_error(self):
        with pytest.raises(RevenueRecognitionError):
            raise RevenueRecognitionError("test")

    def test_service_contract_not_found_error(self):
        with pytest.raises(ServiceContractNotFoundError):
            raise ServiceContractNotFoundError("test")


# ============================================================================
# PSAK23GoodsSale TESTS
# ============================================================================

class TestPSAK23GoodsSale:
    def test_construction(self, sample_goods_sale):
        assert sample_goods_sale.sale_id is not None
        assert sample_goods_sale.customer_name == "PT Pelanggan"
        assert sample_goods_sale.revenue_amount == Decimal("1000000")
        assert sample_goods_sale.cost_of_goods_sold == Decimal("600000")

    def test_meets_criteria_all_true(self, sample_goods_sale):
        assert sample_goods_sale.meets_criteria() is True

    def test_meets_criteria_one_false(self, sample_goods_sale):
        sample_goods_sale.transfer_of_risks_rewards = False
        assert sample_goods_sale.meets_criteria() is False

    def test_gross_profit(self, sample_goods_sale):
        assert sample_goods_sale.gross_profit() == Decimal("400000")

    def test_to_dict(self, sample_goods_sale):
        d = sample_goods_sale.to_dict()
        assert d["customer_name"] == "PT Pelanggan"
        assert d["invoice_number"] == "INV-001"
        assert d["revenue_amount"] == "1000000"
        assert d["cost_of_goods_sold"] == "600000"
        assert d["gross_profit"] == "400000"
        assert d["meets_criteria"] is True
        assert d["recognition_timing"] == "saat_penjualan"


# ============================================================================
# PSAK23ServiceContract TESTS
# ============================================================================

class TestPSAK23ServiceContract:
    def test_construction(self, sample_service_contract):
        assert sample_service_contract.contract_id is not None
        assert sample_service_contract.contract_value == Decimal("10000000")
        assert sample_service_contract.estimated_total_cost == Decimal("7000000")

    def test_estimated_profit(self, sample_service_contract):
        assert sample_service_contract.estimated_profit == Decimal("3000000")

    def test_current_progress(self, sample_service_contract):
        # actual_costs = 3.5M, estimated_total = 7M => 50%
        assert sample_service_contract.current_progress == Decimal("50.00")

    def test_current_progress_zero_estimated_cost(self, sample_service_contract):
        sample_service_contract.estimated_total_cost = Decimal("0")
        assert sample_service_contract.current_progress == Decimal("0")

    def test_revenue_to_recognize_percentage_completion(self, sample_service_contract):
        # progress = 50%, contract_value = 10M => 5M
        assert sample_service_contract.revenue_to_recognize() == Decimal("5000000")

    def test_revenue_to_recognize_completed_contract(self, sample_service_contract):
        sample_service_contract.completion_method = PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
        assert sample_service_contract.revenue_to_recognize() == Decimal("0")

    def test_profit_to_recognize_percentage_completion(self, sample_service_contract):
        # estimated_profit = 3M, progress = 50% => 1.5M
        assert sample_service_contract.profit_to_recognize() == Decimal("1500000")

    def test_profit_to_recognize_completed_contract(self, sample_service_contract):
        sample_service_contract.completion_method = PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
        assert sample_service_contract.profit_to_recognize() == Decimal("0")

    def test_to_dict(self, sample_service_contract):
        d = sample_service_contract.to_dict()
        assert d["contract_number"] == "CONT-001"
        assert d["contract_value"] == "10000000"
        assert d["estimated_total_cost"] == "7000000"
        assert d["actual_costs_incurred"] == "3500000"
        assert d["progress_percentage"] == "0"
        assert d["completion_method"] == "persentase_penyelesaian"
        assert d["estimated_profit"] == "3000000"
        assert d["current_progress"] == "50.00"
        assert d["revenue_to_recognize"] == "5000000"
        assert d["profit_to_recognize"] == "1500000"


# ============================================================================
# PSAK23PassiveIncome TESTS
# ============================================================================

class TestPSAK23PassiveIncome:
    def test_construction(self, sample_passive_income):
        assert sample_passive_income.income_id is not None
        assert sample_passive_income.income_type == PSAK23RevenueType.INTEREST
        assert sample_passive_income.amount == Decimal("500000")

    def test_to_dict(self, sample_passive_income):
        d = sample_passive_income.to_dict()
        assert d["income_type"] == "bunga"
        assert d["amount"] == "500000"
        assert d["description"] == "Bunga deposito"
        assert d["effective_interest_rate"] == "0.06"
        assert d["royalty_rate"] is None
        assert d["is_recognized"] is True


# ============================================================================
# PSAK23RevenueSummary TESTS
# ============================================================================

class TestPSAK23RevenueSummary:
    def test_total_goods_revenue(self, sample_summary, sample_goods_sale):
        # Only if meets_criteria (True)
        assert sample_summary.total_goods_revenue() == sample_goods_sale.revenue_amount

    def test_total_goods_revenue_excludes_non_criteria(self, sample_summary, sample_goods_sale):
        sample_goods_sale.meets_criteria = MagicMock(return_value=False)
        # Since meets_criteria is a method, we need to replace it carefully
        # We'll just test with a sale that fails criteria by setting flag
        bad_sale = PSAK23GoodsSale(
            sale_id=uuid4(),
            customer_name="Bad",
            invoice_number="INV-002",
            sale_date=datetime.now(UTC),
            revenue_amount=Decimal("1000"),
            cost_of_goods_sold=Decimal("500"),
            transfer_of_risks_rewards=False,  # fails
        )
        summary = PSAK23RevenueSummary(
            summary_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            period_start=datetime.now(UTC),
            period_end=datetime.now(UTC),
            goods_sales=[sample_goods_sale, bad_sale],
        )
        # Only good_sale (1M) is counted
        assert summary.total_goods_revenue() == Decimal("1000000")

    def test_total_service_revenue_percentage_completion(self, sample_summary, sample_service_contract):
        # progress = 50%, contract_value = 10M => 5M
        assert sample_summary.total_service_revenue() == Decimal("5000000")

    def test_total_service_revenue_completed_contract_not_complete(self, sample_summary, sample_service_contract):
        sample_service_contract.completion_method = PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
        sample_service_contract.actual_costs_incurred = Decimal("3500000")  # 50% progress
        # Should be 0 because not complete
        assert sample_summary.total_service_revenue() == Decimal("0")

    def test_total_service_revenue_completed_contract_complete(self, sample_summary, sample_service_contract):
        sample_service_contract.completion_method = PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
        sample_service_contract.actual_costs_incurred = Decimal("7000000")  # 100% progress
        sample_service_contract.revenue_recognized_to_date = Decimal("0")
        # Should recognize full contract value
        # But our total_service_revenue calculates based on progress >= 100
        # It uses current_progress which is based on actual_costs / estimated_total
        # For 7M / 7M = 100%
        assert sample_summary.total_service_revenue() == Decimal("10000000")

    def test_total_passive_income(self, sample_summary, sample_passive_income):
        assert sample_summary.total_passive_income() == sample_passive_income.amount

    def test_total_passive_income_excludes_non_recognized(self, sample_summary, sample_passive_income):
        sample_passive_income.is_recognized = False
        assert sample_summary.total_passive_income() == Decimal("0")

    def test_total_revenue(self, sample_summary):
        # goods: 1M, service: 5M, passive: 500k => 6.5M
        assert sample_summary.total_revenue() == Decimal("6500000")

    def test_to_dict(self, sample_summary):
        d = sample_summary.to_dict()
        assert d["entity_name"] == "PT Abadi"
        assert d["goods_revenue"] == "1000000"
        assert d["service_revenue"] == "5000000"
        assert d["passive_income"] == "500000"
        assert d["total_revenue"] == "6500000"
        assert len(d["goods_sales"]) == 1
        assert len(d["service_contracts"]) == 1
        assert len(d["passive_incomes"]) == 1


# ============================================================================
# PSAK23ValidationResult TESTS
# ============================================================================

class TestPSAK23ValidationResult:
    def test_construction(self):
        result = PSAK23ValidationResult(
            is_compliant=True,
            compliance_level=PSAK23ComplianceLevel.FULL,
            errors=[],
            warnings=[],
        )
        assert result.is_compliant is True
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK23ValidationResult(
            is_compliant=True,
            compliance_level=PSAK23ComplianceLevel.FULL,
        )
        result.add_error("error1")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK23ComplianceLevel.NON_COMPLIANT
        assert result.errors == ["error1"]

    def test_add_warning(self):
        result = PSAK23ValidationResult(
            is_compliant=True,
            compliance_level=PSAK23ComplianceLevel.FULL,
        )
        result.add_warning("warning1")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK23ComplianceLevel.SUBSTANTIAL
        assert result.warnings == ["warning1"]

    def test_add_warning_already_non_compliant(self):
        result = PSAK23ValidationResult(
            is_compliant=False,
            compliance_level=PSAK23ComplianceLevel.NON_COMPLIANT,
        )
        result.add_warning("warning")
        assert result.compliance_level == PSAK23ComplianceLevel.NON_COMPLIANT

    def test_to_dict(self):
        result = PSAK23ValidationResult(
            is_compliant=False,
            compliance_level=PSAK23ComplianceLevel.NON_COMPLIANT,
            errors=["e1", "e2"],
            warnings=["w1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["e1", "e2"]
        assert d["warnings"] == ["w1"]
        assert "hash" in d

    def test_hash_computation(self):
        result1 = PSAK23ValidationResult(is_compliant=True, compliance_level=PSAK23ComplianceLevel.FULL)
        result2 = PSAK23ValidationResult(is_compliant=True, compliance_level=PSAK23ComplianceLevel.FULL)
        assert result1.hash_sha256 == result2.hash_sha256
        result3 = PSAK23ValidationResult(is_compliant=False, compliance_level=PSAK23ComplianceLevel.NON_COMPLIANT)
        assert result1.hash_sha256 != result3.hash_sha256


# ============================================================================
# PSAK23RevenueService TESTS
# ============================================================================

class TestPSAK23RevenueService:
    def test_recognize_goods_sale_valid(self, sample_goods_sale):
        result = PSAK23RevenueService.recognize_goods_sale(sample_goods_sale)
        assert result is sample_goods_sale

    def test_recognize_goods_sale_invalid_raises(self, sample_goods_sale):
        sample_goods_sale.transfer_of_risks_rewards = False
        with pytest.raises(RevenueRecognitionError, match="tidak memenuhi kriteria"):
            PSAK23RevenueService.recognize_goods_sale(sample_goods_sale)

    def test_recognize_service_revenue_percentage_completion(self, sample_service_contract):
        # 50% progress => revenue 5M
        result = PSAK23RevenueService.recognize_service_revenue(sample_service_contract, datetime.now(UTC))
        assert result.revenue_recognized_to_date == Decimal("5000000")
        assert result.progress_percentage == Decimal("50.00")

    def test_recognize_service_revenue_percentage_completion_progress_capped(self, sample_service_contract):
        sample_service_contract.actual_costs_incurred = Decimal("8000000")  # > estimated 7M
        result = PSAK23RevenueService.recognize_service_revenue(sample_service_contract, datetime.now(UTC))
        # progress should be capped at 100%
        assert result.progress_percentage == Decimal("100.00")
        assert result.revenue_recognized_to_date == Decimal("10000000")

    def test_recognize_service_revenue_completed_contract_not_complete(self, sample_service_contract):
        sample_service_contract.completion_method = PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
        sample_service_contract.actual_costs_incurred = Decimal("3500000")  # 50%
        result = PSAK23RevenueService.recognize_service_revenue(sample_service_contract, datetime.now(UTC))
        # No revenue recognized yet
        assert result.revenue_recognized_to_date == Decimal("0")

    def test_recognize_service_revenue_completed_contract_complete(self, sample_service_contract):
        sample_service_contract.completion_method = PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
        sample_service_contract.actual_costs_incurred = Decimal("7000000")  # 100%
        sample_service_contract.revenue_recognized_to_date = Decimal("0")
        result = PSAK23RevenueService.recognize_service_revenue(sample_service_contract, datetime.now(UTC))
        # Should recognize full contract value
        assert result.revenue_recognized_to_date == Decimal("10000000")

    def test_recognize_service_revenue_completed_contract_already_partial(self, sample_service_contract):
        sample_service_contract.completion_method = PSAK23ServiceCompletionMethod.COMPLETED_CONTRACT
        sample_service_contract.actual_costs_incurred = Decimal("7000000")
        sample_service_contract.revenue_recognized_to_date = Decimal("3000000")
        result = PSAK23RevenueService.recognize_service_revenue(sample_service_contract, datetime.now(UTC))
        # Should recognize remaining 7M
        assert result.revenue_recognized_to_date == Decimal("10000000")

    def test_record_actual_cost(self, sample_service_contract):
        result = PSAK23RevenueService.record_actual_cost(sample_service_contract, Decimal("1000000"))
        assert result.actual_costs_incurred == Decimal("4500000")  # 3.5M + 1M


# ============================================================================
# PSAK23Rules TESTS
# ============================================================================

class TestPSAK23Rules:
    def test_validate_service_contract_valid(self, sample_service_contract):
        result = PSAK23Rules.validate_service_contract(sample_service_contract)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK23ComplianceLevel.FULL

    def test_validate_service_contract_zero_estimated_cost(self, sample_service_contract):
        sample_service_contract.estimated_total_cost = Decimal("0")
        result = PSAK23Rules.validate_service_contract(sample_service_contract)
        assert result.is_compliant is False
        assert any("estimasi total biaya" in e for e in result.errors)

    def test_validate_service_contract_progress_exceeds_100(self, sample_service_contract):
        sample_service_contract.progress_percentage = Decimal("150")
        result = PSAK23Rules.validate_service_contract(sample_service_contract)
        assert result.is_compliant is False
        assert any("tidak boleh melebihi 100%" in e for e in result.errors)

    def test_validate_goods_sale_valid(self, sample_goods_sale):
        result = PSAK23Rules.validate_goods_sale(sample_goods_sale)
        assert result.is_compliant is True

    def test_validate_goods_sale_zero_revenue(self, sample_goods_sale):
        sample_goods_sale.revenue_amount = Decimal("0")
        result = PSAK23Rules.validate_goods_sale(sample_goods_sale)
        assert result.is_compliant is False
        assert any("positif" in e for e in result.errors)

    def test_validate_goods_sale_negative_cogs(self, sample_goods_sale):
        sample_goods_sale.cost_of_goods_sold = Decimal("-100")
        result = PSAK23Rules.validate_goods_sale(sample_goods_sale)
        assert result.is_compliant is False
        assert any("tidak boleh negatif" in e for e in result.errors)

    def test_validate_passive_income_positive(self, sample_passive_income):
        result = PSAK23Rules.validate_passive_income(sample_passive_income)
        assert result.is_compliant is True
        assert result.warnings == []

    def test_validate_passive_income_zero(self, sample_passive_income):
        sample_passive_income.amount = Decimal("0")
        result = PSAK23Rules.validate_passive_income(sample_passive_income)
        assert result.is_compliant is True  # warning only
        assert any("non-positif" in w for w in result.warnings)


# ============================================================================
# PSAK23Validator TESTS
# ============================================================================

class TestPSAK23Validator:
    def test_create_goods_sale(self, validator, fixed_now):
        sale = validator.create_goods_sale(
            customer_name="PT X",
            invoice_number="INV-001",
            sale_date=fixed_now,
            revenue_amount=Decimal("1000000"),
            cost_of_goods_sold=Decimal("600000"),
        )
        assert sale.sale_id is not None
        assert sale.customer_name == "PT X"
        assert sale.revenue_amount == Decimal("1000000")
        assert sale.cost_of_goods_sold == Decimal("600000")
        assert sale.meets_criteria() is True

    def test_create_service_contract(self, validator, fixed_now, fixed_future):
        contract = validator.create_service_contract(
            contract_number="CONT-001",
            customer_name="PT Jasa",
            contract_value=Decimal("10000000"),
            start_date=fixed_now,
            estimated_completion_date=fixed_future,
            estimated_total_cost=Decimal("7000000"),
            completion_method=PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION,
        )
        assert contract.contract_id is not None
        assert contract.contract_value == Decimal("10000000")
        assert contract.estimated_total_cost == Decimal("7000000")
        assert contract.completion_method == PSAK23ServiceCompletionMethod.PERCENTAGE_OF_COMPLETION

    def test_create_passive_income(self, validator, fixed_now):
        income = validator.create_passive_income(
            income_type=PSAK23RevenueType.INTEREST,
            amount=Decimal("500000"),
            accrual_date=fixed_now,
            description="Interest",
            effective_interest_rate=Decimal("0.06"),
        )
        assert income.income_id is not None
        assert income.income_type == PSAK23RevenueType.INTEREST
        assert income.amount == Decimal("500000")

    def test_create_summary(self, validator, fixed_past, fixed_future):
        entity_id = uuid4()
        summary = validator.create_summary(
            entity_id=entity_id,
            entity_name="PT Abadi",
            period_start=fixed_past,
            period_end=fixed_future,
        )
        assert summary.summary_id is not None
        assert summary.entity_id == entity_id
        assert summary.entity_name == "PT Abadi"
        assert summary.goods_sales == []
        assert summary.service_contracts == []
        assert summary.passive_incomes == []

    def test_add_goods_sale(self, validator, sample_summary, sample_goods_sale):
        new_summary = validator.add_goods_sale(sample_summary, sample_goods_sale)
        assert len(new_summary.goods_sales) == len(sample_summary.goods_sales) + 1
        assert new_summary.goods_sales[-1] == sample_goods_sale

    def test_add_service_contract(self, validator, sample_summary, sample_service_contract):
        new_summary = validator.add_service_contract(sample_summary, sample_service_contract)
        assert len(new_summary.service_contracts) == len(sample_summary.service_contracts) + 1

    def test_add_passive_income(self, validator, sample_summary, sample_passive_income):
        new_summary = validator.add_passive_income(sample_summary, sample_passive_income)
        assert len(new_summary.passive_incomes) == len(sample_summary.passive_incomes) + 1

    def test_record_service_cost(self, validator, sample_summary, sample_service_contract, fixed_now):
        contract_id = sample_service_contract.contract_id
        new_summary = validator.record_service_cost(sample_summary, contract_id, Decimal("1000000"))
        # Find updated contract
        updated = None
        for c in new_summary.service_contracts:
            if c.contract_id == contract_id:
                updated = c
                break
        assert updated is not None
        assert updated.actual_costs_incurred == Decimal("4500000")  # 3.5M + 1M

    def test_record_service_cost_contract_not_found(self, validator, sample_summary):
        # Should not raise; just return same
        new_summary = validator.record_service_cost(sample_summary, uuid4(), Decimal("1000"))
        assert len(new_summary.service_contracts) == len(sample_summary.service_contracts)

    def test_recognize_service_revenue(self, validator, sample_summary, sample_service_contract, fixed_now):
        contract_id = sample_service_contract.contract_id
        new_summary = validator.recognize_service_revenue(sample_summary, contract_id, fixed_now)
        updated = None
        for c in new_summary.service_contracts:
            if c.contract_id == contract_id:
                updated = c
                break
        assert updated is not None
        assert updated.revenue_recognized_to_date == Decimal("5000000")
        assert updated.progress_percentage == Decimal("50.00")

    def test_recognize_service_revenue_contract_not_found(self, validator, sample_summary):
        new_summary = validator.recognize_service_revenue(sample_summary, uuid4(), datetime.now(UTC))
        assert len(new_summary.service_contracts) == len(sample_summary.service_contracts)

    def test_validate_summary_valid(self, validator, sample_summary):
        result = validator.validate_summary(sample_summary)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK23ComplianceLevel.FULL

    def test_validate_summary_with_errors(self, validator, sample_summary, sample_goods_sale):
        sample_goods_sale.revenue_amount = Decimal("0")
        # Add the invalid sale
        summary = validator.add_goods_sale(PSAK23RevenueSummary(
            summary_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            period_start=datetime.now(UTC),
            period_end=datetime.now(UTC),
        ), sample_goods_sale)
        result = validator.validate_summary(summary)
        assert result.is_compliant is False
        assert any("positif" in e for e in result.errors)

    def test_merge_results(self, validator):
        main = PSAK23ValidationResult(
            is_compliant=True,
            compliance_level=PSAK23ComplianceLevel.FULL,
            errors=[],
            warnings=[],
        )
        other = PSAK23ValidationResult(
            is_compliant=False,
            compliance_level=PSAK23ComplianceLevel.NON_COMPLIANT,
            errors=["error1"],
            warnings=[],
        )
        merged = validator._merge_results(main, other)
        assert merged.is_compliant is False
        assert merged.compliance_level == PSAK23ComplianceLevel.NON_COMPLIANT
        assert merged.errors == ["error1"]

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "goods_sale_criteria" in summary
        assert len(summary["goods_sale_criteria"]) == 5
        assert "services" in summary
        assert "interest" in summary
        assert "royalties" in summary
        assert "dividends" in summary
        assert "disclosures" in summary


# ============================================================================
# SINGLETON ACCESSOR TESTS
# ============================================================================

def test_get_psak23_validator():
    v1 = get_psak23_validator()
    v2 = get_psak23_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK23Validator)


# ============================================================================
# ALIAS TESTS
# ============================================================================

def test_aliases():
    assert RevenueRecognitionLegacy is PSAK23RevenueService
    assert RevenueTransaction is PSAK23GoodsSale
