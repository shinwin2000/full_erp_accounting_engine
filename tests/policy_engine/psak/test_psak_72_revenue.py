# tests/policy_engine/psak/test_psak_72_revenue.py
# Comprehensive tests for PSAK 72 Revenue from Contracts with Customers
# Covers all classes: enums, exceptions, data classes, service, rules, validator, convenience class

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_72_revenue import (
    PSAK72,
    AllocationError,
    ContractNotValidError,
    PerformanceObligationStatus,
    PSAK72ComplianceLevel,
    PSAK72ContractAssetLiability,
    PSAK72ContractType,
    PSAK72ContractWithCustomer,
    PSAK72Error,
    PSAK72LicenceType,
    PSAK72PerformanceObligation,
    PSAK72PerformanceObligationTiming,
    PSAK72ProgressMeasureMethod,
    PSAK72RevenueRecognitionResult,
    PSAK72RevenueService,
    PSAK72Rules,
    PSAK72TransactionPriceAllocationMethod,
    PSAK72ValidationResult,
    PSAK72Validator,
    PSAK72VariableConsideration,
    PSAK72VariableConsiderationMethod,
    get_psak72_validator,
)

# ============================================================================
# Fixtures with fixed dates to avoid flakiness
# ============================================================================

@pytest.fixture
def fixed_now():
    """Fixed datetime for deterministic tests."""
    return datetime(2026, 6, 15, 10, 30, 0, tzinfo=UTC)


@pytest.fixture
def contract_date():
    return datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def period_end():
    return datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)


@pytest.fixture
def validator():
    return PSAK72Validator()


@pytest.fixture
def customer_id():
    return uuid4()


@pytest.fixture
def sample_po():
    return PSAK72PerformanceObligation(
        obligation_id=uuid4(),
        description="Sample service",
        stand_alone_selling_price=Decimal("100000"),
        timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
    )


@pytest.fixture
def sample_contract(validator, customer_id, contract_date):
    return validator.create_contract(
        contract_number="CONT-001",
        customer_id=customer_id,
        customer_name="PT Pelanggan Utama",
        contract_date=contract_date,
        contract_type=PSAK72ContractType.BUNDLED,
        total_contract_price=Decimal("500000000"),
    )


@pytest.fixture
def sample_contract_with_obs(validator, sample_contract):
    contract = validator.add_performance_obligation(
        sample_contract,
        description="Hardware",
        stand_alone_selling_price=Decimal("300000000"),
        timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
    )
    contract = validator.add_performance_obligation(
        contract,
        description="Software",
        stand_alone_selling_price=Decimal("200000000"),
        timing=PSAK72PerformanceObligationTiming.OVER_TIME,
        progress_measure_method=PSAK72ProgressMeasureMethod.INPUT_METHOD,
        estimated_costs=Decimal("100000000"),
    )
    contract = validator.add_variable_consideration(
        contract,
        description="Bonus",
        amount_range_low=Decimal("0"),
        amount_range_high=Decimal("50000000"),
        probability=Decimal("80"),
        method=PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
    )
    return contract


# ============================================================================
# Enum tests (parameterized to eliminate duplication)
# ============================================================================

ENUM_TEST_DATA = [
    (PSAK72ContractType, ["GOODS", "SERVICES", "CONSTRUCTION", "LICENSE", "BUNDLED"]),
    (PSAK72PerformanceObligationTiming, ["AT_A_POINT_IN_TIME", "OVER_TIME"]),
    (PSAK72ProgressMeasureMethod, ["INPUT_METHOD", "OUTPUT_METHOD"]),
    (PSAK72TransactionPriceAllocationMethod, ["STANDALONE_SELLING_PRICES", "ADJUSTED_MARKET_ASSESSMENT", "EXPECTED_COST_PLUS_MARGIN", "RESIDUAL_APPROACH"]),
    (PSAK72VariableConsiderationMethod, ["EXPECTED_VALUE", "MOST_LIKELY_AMOUNT"]),
    (PSAK72LicenceType, ["RIGHT_TO_ACCESS", "RIGHT_TO_USE"]),
    (PSAK72ContractAssetLiability, ["CONTRACT_ASSET", "CONTRACT_LIABILITY"]),
    (PSAK72ComplianceLevel, ["FULL", "SUBSTANTIAL", "PARTIAL", "NON_COMPLIANT"]),
    (PerformanceObligationStatus, ["PENDING", "IN_PROGRESS", "SATISFIED"]),
]


@pytest.mark.parametrize("enum_cls,expected_names", ENUM_TEST_DATA)
def test_enum_members(enum_cls, expected_names):
    """All enum members exist and have expected names."""
    for name in expected_names:
        assert hasattr(enum_cls, name)
    # Also verify value uniqueness (if applicable)
    values = [getattr(enum_cls, name).value for name in expected_names]
    assert len(set(values)) == len(values)


# ============================================================================
# Exception tests
# ============================================================================

class TestExceptions:
    def test_psak72_error(self):
        exc = PSAK72Error("test message")
        assert isinstance(exc, Exception)
        assert str(exc) == "test message"

    def test_contract_not_valid_error(self):
        exc = ContractNotValidError("invalid")
        assert isinstance(exc, PSAK72Error)
        assert str(exc) == "invalid"

    def test_allocation_error(self):
        exc = AllocationError("alloc failed")
        assert isinstance(exc, PSAK72Error)
        assert str(exc) == "alloc failed"


# ============================================================================
# PSAK72VariableConsideration tests
# ============================================================================

class TestVariableConsideration:
    def test_expected_value_method(self):
        vc = PSAK72VariableConsideration(
            description="Bonus",
            amount_range_low=Decimal("0"),
            amount_range_high=Decimal("100000"),
            probability=Decimal("80"),
            method=PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        assert vc.estimated_amount == Decimal("50000")

    def test_most_likely_method(self):
        vc = PSAK72VariableConsideration(
            description="Discount",
            amount_range_low=Decimal("0"),
            amount_range_high=Decimal("50000"),
            probability=Decimal("60"),
            method=PSAK72VariableConsiderationMethod.MOST_LIKELY_AMOUNT,
        )
        assert vc.estimated_amount == Decimal("50000")

    def test_to_dict(self):
        vc = PSAK72VariableConsideration(
            description="Test",
            amount_range_low=Decimal("100"),
            amount_range_high=Decimal("200"),
            probability=Decimal("50"),
            method=PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        d = vc.to_dict()
        assert d["description"] == "Test"
        assert d["range_low"] == "100"
        assert d["range_high"] == "200"
        assert d["probability"] == "50"
        assert d["method"] == "nilai_yang_diharapkan"
        assert d["estimated"] == "150"


# ============================================================================
# PSAK72PerformanceObligation tests
# ============================================================================

class TestPerformanceObligation:
    def test_progress_percentage_input_method(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Software dev",
            stand_alone_selling_price=Decimal("1000000"),
            timing=PSAK72PerformanceObligationTiming.OVER_TIME,
            progress_measure_method=PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("500000"),
            costs_incurred_to_date=Decimal("250000"),
        )
        assert po.progress_percentage() == Decimal("50.00")

    def test_progress_percentage_output_method(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Construction",
            stand_alone_selling_price=Decimal("2000000"),
            timing=PSAK72PerformanceObligationTiming.OVER_TIME,
            progress_measure_method=PSAK72ProgressMeasureMethod.OUTPUT_METHOD,
            total_units_expected=Decimal("100"),
            units_delivered_to_date=Decimal("30"),
        )
        assert po.progress_percentage() == Decimal("30.00")

    def test_progress_percentage_not_over_time(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Hardware",
            stand_alone_selling_price=Decimal("500000"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        assert po.progress_percentage() == Decimal("0")

    def test_progress_percentage_no_estimated_costs(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Software",
            stand_alone_selling_price=Decimal("1000000"),
            timing=PSAK72PerformanceObligationTiming.OVER_TIME,
            progress_measure_method=PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("0"),
            costs_incurred_to_date=Decimal("100"),
        )
        assert po.progress_percentage() == Decimal("0")

    def test_revenue_to_recognize_at_point_in_time_not_satisfied(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Hardware",
            stand_alone_selling_price=Decimal("500000"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
            revenue_recognized_to_date=Decimal("0"),
            satisfied_date=None,
        )
        assert po.revenue_to_recognize(allocated_price=Decimal("500000")) == Decimal("0")

    def test_revenue_to_recognize_at_point_in_time_satisfied(self, fixed_now):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Hardware",
            stand_alone_selling_price=Decimal("500000"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
            satisfied_date=fixed_now,
            revenue_recognized_to_date=Decimal("100000"),
        )
        assert po.revenue_to_recognize(allocated_price=Decimal("500000")) == Decimal("400000")

    def test_revenue_to_recognize_over_time(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Software",
            stand_alone_selling_price=Decimal("1000000"),
            timing=PSAK72PerformanceObligationTiming.OVER_TIME,
            progress_measure_method=PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("500000"),
            costs_incurred_to_date=Decimal("250000"),
            revenue_recognized_to_date=Decimal("0"),
        )
        assert po.revenue_to_recognize(allocated_price=Decimal("800000")) == Decimal("400000")

    def test_revenue_to_recognize_over_time_with_previous_revenue(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Software",
            stand_alone_selling_price=Decimal("1000000"),
            timing=PSAK72PerformanceObligationTiming.OVER_TIME,
            progress_measure_method=PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("500000"),
            costs_incurred_to_date=Decimal("500000"),
            revenue_recognized_to_date=Decimal("300000"),
        )
        # 100% progress, allocated 800000, total 800000 - already 300000 = 500000
        assert po.revenue_to_recognize(allocated_price=Decimal("800000")) == Decimal("500000")

    def test_to_dict(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Service",
            stand_alone_selling_price=Decimal("1000"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        d = po.to_dict()
        assert d["description"] == "Service"
        assert d["standalone_price"] == "1000"
        assert d["timing"] == "pada_saat_tertentu"
        assert d["progress"] == "0"
        assert "obligation_id" in d


# ============================================================================
# PSAK72ContractWithCustomer tests
# ============================================================================

class TestContractWithCustomer:
    def test_transaction_price_includes_variable(self):
        vc = PSAK72VariableConsideration(
            description="Bonus",
            amount_range_low=Decimal("0"),
            amount_range_high=Decimal("100000"),
            probability=Decimal("80"),
            method=PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000000"),
            variable_considerations=[vc],
        )
        assert contract.transaction_price == Decimal("1050000")

    def test_transaction_price_no_variable(self):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000000"),
            variable_considerations=[],
        )
        assert contract.transaction_price == Decimal("1000000")

    def test_total_standalone_prices(self):
        po1 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("300"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        po2 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="B", stand_alone_selling_price=Decimal("700"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po1, po2],
        )
        assert contract.total_standalone_prices() == Decimal("1000")

    def test_total_standalone_prices_empty(self):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[],
        )
        assert contract.total_standalone_prices() == Decimal("0")

    def test_allocate_transaction_price(self):
        po1 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("300"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        po2 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="B", stand_alone_selling_price=Decimal("700"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po1, po2],
            variable_considerations=[],
        )
        allocation = contract.allocate_transaction_price()
        assert allocation[po1.obligation_id] == Decimal("300")
        assert allocation[po2.obligation_id] == Decimal("700")
        assert len(allocation) == 2

    def test_allocate_transaction_price_with_variable(self):
        vc = PSAK72VariableConsideration(
            description="Bonus",
            amount_range_low=Decimal("0"),
            amount_range_high=Decimal("100"),
            probability=Decimal("50"),
            method=PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        po1 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("60"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        po2 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="B", stand_alone_selling_price=Decimal("40"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("100"),
            performance_obligations=[po1, po2],
            variable_considerations=[vc],
        )
        # transaction_price = 100 + 50 = 150
        allocation = contract.allocate_transaction_price()
        # 60/100*150 = 90, 40/100*150 = 60
        assert allocation[po1.obligation_id] == Decimal("90")
        assert allocation[po2.obligation_id] == Decimal("60")

    def test_allocate_transaction_price_zero_ssp_raises(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("0"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po],
        )
        with pytest.raises(AllocationError, match="standalone selling price"):
            contract.allocate_transaction_price()

    def test_to_dict(self, sample_po):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[sample_po],
        )
        d = contract.to_dict()
        assert d["contract_number"] == "C001"
        assert d["customer_name"] == "PT X"
        assert len(d["performance_obligations"]) == 1
        assert d["contract_asset"] == "0"
        assert d["contract_liability"] == "0"
        assert d["total_price"] == "1000"


# ============================================================================
# PSAK72RevenueRecognitionResult tests
# ============================================================================

class TestRevenueRecognitionResult:
    def test_to_dict(self):
        result = PSAK72RevenueRecognitionResult(
            result_id=uuid4(),
            contract_id=uuid4(),
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 6, 30, tzinfo=UTC),
            revenue_recognized=Decimal("150000"),
            contract_asset_change=Decimal("10000"),
            contract_liability_change=Decimal("5000"),
            details={uuid4(): Decimal("80000"), uuid4(): Decimal("70000")},
        )
        d = result.to_dict()
        assert d["revenue"] == "150000"
        assert d["contract_asset_change"] == "10000"
        assert d["contract_liability_change"] == "5000"
        assert "details" in d
        assert len(d["details"]) == 2


# ============================================================================
# PSAK72ValidationResult tests
# ============================================================================

class TestValidationResult:
    def test_initial_state(self):
        result = PSAK72ValidationResult(is_compliant=True, compliance_level=PSAK72ComplianceLevel.FULL)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK72ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []
        assert result.hash_sha256 is not None
        assert len(result.hash_sha256) == 64

    def test_add_error(self):
        result = PSAK72ValidationResult(is_compliant=True, compliance_level=PSAK72ComplianceLevel.FULL)
        result.add_error("Error 1")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK72ComplianceLevel.NON_COMPLIANT
        assert result.errors == ["Error 1"]

    def test_add_multiple_errors(self):
        result = PSAK72ValidationResult(is_compliant=True, compliance_level=PSAK72ComplianceLevel.FULL)
        result.add_error("Error 1")
        result.add_error("Error 2")
        assert result.errors == ["Error 1", "Error 2"]
        assert result.is_compliant is False

    def test_add_warning(self):
        result = PSAK72ValidationResult(is_compliant=True, compliance_level=PSAK72ComplianceLevel.FULL)
        result.add_warning("Warning 1")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK72ComplianceLevel.SUBSTANTIAL
        assert result.warnings == ["Warning 1"]

    def test_add_warning_does_not_downgrade_from_non_compliant(self):
        result = PSAK72ValidationResult(is_compliant=False, compliance_level=PSAK72ComplianceLevel.NON_COMPLIANT)
        result.add_warning("Warning")
        assert result.compliance_level == PSAK72ComplianceLevel.NON_COMPLIANT

    def test_to_dict(self):
        result = PSAK72ValidationResult(is_compliant=False, compliance_level=PSAK72ComplianceLevel.NON_COMPLIANT,
                                        errors=["e1", "e2"], warnings=["w1"])
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["e1", "e2"]
        assert d["warnings"] == ["w1"]
        assert "hash" in d


# ============================================================================
# PSAK72RevenueService tests
# ============================================================================

class TestRevenueService:
    def test_is_contract_valid_all_true(self):
        assert PSAK72RevenueService.is_contract_valid(
            has_approval=True,
            rights_identifiable=True,
            payment_terms_identifiable=True,
            has_commercial_substance=True,
            probable_collection=True
        ) is True

    def test_is_contract_valid_one_false(self):
        assert PSAK72RevenueService.is_contract_valid(
            has_approval=False,
            rights_identifiable=True,
            payment_terms_identifiable=True,
            has_commercial_substance=True,
            probable_collection=True
        ) is False

    def test_is_contract_valid_multiple_false(self):
        assert PSAK72RevenueService.is_contract_valid(
            has_approval=True,
            rights_identifiable=False,
            payment_terms_identifiable=True,
            has_commercial_substance=False,
            probable_collection=True
        ) is False

    def test_determine_performance_obligation_timing_over_time(self):
        assert PSAK72RevenueService.determine_performance_obligation_timing(
            asset_created_with_no_alternative_use=True,
            entity_has_enforceable_right_to_payment=True
        ) == PSAK72PerformanceObligationTiming.OVER_TIME

    def test_determine_performance_obligation_timing_point_in_time(self):
        assert PSAK72RevenueService.determine_performance_obligation_timing(
            asset_created_with_no_alternative_use=False,
            entity_has_enforceable_right_to_payment=True
        ) == PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME

    def test_determine_performance_obligation_timing_both_false(self):
        assert PSAK72RevenueService.determine_performance_obligation_timing(
            asset_created_with_no_alternative_use=False,
            entity_has_enforceable_right_to_payment=False
        ) == PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME

    def test_estimate_variable_consideration_expected_value(self):
        amounts = [(Decimal("100000"), Decimal("60")), (Decimal("200000"), Decimal("40"))]
        result = PSAK72RevenueService.estimate_variable_consideration(
            amounts, PSAK72VariableConsiderationMethod.EXPECTED_VALUE
        )
        assert result == Decimal("140000")

    def test_estimate_variable_consideration_expected_value_with_rounding(self):
        amounts = [(Decimal("100"), Decimal("33")), (Decimal("200"), Decimal("33")), (Decimal("300"), Decimal("34"))]
        result = PSAK72RevenueService.estimate_variable_consideration(
            amounts, PSAK72VariableConsiderationMethod.EXPECTED_VALUE
        )
        # 100*0.33 + 200*0.33 + 300*0.34 = 33+66+102 = 201
        assert result == Decimal("201")

    def test_estimate_variable_consideration_most_likely(self):
        amounts = [(Decimal("100000"), Decimal("30")), (Decimal("200000"), Decimal("70"))]
        result = PSAK72RevenueService.estimate_variable_consideration(
            amounts, PSAK72VariableConsiderationMethod.MOST_LIKELY_AMOUNT
        )
        assert result == Decimal("200000")

    def test_estimate_variable_consideration_most_likely_tie(self):
        amounts = [(Decimal("100"), Decimal("50")), (Decimal("200"), Decimal("50"))]
        result = PSAK72RevenueService.estimate_variable_consideration(
            amounts, PSAK72VariableConsiderationMethod.MOST_LIKELY_AMOUNT
        )
        # First one with max probability (50) wins
        assert result == Decimal("100")

    def test_recognize_licence_revenue_right_to_access(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        recognition = datetime(2026, 6, 30, tzinfo=UTC)
        fee = Decimal("365000")
        result = PSAK72RevenueService.recognize_licence_revenue(
            PSAK72LicenceType.RIGHT_TO_ACCESS, start, end, fee, recognition
        )
        # 181 days elapsed (Jan 1 to Jun 30 inclusive? Actually days difference is 180, but code uses days difference)
        # From 2026-01-01 to 2026-06-30 is 180 days difference, but code uses (recognition_date - start).days
        # Let's calculate: (2026-06-30 - 2026-01-01).days = 180
        # Total days = 364, 180/364*365000 = 180494.505...
        expected = (Decimal("180") / Decimal("364")) * fee
        expected = expected.quantize(Decimal("0"), rounding=Decimal("ROUND_HALF_EVEN"))
        assert result == expected

    def test_recognize_licence_revenue_right_to_access_zero_days(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        fee = Decimal("1000")
        result = PSAK72RevenueService.recognize_licence_revenue(
            PSAK72LicenceType.RIGHT_TO_ACCESS, start, end, fee, start
        )
        assert result == Decimal("0")

    def test_recognize_licence_revenue_right_to_use(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        fee = Decimal("100000")
        result = PSAK72RevenueService.recognize_licence_revenue(
            PSAK72LicenceType.RIGHT_TO_USE, start, end, fee, datetime(2026, 6, 30, tzinfo=UTC)
        )
        assert result == fee

    def test_compute_cost_to_fulfill_contract(self):
        result = PSAK72RevenueService.compute_cost_to_fulfill_contract(
            direct_labor=Decimal("50000"),
            direct_materials=Decimal("30000"),
            allocated_overhead=Decimal("20000"),
        )
        assert result == Decimal("100000")

    def test_compute_cost_to_fulfill_contract_zero(self):
        result = PSAK72RevenueService.compute_cost_to_fulfill_contract(
            direct_labor=Decimal("0"),
            direct_materials=Decimal("0"),
            allocated_overhead=Decimal("0"),
        )
        assert result == Decimal("0")


# ============================================================================
# PSAK72Rules tests
# ============================================================================

class TestRules:
    def test_validate_contract_valid(self, sample_po):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[sample_po],
        )
        result = PSAK72Rules.validate_contract(contract)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK72ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_contract_no_obligations(self):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[],
        )
        result = PSAK72Rules.validate_contract(contract)
        assert result.is_compliant is False
        assert "harus memiliki" in result.errors[0]

    def test_validate_contract_negative_price(self, sample_po):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("-100"),
            performance_obligations=[sample_po],
        )
        result = PSAK72Rules.validate_contract(contract)
        assert result.is_compliant is False
        assert "positif" in result.errors[0]

    def test_validate_contract_zero_price(self, sample_po):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("0"),
            performance_obligations=[sample_po],
        )
        result = PSAK72Rules.validate_contract(contract)
        assert result.is_compliant is False
        assert "positif" in result.errors[0]

    def test_validate_contract_warning_on_zero_ssp(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("0"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po],
        )
        result = PSAK72Rules.validate_contract(contract)
        assert result.is_compliant is True
        assert result.warnings == ["Kewajiban kinerja A memiliki harga jual berdiri sendiri non-positif"]

    def test_validate_allocation_correct(self):
        po1 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("300"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        po2 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="B", stand_alone_selling_price=Decimal("700"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po1, po2],
        )
        allocation = {po1.obligation_id: Decimal("300"), po2.obligation_id: Decimal("700")}
        result = PSAK72Rules.validate_allocation(contract, allocation)
        assert result.is_compliant is True

    def test_validate_allocation_incorrect_total(self):
        po1 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("300"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        po2 = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="B", stand_alone_selling_price=Decimal("700"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po1, po2],
        )
        allocation = {po1.obligation_id: Decimal("400"), po2.obligation_id: Decimal("500")}
        result = PSAK72Rules.validate_allocation(contract, allocation)
        assert result.is_compliant is False
        assert "tidak sama dengan" in result.errors[0]

    def test_validate_disclosure_valid(self, sample_po):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[sample_po],
        )
        result = PSAK72Rules.validate_disclosure(contract, recognized_revenue=Decimal("500"))
        assert result.is_compliant is True

    def test_validate_disclosure_exceeds(self, sample_po):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[sample_po],
        )
        result = PSAK72Rules.validate_disclosure(contract, recognized_revenue=Decimal("1200"))
        assert result.is_compliant is False
        assert "melebihi" in result.errors[0]

    def test_validate_disclosure_exact_match(self, sample_po):
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[sample_po],
        )
        result = PSAK72Rules.validate_disclosure(contract, recognized_revenue=Decimal("1000"))
        assert result.is_compliant is True


# ============================================================================
# PSAK72Validator integration tests
# ============================================================================

class TestValidator:
    def test_create_contract(self, validator, customer_id, contract_date):
        contract = validator.create_contract(
            contract_number="C001",
            customer_id=customer_id,
            customer_name="PT X",
            contract_date=contract_date,
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000000"),
        )
        assert contract.contract_id is not None
        assert contract.contract_number == "C001"
        assert contract.customer_id == customer_id
        assert contract.total_contract_price == Decimal("1000000")
        assert contract.performance_obligations == []

    def test_add_performance_obligation(self, validator, sample_contract):
        new_contract = validator.add_performance_obligation(
            sample_contract,
            description="Hardware",
            stand_alone_selling_price=Decimal("300000000"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        assert len(new_contract.performance_obligations) == 1
        po = new_contract.performance_obligations[0]
        assert po.description == "Hardware"
        assert po.stand_alone_selling_price == Decimal("300000000")
        assert po.timing == PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME
        # Original contract unchanged
        assert len(sample_contract.performance_obligations) == 0

    def test_add_performance_obligation_with_progress_method(self, validator, sample_contract):
        new_contract = validator.add_performance_obligation(
            sample_contract,
            description="Software",
            stand_alone_selling_price=Decimal("200000000"),
            timing=PSAK72PerformanceObligationTiming.OVER_TIME,
            progress_measure_method=PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("100000000"),
            total_units_expected=Decimal("100"),
        )
        po = new_contract.performance_obligations[0]
        assert po.progress_measure_method == PSAK72ProgressMeasureMethod.INPUT_METHOD
        assert po.estimated_costs == Decimal("100000000")
        assert po.total_units_expected == Decimal("100")

    def test_add_variable_consideration(self, validator, sample_contract):
        new_contract = validator.add_variable_consideration(
            sample_contract,
            description="Bonus",
            amount_range_low=Decimal("0"),
            amount_range_high=Decimal("50000000"),
            probability=Decimal("80"),
            method=PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        assert len(new_contract.variable_considerations) == 1
        vc = new_contract.variable_considerations[0]
        assert vc.description == "Bonus"
        assert vc.estimated_amount == Decimal("25000000")
        # Original unchanged
        assert len(sample_contract.variable_considerations) == 0

    def test_allocate_prices(self, validator, sample_contract_with_obs):
        contract, allocation = validator.allocate_prices(sample_contract_with_obs)
        assert contract.allocation_method == PSAK72TransactionPriceAllocationMethod.STANDALONE_SELLING_PRICES
        # Transaction price = 500,000,000 + 25,000,000 = 525,000,000
        # SSP: 300M + 200M = 500M
        expected_hw = Decimal("315000000")
        expected_sw = Decimal("210000000")
        ob1_id = sample_contract_with_obs.performance_obligations[0].obligation_id
        ob2_id = sample_contract_with_obs.performance_obligations[1].obligation_id
        assert allocation[ob1_id] == expected_hw
        assert allocation[ob2_id] == expected_sw
        assert allocation[ob1_id] + allocation[ob2_id] == Decimal("525000000")

    def test_allocate_prices_residual_method(self, validator, sample_contract_with_obs):
        contract, _allocation = validator.allocate_prices(
            sample_contract_with_obs,
            method=PSAK72TransactionPriceAllocationMethod.RESIDUAL_APPROACH
        )
        assert contract.allocation_method == PSAK72TransactionPriceAllocationMethod.RESIDUAL_APPROACH

    def test_record_progress_costs(self, validator, sample_contract_with_obs):
        po_id = sample_contract_with_obs.performance_obligations[1].obligation_id
        new_contract = validator.record_progress(
            sample_contract_with_obs, po_id, costs_incurred=Decimal("30000000")
        )
        po = new_contract.performance_obligations[1]
        assert po.costs_incurred_to_date == Decimal("30000000")

    def test_record_progress_units(self, validator, sample_contract_with_obs):
        po_id = sample_contract_with_obs.performance_obligations[1].obligation_id
        new_contract = validator.record_progress(
            sample_contract_with_obs, po_id, units_delivered=Decimal("10")
        )
        po = new_contract.performance_obligations[1]
        assert po.units_delivered_to_date == Decimal("10")

    def test_record_progress_satisfied_date(self, validator, sample_contract_with_obs, fixed_now):
        po_id = sample_contract_with_obs.performance_obligations[0].obligation_id
        new_contract = validator.record_progress(
            sample_contract_with_obs, po_id, satisfied_date=fixed_now
        )
        po = new_contract.performance_obligations[0]
        assert po.satisfied_date == fixed_now

    def test_record_progress_multiple_updates(self, validator, sample_contract_with_obs):
        po_id = sample_contract_with_obs.performance_obligations[1].obligation_id
        contract = validator.record_progress(
            sample_contract_with_obs, po_id, costs_incurred=Decimal("10000000")
        )
        contract = validator.record_progress(
            contract, po_id, costs_incurred=Decimal("20000000")
        )
        po = contract.performance_obligations[1]
        assert po.costs_incurred_to_date == Decimal("30000000")

    def test_recognize_revenue(self, validator, sample_contract_with_obs, period_end):
        # Get allocation
        contract, allocation = validator.allocate_prices(sample_contract_with_obs)
        # Record progress for software
        sw_id = contract.performance_obligations[1].obligation_id
        contract = validator.record_progress(contract, sw_id, costs_incurred=Decimal("30000000"))
        # Recognize revenue
        new_contract, result = validator.recognize_revenue(contract, allocation, period_end)
        # Software allocated = 210M, progress 30% => 63M
        assert result.revenue_recognized == Decimal("63000000")
        assert result.details[sw_id] == Decimal("63000000")
        # Hardware not yet satisfied => 0
        hw_id = contract.performance_obligations[0].obligation_id
        assert result.details.get(hw_id, Decimal("0")) == Decimal("0")
        # Contract asset: 63M (software revenue recognized but not invoiced)
        assert new_contract.contract_asset == Decimal("63000000")
        assert new_contract.contract_liability == Decimal("0")

    def test_recognize_revenue_hardware_delivered(self, validator, sample_contract_with_obs, period_end, fixed_now):
        contract, allocation = validator.allocate_prices(sample_contract_with_obs)
        # Deliver hardware
        hw_id = contract.performance_obligations[0].obligation_id
        contract = validator.record_progress(contract, hw_id, satisfied_date=fixed_now)
        # Record progress for software
        sw_id = contract.performance_obligations[1].obligation_id
        contract = validator.record_progress(contract, sw_id, costs_incurred=Decimal("100000000"))
        # Recognize revenue
        new_contract, result = validator.recognize_revenue(contract, allocation, period_end)
        # Hardware allocated 315M, recognized at point in time
        # Software allocated 210M, 100% progress => 210M
        assert result.revenue_recognized == Decimal("525000000")
        assert result.details[hw_id] == Decimal("315000000")
        assert result.details[sw_id] == Decimal("210000000")
        # Contract asset: both revenues recognized but not invoiced
        assert new_contract.contract_asset == Decimal("525000000")

    def test_recognize_revenue_with_existing_revenue(self, validator, sample_contract_with_obs, period_end):
        contract, allocation = validator.allocate_prices(sample_contract_with_obs)
        sw_id = contract.performance_obligations[1].obligation_id
        # First recognition: 30% progress
        contract = validator.record_progress(contract, sw_id, costs_incurred=Decimal("30000000"))
        contract, result1 = validator.recognize_revenue(contract, allocation, period_end)
        assert result1.revenue_recognized == Decimal("63000000")
        # Second recognition: additional 30% progress
        contract = validator.record_progress(contract, sw_id, costs_incurred=Decimal("30000000"))
        contract, result2 = validator.recognize_revenue(contract, allocation, period_end)
        # Additional revenue should be 63000000, total 126000000
        assert result2.revenue_recognized == Decimal("63000000")
        # Check cumulative in PO
        po = contract.performance_obligations[1]
        assert po.revenue_recognized_to_date == Decimal("126000000")

    def test_record_payment_advance(self, validator, sample_contract):
        new_contract = validator.record_payment(sample_contract, Decimal("100000000"), is_advance=True)
        assert new_contract.contract_liability == Decimal("100000000")
        assert new_contract.contract_asset == Decimal("0")

    def test_record_payment_advance_multiple(self, validator, sample_contract):
        contract = validator.record_payment(sample_contract, Decimal("50000000"), is_advance=True)
        contract = validator.record_payment(contract, Decimal("30000000"), is_advance=True)
        assert contract.contract_liability == Decimal("80000000")

    def test_record_payment_reduce_asset(self, validator, sample_contract):
        # Set asset first
        sample_contract.contract_asset = Decimal("50000000")
        new_contract = validator.record_payment(sample_contract, Decimal("20000000"), is_advance=False)
        assert new_contract.contract_asset == Decimal("30000000")
        assert new_contract.contract_liability == Decimal("0")

    def test_record_payment_reduce_asset_to_zero(self, validator, sample_contract):
        sample_contract.contract_asset = Decimal("50000000")
        new_contract = validator.record_payment(sample_contract, Decimal("60000000"), is_advance=False)
        assert new_contract.contract_asset == Decimal("0")
        assert new_contract.contract_liability == Decimal("0")

    def test_validate_contract(self, validator, sample_contract_with_obs):
        result = validator.validate_contract(sample_contract_with_obs)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK72ComplianceLevel.FULL

    def test_validate_contract_invalid(self, validator, sample_contract):
        result = validator.validate_contract(sample_contract)
        assert result.is_compliant is False
        assert "harus memiliki" in result.errors[0]

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "five_steps" in summary
        assert len(summary["five_steps"]) == 5
        assert "contract_validity_criteria" in summary
        assert len(summary["contract_validity_criteria"]) == 5
        assert "disclosures" in summary
        assert len(summary["disclosures"]) >= 4


# ============================================================================
# PSAK72 convenience class tests
# ============================================================================

class TestPSAK72:
    def test_create_transaction(self):
        obligations = [
            {"description": "A", "standalone_price": Decimal("300")},
            {"description": "B", "standalone_price": Decimal("700")},
        ]
        transaction = PSAK72.create_transaction(
            contract_price=Decimal("1000"),
            performance_obligations=obligations,
        )
        assert transaction["contract_price"] == Decimal("1000")
        assert transaction["total_standalone_prices"] == Decimal("1000")
        assert len(transaction["performance_obligations"]) == 2

    def test_allocate_transaction_price(self):
        obligations = [
            {"description": "A", "standalone_price": Decimal("300")},
            {"description": "B", "standalone_price": Decimal("700")},
        ]
        transaction = PSAK72.create_transaction(
            contract_price=Decimal("1000"),
            performance_obligations=obligations,
        )
        allocation = PSAK72.allocate_transaction_price(transaction)
        assert allocation["A"] == Decimal("300")
        assert allocation["B"] == Decimal("700")
        assert sum(allocation.values()) == Decimal("1000")

    def test_allocate_transaction_price_with_rounding(self):
        obligations = [
            {"description": "A", "standalone_price": Decimal("333")},
            {"description": "B", "standalone_price": Decimal("333")},
            {"description": "C", "standalone_price": Decimal("334")},
        ]
        transaction = PSAK72.create_transaction(
            contract_price=Decimal("1000"),
            performance_obligations=obligations,
        )
        allocation = PSAK72.allocate_transaction_price(transaction)
        assert allocation["A"] == Decimal("333")
        assert allocation["B"] == Decimal("333")
        assert allocation["C"] == Decimal("334")

    def test_allocate_transaction_price_zero_ssp_raises(self):
        obligations = [{"description": "A", "standalone_price": Decimal("0")}]
        transaction = PSAK72.create_transaction(
            contract_price=Decimal("100"),
            performance_obligations=obligations,
        )
        with pytest.raises(ValueError, match="zero"):
            PSAK72.allocate_transaction_price(transaction)

    def test_is_control_transferred(self):
        assert PSAK72.is_control_transferred(date.today()) is True
        assert PSAK72.is_control_transferred(date(2020, 1, 1)) is True


# ============================================================================
# Singleton accessor test
# ============================================================================

def test_get_psak72_validator_singleton():
    v1 = get_psak72_validator()
    v2 = get_psak72_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK72Validator)
