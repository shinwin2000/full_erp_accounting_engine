# tests/compliance/test_sox_control_tester.py
"""
Comprehensive tests for compliance/sox_control_tester.py
"""

import json
from datetime import date
from uuid import uuid4

import pytest

from compliance.sox_control_tester import (
    Control,
    ControlFrequency,
    ControlNotFoundError,
    ControlTest,
    ControlTestResult,
    ControlType,
    DeficiencySeverity,
    SoxControlTester,
    SOXError,
)
from compliance.sox_control_tester import (
    TestType as EnumTestType,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tester():
    return SoxControlTester(company_name="Test Corp", fiscal_year=2026)


@pytest.fixture
def sample_control(tester):
    return tester.define_control(
        control_id="FIN-001",
        name="Journal Approval",
        description="Every journal must be approved",
        control_type=ControlType.PREVENTIVE,
        frequency=ControlFrequency.CONTINUOUS,
        owner="Finance Manager",
        risk_level="high",
        assertion="accuracy",
        key_report="Journal Entry Report",
        is_automated=False,
        system_source="ERP",
    )


@pytest.fixture
def sample_test_plan(tester, sample_control):
    tester.define_test_plan(
        control_id="FIN-001",
        test_type=EnumTestType.OPERATING_EFFECTIVENESS,
        sample_method="random",
        sample_size=25,
        threshold_deviation_rate=0.05,
        test_procedure="Select 25 journal entries",
        evidence_requirements=["Screenshot"],
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestControlType:
    def test_members_exist(self):
        assert hasattr(ControlType, 'PREVENTIVE')
        assert hasattr(ControlType, 'DETECTIVE')
        assert hasattr(ControlType, 'CORRECTIVE')

    def test_member_is_instance(self):
        assert isinstance(ControlType.PREVENTIVE, ControlType)


class TestControlFrequency:
    def test_members_exist(self):
        assert hasattr(ControlFrequency, 'CONTINUOUS')
        assert hasattr(ControlFrequency, 'DAILY')
        assert hasattr(ControlFrequency, 'WEEKLY')
        assert hasattr(ControlFrequency, 'MONTHLY')
        assert hasattr(ControlFrequency, 'QUARTERLY')
        assert hasattr(ControlFrequency, 'ANNUALLY')

    def test_member_is_instance(self):
        assert isinstance(ControlFrequency.CONTINUOUS, ControlFrequency)


class TestControlTestResult:
    def test_members_exist(self):
        assert hasattr(ControlTestResult, 'PASS')
        assert hasattr(ControlTestResult, 'FAIL')
        assert hasattr(ControlTestResult, 'NOT_TESTED')
        assert hasattr(ControlTestResult, 'REMEDIATED')
        assert hasattr(ControlTestResult, 'WAIVED')

    def test_member_is_instance(self):
        assert isinstance(ControlTestResult.PASS, ControlTestResult)


class TestEnumTestType:
    def test_members_exist(self):
        assert hasattr(EnumTestType, 'DESIGN_EFFECTIVENESS')
        assert hasattr(EnumTestType, 'OPERATING_EFFECTIVENESS')

    def test_member_is_instance(self):
        assert isinstance(EnumTestType.DESIGN_EFFECTIVENESS, EnumTestType)


class TestDeficiencySeverity:
    def test_members_exist(self):
        assert hasattr(DeficiencySeverity, 'CONTROL_DEFICIENCY')
        assert hasattr(DeficiencySeverity, 'SIGNIFICANT_DEFICIENCY')
        assert hasattr(DeficiencySeverity, 'MATERIAL_WEAKNESS')

    def test_member_is_instance(self):
        assert isinstance(DeficiencySeverity.CONTROL_DEFICIENCY, DeficiencySeverity)


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestSOXError:
    def test_raise(self):
        with pytest.raises(SOXError):
            raise SOXError("SOX error")

    def test_inheritance(self):
        assert issubclass(SOXError, Exception)


class TestControlNotFoundError:
    def test_raise(self):
        with pytest.raises(ControlNotFoundError):
            raise ControlNotFoundError("Control not found")

    def test_inheritance(self):
        assert issubclass(ControlNotFoundError, SOXError)


# ============================================================================
# Tests for Control Dataclass
# ============================================================================

class TestControl:
    def test_construction(self):
        control = Control(
            control_id="CTRL-001",
            name="Test Control",
            description="Test description",
            control_type=ControlType.PREVENTIVE,
            frequency=ControlFrequency.DAILY,
            owner="Owner",
            risk_level="high",
            assertion="accuracy",
            key_report="Report",
            is_automated=True,
            system_source="ERP",
        )
        assert control.control_id == "CTRL-001"
        assert control.name == "Test Control"
        assert control.control_type == ControlType.PREVENTIVE
        assert control.frequency == ControlFrequency.DAILY
        assert control.is_automated is True
        assert control.system_source == "ERP"
        assert control.created_at is not None

    def test_to_dict(self):
        control = Control(
            control_id="CTRL-001",
            name="Test Control",
            description="Test description",
            control_type=ControlType.DETECTIVE,
            frequency=ControlFrequency.WEEKLY,
            owner="Owner",
            risk_level="medium",
            assertion="completeness",
            key_report="Report",
            is_automated=False,
            system_source=None,
        )
        d = control.to_dict()
        assert d["control_id"] == "CTRL-001"
        assert d["name"] == "Test Control"
        assert d["control_type"] == "detective"
        assert d["frequency"] == "weekly"
        assert d["owner"] == "Owner"
        assert d["risk_level"] == "medium"
        assert d["assertion"] == "completeness"
        assert d["key_report"] == "Report"
        assert d["is_automated"] is False
        assert d["system_source"] is None


# ============================================================================
# Tests for ControlTest Dataclass
# ============================================================================

class TestControlTest:
    def test_construction(self):
        test_id = uuid4()
        test = ControlTest(
            test_id=test_id,
            control_id="CTRL-001",
            test_type=EnumTestType.DESIGN_EFFECTIVENESS,
            test_date=date(2026, 1, 15),
            tested_by="Auditor",
            result=ControlTestResult.PASS,
            sample_size=50,
            deviations=1,
            deviation_rate=0.02,
            evidence=["evidence1.pdf"],
            notes="Test notes",
            severity=DeficiencySeverity.CONTROL_DEFICIENCY,
            remediation_deadline=date(2026, 3, 15),
            remediation_plan="Plan",
            remediation_status="in_progress",
        )
        assert test.test_id == test_id
        assert test.control_id == "CTRL-001"
        assert test.test_type == EnumTestType.DESIGN_EFFECTIVENESS
        assert test.result == ControlTestResult.PASS
        assert test.sample_size == 50
        assert test.deviations == 1
        assert test.deviation_rate == 0.02
        assert test.evidence == ["evidence1.pdf"]
        assert test.notes == "Test notes"
        assert test.severity == DeficiencySeverity.CONTROL_DEFICIENCY
        assert test.remediation_deadline == date(2026, 3, 15)
        assert test.remediation_plan == "Plan"
        assert test.remediation_status == "in_progress"
        assert test.hash_sha256 != ""

    def test_compute_hash(self):
        test = ControlTest(
            test_id=uuid4(),
            control_id="CTRL-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            test_date=date(2026, 1, 15),
            tested_by="Auditor",
            result=ControlTestResult.FAIL,
            sample_size=10,
            deviations=3,
        )
        h1 = test._compute_hash()
        h2 = test._compute_hash()
        assert h1 == h2
        # Change something
        test.deviations = 4
        h3 = test._compute_hash()
        assert h1 != h3

    def test_to_dict(self):
        test_id = uuid4()
        test = ControlTest(
            test_id=test_id,
            control_id="CTRL-001",
            test_type=EnumTestType.DESIGN_EFFECTIVENESS,
            test_date=date(2026, 1, 15),
            tested_by="Auditor",
            result=ControlTestResult.PASS,
            sample_size=50,
            deviations=1,
            deviation_rate=0.02,
            evidence=["evidence1.pdf"],
            notes="Test notes",
            severity=DeficiencySeverity.CONTROL_DEFICIENCY,
            remediation_plan="Fix it",
            remediation_status="completed",
        )
        d = test.to_dict()
        assert d["test_id"] == str(test_id)
        assert d["control_id"] == "CTRL-001"
        assert d["test_type"] == "design_effectiveness"
        assert d["result"] == "pass"
        assert d["sample_size"] == 50
        assert d["deviations"] == 1
        assert d["deviation_rate"] == 0.02
        assert d["evidence"] == ["evidence1.pdf"]
        assert d["notes"] == "Test notes"
        assert d["severity"] == "control_deficiency"
        assert d["remediation_plan"] == "Fix it"
        assert d["remediation_status"] == "completed"
        assert "hash" in d


# ============================================================================
# Tests for SoxControlTester
# ============================================================================

class TestSoxControlTester:
    def test_init(self):
        tester = SoxControlTester(company_name="Acme Corp", fiscal_year=2025)
        assert tester.company_name == "Acme Corp"
        assert tester.fiscal_year == 2025
        assert tester._controls == {}
        assert tester._tests == []
        assert tester._deficiencies == {}
        assert tester._test_plans == {}

    def test_define_control_success(self, tester):
        control = tester.define_control(
            control_id="FIN-001",
            name="Journal Approval",
            description="Every journal must be approved",
            control_type=ControlType.PREVENTIVE,
            frequency=ControlFrequency.CONTINUOUS,
            owner="Finance Manager",
            risk_level="high",
            assertion="accuracy",
            key_report="Journal Entry Report",
            is_automated=False,
            system_source="ERP",
        )
        assert control.control_id == "FIN-001"
        assert control.name == "Journal Approval"
        assert control.control_type == ControlType.PREVENTIVE
        assert control.frequency == ControlFrequency.CONTINUOUS
        assert control.owner == "Finance Manager"
        assert control.risk_level == "high"
        assert control.assertion == "accuracy"
        assert control.key_report == "Journal Entry Report"
        assert control.is_automated is False
        assert control.system_source == "ERP"
        assert control.control_id in tester._controls

    def test_define_control_duplicate_raises(self, tester):
        tester.define_control(
            control_id="FIN-001",
            name="Journal Approval",
            description="desc",
            control_type=ControlType.PREVENTIVE,
            frequency=ControlFrequency.CONTINUOUS,
            owner="Owner",
        )
        with pytest.raises(SOXError, match="Control FIN-001 already defined"):
            tester.define_control(
                control_id="FIN-001",
                name="Duplicate",
                description="desc",
                control_type=ControlType.PREVENTIVE,
                frequency=ControlFrequency.CONTINUOUS,
                owner="Owner",
            )

    def test_get_control_found(self, tester, sample_control):
        control = tester.get_control("FIN-001")
        assert control is sample_control

    def test_get_control_not_found(self, tester):
        control = tester.get_control("NONEXISTENT")
        assert control is None

    def test_get_all_controls(self, tester, sample_control):
        controls = tester.get_all_controls()
        assert len(controls) == 1
        assert controls[0] is sample_control
        # Add another
        tester.define_control(
            control_id="FIN-002",
            name="Another",
            description="desc",
            control_type=ControlType.DETECTIVE,
            frequency=ControlFrequency.DAILY,
            owner="Owner",
        )
        controls2 = tester.get_all_controls()
        assert len(controls2) == 2

    def test_define_test_plan_success(self, tester, sample_control):
        tester.define_test_plan(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            sample_method="random",
            sample_size=25,
            threshold_deviation_rate=0.05,
            test_procedure="Test procedure",
            evidence_requirements=["Screenshot", "Log"],
        )
        plan = tester._test_plans["FIN-001"]
        assert plan["test_type"] == EnumTestType.OPERATING_EFFECTIVENESS
        assert plan["sample_method"] == "random"
        assert plan["sample_size"] == 25
        assert plan["threshold_deviation_rate"] == 0.05
        assert plan["test_procedure"] == "Test procedure"
        assert plan["evidence_requirements"] == ["Screenshot", "Log"]
        assert "updated_at" in plan

    def test_define_test_plan_control_not_found_raises(self, tester):
        with pytest.raises(ControlNotFoundError, match="Control NONEXISTENT not found"):
            tester.define_test_plan(
                control_id="NONEXISTENT",
                test_type=EnumTestType.OPERATING_EFFECTIVENESS,
                sample_method="random",
                sample_size=25,
                threshold_deviation_rate=0.05,
                test_procedure="Test",
                evidence_requirements=[],
            )

    def test_run_test_pass(self, tester, sample_control, sample_test_plan):
        test = tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Internal Audit",
            sample_size=25,
            deviations=0,
            evidence=["evidence1.pdf"],
            notes="All approved",
        )
        assert isinstance(test, ControlTest)
        assert test.control_id == "FIN-001"
        assert test.result == ControlTestResult.PASS
        assert test.sample_size == 25
        assert test.deviations == 0
        assert test.deviation_rate == 0.0
        assert test.evidence == ["evidence1.pdf"]
        assert test.notes == "All approved"
        assert test.severity is None
        # Should be in tests list
        assert len(tester._tests) == 1
        # No deficiency created
        assert len(tester._deficiencies) == 0

    def test_run_test_fail_with_threshold(self, tester, sample_control, sample_test_plan):
        test = tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Internal Audit",
            sample_size=25,
            deviations=3,  # 3/25 = 0.12 > 0.05 threshold -> FAIL
            evidence=["evidence1.pdf"],
            notes="3 entries missing approval",
        )
        assert test.result == ControlTestResult.FAIL
        assert test.deviation_rate == 0.12
        # Severity should be determined: high risk + deviation_rate > 0.10 -> MATERIAL_WEAKNESS
        assert test.severity == DeficiencySeverity.MATERIAL_WEAKNESS
        # Deficiency should be created
        assert len(tester._deficiencies) == 1

    def test_run_test_fail_control_not_found_raises(self, tester):
        with pytest.raises(ControlNotFoundError, match="Control NONEXISTENT not found"):
            tester.run_test(
                control_id="NONEXISTENT",
                test_type=EnumTestType.OPERATING_EFFECTIVENESS,
                tested_by="Auditor",
                sample_size=10,
                deviations=1,
                evidence=[],
            )

    def test_run_test_fail_without_test_plan(self, tester, sample_control):
        # No test plan defined, but should still work with default threshold 0.05
        test = tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Internal Audit",
            sample_size=20,
            deviations=2,  # 0.10 > default 0.05 -> FAIL
            evidence=[],
        )
        assert test.result == ControlTestResult.FAIL
        assert test.deviation_rate == 0.10
        # Deficiency should be created
        assert len(tester._deficiencies) == 1

    def test_determine_severity_high_risk_material(self, tester, sample_control):
        # Control is high risk, deviation_rate > 0.10 -> MATERIAL_WEAKNESS
        severity = tester._determine_severity("FIN-001", 0.15)
        assert severity == DeficiencySeverity.MATERIAL_WEAKNESS

    def test_determine_severity_high_risk_significant(self, tester, sample_control):
        # Control is high risk, deviation_rate between 0.05 and 0.10 -> SIGNIFICANT_DEFICIENCY
        severity = tester._determine_severity("FIN-001", 0.08)
        assert severity == DeficiencySeverity.SIGNIFICANT_DEFICIENCY

    def test_determine_severity_medium_risk_significant(self, tester, sample_control):
        # Change to medium risk
        sample_control.risk_level = "medium"
        severity = tester._determine_severity("FIN-001", 0.08)
        assert severity == DeficiencySeverity.SIGNIFICANT_DEFICIENCY

    def test_determine_severity_low_risk_control_deficiency(self, tester, sample_control):
        sample_control.risk_level = "low"
        severity = tester._determine_severity("FIN-001", 0.15)
        assert severity == DeficiencySeverity.CONTROL_DEFICIENCY

    def test_determine_severity_control_not_found(self, tester):
        severity = tester._determine_severity("NONEXISTENT", 0.10)
        assert severity == DeficiencySeverity.CONTROL_DEFICIENCY

    def test_create_deficiency(self, tester, sample_control, sample_test_plan):
        test = tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=10,
            deviations=2,
            evidence=[],
        )
        # Deficiency should have been created automatically
        assert len(tester._deficiencies) == 1
        deficiency_id = next(iter(tester._deficiencies))
        deficiency = tester._deficiencies[deficiency_id]
        assert deficiency["control_id"] == "FIN-001"
        assert deficiency["test_id"] == test.test_id
        assert "failed testing" in deficiency["description"]
        assert deficiency["status"] == "open"
        assert "created_at" in deficiency

    def test_get_deficiencies_all(self, tester, sample_control, sample_test_plan):
        # Create a failing test
        tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=20,
            deviations=3,
            evidence=[],
        )
        deficiencies = tester.get_deficiencies()
        assert len(deficiencies) == 1
        assert deficiencies[0].control_id == "FIN-001"
        assert "failed testing" in deficiencies[0].issue
        assert deficiencies[0].status == "open"

    def test_get_deficiencies_filter_by_status(self, tester, sample_control, sample_test_plan):
        tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=20,
            deviations=3,
            evidence=[],
        )
        # Get only open deficiencies
        open_deficiencies = tester.get_deficiencies(status="open")
        assert len(open_deficiencies) == 1
        # Get only remediated deficiencies (none)
        remediated = tester.get_deficiencies(status="remediated")
        assert len(remediated) == 0

    def test_remediate_deficiency_success(self, tester, sample_control, sample_test_plan):
        test = tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=20,
            deviations=3,
            evidence=[],
        )
        # Get the deficiency ID
        deficiency_id = next(iter(tester._deficiencies))
        result = tester.remediate_deficiency(
            deficiency_id=deficiency_id,
            remediation_plan="Implement approval workflow",
            remediated_by="Audit Manager",
            remediated_date=date(2026, 2, 1),
        )
        assert result is True
        deficiency = tester._deficiencies[deficiency_id]
        assert deficiency["status"] == "remediated"
        assert deficiency["remediation_plan"] == "Implement approval workflow"
        assert deficiency["remediated_by"] == "Audit Manager"
        assert deficiency["remediated_at"] == "2026-02-01"
        # Check that the test is updated
        for t in tester._tests:
            if t.test_id == test.test_id:
                assert t.result == ControlTestResult.REMEDIATED
                assert t.remediation_plan == "Implement approval workflow"
                assert t.remediation_status == "completed"
                break

    def test_remediate_deficiency_not_found(self, tester):
        result = tester.remediate_deficiency(
            deficiency_id=uuid4(),
            remediation_plan="Plan",
            remediated_by="User",
        )
        assert result is False

    def test_generate_test_report_empty(self, tester):
        report = tester.generate_test_report("Q1 2026")
        assert report["company"] == "Test Corp"
        assert report["fiscal_year"] == 2026
        assert report["period"] == "Q1 2026"
        assert report["controls"]["total"] == 0
        assert report["controls"]["tested"] == 0
        assert report["controls"]["passed"] == 0
        assert report["controls"]["failed"] == 0
        assert report["controls"]["remediated"] == 0
        assert report["controls"]["not_tested"] == 0
        assert report["deficiencies"]["total"] == 0
        assert report["deficiencies"]["open"] == 0
        assert report["deficiencies"]["material_weaknesses"] == 0
        assert report["overall_opinion"] == "Unqualified - Controls are effective"

    def test_generate_test_report_with_data(self, tester, sample_control, sample_test_plan):
        # Pass test
        tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=25,
            deviations=0,
            evidence=[],
        )
        # Create another control and test
        tester.define_control(
            control_id="FIN-002",
            name="Payment Approval",
            description="Payments must be approved",
            control_type=ControlType.PREVENTIVE,
            frequency=ControlFrequency.DAILY,
            owner="Treasurer",
            risk_level="high",
            assertion="accuracy",
            key_report="Payment Report",
            is_automated=False,
        )
        tester.define_test_plan(
            control_id="FIN-002",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            sample_method="random",
            sample_size=10,
            threshold_deviation_rate=0.05,
            test_procedure="Test",
            evidence_requirements=[],
        )
        # Fail test
        tester.run_test(
            control_id="FIN-002",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=10,
            deviations=2,
            evidence=[],
        )

        report = tester.generate_test_report("Q1 2026")
        assert report["controls"]["total"] == 2
        assert report["controls"]["tested"] == 2
        assert report["controls"]["passed"] == 1
        assert report["controls"]["failed"] == 1
        assert report["controls"]["not_tested"] == 0
        assert report["deficiencies"]["total"] == 1
        assert report["deficiencies"]["open"] == 1
        # material_weaknesses: control FIN-001 high risk, pass. FIN-002 high risk, fail. Deviation rate 0.20 > 0.10 -> material weakness
        assert report["deficiencies"]["material_weaknesses"] == 1
        # Overall opinion: material weaknesses identified -> Adverse
        assert report["overall_opinion"] == "Adverse - Material Weaknesses Identified"

    def test_determine_overall_opinion_material_weakness(self, tester):
        # Test with material weaknesses
        material_weaknesses = [{"id": "MW1"}]
        failed_tests = []
        opinion = tester._determine_overall_opinion(material_weaknesses, failed_tests)
        assert opinion == "Adverse - Material Weaknesses Identified"

    def test_determine_overall_opinion_significant_deficiency(self, tester):
        material_weaknesses = []
        failed_tests = [{"id": "T1"}]
        opinion = tester._determine_overall_opinion(material_weaknesses, failed_tests)
        assert opinion == "Qualified - Significant Deficiencies Identified"

    def test_determine_overall_opinion_unqualified(self, tester):
        material_weaknesses = []
        failed_tests = []
        opinion = tester._determine_overall_opinion(material_weaknesses, failed_tests)
        assert opinion == "Unqualified - Controls are effective"

    def test_test_control_pass(self, tester, sample_control, sample_test_plan):
        tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=25,
            deviations=0,
            evidence=[],
        )
        result = tester.test_control("FIN-001")
        assert result.status == "PASS"

    def test_test_control_fail(self, tester, sample_control, sample_test_plan):
        tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=25,
            deviations=5,
            evidence=[],
        )
        result = tester.test_control("FIN-001")
        assert result.status == "FAIL"

    def test_test_control_not_tested(self, tester, sample_control):
        # No test run, status defaults to PASS
        result = tester.test_control("FIN-001")
        assert result.status == "PASS"

    def test_record_deficiency(self, tester, sample_control):
        tester.record_deficiency(
            control_id="FIN-001",
            issue="Approval missing",
            severity="material_weakness",
        )
        assert len(tester._deficiencies) == 1
        deficiency_id = next(iter(tester._deficiencies))
        deficiency = tester._deficiencies[deficiency_id]
        assert deficiency["control_id"] == "FIN-001"
        assert deficiency["issue"] == "Approval missing"
        assert deficiency["severity"] == "material_weakness"
        assert deficiency["status"] == "open"

    def test_record_deficiency_default_severity(self, tester, sample_control):
        tester.record_deficiency(
            control_id="FIN-001",
            issue="Issue",
        )
        deficiency = next(iter(tester._deficiencies.values()))
        assert deficiency["severity"] == "material_weakness"

    def test_to_json(self, tester, sample_control, sample_test_plan):
        tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Auditor",
            sample_size=25,
            deviations=0,
            evidence=[],
        )
        json_str = tester.to_json()
        data = json.loads(json_str)
        assert data["company"] == "Test Corp"
        assert data["fiscal_year"] == 2026
        assert "report" in data
        assert "controls" in data
        assert len(data["controls"]) == 1
        assert "tests" in data
        assert len(data["tests"]) == 1
        assert "deficiencies" in data

    def test_to_json_with_file(self, tester, tmp_path):
        file_path = tmp_path / "sox_report.json"
        tester.to_json(str(file_path))
        assert file_path.exists()
        data = json.loads(file_path.read_text())
        assert data["company"] == "Test Corp"

    def test_full_workflow_integration(self, tester):
        # Define control
        tester.define_control(
            control_id="FIN-001",
            name="Journal Approval",
            description="Every journal must be approved",
            control_type=ControlType.PREVENTIVE,
            frequency=ControlFrequency.CONTINUOUS,
            owner="Finance Manager",
            risk_level="high",
            assertion="accuracy",
            key_report="Journal Entry Report",
            is_automated=False,
        )
        # Define test plan
        tester.define_test_plan(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            sample_method="random",
            sample_size=25,
            threshold_deviation_rate=0.05,
            test_procedure="Select 25 journal entries",
            evidence_requirements=["Screenshot"],
        )
        # Run test - pass
        tester.run_test(
            control_id="FIN-001",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Internal Audit",
            sample_size=25,
            deviations=0,
            evidence=["screenshots.zip"],
            notes="All approved",
        )
        # Get report
        report = tester.generate_test_report("Q1 2026")
        assert report["controls"]["passed"] == 1
        assert report["overall_opinion"] == "Unqualified - Controls are effective"

        # Create another control with failure
        tester.define_control(
            control_id="FIN-002",
            name="Payment Approval",
            description="Payments must be approved",
            control_type=ControlType.PREVENTIVE,
            frequency=ControlFrequency.DAILY,
            owner="Treasurer",
            risk_level="medium",
            assertion="accuracy",
            key_report="Payment Report",
            is_automated=False,
        )
        tester.define_test_plan(
            control_id="FIN-002",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            sample_method="random",
            sample_size=20,
            threshold_deviation_rate=0.05,
            test_procedure="Test",
            evidence_requirements=[],
        )
        tester.run_test(
            control_id="FIN-002",
            test_type=EnumTestType.OPERATING_EFFECTIVENESS,
            tested_by="Internal Audit",
            sample_size=20,
            deviations=3,  # 0.15 > 0.05 -> FAIL
            evidence=[],
            notes="Missing approvals",
        )
        report2 = tester.generate_test_report("Q1 2026")
        assert report2["controls"]["failed"] == 1
        assert report2["deficiencies"]["total"] == 1
        # Deficiency severity: medium risk, deviation_rate 0.15 -> SIGNIFICANT_DEFICIENCY
        assert report2["deficiencies"]["material_weaknesses"] == 0
        assert report2["overall_opinion"] == "Qualified - Significant Deficiencies Identified"

        # Remediate
        deficiency_id = next(iter(tester._deficiencies))
        tester.remediate_deficiency(
            deficiency_id=deficiency_id,
            remediation_plan="Implement approval workflow",
            remediated_by="Audit Manager",
        )
        report3 = tester.generate_test_report("Q1 2026")
        assert report3["deficiencies"]["open"] == 0
        # Test should now be remediated
        tests = tester._tests
        for t in tests:
            if t.control_id == "FIN-002":
                assert t.result == ControlTestResult.REMEDIATED
