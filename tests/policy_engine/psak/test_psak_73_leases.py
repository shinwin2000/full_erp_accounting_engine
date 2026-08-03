# test_psak_73_leases.py
# Comprehensive tests for policy_engine/psak/psak_73_leases.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from policy_engine.psak.psak_73_leases import (
    PSAK73,
    LeaseModificationError,
    PSAK73ComplianceLevel,
    PSAK73Error,
    PSAK73IncrementalBorrowingRateSource,
    PSAK73LeaseContract,
    PSAK73LeaseLiability,
    PSAK73LeaseModification,
    PSAK73LeasePayment,
    PSAK73LeaseService,
    PSAK73LeaseType,
    PSAK73LowValueAssetExemption,
    PSAK73ModificationType,
    PSAK73PaymentTiming,
    PSAK73RightOfUseAsset,
    PSAK73Rules,
    PSAK73ShortTermLeaseExemption,
    PSAK73ValidationResult,
    PSAK73Validator,
    _calculate_lease_liability_compat,
    _calculate_right_of_use_asset_compat,
    # import compat functions directly for explicit testing
    _create_lease_compat,
    _record_amortization_compat,
    _record_lease_payment_compat,
    _validate_lease_compliance_compat,
    get_psak73_validator,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def fixed_now():
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("policy_engine.psak.psak_73_leases.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_lease_payment():
    return PSAK73LeasePayment(
        amount=Decimal("120000000"),
        due_date=datetime(2026, 12, 31, tzinfo=UTC),
        is_variable=False,
        variable_basis="",
    )


@pytest.fixture
def sample_lease_contract(fixed_now):
    payments = []
    for year in range(1, 6):
        due_date = datetime(2026 + year - 1, 12, 31, tzinfo=UTC)
        payments.append(PSAK73LeasePayment(amount=Decimal("120000000"), due_date=due_date))
    return PSAK73LeaseContract(
        contract_id=uuid4(),
        contract_number="LEASE-001",
        asset_name="Mesin Produksi",
        lessor_name="PT Sewa Guna",
        commencement_date=fixed_now,
        lease_term_years=5,
        payments=payments,
        discount_rate=Decimal("8"),
        discount_rate_source=PSAK73IncrementalBorrowingRateSource.ESTIMATED,
        initial_direct_costs=Decimal("5000000"),
        lease_incentives_received=Decimal("1000000"),
        restoration_cost_estimate=Decimal("2000000"),
        payment_timing=PSAK73PaymentTiming.IN_ARREARS,
        short_term_exemption=PSAK73ShortTermLeaseExemption.NOT_EXEMPT,
        low_value_exemption=PSAK73LowValueAssetExemption.NOT_EXEMPT,
    )


@pytest.fixture
def sample_liability():
    return PSAK73LeaseLiability(
        liability_id=uuid4(),
        contract_id=uuid4(),
        initial_measurement=Decimal("500000000"),
        outstanding_balance=Decimal("400000000"),
        interest_expense_ytd=Decimal("0"),
        principal_paid_ytd=Decimal("0"),
        last_payment_date=None,
    )


@pytest.fixture
def sample_rou_asset():
    return PSAK73RightOfUseAsset(
        asset_id=uuid4(),
        contract_id=uuid4(),
        initial_measurement=Decimal("520000000"),
        accumulated_depreciation=Decimal("0"),
        accumulated_impairment=Decimal("0"),
        useful_life_years=5,
        depreciation_method="straight_line",
    )


@pytest.fixture
def sample_validation_result():
    return PSAK73ValidationResult(
        is_compliant=True,
        compliance_level=PSAK73ComplianceLevel.FULL,
        errors=[],
        warnings=[],
    )


@pytest.fixture
def validator():
    return PSAK73Validator()


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_lease_type(self):
        assert PSAK73LeaseType.FINANCE.value == "pembiayaan"
        assert PSAK73LeaseType.OPERATING.value == "operasi"

    def test_payment_timing(self):
        assert PSAK73PaymentTiming.IN_ADVANCE.value == "di_muka"
        assert PSAK73PaymentTiming.IN_ARREARS.value == "di_belakang"

    def test_incremental_borrowing_rate_source(self):
        assert PSAK73IncrementalBorrowingRateSource.IMPLICIT_RATE_KNOWN.value == "suku_bunga_implisit_diketahui"
        assert PSAK73IncrementalBorrowingRateSource.ESTIMATED.value == "estimasi"

    def test_modification_type(self):
        assert PSAK73ModificationType.EXTENSION.value == "perpanjangan"
        assert PSAK73ModificationType.TERMINATION.value == "penghentian_sebagian"

    def test_short_term_exemption(self):
        assert PSAK73ShortTermLeaseExemption.EXEMPT.value == "dikecualikan"
        assert PSAK73ShortTermLeaseExemption.NOT_EXEMPT.value == "tidak_dikecualikan"

    def test_low_value_exemption(self):
        assert PSAK73LowValueAssetExemption.EXEMPT.value == "dikecualikan"
        assert PSAK73LowValueAssetExemption.NOT_EXEMPT.value == "tidak_dikecualikan"

    def test_compliance_level(self):
        assert PSAK73ComplianceLevel.FULL.value == "penuh"
        assert PSAK73ComplianceLevel.SUBSTANTIAL.value == "substansial"
        assert PSAK73ComplianceLevel.PARTIAL.value == "sebagian"
        assert PSAK73ComplianceLevel.NON_COMPLIANT.value == "tidak_patuh"


# -------------------- Tests for Exceptions --------------------
class TestExceptions:
    def test_psak73_error(self):
        with pytest.raises(PSAK73Error):
            raise PSAK73Error("error")

    def test_lease_modification_error(self):
        with pytest.raises(LeaseModificationError):
            raise LeaseModificationError("modification error")


# -------------------- Tests for Data Classes --------------------
class TestPSAK73LeasePayment:
    def test_construction(self, sample_lease_payment):
        assert sample_lease_payment.amount == Decimal("120000000")
        assert sample_lease_payment.due_date == datetime(2026, 12, 31, tzinfo=UTC)
        assert sample_lease_payment.is_variable is False

    def test_to_dict(self, sample_lease_payment):
        d = sample_lease_payment.to_dict()
        assert d["amount"] == "120000000"
        assert d["due_date"] == "2026-12-31T00:00:00+00:00"
        assert d["is_variable"] is False


class TestPSAK73LeaseContract:
    def test_construction(self, sample_lease_contract):
        assert sample_lease_contract.contract_number == "LEASE-001"
        assert sample_lease_contract.lease_term_years == 5
        assert len(sample_lease_contract.payments) == 5

    def test_total_payments_undiscounted(self, sample_lease_contract):
        total = sample_lease_contract.total_payments_undiscounted()
        assert total == Decimal("600000000")  # 5 * 120,000,000

    def test_present_value_of_lease_payments(self, sample_lease_contract):
        pv = sample_lease_contract.present_value_of_lease_payments()
        # Expected approximate PV: 120M * annuity factor at 8% for 5 years (in arrears)
        # Annuity factor = (1 - (1+0.08)^-5)/0.08 = 3.99271, so PV ≈ 479,125,000
        assert pv == Decimal("479125000")  # rounded to nearest integer

    def test_present_value_with_advance_payments(self, sample_lease_contract):
        # Change timing to IN_ADVANCE
        sample_lease_contract.payment_timing = PSAK73PaymentTiming.IN_ADVANCE
        pv = sample_lease_contract.present_value_of_lease_payments()
        # For advance, first payment at time 0, so PV = payment + payment*(1+i)^-1 + ...
        # Approx: 120M + 120M/1.08 + 120M/1.08^2 + ... = 120M * (1 + 3.3121) = 517,452,000
        assert pv == Decimal("517452000")

    def test_to_dict(self, sample_lease_contract):
        d = sample_lease_contract.to_dict()
        assert d["contract_id"] == str(sample_lease_contract.contract_id)
        assert d["contract_number"] == "LEASE-001"
        assert d["lease_term_years"] == 5
        assert len(d["payments"]) == 5
        assert d["pv_payments"] == str(sample_lease_contract.present_value_of_lease_payments())


class TestPSAK73RightOfUseAsset:
    def test_construction(self, sample_rou_asset):
        assert sample_rou_asset.initial_measurement == Decimal("520000000")

    def test_carrying_amount(self, sample_rou_asset):
        assert sample_rou_asset.carrying_amount() == Decimal("520000000")
        # With depreciation
        sample_rou_asset.accumulated_depreciation = Decimal("100000000")
        assert sample_rou_asset.carrying_amount() == Decimal("420000000")

    def test_annual_depreciation(self, sample_rou_asset):
        dep = sample_rou_asset.annual_depreciation(lease_term_years=5)
        assert dep == Decimal("104000000")  # 520,000,000 / 5
        # With useful life override
        sample_rou_asset.useful_life_years = 10
        dep2 = sample_rou_asset.annual_depreciation(lease_term_years=5)
        assert dep2 == Decimal("52000000")  # 520M / 10

    def test_annual_depreciation_zero_term(self, sample_rou_asset):
        dep = sample_rou_asset.annual_depreciation(lease_term_years=0)
        assert dep == Decimal(0)

    def test_to_dict(self, sample_rou_asset):
        d = sample_rou_asset.to_dict()
        assert d["asset_id"] == str(sample_rou_asset.asset_id)
        assert d["initial"] == "520000000"
        assert d["carrying"] == "520000000"


class TestPSAK73LeaseLiability:
    def test_construction(self, sample_liability):
        assert sample_liability.outstanding_balance == Decimal("400000000")

    def test_to_dict(self, sample_liability):
        d = sample_liability.to_dict()
        assert d["liability_id"] == str(sample_liability.liability_id)
        assert d["initial"] == "500000000"
        assert d["outstanding"] == "400000000"


class TestPSAK73LeaseModification:
    def test_construction(self, fixed_now):
        mod = PSAK73LeaseModification(
            modification_id=uuid4(),
            contract_id=uuid4(),
            modification_type=PSAK73ModificationType.EXTENSION,
            effective_date=fixed_now,
            old_pv_payments=Decimal("400000000"),
            new_pv_payments=Decimal("500000000"),
            adjustment_to_rou_asset=Decimal("100000000"),
            adjustment_to_lease_liability=Decimal("100000000"),
            notes="Extension",
        )
        assert mod.modification_type == PSAK73ModificationType.EXTENSION
        assert mod.adjustment_to_rou_asset == Decimal("100000000")

    def test_to_dict(self, fixed_now):
        mod = PSAK73LeaseModification(
            modification_id=uuid4(),
            contract_id=uuid4(),
            modification_type=PSAK73ModificationType.EXTENSION,
            effective_date=fixed_now,
            old_pv_payments=Decimal("400000000"),
            new_pv_payments=Decimal("500000000"),
            adjustment_to_rou_asset=Decimal("100000000"),
            adjustment_to_lease_liability=Decimal("100000000"),
            notes="Extension",
        )
        d = mod.to_dict()
        assert d["type"] == "perpanjangan"
        assert d["pv_change"] == "100000000"
        assert d["rou_asset_adjustment"] == "100000000"


class TestPSAK73ValidationResult:
    def test_initialization(self):
        result = PSAK73ValidationResult(
            is_compliant=True,
            compliance_level=PSAK73ComplianceLevel.FULL,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK73ComplianceLevel.FULL
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK73ValidationResult(is_compliant=True, compliance_level=PSAK73ComplianceLevel.FULL)
        result.add_error("Error message")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK73ComplianceLevel.NON_COMPLIANT
        assert "Error message" in result.errors

    def test_add_warning(self):
        result = PSAK73ValidationResult(is_compliant=True, compliance_level=PSAK73ComplianceLevel.FULL)
        result.add_warning("Warning message")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK73ComplianceLevel.SUBSTANTIAL
        assert "Warning message" in result.warnings

    def test_to_dict(self):
        result = PSAK73ValidationResult(
            is_compliant=False,
            compliance_level=PSAK73ComplianceLevel.NON_COMPLIANT,
            errors=["e1"],
            warnings=["w1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]
        assert "hash" in d


# -------------------- Tests for PSAK73LeaseService --------------------
class TestPSAK73LeaseService:
    def test_apply_exemption(self):
        short, low = PSAK73LeaseService.apply_exemption(lease_term_years=1, asset_value=Decimal("1000"))
        assert short == PSAK73ShortTermLeaseExemption.EXEMPT
        assert low == PSAK73LowValueAssetExemption.EXEMPT
        # Not exempt
        short2, low2 = PSAK73LeaseService.apply_exemption(lease_term_years=2, asset_value=Decimal("10000"))
        assert short2 == PSAK73ShortTermLeaseExemption.NOT_EXEMPT
        assert low2 == PSAK73LowValueAssetExemption.NOT_EXEMPT

    def test_allocate_lease_payment_arrears(self):
        interest, principal = PSAK73LeaseService.allocate_lease_payment(
            outstanding_liability=Decimal("500000000"),
            annual_payment=Decimal("120000000"),
            discount_rate=Decimal("8"),
            payment_timing=PSAK73PaymentTiming.IN_ARREARS,
        )
        assert interest == Decimal("40000000")  # 500M * 8%
        assert principal == Decimal("80000000")  # 120M - 40M

    def test_allocate_lease_payment_advance(self):
        interest, principal = PSAK73LeaseService.allocate_lease_payment(
            outstanding_liability=Decimal("500000000"),
            annual_payment=Decimal("120000000"),
            discount_rate=Decimal("8"),
            payment_timing=PSAK73PaymentTiming.IN_ADVANCE,
        )
        assert interest == Decimal(0)
        assert principal == Decimal("120000000")

    def test_calculate_right_of_use_asset(self):
        rou = PSAK73LeaseService.calculate_right_of_use_asset(
            pv_lease_payments=Decimal("479125000"),
            initial_direct_costs=Decimal("5000000"),
            lease_incentives=Decimal("1000000"),
            restoration_cost=Decimal("2000000"),
        )
        assert rou == Decimal("485125000")  # 479,125,000 + 5,000,000 - 1,000,000 + 2,000,000

    def test_compute_modified_pv(self):
        original = [
            PSAK73LeasePayment(amount=Decimal("120000000"), due_date=datetime(2026, 12, 31, tzinfo=UTC)),
            PSAK73LeasePayment(amount=Decimal("120000000"), due_date=datetime(2027, 12, 31, tzinfo=UTC)),
        ]
        new = [
            PSAK73LeasePayment(amount=Decimal("100000000"), due_date=datetime(2026, 12, 31, tzinfo=UTC)),
            PSAK73LeasePayment(amount=Decimal("100000000"), due_date=datetime(2027, 12, 31, tzinfo=UTC)),
        ]
        old_pv, new_pv = PSAK73LeaseService.compute_modified_pv(
            original, new, Decimal("8"), PSAK73PaymentTiming.IN_ARREARS
        )
        assert old_pv > new_pv


# -------------------- Tests for PSAK73Rules --------------------
class TestPSAK73Rules:
    def test_validate_lease_contract_valid(self, sample_lease_contract):
        result = PSAK73Rules.validate_lease_contract(sample_lease_contract)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK73ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_lease_contract_invalid_term(self, sample_lease_contract):
        sample_lease_contract.lease_term_years = 0
        result = PSAK73Rules.validate_lease_contract(sample_lease_contract)
        assert result.is_compliant is False
        assert "Masa sewa harus positif" in result.errors

    def test_validate_lease_contract_negative_discount(self, sample_lease_contract):
        sample_lease_contract.discount_rate = Decimal("-5")
        result = PSAK73Rules.validate_lease_contract(sample_lease_contract)
        assert result.is_compliant is False
        assert "Tingkat diskonto tidak boleh negatif" in result.errors

    def test_validate_lease_contract_no_payments(self, sample_lease_contract):
        sample_lease_contract.payments = []
        result = PSAK73Rules.validate_lease_contract(sample_lease_contract)
        assert result.is_compliant is False
        assert "Setidaknya satu pembayaran sewa harus ada" in result.errors

    def test_validate_lease_contract_short_term_exemption_mismatch(self, sample_lease_contract):
        sample_lease_contract.short_term_exemption = PSAK73ShortTermLeaseExemption.EXEMPT
        sample_lease_contract.lease_term_years = 2
        result = PSAK73Rules.validate_lease_contract(sample_lease_contract)
        assert result.is_compliant is False
        assert "pengecualian" in result.errors[0].lower()

    def test_validate_modification_valid(self):
        mod = PSAK73LeaseModification(
            modification_id=uuid4(),
            contract_id=uuid4(),
            modification_type=PSAK73ModificationType.EXTENSION,
            effective_date=datetime.now(UTC),
            old_pv_payments=Decimal("400000000"),
            new_pv_payments=Decimal("500000000"),
            adjustment_to_rou_asset=Decimal("100000000"),
            adjustment_to_lease_liability=Decimal("-100000000"),  # Should be consistent
            notes="",
        )
        PSAK73Rules.validate_modification(mod)
        # adjustment_to_rou_asset + adjustment_to_lease_liability should be near 0, but here it's 100M + (-100M) = 0, so valid
        # But we need to create a consistent one: rou adjustment = 100M, liability adjustment = -100M? Actually the rule checks absolute sum <= 1
        # So we set them both +100M to trigger error.
        mod.adjustment_to_rou_asset = Decimal("100000000")
        mod.adjustment_to_lease_liability = Decimal("100000000")
        result2 = PSAK73Rules.validate_modification(mod)
        assert result2.is_compliant is False
        assert "tidak konsisten" in result2.errors[0]


# -------------------- Tests for PSAK73Validator --------------------
class TestPSAK73Validator:
    def test_create_lease_contract(self, validator, fixed_now):
        contract = validator.create_lease_contract(
            contract_number="LEASE-002",
            asset_name="Truck",
            lessor_name="PT Truck Leasing",
            commencement_date=fixed_now,
            lease_term_years=3,
            annual_payment=Decimal("150000000"),
            discount_rate=Decimal("9"),
            payment_timing=PSAK73PaymentTiming.IN_ADVANCE,
            initial_direct_costs=Decimal("2000000"),
            lease_incentives=Decimal("500000"),
            restoration_cost=Decimal("1000000"),
            asset_value_for_exemption=Decimal("6000"),
        )
        assert contract.contract_number == "LEASE-002"
        assert contract.lease_term_years == 3
        assert len(contract.payments) == 3
        assert contract.short_term_exemption == PSAK73ShortTermLeaseExemption.NOT_EXEMPT
        assert contract.low_value_exemption == PSAK73LowValueAssetExemption.NOT_EXEMPT  # 6000 > 5000
        # With low value
        contract2 = validator.create_lease_contract(
            contract_number="LOW-VALUE",
            asset_name="Laptop",
            lessor_name="Leasing",
            commencement_date=fixed_now,
            lease_term_years=1,
            annual_payment=Decimal("1000000"),
            discount_rate=Decimal("5"),
            asset_value_for_exemption=Decimal("4000"),
        )
        assert contract2.low_value_exemption == PSAK73LowValueAssetExemption.EXEMPT
        assert contract2.short_term_exemption == PSAK73ShortTermLeaseExemption.EXEMPT

    def test_compute_lease_liability(self, validator, sample_lease_contract):
        liability = validator.compute_lease_liability(sample_lease_contract)
        assert liability.contract_id == sample_lease_contract.contract_id
        pv = sample_lease_contract.present_value_of_lease_payments()
        assert liability.initial_measurement == pv
        assert liability.outstanding_balance == pv

    def test_compute_right_of_use_asset(self, validator, sample_lease_contract):
        rou = validator.compute_right_of_use_asset(sample_lease_contract)
        assert rou.contract_id == sample_lease_contract.contract_id
        pv = sample_lease_contract.present_value_of_lease_payments()
        expected_rou = pv + sample_lease_contract.initial_direct_costs - sample_lease_contract.lease_incentives_received + sample_lease_contract.restoration_cost_estimate
        assert rou.initial_measurement == expected_rou

    def test_record_annual_payment_arrears(self, validator, sample_lease_contract, sample_liability):
        liability = sample_liability
        liability.outstanding_balance = Decimal("479125000")  # PV
        payment_date = datetime(2026, 12, 31, tzinfo=UTC)
        new_liability, interest, principal = validator.record_annual_payment(
            liability, sample_lease_contract, payment_date
        )
        # interest = 8% of outstanding = 38,330,000
        # principal = 120,000,000 - interest = 81,670,000
        # new balance = 479,125,000 - 81,670,000 = 397,455,000
        assert interest == Decimal("38330000")
        assert principal == Decimal("81670000")
        assert new_liability.outstanding_balance == Decimal("397455000")
        assert new_liability.interest_expense_ytd == Decimal("38330000")
        assert new_liability.principal_paid_ytd == Decimal("81670000")
        assert new_liability.last_payment_date == payment_date

    def test_record_annual_payment_advance(self, validator, sample_lease_contract):
        sample_lease_contract.payment_timing = PSAK73PaymentTiming.IN_ADVANCE
        liability = PSAK73LeaseLiability(
            liability_id=uuid4(),
            contract_id=sample_lease_contract.contract_id,
            initial_measurement=Decimal("500000000"),
            outstanding_balance=Decimal("500000000"),
        )
        payment_date = datetime(2026, 1, 1, tzinfo=UTC)
        new_liability, interest, principal = validator.record_annual_payment(
            liability, sample_lease_contract, payment_date
        )
        assert interest == Decimal(0)
        assert principal == Decimal("120000000")
        assert new_liability.outstanding_balance == Decimal("380000000")

    def test_record_depreciation(self, validator, sample_rou_asset):
        rou = validator.record_depreciation(sample_rou_asset, lease_term_years=5)
        expected_dep = sample_rou_asset.initial_measurement / 5
        assert rou.accumulated_depreciation == expected_dep
        assert rou.carrying_amount() == sample_rou_asset.initial_measurement - expected_dep

    def test_modify_lease_extension(self, validator, sample_lease_contract, sample_liability, sample_rou_asset, fixed_now):
        # Create new payments: extend by 1 year
        new_payments = [*sample_lease_contract.payments, PSAK73LeasePayment(amount=Decimal("120000000"), due_date=fixed_now + timedelta(days=365 * 5))]
        new_contract, new_liability, new_rou, modification = validator.modify_lease(
            contract=sample_lease_contract,
            liability=sample_liability,
            rou_asset=sample_rou_asset,
            new_payments=new_payments,
            modification_type=PSAK73ModificationType.EXTENSION,
            effective_date=fixed_now + timedelta(days=365*3),
            new_discount_rate=Decimal("7"),
            notes="Extended",
        )
        assert new_contract.lease_term_years == len(new_payments)
        assert modification.modification_type == PSAK73ModificationType.EXTENSION
        # Check that liability and ROU asset adjusted
        # Since new PV may be different, we can't assert exact values, but we can check that they changed
        assert new_liability.outstanding_balance != sample_liability.outstanding_balance
        assert new_rou.initial_measurement != sample_rou_asset.initial_measurement

    def test_validate_contract(self, validator, sample_lease_contract):
        result = validator.validate_contract(sample_lease_contract)
        assert result.is_compliant is True
        # Make invalid
        sample_lease_contract.lease_term_years = 0
        result2 = validator.validate_contract(sample_lease_contract)
        assert result2.is_compliant is False

    def test_validate_modification(self, validator):
        mod = PSAK73LeaseModification(
            modification_id=uuid4(),
            contract_id=uuid4(),
            modification_type=PSAK73ModificationType.EXTENSION,
            effective_date=datetime.now(UTC),
            old_pv_payments=Decimal("400000000"),
            new_pv_payments=Decimal("500000000"),
            adjustment_to_rou_asset=Decimal("100000000"),
            adjustment_to_lease_liability=Decimal("100000000"),
        )
        result = validator.validate_modification(mod)
        assert result.is_compliant is False  # inconsistent

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "lessee" in summary
        assert "disclosures" in summary
        assert len(summary["disclosures"]) >= 4


# -------------------- Tests for Compatibility Methods (Orchestration Bridge) --------------------
class TestCompatibilityMethods:
    """Tests for the compatibility methods added to PSAK73Validator (orchestration bridge)."""

    def test_create_lease_compat(self, validator, fixed_now):
        asset_id = uuid4()
        lease = validator.create_lease(
            lease_number="COMPAT-002",
            asset_id=asset_id,
            asset_name="Compat Asset 2",
            lessor_name="Compat Lessor 2",
            commencement_date=fixed_now,
            lease_term_years=2,
            annual_payment=Decimal("50000000"),
            discount_rate=Decimal("7"),
            currency="USD",
            payment_timing=PSAK73PaymentTiming.IN_ADVANCE,
        )
        assert lease.contract_number == "COMPAT-002"
        assert lease.lease_term_years == 2
        assert len(lease.payments) == 2
        # Check that first payment is in advance
        assert lease.payment_timing == PSAK73PaymentTiming.IN_ADVANCE

    def test_calculate_right_of_use_asset_compat(self, validator, sample_lease_contract):
        rou = validator.calculate_right_of_use_asset(
            sample_lease_contract,
            initial_direct_costs=Decimal("2000000"),
            lease_incentives=Decimal("500000")
        )
        assert sample_lease_contract.initial_direct_costs == Decimal("2000000")
        assert sample_lease_contract.lease_incentives_received == Decimal("500000")
        pv = sample_lease_contract.present_value_of_lease_payments()
        expected = pv + Decimal("2000000") - Decimal("500000") + sample_lease_contract.restoration_cost_estimate
        assert rou.initial_measurement == expected

    def test_calculate_lease_liability_compat(self, validator, sample_lease_contract):
        liability = validator.calculate_lease_liability(sample_lease_contract)
        assert isinstance(liability, PSAK73LeaseLiability)
        assert liability.contract_id == sample_lease_contract.contract_id
        pv = sample_lease_contract.present_value_of_lease_payments()
        assert liability.initial_measurement == pv
        assert liability.outstanding_balance == pv

    def test_record_lease_payment_compat_with_contract(self, validator, sample_lease_contract, sample_liability):
        payment_date = datetime(2026, 12, 31, tzinfo=UTC)
        new_liability, interest, _principal = validator.record_lease_payment(
            sample_liability, sample_lease_contract, payment_date
        )
        assert isinstance(new_liability, PSAK73LeaseLiability)
        # Check that interest is calculated based on contract discount rate
        expected_interest = (sample_liability.outstanding_balance * (sample_lease_contract.discount_rate / 100)).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert interest == expected_interest

    def test_record_lease_payment_compat_with_amount(self, validator, sample_liability):
        # Test the legacy mode: (liability, payment_amount, discount_rate)
        new_liability, interest, principal = validator.record_lease_payment(
            sample_liability, payment_amount=Decimal("100000000"), discount_rate=Decimal("8")
        )
        expected_interest = (sample_liability.outstanding_balance * Decimal("0.08")).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert interest == expected_interest
        expected_principal = min(Decimal("100000000") - expected_interest, sample_liability.outstanding_balance)
        assert principal == expected_principal
        assert new_liability.outstanding_balance == sample_liability.outstanding_balance - principal

    def test_record_amortization_compat(self, validator, sample_rou_asset):
        rou = validator.record_amortization(sample_rou_asset, lease_term_years=3)
        assert rou.accumulated_depreciation == sample_rou_asset.initial_measurement / 3
        # Without lease_term_years, uses asset.useful_life_years
        sample_rou_asset.useful_life_years = 4
        rou2 = validator.record_amortization(sample_rou_asset)
        assert rou2.accumulated_depreciation == sample_rou_asset.initial_measurement / 4

    def test_validate_lease_compliance_compat(self, validator, sample_lease_contract):
        result = validator.validate_lease_compliance(sample_lease_contract)
        assert isinstance(result, PSAK73ValidationResult)
        # Should be compliant
        assert result.is_compliant is True

    # --- Explicit direct calls to the compat functions to ensure they are covered ---
    def test_create_lease_compat_direct(self, validator, fixed_now):
        # Call the function directly (imported)
        asset_id = uuid4()
        lease = _create_lease_compat(
            validator,
            lease_number="DIRECT-001",
            asset_id=asset_id,
            asset_name="Direct Asset",
            lessor_name="Direct Lessor",
            commencement_date=fixed_now,
            lease_term_years=3,
            annual_payment=Decimal("60000000"),
            discount_rate=Decimal("8"),
            currency="IDR",
            payment_timing=PSAK73PaymentTiming.IN_ARREARS,
        )
        assert lease.contract_number == "DIRECT-001"
        assert lease.lease_term_years == 3
        assert len(lease.payments) == 3

    def test_calculate_right_of_use_asset_compat_direct(self, validator, sample_lease_contract):
        rou = _calculate_right_of_use_asset_compat(
            validator,
            sample_lease_contract,
            initial_direct_costs=Decimal("3000000"),
            lease_incentives=Decimal("500000")
        )
        # This modifies the contract in place, so check values
        assert sample_lease_contract.initial_direct_costs == Decimal("3000000")
        assert sample_lease_contract.lease_incentives_received == Decimal("500000")
        pv = sample_lease_contract.present_value_of_lease_payments()
        expected = pv + Decimal("3000000") - Decimal("500000") + sample_lease_contract.restoration_cost_estimate
        assert rou.initial_measurement == expected

    def test_calculate_lease_liability_compat_direct(self, validator, sample_lease_contract):
        liability = _calculate_lease_liability_compat(validator, sample_lease_contract)
        assert isinstance(liability, PSAK73LeaseLiability)
        assert liability.contract_id == sample_lease_contract.contract_id
        pv = sample_lease_contract.present_value_of_lease_payments()
        assert liability.initial_measurement == pv
        assert liability.outstanding_balance == pv

    def test_record_lease_payment_compat_direct_with_contract(self, validator, sample_lease_contract, sample_liability):
        payment_date = datetime(2026, 12, 31, tzinfo=UTC)
        # Make the liability balance match the contract's PV for more realistic test
        sample_liability.outstanding_balance = sample_lease_contract.present_value_of_lease_payments()
        new_liability, interest, _principal = _record_lease_payment_compat(
            validator, sample_liability, sample_lease_contract, payment_date
        )
        assert isinstance(new_liability, PSAK73LeaseLiability)
        expected_interest = (sample_liability.outstanding_balance * (sample_lease_contract.discount_rate / 100)).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert interest == expected_interest

    def test_record_lease_payment_compat_direct_with_amount(self, validator, sample_liability):
        # Direct call with amount and discount_rate
        new_liability, interest, principal = _record_lease_payment_compat(
            validator, sample_liability, payment_amount=Decimal("90000000"), discount_rate=Decimal("8")
        )
        expected_interest = (sample_liability.outstanding_balance * Decimal("0.08")).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert interest == expected_interest
        expected_principal = min(Decimal("90000000") - expected_interest, sample_liability.outstanding_balance)
        assert principal == expected_principal
        assert new_liability.outstanding_balance == sample_liability.outstanding_balance - principal

    def test_record_amortization_compat_direct(self, validator, sample_rou_asset):
        rou = _record_amortization_compat(validator, sample_rou_asset, lease_term_years=4)
        assert rou.accumulated_depreciation == sample_rou_asset.initial_measurement / 4
        # Without term, uses useful_life_years
        sample_rou_asset.useful_life_years = 5
        rou2 = _record_amortization_compat(validator, sample_rou_asset)
        assert rou2.accumulated_depreciation == sample_rou_asset.initial_measurement / 5

    def test_validate_lease_compliance_compat_direct(self, validator, sample_lease_contract):
        result = _validate_lease_compliance_compat(validator, sample_lease_contract)
        assert isinstance(result, PSAK73ValidationResult)
        assert result.is_compliant is True
        # Test with invalid contract
        sample_lease_contract.lease_term_years = 0
        result2 = _validate_lease_compliance_compat(validator, sample_lease_contract)
        assert result2.is_compliant is False


# -------------------- Tests for PSAK73 Class --------------------
class TestPSAK73:
    def test_recognize_lease(self, fixed_now):
        with patch("policy_engine.psak.psak_73_leases.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.utcnow.return_value = fixed_now
            result = PSAK73.recognize_lease(
                payment=Decimal("120000000"),
                discount_rate=Decimal("0.08"),  # 8% as decimal
                lease_term=5
            )
            # Should return object with right_of_use_asset and lease_liability
            assert hasattr(result, "right_of_use_asset")
            assert hasattr(result, "lease_liability")
            # Check values approximately
            assert result.lease_liability == Decimal("479125000")  # PV of 5 payments at 8%
            # ROU asset should be same (no initial costs in this call)
            assert result.right_of_use_asset == Decimal("479125000")


# -------------------- Tests for Singleton Accessor --------------------
def test_get_psak73_validator():
    v1 = get_psak73_validator()
    v2 = get_psak73_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK73Validator)
