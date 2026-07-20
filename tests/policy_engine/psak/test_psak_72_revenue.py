# tests/policy_engine/psak/test_psak_72_revenue.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, dan validasi bisnis.

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from policy_engine.psak.psak_72_revenue import (
    ALLOCATION_ERROR,
    CONTRACT_NOT_VALID_ERROR,
    PSAK72,
    PSAK72_COMPLIANCE_LEVEL,
    PSAK72_CONTRACT_ASSET_LIABILITY,
    PSAK72_CONTRACT_TYPE,
    PSAK72_LICENCE_TYPE,
    PSAK72_PERFORMANCE_OBLIGATION_TIMING,
    PSAK72_PROGRESS_MEASURE_METHOD,
    PSAK72_TRANSACTION_PRICE_ALLOCATION_METHOD,
    PSAK72_VARIABLE_CONSIDERATION_METHOD,
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
# Enum tests
# ============================================================================
class TestPSAK72ContractType:
    def test_members(self):
        expected = ["GOODS", "SERVICES", "CONSTRUCTION", "LICENSE", "BUNDLED"]
        for name in expected:
            assert hasattr(PSAK72ContractType, name)
        assert PSAK72ContractType.GOODS.value == "barang"


class TestPSAK72PerformanceObligationTiming:
    def test_members(self):
        expected = ["AT_A_POINT_IN_TIME", "OVER_TIME"]
        for name in expected:
            assert hasattr(PSAK72PerformanceObligationTiming, name)


class TestPSAK72ProgressMeasureMethod:
    def test_members(self):
        expected = ["INPUT_METHOD", "OUTPUT_METHOD"]
        for name in expected:
            assert hasattr(PSAK72ProgressMeasureMethod, name)


class TestPSAK72TransactionPriceAllocationMethod:
    def test_members(self):
        expected = ["STANDALONE_SELLING_PRICES", "ADJUSTED_MARKET_ASSESSMENT",
                    "EXPECTED_COST_PLUS_MARGIN", "RESIDUAL_APPROACH"]
        for name in expected:
            assert hasattr(PSAK72TransactionPriceAllocationMethod, name)


class TestPSAK72VariableConsiderationMethod:
    def test_members(self):
        expected = ["EXPECTED_VALUE", "MOST_LIKELY_AMOUNT"]
        for name in expected:
            assert hasattr(PSAK72VariableConsiderationMethod, name)


class TestPSAK72LicenceType:
    def test_members(self):
        expected = ["RIGHT_TO_ACCESS", "RIGHT_TO_USE"]
        for name in expected:
            assert hasattr(PSAK72LicenceType, name)


class TestPSAK72ContractAssetLiability:
    def test_members(self):
        expected = ["CONTRACT_ASSET", "CONTRACT_LIABILITY"]
        for name in expected:
            assert hasattr(PSAK72ContractAssetLiability, name)


class TestPSAK72ComplianceLevel:
    def test_members(self):
        expected = ["FULL", "SUBSTANTIAL", "PARTIAL", "NON_COMPLIANT"]
        for name in expected:
            assert hasattr(PSAK72ComplianceLevel, name)


class TestPerformanceObligationStatus:
    def test_members(self):
        expected = ["PENDING", "IN_PROGRESS", "SATISFIED"]
        for name in expected:
            assert hasattr(PerformanceObligationStatus, name)


# ============================================================================
# Exception tests
# ============================================================================
class TestPSAK72Error:
    def test_construction(self):
        e = PSAK72Error("test")
        assert isinstance(e, Exception)
        assert str(e) == "test"


class TestContractNotValidError:
    def test_construction(self):
        e = ContractNotValidError("invalid")
        assert isinstance(e, PSAK72Error)


class TestAllocationError:
    def test_construction(self):
        e = AllocationError("alloc failed")
        assert isinstance(e, PSAK72Error)


# ============================================================================
# PSAK72VariableConsideration tests
# ============================================================================
class TestPSAK72VariableConsideration:
    def test_expected_value_method(self):
        vc = PSAK72VariableConsideration(
            description="Bonus",
            amount_range_low=Decimal("0"),
            amount_range_high=Decimal("100000"),
            probability=Decimal("80"),
            method=PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        assert vc.estimated_amount == Decimal("50000")  # (0+100000)/2

    def test_most_likely_method(self):
        vc = PSAK72VariableConsideration(
            description="Discount",
            amount_range_low=Decimal("0"),
            amount_range_high=Decimal("50000"),
            probability=Decimal("60"),
            method=PSAK72VariableConsiderationMethod.MOST_LIKELY_AMOUNT,
        )
        assert vc.estimated_amount == Decimal("50000")  # uses high

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
        assert d["estimated"] == "150"


# ============================================================================
# PSAK72PerformanceObligation tests
# ============================================================================
class TestPSAK72PerformanceObligation:
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

    def test_revenue_to_recognize_at_point_in_time_not_satisfied(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Hardware",
            stand_alone_selling_price=Decimal("500000"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
            revenue_recognized_to_date=Decimal("0"),
        )
        assert po.revenue_to_recognize(allocated_price=Decimal("500000")) == Decimal("0")

    def test_revenue_to_recognize_at_point_in_time_satisfied(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(),
            description="Hardware",
            stand_alone_selling_price=Decimal("500000"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
            satisfied_date=datetime.now(UTC),
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
        # progress = 50%, allocated = 800000 => revenue = 400000
        assert po.revenue_to_recognize(allocated_price=Decimal("800000")) == Decimal("400000")

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


# ============================================================================
# PSAK72ContractWithCustomer tests
# ============================================================================
class TestPSAK72ContractWithCustomer:
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
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000000"),
            variable_considerations=[vc],
        )
        assert contract.transaction_price == Decimal("1050000")  # 1,000,000 + 50,000

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
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po1, po2],
        )
        assert contract.total_standalone_prices() == Decimal("1000")

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
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po1, po2],
            variable_considerations=[],
        )
        allocation = contract.allocate_transaction_price()
        assert allocation[po1.obligation_id] == Decimal("300")
        assert allocation[po2.obligation_id] == Decimal("700")

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
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po],
        )
        with pytest.raises(AllocationError, match="standalone selling price"):
            contract.allocate_transaction_price()

    def test_to_dict(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("100"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po],
        )
        d = contract.to_dict()
        assert d["contract_number"] == "C001"
        assert d["customer_name"] == "PT X"
        assert len(d["performance_obligations"]) == 1
        assert d["contract_asset"] == "0"
        assert d["contract_liability"] == "0"


# ============================================================================
# PSAK72RevenueRecognitionResult tests
# ============================================================================
class TestPSAK72RevenueRecognitionResult:
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
        assert "details" in d
        assert len(d["details"]) == 2


# ============================================================================
# PSAK72ValidationResult tests
# ============================================================================
class TestPSAK72ValidationResult:
    def test_add_error(self):
        result = PSAK72ValidationResult(is_compliant=True, compliance_level=PSAK72ComplianceLevel.FULL)
        result.add_error("Error 1")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK72ComplianceLevel.NON_COMPLIANT
        assert result.errors == ["Error 1"]

    def test_add_warning(self):
        result = PSAK72ValidationResult(is_compliant=True, compliance_level=PSAK72ComplianceLevel.FULL)
        result.add_warning("Warning 1")
        assert result.is_compliant is True  # warnings don't break compliance
        assert result.compliance_level == PSAK72ComplianceLevel.SUBSTANTIAL
        assert result.warnings == ["Warning 1"]

    def test_compute_hash(self):
        result = PSAK72ValidationResult(is_compliant=True, compliance_level=PSAK72ComplianceLevel.FULL)
        assert result.hash_sha256 is not None
        assert len(result.hash_sha256) == 64

    def test_to_dict(self):
        result = PSAK72ValidationResult(is_compliant=False, compliance_level=PSAK72ComplianceLevel.NON_COMPLIANT,
                                        errors=["e"], warnings=["w"])
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["e"]
        assert d["warnings"] == ["w"]
        assert "hash" in d


# ============================================================================
# PSAK72RevenueService tests
# ============================================================================
class TestPSAK72RevenueService:
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

    def test_estimate_variable_consideration_expected_value(self):
        amounts = [(Decimal("100000"), Decimal("60")), (Decimal("200000"), Decimal("40"))]
        result = PSAK72RevenueService.estimate_variable_consideration(
            amounts, PSAK72VariableConsiderationMethod.EXPECTED_VALUE
        )
        # 100000*0.6 + 200000*0.4 = 60000+80000 = 140000
        assert result == Decimal("140000")

    def test_estimate_variable_consideration_most_likely(self):
        amounts = [(Decimal("100000"), Decimal("30")), (Decimal("200000"), Decimal("70"))]
        result = PSAK72RevenueService.estimate_variable_consideration(
            amounts, PSAK72VariableConsiderationMethod.MOST_LIKELY_AMOUNT
        )
        assert result == Decimal("200000")  # highest probability

    def test_recognize_licence_revenue_right_to_access(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        recognition = datetime(2026, 6, 30, tzinfo=UTC)
        # 365 days total, 181 days elapsed (Jan 1 to Jun 30)
        fee = Decimal("365000")
        result = PSAK72RevenueService.recognize_licence_revenue(
            PSAK72LicenceType.RIGHT_TO_ACCESS, start, end, fee, recognition
        )
        # (181/365)*365000 = 181000
        assert result == Decimal("181000")

    def test_recognize_licence_revenue_right_to_use(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 12, 31, tzinfo=UTC)
        fee = Decimal("100000")
        result = PSAK72RevenueService.recognize_licence_revenue(
            PSAK72LicenceType.RIGHT_TO_USE, start, end, fee, datetime.now(UTC)
        )
        assert result == fee  # recognized at point in time

    def test_compute_cost_to_fulfill_contract(self):
        result = PSAK72RevenueService.compute_cost_to_fulfill_contract(
            direct_labor=Decimal("50000"),
            direct_materials=Decimal("30000"),
            allocated_overhead=Decimal("20000"),
        )
        assert result == Decimal("100000")


# ============================================================================
# PSAK72Rules tests
# ============================================================================
class TestPSAK72Rules:
    def test_validate_contract_valid(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("100"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po],
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
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[],
        )
        result = PSAK72Rules.validate_contract(contract)
        assert result.is_compliant is False
        assert "harus memiliki" in result.errors[0]

    def test_validate_contract_negative_price(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("100"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("-100"),
            performance_obligations=[po],
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
            contract_date=datetime.now(UTC),
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
            contract_date=datetime.now(UTC),
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
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po1, po2],
        )
        allocation = {po1.obligation_id: Decimal("400"), po2.obligation_id: Decimal("500")}  # total 900
        result = PSAK72Rules.validate_allocation(contract, allocation)
        assert result.is_compliant is False
        assert "tidak sama dengan" in result.errors[0]

    def test_validate_disclosure_valid(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("100"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po],
        )
        result = PSAK72Rules.validate_disclosure(contract, recognized_revenue=Decimal("500"))
        assert result.is_compliant is True

    def test_validate_disclosure_exceeds(self):
        po = PSAK72PerformanceObligation(
            obligation_id=uuid4(), description="A", stand_alone_selling_price=Decimal("100"),
            timing=PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = PSAK72ContractWithCustomer(
            contract_id=uuid4(),
            contract_number="C001",
            customer_id=uuid4(),
            customer_name="PT X",
            contract_date=datetime.now(UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000"),
            performance_obligations=[po],
        )
        result = PSAK72Rules.validate_disclosure(contract, recognized_revenue=Decimal("1200"))
        assert result.is_compliant is False
        assert "melebihi" in result.errors[0]


# ============================================================================
# PSAK72Validator integration tests
# ============================================================================
class TestPSAK72Validator:
    @pytest.fixture
    def validator(self):
        return PSAK72Validator()

    @pytest.fixture
    def contract(self, validator):
        customer_id = uuid4()
        return validator.create_contract(
            contract_number="CONT-001",
            customer_id=customer_id,
            customer_name="PT Pelanggan Utama",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.BUNDLED,
            total_contract_price=Decimal("500000000"),
        )

    def test_create_contract(self, validator):
        customer_id = uuid4()
        contract = validator.create_contract(
            contract_number="C001",
            customer_id=customer_id,
            customer_name="PT X",
            contract_date=datetime(2026, 1, 1, tzinfo=UTC),
            contract_type=PSAK72ContractType.GOODS,
            total_contract_price=Decimal("1000000"),
        )
        assert contract.contract_id is not None
        assert contract.contract_number == "C001"
        assert contract.customer_id == customer_id
        assert contract.total_contract_price == Decimal("1000000")
        assert contract.performance_obligations == []

    def test_add_performance_obligation(self, validator, contract):
        new_contract = validator.add_performance_obligation(
            contract,
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
        assert len(contract.performance_obligations) == 0

    def test_add_variable_consideration(self, validator, contract):
        new_contract = validator.add_variable_consideration(
            contract,
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
        assert len(contract.variable_considerations) == 0

    def test_allocate_prices(self, validator, contract):
        # Add two obligations
        contract = validator.add_performance_obligation(
            contract, "Hardware", Decimal("300000000"),
            PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = validator.add_performance_obligation(
            contract, "Software", Decimal("200000000"),
            PSAK72PerformanceObligationTiming.OVER_TIME,
            PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("100000000"),
        )
        # Add variable consideration
        contract = validator.add_variable_consideration(
            contract, "Bonus", Decimal("0"), Decimal("50000000"),
            Decimal("80"), PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        # Allocate
        new_contract, allocation = validator.allocate_prices(contract)
        assert new_contract.allocation_method == PSAK72TransactionPriceAllocationMethod.STANDALONE_SELLING_PRICES
        # Total allocated = transaction price = 500,000,000 + 25,000,000 = 525,000,000
        # SSP: 300M + 200M = 500M, ratio: 0.6 and 0.4
        expected_alloc1 = (Decimal("300000000") / Decimal("500000000")) * Decimal("525000000")  # 315M
        expected_alloc2 = (Decimal("200000000") / Decimal("500000000")) * Decimal("525000000")  # 210M
        assert allocation[contract.performance_obligations[0].obligation_id] == Decimal("315000000")
        assert allocation[contract.performance_obligations[1].obligation_id] == Decimal("210000000")

    def test_record_progress(self, validator, contract):
        contract = validator.add_performance_obligation(
            contract, "Software", Decimal("200000000"),
            PSAK72PerformanceObligationTiming.OVER_TIME,
            PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("100000000"),
        )
        po_id = contract.performance_obligations[0].obligation_id
        new_contract = validator.record_progress(
            contract, po_id, costs_incurred=Decimal("30000000")
        )
        po = new_contract.performance_obligations[0]
        assert po.costs_incurred_to_date == Decimal("30000000")
        # Record units
        new_contract2 = validator.record_progress(
            new_contract, po_id, units_delivered=Decimal("10")
        )
        po2 = new_contract2.performance_obligations[0]
        assert po2.units_delivered_to_date == Decimal("10")

    def test_recognize_revenue(self, validator, contract):
        # Setup
        contract = validator.add_performance_obligation(
            contract, "Hardware", Decimal("300000000"),
            PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        contract = validator.add_performance_obligation(
            contract, "Software", Decimal("200000000"),
            PSAK72PerformanceObligationTiming.OVER_TIME,
            PSAK72ProgressMeasureMethod.INPUT_METHOD,
            estimated_costs=Decimal("100000000"),
        )
        contract = validator.add_variable_consideration(
            contract, "Bonus", Decimal("0"), Decimal("50000000"),
            Decimal("80"), PSAK72VariableConsiderationMethod.EXPECTED_VALUE,
        )
        contract, allocation = validator.allocate_prices(contract)
        # Record progress for software (30% completion)
        sw_id = contract.performance_obligations[1].obligation_id
        contract = validator.record_progress(contract, sw_id, costs_incurred=Decimal("30000000"))
        # Recognize revenue
        period_end = datetime(2026, 6, 30, tzinfo=UTC)
        new_contract, result = validator.recognize_revenue(contract, allocation, period_end)
        # Software allocated = 210M, progress 30% => 63M recognized
        # Hardware allocated = 315M, not yet satisfied => 0
        assert result.revenue_recognized == Decimal("63000000")
        assert result.details[sw_id] == Decimal("63000000")
        # Check contract asset: only software has revenue recognized but not invoiced
        # Since hardware not satisfied, no asset for it
        assert new_contract.contract_asset == Decimal("63000000")
        assert new_contract.contract_liability == Decimal("0")

    def test_record_payment_advance(self, validator, contract):
        new_contract = validator.record_payment(contract, Decimal("100000000"), is_advance=True)
        assert new_contract.contract_liability == Decimal("100000000")
        assert new_contract.contract_asset == Decimal("0")  # unchanged

    def test_record_payment_reduce_asset(self, validator, contract):
        contract.contract_asset = Decimal("50000000")
        new_contract = validator.record_payment(contract, Decimal("20000000"), is_advance=False)
        assert new_contract.contract_asset == Decimal("30000000")
        assert new_contract.contract_liability == Decimal("0")  # unchanged

    def test_validate_contract(self, validator, contract):
        contract = validator.add_performance_obligation(
            contract, "Hardware", Decimal("300000000"),
            PSAK72PerformanceObligationTiming.AT_A_POINT_IN_TIME,
        )
        result = validator.validate_contract(contract)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK72ComplianceLevel.FULL

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "five_steps" in summary
        assert len(summary["five_steps"]) == 5
        assert "contract_validity_criteria" in summary
        assert "disclosures" in summary


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
        assert PSAK72.is_control_transferred(date(2020, 1, 1)) is True  # any date


# ============================================================================
# Singleton accessor test
# ============================================================================
def test_get_psak72_validator_singleton():
    v1 = get_psak72_validator()
    v2 = get_psak72_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK72Validator)