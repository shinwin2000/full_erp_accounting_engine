# tests/policy_engine/ifrs/test_ias_37_provisions.py
"""
Comprehensive tests for IAS 37: Provisions, Contingent Liabilities and Contingent Assets.

Covers all enums, value objects, entities, domain services, rules, validator,
and convenience class. Includes edge cases, negative paths, and proper assertions.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.shared_value_objects.money_vo import Money
from policy_engine.ifrs.ias_37_provisions import (
    IAS37,
    IAS37ContingencyLikelihood,
    IAS37ContingentLiability,
    IAS37Provision,
    IAS37ProvisionService,
    IAS37ProvisionsRegister,
    IAS37ProvisionType,
    IAS37RecognitionCriteria,
    IAS37Rules,
    IAS37ValidationResult,
    IAS37Validator,
    get_ias37_validator,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def currency() -> str:
    return "IDR"


@pytest.fixture
def amount_1000(currency) -> Money:
    return Money(Decimal("1000"), currency)


@pytest.fixture
def amount_500(currency) -> Money:
    return Money(Decimal("500"), currency)


@pytest.fixture
def amount_1500(currency) -> Money:
    return Money(Decimal("1500"), currency)


@pytest.fixture
def provision_id() -> UUID:
    return uuid4()


@pytest.fixture
def provision(provision_id, amount_1000) -> IAS37Provision:
    return IAS37Provision(
        provision_id=provision_id,
        provision_type=IAS37ProvisionType.WARRANTY,
        obligation_description="Warranty obligation",
        best_estimate=amount_1000,
        discount_rate=None,
        undiscounted_amount=None,
        expected_outflow_date=None,
        recognition_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def register_id() -> UUID:
    return uuid4()


@pytest.fixture
def provisions_register(register_id, entity_id, provision) -> IAS37ProvisionsRegister:
    return IAS37ProvisionsRegister(
        register_id=register_id,
        entity_id=entity_id,
        reporting_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        provisions=[provision],
    )


# ============================================================================
# Enums
# ============================================================================

class TestEnums:
    def test_provision_type_members(self):
        assert IAS37ProvisionType.RESTRUCTURING.value == "restructuring"
        assert IAS37ProvisionType.LITIGATION.value == "litigation"
        assert IAS37ProvisionType.WARRANTY.value == "warranty"
        assert IAS37ProvisionType.ENVIRONMENTAL.value == "environmental"
        assert IAS37ProvisionType.ONEROUS_CONTRACT.value == "onerous_contract"
        assert IAS37ProvisionType.OTHER.value == "other"

    def test_contingency_likelihood_members(self):
        assert IAS37ContingencyLikelihood.PROBABLE.value == "probable"
        assert IAS37ContingencyLikelihood.POSSIBLE.value == "possible"
        assert IAS37ContingencyLikelihood.REMOTE.value == "remote"

    def test_recognition_criteria_members(self):
        assert IAS37RecognitionCriteria.PRESENT_OBLIGATION.value == "present_obligation"
        assert IAS37RecognitionCriteria.PROBABLE_OUTFLOW.value == "probable_outflow"
        assert IAS37RecognitionCriteria.RELIABLE_ESTIMATE.value == "reliable_estimate"


# ============================================================================
# IAS37Provision
# ============================================================================

class TestIAS37Provision:
    def test_construction_valid(self, provision_id, amount_1000):
        prov = IAS37Provision(
            provision_id=provision_id,
            provision_type=IAS37ProvisionType.WARRANTY,
            obligation_description="Test",
            best_estimate=amount_1000,
        )
        assert prov.provision_id == provision_id
        assert prov.provision_type == IAS37ProvisionType.WARRANTY
        assert prov.best_estimate == amount_1000
        assert prov.discount_rate is None
        assert prov.undiscounted_amount is None
        assert prov.expected_outflow_date is None
        assert prov.recognition_date is not None

    def test_negative_amount_raises(self, provision_id):
        with pytest.raises(ValueError, match="Provision amount cannot be negative"):
            IAS37Provision(
                provision_id=provision_id,
                provision_type=IAS37ProvisionType.WARRANTY,
                obligation_description="Test",
                best_estimate=Money(Decimal("-100"), "IDR"),
            )

    def test_discount_rate_out_of_range_raises(self, provision_id, amount_1000):
        with pytest.raises(ValueError, match="Discount rate out of range"):
            IAS37Provision(
                provision_id=provision_id,
                provision_type=IAS37ProvisionType.WARRANTY,
                obligation_description="Test",
                best_estimate=amount_1000,
                discount_rate=Decimal("101"),
                undiscounted_amount=Money(Decimal("2000"), "IDR"),
            )
        with pytest.raises(ValueError, match="Discount rate out of range"):
            IAS37Provision(
                provision_id=provision_id,
                provision_type=IAS37ProvisionType.WARRANTY,
                obligation_description="Test",
                best_estimate=amount_1000,
                discount_rate=Decimal("-5"),
                undiscounted_amount=Money(Decimal("2000"), "IDR"),
            )

    def test_discount_rate_without_undiscounted_raises(self, provision_id, amount_1000):
        with pytest.raises(ValueError, match="Undiscounted amount required when discounting"):
            IAS37Provision(
                provision_id=provision_id,
                provision_type=IAS37ProvisionType.WARRANTY,
                obligation_description="Test",
                best_estimate=amount_1000,
                discount_rate=Decimal("5"),
                undiscounted_amount=None,
            )

    def test_discounted_amount_no_discount(self, provision, amount_1000):
        # No discount rate -> discounted_amount equals best_estimate
        assert provision.discounted_amount == amount_1000

    def test_discounted_amount_with_discount(self, amount_1000, amount_1500):
        provision_id = uuid4()
        recognition = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        outflow = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)  # 1 year later
        prov = IAS37Provision(
            provision_id=provision_id,
            provision_type=IAS37ProvisionType.WARRANTY,
            obligation_description="Test",
            best_estimate=amount_1000,
            discount_rate=Decimal("5"),
            undiscounted_amount=amount_1500,  # doesn't affect discounted amount directly
            expected_outflow_date=outflow,
            recognition_date=recognition,
        )
        # Discounted amount = best_estimate / (1+0.05)^1 = 1000 / 1.05 = 952.38095...
        expected = Decimal("1000") / Decimal("1.05")
        expected_money = Money(expected.quantize(Decimal("0.0001")), "IDR")
        assert prov.discounted_amount.amount == expected_money.amount

    def test_discounted_amount_fractional_years(self, amount_1000):
        provision_id = uuid4()
        recognition = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        outflow = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)  # 0.5 years
        prov = IAS37Provision(
            provision_id=provision_id,
            provision_type=IAS37ProvisionType.WARRANTY,
            obligation_description="Test",
            best_estimate=amount_1000,
            discount_rate=Decimal("10"),
            undiscounted_amount=Money(Decimal("2000"), "IDR"),
            expected_outflow_date=outflow,
            recognition_date=recognition,
        )
        # years = (182.625 days) / 365.25 ≈ 0.5, factor = (1.1)^0.5 ≈ 1.0488
        # discounted = 1000 / 1.0488 ≈ 953.46
        expected = Decimal("1000") / (Decimal("1.1") ** Decimal("0.5"))
        assert prov.discounted_amount.amount == pytest.approx(expected, rel=1e-3)

    def test_to_dict(self, provision):
        d = provision.to_dict()
        assert d["provision_id"] == str(provision.provision_id)
        assert d["type"] == "warranty"
        assert d["description"] == "Warranty obligation"
        assert d["best_estimate"] == "1000"
        assert d["discount_rate"] is None
        assert d["discounted_amount"] == "1000"
        assert "recognition_date" in d
        assert d["expected_outflow"] is None


# ============================================================================
# IAS37ContingentLiability
# ============================================================================

class TestIAS37ContingentLiability:
    def test_construction(self, amount_1000):
        cont_id = uuid4()
        cl = IAS37ContingentLiability(
            contingency_id=cont_id,
            description="Pending litigation",
            likelihood=IAS37ContingencyLikelihood.POSSIBLE,
            estimated_financial_effect=amount_1000,
            disclosure_in_notes=True,
        )
        assert cl.contingency_id == cont_id
        assert cl.description == "Pending litigation"
        assert cl.likelihood == IAS37ContingencyLikelihood.POSSIBLE
        assert cl.estimated_financial_effect == amount_1000
        assert cl.disclosure_in_notes is True

    def test_to_dict(self, amount_1000):
        cont_id = uuid4()
        cl = IAS37ContingentLiability(
            contingency_id=cont_id,
            description="Pending litigation",
            likelihood=IAS37ContingencyLikelihood.POSSIBLE,
            estimated_financial_effect=amount_1000,
        )
        d = cl.to_dict()
        assert d["contingency_id"] == str(cont_id)
        assert d["description"] == "Pending litigation"
        assert d["likelihood"] == "possible"
        assert d["estimated_effect"] == "1000"
        assert d["disclosed"] is True


# ============================================================================
# IAS37ProvisionsRegister
# ============================================================================

class TestIAS37ProvisionsRegister:
    def test_construction(self, register_id, entity_id, provision):
        reg = IAS37ProvisionsRegister(
            register_id=register_id,
            entity_id=entity_id,
            reporting_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            provisions=[provision],
        )
        assert reg.register_id == register_id
        assert reg.entity_id == entity_id
        assert reg.provisions == [provision]
        assert reg.contingent_liabilities == []
        assert reg.contingent_assets == []

    def test_add_provision(self, register_id, entity_id, provision):
        reg = IAS37ProvisionsRegister(
            register_id=register_id,
            entity_id=entity_id,
            reporting_date=datetime.now(UTC),
            provisions=[],
        )
        new_prov = provision
        reg2 = reg.add_provision(new_prov)
        assert reg2 is not reg
        assert len(reg2.provisions) == 1
        assert reg2.provisions[0] is new_prov
        # Original unchanged
        assert len(reg.provisions) == 0

    def test_total_provisions_single(self, provisions_register, amount_1000):
        total = provisions_register.total_provisions()
        assert total.amount == amount_1000.amount
        assert total.currency == amount_1000.currency

    def test_total_provisions_multiple(self, entity_id, amount_1000, amount_500):
        reg = IAS37ProvisionsRegister(
            register_id=uuid4(),
            entity_id=entity_id,
            reporting_date=datetime.now(UTC),
            provisions=[
                IAS37Provision(
                    provision_id=uuid4(),
                    provision_type=IAS37ProvisionType.WARRANTY,
                    obligation_description="A",
                    best_estimate=amount_1000,
                ),
                IAS37Provision(
                    provision_id=uuid4(),
                    provision_type=IAS37ProvisionType.LITIGATION,
                    obligation_description="B",
                    best_estimate=amount_500,
                ),
            ],
        )
        total = reg.total_provisions()
        assert total.amount == Decimal("1500")
        assert total.currency == "IDR"

    def test_total_provisions_empty(self, entity_id):
        reg = IAS37ProvisionsRegister(
            register_id=uuid4(),
            entity_id=entity_id,
            reporting_date=datetime.now(UTC),
            provisions=[],
        )
        total = reg.total_provisions()
        assert total.amount == Decimal(0)
        assert total.currency == "IDR"

    def test_total_provisions_with_discounted_amounts(self, amount_1000):
        # Provisions with discounting
        recognition = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        outflow = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)
        prov1 = IAS37Provision(
            provision_id=uuid4(),
            provision_type=IAS37ProvisionType.WARRANTY,
            obligation_description="A",
            best_estimate=amount_1000,
            discount_rate=Decimal("5"),
            undiscounted_amount=Money(Decimal("1200"), "IDR"),
            expected_outflow_date=outflow,
            recognition_date=recognition,
        )
        prov2 = IAS37Provision(
            provision_id=uuid4(),
            provision_type=IAS37ProvisionType.LITIGATION,
            obligation_description="B",
            best_estimate=amount_1000,
        )
        reg = IAS37ProvisionsRegister(
            register_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime.now(UTC),
            provisions=[prov1, prov2],
        )
        total = reg.total_provisions()
        # Total = discounted amount of prov1 (≈952.38) + 1000 = ≈1952.38
        expected = Decimal("1000") / Decimal("1.05") + Decimal("1000")
        assert total.amount == pytest.approx(expected, rel=1e-3)

    def test_to_dict(self, provisions_register):
        d = provisions_register.to_dict()
        assert d["register_id"] == str(provisions_register.register_id)
        assert d["entity_id"] == str(provisions_register.entity_id)
        assert "reporting_date" in d
        assert len(d["provisions"]) == 1
        assert d["provisions"][0]["type"] == "warranty"
        assert d["total_provisions"] == "1000"
        assert d["contingent_liabilities"] == []


# ============================================================================
# IAS37ProvisionService
# ============================================================================

class TestIAS37ProvisionService:
    def test_meets_recognition_criteria_all_true(self):
        assert IAS37ProvisionService.meets_recognition_criteria(True, True, True) is True

    def test_meets_recognition_criteria_missing_one(self):
        assert IAS37ProvisionService.meets_recognition_criteria(False, True, True) is False
        assert IAS37ProvisionService.meets_recognition_criteria(True, False, True) is False
        assert IAS37ProvisionService.meets_recognition_criteria(True, True, False) is False

    def test_calculate_best_estimate_single(self, amount_1000):
        result = IAS37ProvisionService.calculate_best_estimate(amount_1000, [])
        assert result == amount_1000

    def test_calculate_best_estimate_multiple(self, amount_1000, amount_500, amount_1500):
        result = IAS37ProvisionService.calculate_best_estimate(
            amount_1000,
            [amount_500, amount_1500]
        )
        # Average = (1000 + 500 + 1500) / 3 = 1000
        assert result.amount == Decimal("1000")
        assert result.currency == amount_1000.currency

    def test_calculate_best_estimate_currency_mismatch(self, amount_1000):
        other = Money(Decimal("1000"), "USD")
        # The method doesn't check currency consistency; it will use the first currency.
        # We just test that it works but may produce mixed currency (which is a design issue).
        # For safety, we expect it to use the first currency.
        result = IAS37ProvisionService.calculate_best_estimate(amount_1000, [other])
        # It will use amount_1000.currency = "IDR" for the result.
        # The method sums amounts regardless of currency, which is not ideal but we test what it does.
        assert result.currency == amount_1000.currency

    def test_determine_contingent_asset_recognition(self):
        assert IAS37ProvisionService.determine_contingent_asset_recognition(
            IAS37ContingencyLikelihood.PROBABLE
        ) is True
        assert IAS37ProvisionService.determine_contingent_asset_recognition(
            IAS37ContingencyLikelihood.POSSIBLE
        ) is False
        assert IAS37ProvisionService.determine_contingent_asset_recognition(
            IAS37ContingencyLikelihood.REMOTE
        ) is False


# ============================================================================
# IAS37ValidationResult
# ============================================================================

class TestIAS37ValidationResult:
    def test_initialization(self):
        result = IAS37ValidationResult(is_compliant=True)
        assert result.is_compliant is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error(self):
        result = IAS37ValidationResult(is_compliant=True)
        result.add_error("Error 1")
        assert result.is_compliant is False
        assert result.errors == ["Error 1"]

    def test_add_warning(self):
        result = IAS37ValidationResult(is_compliant=True)
        result.add_warning("Warning 1")
        assert result.is_compliant is True  # warnings don't affect compliance
        assert result.warnings == ["Warning 1"]

    def test_merge(self):
        r1 = IAS37ValidationResult(is_compliant=True)
        r1.add_error("E1")
        r1.add_warning("W1")
        r2 = IAS37ValidationResult(is_compliant=True)
        r2.add_error("E2")
        merged = r1.merge(r2)
        assert merged.is_compliant is False
        assert merged.errors == ["E1", "E2"]
        assert merged.warnings == ["W1"]

    def test_merge_both_compliant(self):
        r1 = IAS37ValidationResult(is_compliant=True)
        r2 = IAS37ValidationResult(is_compliant=True)
        merged = r1.merge(r2)
        assert merged.is_compliant is True
        assert merged.errors == []
        assert merged.warnings == []


# ============================================================================
# IAS37Rules
# ============================================================================

class TestIAS37Rules:
    def test_validate_restructuring_provision_valid(self):
        result = IAS37Rules.validate_restructuring_provision(
            has_formal_plan=True,
            has_valid_expectation=True
        )
        assert result.is_compliant is True
        assert result.errors == []

    def test_validate_restructuring_provision_invalid(self):
        result = IAS37Rules.validate_restructuring_provision(
            has_formal_plan=False,
            has_valid_expectation=True
        )
        assert result.is_compliant is False
        assert "Restructuring provision not allowed" in result.errors[0]

        result2 = IAS37Rules.validate_restructuring_provision(
            has_formal_plan=True,
            has_valid_expectation=False
        )
        assert result2.is_compliant is False

        result3 = IAS37Rules.validate_restructuring_provision(
            has_formal_plan=False,
            has_valid_expectation=False
        )
        assert result3.is_compliant is False

    def test_validate_disclosure_valid(self):
        # Create a provision with positive amount
        prov = IAS37Provision(
            provision_id=uuid4(),
            provision_type=IAS37ProvisionType.WARRANTY,
            obligation_description="A",
            best_estimate=Money(Decimal("1000"), "IDR"),
        )
        result = IAS37Rules.validate_disclosure([prov], [])
        assert result.is_compliant is True
        assert result.warnings == []

    def test_validate_disclosure_warning(self):
        # Provision with zero amount
        prov = IAS37Provision(
            provision_id=uuid4(),
            provision_type=IAS37ProvisionType.WARRANTY,
            obligation_description="A",
            best_estimate=Money(Decimal("0"), "IDR"),  # zero amount
        )
        result = IAS37Rules.validate_disclosure([prov], [])
        assert result.is_compliant is True
        assert "Provisions exist but no material amounts disclosed" in result.warnings

    def test_validate_disclosure_empty(self):
        result = IAS37Rules.validate_disclosure([], [])
        assert result.is_compliant is True
        assert result.warnings == []


# ============================================================================
# IAS37Validator
# ============================================================================

class TestIAS37Validator:
    def test_validate_provision_valid(self, provision):
        validator = IAS37Validator()
        result = validator.validate_provision(provision)
        assert result.is_compliant is True
        assert result.errors == []

    def test_validate_provision_negative_amount(self):
        provision = IAS37Provision(
            provision_id=uuid4(),
            provision_type=IAS37ProvisionType.WARRANTY,
            obligation_description="A",
            best_estimate=Money(Decimal("-100"), "IDR"),
        )
        validator = IAS37Validator()
        result = validator.validate_provision(provision)
        assert result.is_compliant is False
        assert "Provision amount must be positive" in result.errors

    def test_get_requirements_summary(self):
        validator = IAS37Validator()
        summary = validator.get_requirements_summary()
        assert "recognition_criteria" in summary
        assert "measurement" in summary
        assert "discounting" in summary
        assert "reimbursements" in summary
        assert "contingent_liabilities" in summary
        assert "contingent_assets" in summary


# ============================================================================
# IAS37 Convenience Class
# ============================================================================

class TestIAS37:
    def test_should_recognize_provision_all_true(self):
        assert IAS37.should_recognize_provision(True, True, True) is True

    def test_should_recognize_provision_missing_one(self):
        assert IAS37.should_recognize_provision(False, True, True) is False
        assert IAS37.should_recognize_provision(True, False, True) is False
        assert IAS37.should_recognize_provision(True, True, False) is False

    def test_best_estimate_valid(self):
        outcomes = [Decimal("100"), Decimal("200"), Decimal("300")]
        probs = [Decimal("0.2"), Decimal("0.5"), Decimal("0.3")]
        result = IAS37.best_estimate(outcomes, probs)
        expected = Decimal("100") * Decimal("0.2") + Decimal("200") * Decimal("0.5") + Decimal("300") * Decimal("0.3")
        expected = expected.quantize(Decimal("0.01"))
        assert result == expected

    def test_best_estimate_length_mismatch_raises(self):
        outcomes = [Decimal("100"), Decimal("200")]
        probs = [Decimal("0.5")]  # length mismatch
        with pytest.raises(ValueError, match="same length"):
            IAS37.best_estimate(outcomes, probs)


# ============================================================================
# Singleton Accessor
# ============================================================================

def test_get_ias37_validator():
    v1 = get_ias37_validator()
    v2 = get_ias37_validator()
    assert v1 is v2
    assert isinstance(v1, IAS37Validator)
