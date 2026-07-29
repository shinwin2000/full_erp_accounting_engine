# tests/policy_engine/psak/test_psak_01_presentation.py
"""
Comprehensive unit tests for policy_engine/psak/psak_01_presentation.py.
Covers all enums, dataclasses, services, rules, and validator.
Includes explicit tests for all flagged methods and exception paths.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_01_presentation import (
    PSAK1,
    GoingConcernAssessment,
    PSAK1ComplianceLevel,
    PSAK1Error,
    PSAK1FinancialStatementComponent,
    PSAK1FinancialStatementSet,
    PSAK1GoingConcernStatus,
    PSAK1PresentationFormat,
    PSAK1PresentationService,
    PSAK1Rules,
    PSAK1ValidationError,
    PSAK1ValidationResult,
    PSAK1Validator,
    _ComparativeReport,
    get_psak1_validator,
)

# ============================================================================
# ENUM TESTS
# ============================================================================

class TestPSAK1FinancialStatementComponent:
    def test_members_exist(self):
        assert hasattr(PSAK1FinancialStatementComponent, 'STATEMENT_OF_FINANCIAL_POSITION')
        assert hasattr(PSAK1FinancialStatementComponent, 'STATEMENT_OF_PROFIT_OR_LOSS')
        assert hasattr(PSAK1FinancialStatementComponent, 'STATEMENT_OF_OTHER_COMPREHENSIVE_INCOME')
        assert hasattr(PSAK1FinancialStatementComponent, 'STATEMENT_OF_CHANGES_IN_EQUITY')
        assert hasattr(PSAK1FinancialStatementComponent, 'STATEMENT_OF_CASH_FLOWS')
        assert hasattr(PSAK1FinancialStatementComponent, 'NOTES')

    def test_member_is_instance(self):
        comp = PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION
        assert isinstance(comp, PSAK1FinancialStatementComponent)


class TestPSAK1PresentationFormat:
    def test_members_exist(self):
        assert hasattr(PSAK1PresentationFormat, 'CLASSIFIED')
        assert hasattr(PSAK1PresentationFormat, 'UNCLASSIFIED')

    def test_member_is_instance(self):
        assert isinstance(PSAK1PresentationFormat.CLASSIFIED, PSAK1PresentationFormat)


class TestPSAK1ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK1ComplianceLevel, 'FULL')
        assert hasattr(PSAK1ComplianceLevel, 'SUBSTANTIAL')
        assert hasattr(PSAK1ComplianceLevel, 'PARTIAL')
        assert hasattr(PSAK1ComplianceLevel, 'NON_COMPLIANT')

    def test_member_is_instance(self):
        assert isinstance(PSAK1ComplianceLevel.FULL, PSAK1ComplianceLevel)


class TestPSAK1GoingConcernStatus:
    def test_members_exist(self):
        assert hasattr(PSAK1GoingConcernStatus, 'APPROPRIATE')
        assert hasattr(PSAK1GoingConcernStatus, 'MATERIAL_UNCERTAINTY')
        assert hasattr(PSAK1GoingConcernStatus, 'INAPPROPRIATE')

    def test_member_is_instance(self):
        assert isinstance(PSAK1GoingConcernStatus.APPROPRIATE, PSAK1GoingConcernStatus)


# ============================================================================
# EXCEPTION TESTS
# ============================================================================

class TestExceptions:
    def test_psak1_error(self):
        exc = PSAK1Error("test")
        assert isinstance(exc, Exception)
        assert str(exc) == "test"

    def test_psak1_validation_error(self):
        exc = PSAK1ValidationError("validation")
        assert isinstance(exc, PSAK1Error)
        assert str(exc) == "validation"

    # ---- Explicit test for PSAK1ValidationError being raised ----
    def test_psak1_validation_error_raised_on_invalid_comparative_periods(self):
        with pytest.raises(PSAK1ValidationError, match="Minimal satu periode komparatif"):
            PSAK1FinancialStatementSet(
                statement_id=uuid4(),
                entity_id=uuid4(),
                entity_name="Test",
                reporting_period_end=datetime.now(UTC),
                comparative_periods=0,  # invalid
                presentation_currency="IDR",
                presentation_format=PSAK1PresentationFormat.CLASSIFIED,
                components_present=[PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION],
                going_concern=GoingConcernAssessment(
                    status=PSAK1GoingConcernStatus.APPROPRIATE,
                    assessment_date=datetime.now(UTC),
                    assessed_by="system",
                ),
            )

    def test_psak1_validation_error_raised_on_invalid_currency(self):
        with pytest.raises(PSAK1ValidationError, match="Kode mata uang tidak valid"):
            PSAK1FinancialStatementSet(
                statement_id=uuid4(),
                entity_id=uuid4(),
                entity_name="Test",
                reporting_period_end=datetime.now(UTC),
                comparative_periods=1,
                presentation_currency="INVALID",  # not 3 chars
                presentation_format=PSAK1PresentationFormat.CLASSIFIED,
                components_present=[PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION],
                going_concern=GoingConcernAssessment(
                    status=PSAK1GoingConcernStatus.APPROPRIATE,
                    assessment_date=datetime.now(UTC),
                    assessed_by="system",
                ),
            )

    def test_psak1_validation_error_raised_on_empty_components(self):
        with pytest.raises(PSAK1ValidationError, match="Tidak ada komponen laporan keuangan"):
            PSAK1FinancialStatementSet(
                statement_id=uuid4(),
                entity_id=uuid4(),
                entity_name="Test",
                reporting_period_end=datetime.now(UTC),
                comparative_periods=1,
                presentation_currency="IDR",
                presentation_format=PSAK1PresentationFormat.CLASSIFIED,
                components_present=[],  # empty
                going_concern=GoingConcernAssessment(
                    status=PSAK1GoingConcernStatus.APPROPRIATE,
                    assessment_date=datetime.now(UTC),
                    assessed_by="system",
                ),
            )


# ============================================================================
# GOING CONCERN ASSESSMENT TESTS
# ============================================================================

class TestGoingConcernAssessment:
    @pytest.fixture
    def appropriate_gc(self):
        return GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.APPROPRIATE,
            assessment_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            assessed_by="auditor",
            key_assumptions=["stable economy"],
        )

    @pytest.fixture
    def material_uncertainty_gc(self):
        return GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.MATERIAL_UNCERTAINTY,
            assessment_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            assessed_by="auditor",
            key_assumptions=["net loss"],
            uncertainty_description="Significant net loss for 3 years",
            management_plan="Cost cutting",
        )

    def test_construction(self):
        gc = GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.APPROPRIATE,
            assessment_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            assessed_by="system",
        )
        assert gc.status == PSAK1GoingConcernStatus.APPROPRIATE
        assert gc.assessed_by == "system"

    def test_is_appropriate_true(self, appropriate_gc):
        assert appropriate_gc.is_appropriate() is True

    def test_is_appropriate_false(self, material_uncertainty_gc):
        assert material_uncertainty_gc.is_appropriate() is False

    def test_has_material_uncertainty_true(self, material_uncertainty_gc):
        assert material_uncertainty_gc.has_material_uncertainty() is True

    def test_has_material_uncertainty_false(self, appropriate_gc):
        assert appropriate_gc.has_material_uncertainty() is False

    def test_to_dict(self, appropriate_gc):
        d = appropriate_gc.to_dict()
        assert d["status"] == "layak"
        assert d["assessment_date"] == "2026-01-01T12:00:00+00:00"
        assert d["assessed_by"] == "auditor"
        assert d["key_assumptions"] == ["stable economy"]
        assert d["uncertainty_description"] is None
        assert d["management_plan"] is None


# ============================================================================
# PSAK1 FINANCIAL STATEMENT SET TESTS
# ============================================================================

class TestPSAK1FinancialStatementSet:
    @pytest.fixture
    def valid_statement_set(self):
        return PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=uuid4(),
            entity_name="PT Test",
            reporting_period_end=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
            comparative_periods=1,
            presentation_currency="IDR",
            presentation_format=PSAK1PresentationFormat.CLASSIFIED,
            components_present=[
                PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
                PSAK1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
                PSAK1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
                PSAK1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
                PSAK1FinancialStatementComponent.NOTES,
            ],
            going_concern=GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by="system",
            ),
        )

    def test_construction(self, valid_statement_set):
        assert valid_statement_set.entity_name == "PT Test"
        assert valid_statement_set.comparative_periods == 1
        assert valid_statement_set.is_complete() is True

    def test_missing_components_complete(self, valid_statement_set):
        assert valid_statement_set.missing_components() == []

    def test_missing_components_incomplete(self):
        statement = PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_period_end=datetime.now(UTC),
            comparative_periods=1,
            presentation_currency="IDR",
            presentation_format=PSAK1PresentationFormat.CLASSIFIED,
            components_present=[
                PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
                PSAK1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
                # Missing changes in equity, cash flows, notes
            ],
            going_concern=GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by="system",
            ),
        )
        missing = statement.missing_components()
        assert len(missing) == 3
        assert PSAK1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY in missing
        assert PSAK1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS in missing
        assert PSAK1FinancialStatementComponent.NOTES in missing

    def test_is_complete_true(self, valid_statement_set):
        assert valid_statement_set.is_complete() is True

    def test_is_complete_false(self):
        statement = PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_period_end=datetime.now(UTC),
            comparative_periods=1,
            presentation_currency="IDR",
            presentation_format=PSAK1PresentationFormat.CLASSIFIED,
            components_present=[PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION],
            going_concern=GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by="system",
            ),
        )
        assert statement.is_complete() is False

    def test_to_dict(self, valid_statement_set):
        d = valid_statement_set.to_dict()
        assert d["entity_name"] == "PT Test"
        assert d["comparative_periods"] == 1
        assert d["presentation_currency"] == "IDR"
        assert d["presentation_format"] == "klasifikasi"
        assert d["components_present"] == [
            "laporan_posisi_keuangan",
            "laporan_laba_rugi",
            "laporan_perubahan_ekuitas",
            "laporan_arus_kas",
            "catatan_atas_laporan_keuangan",
        ]
        assert d["missing_components"] == []
        assert "going_concern" in d


# ============================================================================
# PSAK1 VALIDATION RESULT TESTS
# ============================================================================

class TestPSAK1ValidationResult:
    def test_construction(self):
        result = PSAK1ValidationResult(
            is_compliant=True,
            compliance_level=PSAK1ComplianceLevel.FULL,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK1ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []
        assert result.hash_sha256 is not None

    def test_add_error(self):
        result = PSAK1ValidationResult(is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL)
        result.add_error("Test error")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK1ComplianceLevel.NON_COMPLIANT
        assert result.errors == ["Test error"]

    def test_add_warning(self):
        result = PSAK1ValidationResult(is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL)
        result.add_warning("Test warning")
        assert result.is_compliant is True  # warning does not make non-compliant
        assert result.compliance_level == PSAK1ComplianceLevel.SUBSTANTIAL
        assert result.warnings == ["Test warning"]

    def test_add_warning_when_already_partial(self):
        result = PSAK1ValidationResult(
            is_compliant=True,
            compliance_level=PSAK1ComplianceLevel.PARTIAL,
        )
        result.add_warning("Another warning")
        assert result.compliance_level == PSAK1ComplianceLevel.PARTIAL  # unchanged

    def test_to_dict(self):
        result = PSAK1ValidationResult(
            is_compliant=True,
            compliance_level=PSAK1ComplianceLevel.FULL,
            errors=["e1"],
            warnings=["w1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is True
        assert d["compliance_level"] == "penuh"
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]
        assert d["hash"] == result.hash_sha256

    def test_hash_computation(self):
        result1 = PSAK1ValidationResult(is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL)
        result2 = PSAK1ValidationResult(is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL)
        assert result1.hash_sha256 == result2.hash_sha256
        result1.add_error("error")
        assert result1.hash_sha256 != result2.hash_sha256


# ============================================================================
# PSAK1 PRESENTATION SERVICE TESTS
# ============================================================================

class TestPSAK1PresentationService:
    def test_validate_completeness_complete(self):
        statement = PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_period_end=datetime.now(UTC),
            comparative_periods=1,
            presentation_currency="IDR",
            presentation_format=PSAK1PresentationFormat.CLASSIFIED,
            components_present=[
                PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
                PSAK1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
                PSAK1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
                PSAK1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
                PSAK1FinancialStatementComponent.NOTES,
            ],
            going_concern=GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by="system",
            ),
        )
        result = PSAK1PresentationService.validate_completeness(statement)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK1ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_completeness_incomplete(self):
        statement = PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_period_end=datetime.now(UTC),
            comparative_periods=1,
            presentation_currency="IDR",
            presentation_format=PSAK1PresentationFormat.CLASSIFIED,
            components_present=[PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION],
            going_concern=GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by="system",
            ),
        )
        result = PSAK1PresentationService.validate_completeness(statement)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK1ComplianceLevel.NON_COMPLIANT
        assert len(result.errors) == 4  # missing 4 components

    def test_validate_going_concern_disclosure_appropriate_with_plan(self):
        assessment = GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.APPROPRIATE,
            assessment_date=datetime.now(UTC),
            assessed_by="system",
            management_plan="Some plan",  # not needed, triggers warning
        )
        result = PSAK1PresentationService.validate_going_concern_disclosure(assessment)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK1ComplianceLevel.SUBSTANTIAL
        assert "Rencana manajemen diungkapkan" in result.warnings[0]

    def test_validate_going_concern_disclosure_material_uncertainty_no_description(self):
        assessment = GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.MATERIAL_UNCERTAINTY,
            assessment_date=datetime.now(UTC),
            assessed_by="system",
            key_assumptions=["loss"],
            uncertainty_description=None,  # missing description
        )
        result = PSAK1PresentationService.validate_going_concern_disclosure(assessment)
        assert result.is_compliant is False
        assert "Ketidakpastian material going concern harus diungkapkan" in result.errors[0]

    def test_validate_going_concern_disclosure_material_uncertainty_with_description(self):
        assessment = GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.MATERIAL_UNCERTAINTY,
            assessment_date=datetime.now(UTC),
            assessed_by="system",
            key_assumptions=["loss"],
            uncertainty_description="Significant loss",
            management_plan="Cost cutting",
        )
        result = PSAK1PresentationService.validate_going_concern_disclosure(assessment)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK1ComplianceLevel.FULL

    def test_validate_comparative_info_valid(self):
        result = PSAK1PresentationService.validate_comparative_info(
            current_data=True, prior_data=True, periods=1
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK1ComplianceLevel.FULL

    def test_validate_comparative_info_missing_current(self):
        result = PSAK1PresentationService.validate_comparative_info(
            current_data=False, prior_data=True, periods=1
        )
        assert result.is_compliant is False
        assert "Data periode berjalan tidak tersedia" in result.errors[0]

    def test_validate_comparative_info_missing_prior(self):
        result = PSAK1PresentationService.validate_comparative_info(
            current_data=True, prior_data=False, periods=1
        )
        assert result.is_compliant is False
        assert "Data komparatif periode sebelumnya tidak disajikan" in result.errors[0]

    def test_validate_comparative_info_less_than_one_period(self):
        result = PSAK1PresentationService.validate_comparative_info(
            current_data=True, prior_data=True, periods=0
        )
        assert result.is_compliant is True  # warning only
        assert result.compliance_level == PSAK1ComplianceLevel.SUBSTANTIAL
        assert "Periode komparatif kurang dari 1 periode" in result.warnings[0]

    def test_validate_materiality_and_aggregation(self):
        items = [
            {"name": "Cash", "amount": Decimal("50000")},
            {"name": "Inventory", "amount": Decimal("200000")},
            {"name": "Equipment", "amount": Decimal("150000")},
        ]
        result = PSAK1PresentationService.validate_materiality_and_aggregation(items)
        # Only items below 100000 trigger warnings
        assert len(result.warnings) == 1
        assert "Cash" in result.warnings[0]

    # ---- Explicit test for validate_consistency ----
    def test_validate_consistency_identical(self):
        current = {"depreciation": "straight_line", "inventory": "fifo"}
        prior = {"depreciation": "straight_line", "inventory": "fifo"}
        result = PSAK1PresentationService.validate_consistency(current, prior)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK1ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_consistency_with_changes(self):
        current = {"depreciation": "straight_line", "inventory": "weighted_average"}
        prior = {"depreciation": "straight_line", "inventory": "fifo"}
        result = PSAK1PresentationService.validate_consistency(current, prior)
        assert result.is_compliant is False
        assert "Perubahan kebijakan akuntansi pada inventory" in result.errors[0]

    def test_validate_consistency_with_new_key(self):
        # New key in current not in prior: no error (new policy)
        current = {"depreciation": "straight_line", "revenue": "accrual"}
        prior = {"depreciation": "straight_line"}
        result = PSAK1PresentationService.validate_consistency(current, prior)
        assert result.is_compliant is True


# ============================================================================
# PSAK1 RULES TESTS
# ============================================================================

class TestPSAK1Rules:
    def test_assess_going_concern_appropriate(self):
        assessment = PSAK1Rules.assess_going_concern(
            has_net_loss_three_years=False,
            has_debt_default=False,
            has_negative_cash_flow_operations=False,
            has_litigation=False,
            management_plan_exists=False,
            assessed_by="auditor",
        )
        assert assessment.status == PSAK1GoingConcernStatus.APPROPRIATE
        assert assessment.key_assumptions == []

    def test_assess_going_concern_material_uncertainty_with_plan(self):
        assessment = PSAK1Rules.assess_going_concern(
            has_net_loss_three_years=True,
            has_debt_default=False,
            has_negative_cash_flow_operations=True,
            has_litigation=False,
            management_plan_exists=True,
            assessed_by="auditor",
        )
        assert assessment.status == PSAK1GoingConcernStatus.MATERIAL_UNCERTAINTY
        assert len(assessment.key_assumptions) == 2
        assert assessment.uncertainty_description is not None
        assert assessment.management_plan is not None

    def test_assess_going_concern_inappropriate_no_plan(self):
        assessment = PSAK1Rules.assess_going_concern(
            has_net_loss_three_years=True,
            has_debt_default=True,
            has_negative_cash_flow_operations=False,
            has_litigation=False,
            management_plan_exists=False,
            assessed_by="auditor",
        )
        assert assessment.status == PSAK1GoingConcernStatus.INAPPROPRIATE
        assert len(assessment.key_assumptions) == 2
        assert assessment.management_plan is None

    def test_validate_balance_sheet_classification_classified_without_current(self):
        accounts = [
            {"name": "Building", "type": "asset", "is_current": False, "amount": Decimal("1000")},
            {"name": "Equipment", "type": "asset", "is_current": False, "amount": Decimal("500")},
        ]
        result = PSAK1Rules.validate_balance_sheet_classification(
            accounts, PSAK1PresentationFormat.CLASSIFIED
        )
        # Should have warning about no current assets
        assert result.compliance_level == PSAK1ComplianceLevel.SUBSTANTIAL
        assert "Aset lancar tidak disajikan" in result.warnings[0]

    def test_validate_balance_sheet_classification_classified_with_current(self):
        accounts = [
            {"name": "Cash", "type": "asset", "is_current": True, "amount": Decimal("100")},
            {"name": "Building", "type": "asset", "is_current": False, "amount": Decimal("1000")},
        ]
        result = PSAK1Rules.validate_balance_sheet_classification(
            accounts, PSAK1PresentationFormat.CLASSIFIED
        )
        assert result.is_compliant is True
        assert result.warnings == []

    def test_validate_balance_sheet_classification_unclassified(self):
        accounts = [{"name": "Cash", "type": "asset", "amount": Decimal("100")}]
        result = PSAK1Rules.validate_balance_sheet_classification(
            accounts, PSAK1PresentationFormat.UNCLASSIFIED
        )
        assert result.is_compliant is True


# ============================================================================
# PSAK1 VALIDATOR TESTS
# ============================================================================

class TestPSAK1Validator:
    @pytest.fixture
    def validator(self):
        return PSAK1Validator()

    @pytest.fixture
    def valid_statement_set(self):
        return PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=uuid4(),
            entity_name="PT Test",
            reporting_period_end=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
            comparative_periods=1,
            presentation_currency="IDR",
            presentation_format=PSAK1PresentationFormat.CLASSIFIED,
            components_present=[
                PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION,
                PSAK1FinancialStatementComponent.STATEMENT_OF_PROFIT_OR_LOSS,
                PSAK1FinancialStatementComponent.STATEMENT_OF_CHANGES_IN_EQUITY,
                PSAK1FinancialStatementComponent.STATEMENT_OF_CASH_FLOWS,
                PSAK1FinancialStatementComponent.NOTES,
            ],
            going_concern=GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by="system",
            ),
        )

    def test_construction(self, validator):
        assert isinstance(validator, PSAK1Validator)
        assert validator._rules is not None

    def test_validate_financial_statements_all_valid(self, validator, valid_statement_set):
        accounts = [
            {"name": "Cash", "type": "asset", "is_current": True, "amount": Decimal("100")},
            {"name": "Building", "type": "asset", "is_current": False, "amount": Decimal("1000")},
        ]
        policies = {"depreciation": "straight_line"}
        result = validator.validate_financial_statements(
            statement_set=valid_statement_set,
            balance_sheet_accounts=accounts,
            policies_current=policies,
            policies_prior=policies,
            current_data_available=True,
            prior_data_available=True,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK1ComplianceLevel.FULL

    def test_validate_financial_statements_with_errors(self, validator, valid_statement_set):
        # Missing a component, missing prior data, etc.
        invalid_statement = PSAK1FinancialStatementSet(
            statement_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_period_end=datetime.now(UTC),
            comparative_periods=1,
            presentation_currency="IDR",
            presentation_format=PSAK1PresentationFormat.CLASSIFIED,
            components_present=[PSAK1FinancialStatementComponent.STATEMENT_OF_FINANCIAL_POSITION],
            going_concern=GoingConcernAssessment(
                status=PSAK1GoingConcernStatus.APPROPRIATE,
                assessment_date=datetime.now(UTC),
                assessed_by="system",
            ),
        )
        accounts = [{"name": "Cash", "type": "asset", "amount": Decimal("100")}]
        policies = {"depreciation": "straight_line"}
        result = validator.validate_financial_statements(
            statement_set=invalid_statement,
            balance_sheet_accounts=accounts,
            policies_current=policies,
            policies_prior=policies,
            current_data_available=True,
            prior_data_available=False,  # missing prior
        )
        assert result.is_compliant is False
        assert result.compliance_level == PSAK1ComplianceLevel.NON_COMPLIANT
        # Should have errors from missing components and missing prior data
        assert len(result.errors) > 0

    def test_merge_results(self, validator):
        main = PSAK1ValidationResult(is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL)
        other = PSAK1ValidationResult(
            is_compliant=False,
            compliance_level=PSAK1ComplianceLevel.NON_COMPLIANT,
            errors=["error1"],
            warnings=["warning1"],
        )
        merged = validator._merge_results(main, other)
        assert merged.is_compliant is False
        assert merged.compliance_level == PSAK1ComplianceLevel.NON_COMPLIANT
        assert merged.errors == ["error1"]
        assert merged.warnings == ["warning1"]

    def test_create_statement_set(self, validator):
        entity_id = uuid4()
        period_end = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
        statement = validator.create_statement_set(
            entity_id=entity_id,
            entity_name="PT ABC",
            reporting_period_end=period_end,
            presentation_currency="usd",  # lower case should be upper
            presentation_format=PSAK1PresentationFormat.UNCLASSIFIED,
            comparative_periods=2,
            is_consolidated=True,
            parent_entity_id=uuid4(),
        )
        assert statement.entity_id == entity_id
        assert statement.entity_name == "PT ABC"
        assert statement.reporting_period_end == period_end
        assert statement.presentation_currency == "USD"
        assert statement.presentation_format == PSAK1PresentationFormat.UNCLASSIFIED
        assert statement.comparative_periods == 2
        assert statement.is_consolidated is True
        assert statement.parent_entity_id is not None
        assert statement.is_complete() is True
        assert statement.going_concern.status == PSAK1GoingConcernStatus.APPROPRIATE

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "required_components" in summary
        assert "presentation_formats" in summary
        assert "comparative_info" in summary
        assert "going_concern" in summary
        assert "materiality" in summary
        assert "consistency" in summary


# ============================================================================
# COMPARATIVE REPORT TESTS
# ============================================================================

class TestComparativeReport:
    def test_construction(self):
        report = _ComparativeReport(tahun=2025)
        assert report.has_comparative_figures is True
        assert report.tahun_berjalan == 2025
        assert report.tahun_sebelumnya == 2024


# ============================================================================
# PSAK1 WRAPPER TESTS
# ============================================================================

class TestPSAK1:
    def test_generate_comparative_report(self):
        report = PSAK1.generate_comparative_report(2026)
        assert isinstance(report, _ComparativeReport)
        assert report.tahun_berjalan == 2026
        assert report.tahun_sebelumnya == 2025

    def test_is_going_concern_disclosed(self):
        assert PSAK1.is_going_concern_disclosed() is True


# ============================================================================
# SINGLETON ACCESSOR TEST
# ============================================================================

def test_get_psak1_validator():
    validator1 = get_psak1_validator()
    validator2 = get_psak1_validator()
    assert validator1 is validator2
    assert isinstance(validator1, PSAK1Validator)


# ============================================================================
# EDGE CASES & ADDITIONAL COVERAGE
# ============================================================================

class TestEdgeCases:
    def test_going_concern_assessment_immutable(self):
        # GoingConcernAssessment is frozen (dataclass(frozen=True))
        # We should not be able to modify attributes
        gc = GoingConcernAssessment(
            status=PSAK1GoingConcernStatus.APPROPRIATE,
            assessment_date=datetime.now(UTC),
            assessed_by="system",
        )
        with pytest.raises(Exception):
            gc.status = PSAK1GoingConcernStatus.MATERIAL_UNCERTAINTY  # type: ignore

    def test_validation_result_hash_changes_on_error(self):
        result = PSAK1ValidationResult(is_compliant=True, compliance_level=PSAK1ComplianceLevel.FULL)
        h1 = result.hash_sha256
        result.add_error("error")
        assert result.hash_sha256 != h1
        h2 = result.hash_sha256
        result.add_warning("warning")
        assert result.hash_sha256 != h2

    def test_validate_materiality_with_empty_items(self):
        result = PSAK1PresentationService.validate_materiality_and_aggregation([])
        assert result.is_compliant is True
        assert result.warnings == []

    def test_validate_materiality_with_no_amount(self):
        items = [{"name": "Item"}]
        result = PSAK1PresentationService.validate_materiality_and_aggregation(items)
        assert result.is_compliant is True
        # No amount, so no warning (amount defaults to 0, which triggers warning? Actually abs(0) < 100000 => warning)
        # Since amount not present, Decimal('0') is used, warning triggered
        assert len(result.warnings) == 1

    def test_validate_balance_sheet_classification_with_no_accounts(self):
        result = PSAK1Rules.validate_balance_sheet_classification(
            [], PSAK1PresentationFormat.CLASSIFIED
        )
        # No warning about current assets because no accounts
        assert result.is_compliant is True
        assert result.warnings == []  # Wait, rule checks if current_assets empty and non_current exists. With no accounts, both empty, no warning.

    def test_assess_going_concern_with_unknown_assessed_by(self):
        assessment = PSAK1Rules.assess_going_concern(
            has_net_loss_three_years=False,
            has_debt_default=False,
            has_negative_cash_flow_operations=False,
            has_litigation=False,
            management_plan_exists=False,
            assessed_by="",  # empty string
        )
        assert assessment.assessed_by == ""

    def test_create_statement_set_default_values(self, validator):
        entity_id = uuid4()
        statement = validator.create_statement_set(
            entity_id=entity_id,
            entity_name="Test",
            reporting_period_end=datetime.now(UTC),
            presentation_currency="IDR",
        )
        assert statement.presentation_format == PSAK1PresentationFormat.CLASSIFIED
        assert statement.comparative_periods == 1
        assert statement.is_consolidated is False
        assert statement.parent_entity_id is None
