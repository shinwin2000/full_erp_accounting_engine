# tests/policy_engine/psak/test_psak_aggregator.py
"""
Comprehensive tests for policy_engine/psak/psak_aggregator.py.

Covers:
- Enums: PSAKStandard, ComplianceLevel
- ComplianceReport: construction, to_dict
- PSAKAggregator: singleton, validators, requirements summary
- assess_compliance with all standards, subset, errors/warnings
- Private _assess_psak* methods (tested indirectly via assess_compliance)
- get_supported_standards, list_standards, validate_all (test compatibility)
- reset
- Singleton accessor get_psak_aggregator
- Edge cases: missing validator, empty standards, validation results with errors/warnings
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from policy_engine.psak.psak_aggregator import (
    ComplianceLevel,
    ComplianceReport,
    PSAKAggregator,
    PSAKStandard,
    get_psak_aggregator,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def aggregator():
    """Fresh PSAKAggregator instance."""
    # Reset singleton
    PSAKAggregator._instance = None
    return PSAKAggregator()


@pytest.fixture
def mock_validator_result():
    """Create a mock validation result with configurable compliance."""
    result = MagicMock()
    result.is_compliant = True
    result.errors = []
    result.warnings = []
    return result


# ============================================================================
# Tests for Enums
# ============================================================================

class TestPSAKStandard:
    def test_members(self):
        assert PSAKStandard.PSAK_1.value == "PSAK 1"
        assert PSAKStandard.PSAK_2.value == "PSAK 2"
        assert PSAKStandard.PSAK_14.value == "PSAK 14"
        assert PSAKStandard.PSAK_71.value == "PSAK 71"
        assert PSAKStandard.PSAK_72.value == "PSAK 72"
        assert PSAKStandard.PSAK_73.value == "PSAK 73"
        # Check some others
        assert PSAKStandard.PSAK_27.value == "PSAK 27"


class TestComplianceLevel:
    def test_members(self):
        assert ComplianceLevel.FULLY_COMPLIANT.value == "fully_compliant"
        assert ComplianceLevel.SUBSTANTIALLY_COMPLIANT.value == "substantially_compliant"
        assert ComplianceLevel.PARTIALLY_COMPLIANT.value == "partially_compliant"
        assert ComplianceLevel.NON_COMPLIANT.value == "non_compliant"


# ============================================================================
# Tests for ComplianceReport
# ============================================================================

class TestComplianceReport:
    def test_construction(self, entity_id):
        report = ComplianceReport(
            report_id="REP-001",
            entity_id=entity_id,
            entity_name="Test Entity",
            reporting_period="2025-Q1",
            assessed_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
            overall_compliance=ComplianceLevel.FULLY_COMPLIANT,
            standards_assessed=[PSAKStandard.PSAK_1, PSAKStandard.PSAK_2],
            results={"PSAK 1": MagicMock(is_compliant=True)},
            recommendations=["Recommendation 1"],
        )
        assert report.report_id == "REP-001"
        assert report.entity_id == entity_id
        assert report.overall_compliance == ComplianceLevel.FULLY_COMPLIANT

    def test_to_dict(self, entity_id):
        report = ComplianceReport(
            report_id="REP-002",
            entity_id=entity_id,
            entity_name="Entity",
            reporting_period="2025",
            assessed_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
            overall_compliance=ComplianceLevel.PARTIALLY_COMPLIANT,
            standards_assessed=[PSAKStandard.PSAK_1],
            results={},
            recommendations=["Fix disclosure"],
        )
        d = report.to_dict()
        assert d["report_id"] == "REP-002"
        assert d["entity_id"] == str(entity_id)
        assert d["overall_compliance"] == "partially_compliant"
        assert d["standards_assessed"] == ["PSAK 1"]
        assert d["recommendations"] == ["Fix disclosure"]
        assert "assessed_at" in d


# ============================================================================
# Tests for PSAKAggregator
# ============================================================================

class TestPSAKAggregator:
    def test_singleton(self):
        PSAKAggregator._instance = None
        a1 = PSAKAggregator()
        a2 = PSAKAggregator()
        assert a1 is a2

    def test_init_sets_validators(self, aggregator):
        assert aggregator._psak1 is not None
        assert aggregator._psak2 is not None
        assert aggregator._psak14 is not None
        assert aggregator._psak16 is not None
        assert aggregator._psak71 is not None
        assert aggregator._psak72 is not None
        assert aggregator._psak73 is not None
        assert len(aggregator._validators) == 7

    def test_get_validator(self, aggregator):
        v = aggregator.get_validator(PSAKStandard.PSAK_1)
        assert v is aggregator._psak1
        assert aggregator.get_validator(PSAKStandard.PSAK_2) is aggregator._psak2
        assert aggregator.get_validator(PSAKStandard.PSAK_73) is aggregator._psak73
        assert aggregator.get_validator(PSAKStandard.PSAK_3) is None  # not supported

    def test_get_all_validators(self, aggregator):
        validators = aggregator.get_all_validators()
        assert isinstance(validators, dict)
        assert len(validators) == 7
        assert validators[PSAKStandard.PSAK_1] is aggregator._psak1

    def test_get_requirements_summary(self, aggregator):
        summary = aggregator.get_requirements_summary()
        assert "PSAK_1" in summary
        assert "PSAK_2" in summary
        assert "PSAK_14" in summary
        assert "PSAK_16" in summary
        assert "PSAK_71" in summary
        assert "PSAK_72" in summary
        assert "PSAK_73" in summary
        # Each should be a dict (from the validator's get_requirements_summary)
        # We can't assert deeply without knowing the mock, but we check existence.

    # ---- assess_compliance ----

    def test_assess_compliance_all_standards(self, aggregator, entity_id):
        # Patch all validators to return compliant results
        with patch.object(aggregator._psak1, 'validate_financial_statements') as mock1:
            with patch.object(aggregator._psak2, 'validate_cash_flow_statement') as mock2:
                with patch.object(aggregator._psak14, 'validate_inventory_valuation') as mock14:
                    with patch.object(aggregator._psak16, 'validate_asset_recognition') as mock16:
                        with patch.object(aggregator._psak71, 'validate_hedge_effectiveness') as mock71:
                            with patch.object(aggregator._psak72, 'validate_contract_compliance') as mock72:
                                with patch.object(aggregator._psak73, 'validate_lease_compliance') as mock73:
                                    # Make all compliant
                                    for m in [mock1, mock2, mock14, mock16, mock71, mock72, mock73]:
                                        result = MagicMock()
                                        result.is_compliant = True
                                        result.errors = []
                                        result.warnings = []
                                        m.return_value = result

                                    report = aggregator.assess_compliance(
                                        entity_id=entity_id,
                                        entity_name="Test",
                                        reporting_period="2025",
                                        standards=None,  # all
                                    )
                                    assert report.overall_compliance == ComplianceLevel.FULLY_COMPLIANT
                                    assert len(report.standards_assessed) == len(PSAKStandard)
                                    assert report.recommendations == []

    def test_assess_compliance_subset(self, aggregator, entity_id):
        # Patch only PSAK1 and PSAK2
        with patch.object(aggregator._psak1, 'validate_financial_statements') as mock1:
            with patch.object(aggregator._psak2, 'validate_cash_flow_statement') as mock2:
                result = MagicMock()
                result.is_compliant = True
                result.errors = []
                result.warnings = []
                mock1.return_value = result
                mock2.return_value = result

                report = aggregator.assess_compliance(
                    entity_id=entity_id,
                    entity_name="Test",
                    reporting_period="2025",
                    standards=[PSAKStandard.PSAK_1, PSAKStandard.PSAK_2],
                )
                assert report.overall_compliance == ComplianceLevel.FULLY_COMPLIANT
                assert set(report.standards_assessed) == {PSAKStandard.PSAK_1, PSAKStandard.PSAK_2}
                assert "PSAK 1" in report.results
                assert "PSAK 2" in report.results

    def test_assess_compliance_with_errors(self, aggregator, entity_id):
        with patch.object(aggregator._psak1, 'validate_financial_statements') as mock1:
            with patch.object(aggregator._psak2, 'validate_cash_flow_statement') as mock2:
                # PSAK1 has errors
                result1 = MagicMock()
                result1.is_compliant = False
                result1.errors = ["Missing balance sheet", "Incorrect format"]
                result1.warnings = []
                mock1.return_value = result1

                # PSAK2 has warnings only
                result2 = MagicMock()
                result2.is_compliant = True
                result2.errors = []
                result2.warnings = ["Minor disclosure issue"]
                mock2.return_value = result2

                report = aggregator.assess_compliance(
                    entity_id=entity_id,
                    entity_name="Test",
                    reporting_period="2025",
                    standards=[PSAKStandard.PSAK_1, PSAKStandard.PSAK_2],
                )
                assert report.overall_compliance == ComplianceLevel.NON_COMPLIANT
                assert len(report.recommendations) == 2
                assert any("PSAK 1" in r for r in report.recommendations)
                assert any("PSAK 2" in r for r in report.recommendations)

    def test_assess_compliance_with_warnings_only(self, aggregator, entity_id):
        with patch.object(aggregator._psak1, 'validate_financial_statements') as mock1:
            with patch.object(aggregator._psak2, 'validate_cash_flow_statement') as mock2:
                result1 = MagicMock()
                result1.is_compliant = True
                result1.errors = []
                result1.warnings = ["Warning 1"]
                mock1.return_value = result1

                result2 = MagicMock()
                result2.is_compliant = True
                result2.errors = []
                result2.warnings = ["Warning 2"]
                mock2.return_value = result2

                report = aggregator.assess_compliance(
                    entity_id=entity_id,
                    entity_name="Test",
                    reporting_period="2025",
                    standards=[PSAKStandard.PSAK_1, PSAKStandard.PSAK_2],
                )
                assert report.overall_compliance == ComplianceLevel.PARTIALLY_COMPLIANT
                assert len(report.recommendations) == 2

    def test_assess_compliance_unknown_standard(self, aggregator, entity_id):
        # Standards list contains PSAK_3 which is not supported
        with patch.object(aggregator._psak1, 'validate_financial_statements') as mock1:
            result = MagicMock()
            result.is_compliant = True
            result.errors = []
            result.warnings = []
            mock1.return_value = result

            report = aggregator.assess_compliance(
                entity_id=entity_id,
                entity_name="Test",
                reporting_period="2025",
                standards=[PSAKStandard.PSAK_1, PSAKStandard.PSAK_3],
            )
            # PSAK_3 should be skipped (no validator)
            assert len(report.standards_assessed) == 1  # only PSAK_1
            assert "PSAK 1" in report.results
            assert "PSAK 3" not in report.results
            assert report.overall_compliance == ComplianceLevel.FULLY_COMPLIANT

    # ---- Private _assess_psak* methods (tested indirectly) ----

    def test_assess_psak1_calls_validator(self, aggregator):
        with patch.object(aggregator._psak1, 'validate_financial_statements') as mock:
            mock.return_value = MagicMock(is_compliant=True)
            kwargs = {
                "components": ["balance_sheet"],
                "balance_sheet_accounts": ["cash"],
                "presentation_format": "classified",
                "is_going_concern_uncertain": False,
            }
            result = aggregator._assess_psak1(kwargs)
            mock.assert_called_once_with(
                components=["balance_sheet"],
                balance_sheet_accounts=["cash"],
                income_statement_accounts=[],
                presentation_format="classified",
                current_period_data=None,
                prior_period_data=None,
                is_going_concern_uncertain=False,
                has_going_concern_disclosure=False,
                material_items=None,
                material_items_disclosed=False,
            )
            assert result.is_compliant is True

    def test_assess_psak2_with_statement(self, aggregator):
        with patch.object(aggregator._psak2, 'validate_cash_flow_statement') as mock:
            mock.return_value = MagicMock(is_compliant=True)
            statement = {"operating": 100}
            kwargs = {"cash_flow_statement": statement, "previous_statement": None}
            result = aggregator._assess_psak2(kwargs)
            mock.assert_called_once_with(statement, previous_statement=None)
            assert result.is_compliant is True

    def test_assess_psak2_without_statement(self, aggregator):
        result = aggregator._assess_psak2({})
        assert result.is_compliant is True  # default

    def test_assess_psak14(self, aggregator):
        with patch.object(aggregator._psak14, 'validate_inventory_valuation') as mock:
            mock.return_value = MagicMock(is_compliant=True)
            kwargs = {"valuations": [{"item": "A"}], "valuation_method": "FIFO", "previous_method": None}
            result = aggregator._assess_psak14(kwargs)
            mock.assert_called_once_with([{"item": "A"}], "FIFO", None)
            assert result.is_compliant is True

    def test_assess_psak16(self, aggregator):
        with patch.object(aggregator._psak16, 'validate_asset_recognition') as mock:
            mock.return_value = MagicMock(is_compliant=True)
            kwargs = {
                "cost": Decimal("10000"),
                "useful_life_years": 5,
                "asset_category": "Equipment",
                "salvage_value": Decimal("1000"),
                "depreciation_method": "straight_line",
            }
            result = aggregator._assess_psak16(kwargs)
            mock.assert_called_once_with(
                Decimal("10000"), 5, "Equipment", Decimal("1000"), "straight_line"
            )
            assert result.is_compliant is True

    def test_assess_psak71_with_hedge(self, aggregator):
        with patch.object(aggregator._psak71, 'validate_hedge_effectiveness') as mock:
            mock.return_value = MagicMock(is_compliant=True)
            hedge = {"id": 1}
            kwargs = {"hedging_relationship": hedge}
            result = aggregator._assess_psak71(kwargs)
            mock.assert_called_once_with(hedge)
            assert result.is_compliant is True

    def test_assess_psak71_without_hedge(self, aggregator):
        result = aggregator._assess_psak71({})
        assert result.is_compliant is True

    def test_assess_psak72_with_contract(self, aggregator):
        with patch.object(aggregator._psak72, 'validate_contract_compliance') as mock:
            mock.return_value = MagicMock(is_compliant=True)
            contract = {"id": 1}
            kwargs = {"contract": contract}
            result = aggregator._assess_psak72(kwargs)
            mock.assert_called_once_with(contract)
            assert result.is_compliant is True

    def test_assess_psak72_without_contract(self, aggregator):
        result = aggregator._assess_psak72({})
        assert result.is_compliant is True

    def test_assess_psak73_with_lease(self, aggregator):
        with patch.object(aggregator._psak73, 'validate_lease_compliance') as mock:
            mock.return_value = MagicMock(is_compliant=True)
            lease = {"id": 1}
            fair_value = Decimal("50000")
            kwargs = {"lease": lease, "fair_value": fair_value}
            result = aggregator._assess_psak73(kwargs)
            mock.assert_called_once_with(lease, fair_value)
            assert result.is_compliant is True

    def test_assess_psak73_without_lease(self, aggregator):
        result = aggregator._assess_psak73({})
        assert result.is_compliant is True

    # ---- get_supported_standards ----

    def test_get_supported_standards(self, aggregator):
        standards = aggregator.get_supported_standards()
        assert isinstance(standards, list)
        # Should include PSAK 1-27 and 71,72,73
        expected = [f"PSAK {i}" for i in range(1, 28)] + ["PSAK 71", "PSAK 72", "PSAK 73"]
        assert standards == expected

    # ---- list_standards (test compatibility) ----

    def test_list_standards(self, aggregator):
        standards = aggregator.list_standards()
        assert standards == aggregator.get_supported_standards()

    # ---- validate_all (test compatibility) ----

    def test_validate_all(self, aggregator):
        report = aggregator.validate_all()
        assert isinstance(report, SimpleNamespace)
        assert report.total_standards == 27
        assert report.compliant_standards == 27

    # ---- reset ----

    def test_reset(self, aggregator):
        # Change validators
        old_psak1 = aggregator._psak1
        aggregator.reset()
        assert aggregator._psak1 is not old_psak1
        assert len(aggregator._validators) == 7
        assert aggregator._validators[PSAKStandard.PSAK_1] is aggregator._psak1


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

def test_get_psak_aggregator():
    # Reset singleton
    import policy_engine.psak.psak_aggregator as module
    module._psak_aggregator_instance = None
    a1 = get_psak_aggregator()
    a2 = get_psak_aggregator()
    assert a1 is a2
    assert isinstance(a1, PSAKAggregator)


# ============================================================================
# Additional edge cases
# ============================================================================

class TestEdgeCases:
    def test_assess_compliance_with_empty_standards(self, aggregator, entity_id):
        report = aggregator.assess_compliance(
            entity_id=entity_id,
            entity_name="Test",
            reporting_period="2025",
            standards=[],
        )
        assert report.standards_assessed == []
        assert report.overall_compliance == ComplianceLevel.FULLY_COMPLIANT  # no standards -> fully compliant
        assert report.results == {}

    def test_assess_compliance_with_none_standards(self, aggregator, entity_id):
        # standards=None should trigger all standards
        with patch.object(aggregator._psak1, 'validate_financial_statements') as mock:
            result = MagicMock()
            result.is_compliant = True
            result.errors = []
            result.warnings = []
            mock.return_value = result
            # Patch others to avoid calls (they will be called but we don't care)
            # We'll just patch all validators quickly.
            with patch.multiple(
                aggregator._psak2, validate_cash_flow_statement=MagicMock(return_value=result)
            ):
                with patch.multiple(
                    aggregator._psak14, validate_inventory_valuation=MagicMock(return_value=result)
                ):
                    with patch.multiple(
                        aggregator._psak16, validate_asset_recognition=MagicMock(return_value=result)
                    ):
                        with patch.multiple(
                            aggregator._psak71, validate_hedge_effectiveness=MagicMock(return_value=result)
                        ):
                            with patch.multiple(
                                aggregator._psak72, validate_contract_compliance=MagicMock(return_value=result)
                            ):
                                with patch.multiple(
                                    aggregator._psak73, validate_lease_compliance=MagicMock(return_value=result)
                                ):
                                    report = aggregator.assess_compliance(
                                        entity_id=entity_id,
                                        entity_name="Test",
                                        reporting_period="2025",
                                        standards=None,
                                    )
                                    assert len(report.standards_assessed) == len(PSAKStandard)

    def test_reset_updates_validators(self, aggregator):
        old_validators = aggregator._validators.copy()
        aggregator.reset()
        assert aggregator._validators is not old_validators
        # Check that each validator is new
        for key in aggregator._validators:
            assert aggregator._validators[key] is not old_validators[key]
