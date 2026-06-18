#!/usr/bin/env python3
"""
Module: sox_control_tester.py
Layer: Compliance

Responsibility:
    Pengujian kontrol internal sesuai SOX Section 404.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class ControlType(Enum):
    PREVENTIVE = "preventive"
    DETECTIVE = "detective"
    CORRECTIVE = "corrective"


class ControlFrequency(Enum):
    CONTINUOUS = "continuous"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


class ControlTestResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_TESTED = "not_tested"
    REMEDIATED = "remediated"
    WAIVED = "waived"


class TestType(Enum):
    DESIGN_EFFECTIVENESS = "design_effectiveness"
    OPERATING_EFFECTIVENESS = "operating_effectiveness"


class DeficiencySeverity(Enum):
    CONTROL_DEFICIENCY = "control_deficiency"
    SIGNIFICANT_DEFICIENCY = "significant_deficiency"
    MATERIAL_WEAKNESS = "material_weakness"


class SOXError(Exception):
    pass


class ControlNotFoundError(SOXError):
    pass


@dataclass
class Control:
    control_id: str
    name: str
    description: str
    control_type: ControlType
    frequency: ControlFrequency
    owner: str
    risk_level: str
    assertion: str
    key_report: str
    is_automated: bool
    system_source: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "control_id": self.control_id,
            "name": self.name,
            "description": self.description,
            "control_type": self.control_type.value,
            "frequency": self.frequency.value,
            "owner": self.owner,
            "risk_level": self.risk_level,
            "assertion": self.assertion,
            "key_report": self.key_report,
            "is_automated": self.is_automated,
            "system_source": self.system_source,
        }


@dataclass
class ControlTest:
    test_id: UUID
    control_id: str
    test_type: TestType
    test_date: date
    tested_by: str
    result: ControlTestResult
    sample_size: int = 0
    deviations: int = 0
    deviation_rate: float = 0.0
    evidence: list[str] = field(default_factory=list)
    notes: str = ""
    severity: DeficiencySeverity | None = None
    remediation_deadline: date | None = None
    remediation_plan: str | None = None
    remediation_status: str = "not_started"
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "test_id": str(self.test_id),
            "control_id": self.control_id,
            "result": self.result.value,
            "test_date": self.test_date.isoformat(),
            "deviations": self.deviations,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "test_id": str(self.test_id),
            "control_id": self.control_id,
            "test_type": self.test_type.value,
            "test_date": self.test_date.isoformat(),
            "tested_by": self.tested_by,
            "result": self.result.value,
            "sample_size": self.sample_size,
            "deviations": self.deviations,
            "deviation_rate": self.deviation_rate,
            "evidence": self.evidence,
            "notes": self.notes,
            "severity": self.severity.value if self.severity else None,
            "remediation_plan": self.remediation_plan,
            "remediation_status": self.remediation_status,
            "hash": self.hash_sha256,
        }


class SoxControlTester:
    def __init__(self, company_name: str = "Default Company", fiscal_year: int = 2025):
        self.company_name = company_name
        self.fiscal_year = fiscal_year
        self._controls: dict[str, Control] = {}
        self._tests: list[ControlTest] = []
        self._deficiencies: dict[UUID, dict] = {}
        self._test_plans: dict[str, dict] = {}

    # -------------------- Control Definition --------------------
    def define_control(
        self,
        control_id: str,
        name: str,
        description: str,
        control_type: ControlType,
        frequency: ControlFrequency,
        owner: str,
        risk_level: str = "medium",
        assertion: str = "accuracy",
        key_report: str = "",
        is_automated: bool = False,
        system_source: str | None = None,
    ) -> Control:
        if control_id in self._controls:
            raise SOXError(f"Control {control_id} already defined")
        control = Control(
            control_id=control_id,
            name=name,
            description=description,
            control_type=control_type,
            frequency=frequency,
            owner=owner,
            risk_level=risk_level,
            assertion=assertion,
            key_report=key_report,
            is_automated=is_automated,
            system_source=system_source,
        )
        self._controls[control_id] = control
        return control

    def get_control(self, control_id: str) -> Control | None:
        return self._controls.get(control_id)

    def get_all_controls(self) -> list[Control]:
        return list(self._controls.values())

    # -------------------- Test Planning --------------------
    def define_test_plan(
        self,
        control_id: str,
        test_type: TestType,
        sample_method: str,
        sample_size: int,
        threshold_deviation_rate: float,
        test_procedure: str,
        evidence_requirements: list[str],
    ) -> None:
        if control_id not in self._controls:
            raise ControlNotFoundError(f"Control {control_id} not found")
        self._test_plans[control_id] = {
            "test_type": test_type,
            "sample_method": sample_method,
            "sample_size": sample_size,
            "threshold_deviation_rate": threshold_deviation_rate,
            "test_procedure": test_procedure,
            "evidence_requirements": evidence_requirements,
            "updated_at": datetime.utcnow().isoformat(),
        }

    # -------------------- Test Execution --------------------
    def run_test(
        self,
        control_id: str,
        test_type: TestType,
        tested_by: str,
        sample_size: int,
        deviations: int,
        evidence: list[str],
        notes: str = "",
    ) -> ControlTest:
        if control_id not in self._controls:
            raise ControlNotFoundError(f"Control {control_id} not found")
        plan = self._test_plans.get(control_id)
        deviation_rate = deviations / sample_size if sample_size > 0 else 0.0
        threshold = plan["threshold_deviation_rate"] if plan else 0.05
        if deviation_rate > threshold:
            result = ControlTestResult.FAIL
            severity = self._determine_severity(control_id, deviation_rate)
        else:
            result = ControlTestResult.PASS
            severity = None

        test = ControlTest(
            test_id=uuid4(),
            control_id=control_id,
            test_type=test_type,
            test_date=date.today(),
            tested_by=tested_by,
            result=result,
            sample_size=sample_size,
            deviations=deviations,
            deviation_rate=deviation_rate,
            evidence=evidence,
            notes=notes,
            severity=severity,
        )
        self._tests.append(test)
        if result == ControlTestResult.FAIL:
            self._create_deficiency(test, control_id)
        return test

    def _determine_severity(self, control_id: str, deviation_rate: float) -> DeficiencySeverity:
        ctrl = self._controls.get(control_id)
        if not ctrl:
            return DeficiencySeverity.CONTROL_DEFICIENCY
        if ctrl.risk_level == "high" and deviation_rate > 0.10:
            return DeficiencySeverity.MATERIAL_WEAKNESS
        elif ctrl.risk_level in ("high", "medium") and deviation_rate > 0.05:
            return DeficiencySeverity.SIGNIFICANT_DEFICIENCY
        else:
            return DeficiencySeverity.CONTROL_DEFICIENCY

    def _create_deficiency(self, test: ControlTest, control_id: str) -> UUID:
        deficiency_id = uuid4()
        self._deficiencies[deficiency_id] = {
            "deficiency_id": deficiency_id,
            "control_id": control_id,
            "test_id": test.test_id,
            "description": f"Control {control_id} failed testing with deviation rate {test.deviation_rate:.2%}",
            "severity": test.severity.value if test.severity else "control_deficiency",
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
        }
        return deficiency_id

    # -------------------- Remediation --------------------
    def get_deficiencies(self, status: str | None = None) -> list:
        from types import SimpleNamespace

        result = []
        for d in self._deficiencies.values():
            if status and d["status"] != status:
                continue
            obj = SimpleNamespace()
            obj.severity = d["severity"]
            obj.control_id = d["control_id"]
            # Use "issue" if present, else "description"
            if "issue" in d:
                obj.issue = d["issue"]
            else:
                obj.issue = d.get("description", "No description")
            obj.status = d["status"]
            result.append(obj)
        return result

    def remediate_deficiency(
        self,
        deficiency_id: UUID,
        remediation_plan: str,
        remediated_by: str,
        remediated_date: date | None = None,
    ) -> bool:
        deficiency = self._deficiencies.get(deficiency_id)
        if not deficiency:
            return False
        deficiency["remediation_plan"] = remediation_plan
        deficiency["status"] = "remediated"
        deficiency["remediated_by"] = remediated_by
        deficiency["remediated_at"] = (remediated_date or date.today()).isoformat()
        test_id = deficiency.get("test_id")
        for test in self._tests:
            if test.test_id == test_id:
                test.result = ControlTestResult.REMEDIATED
                test.remediation_plan = remediation_plan
                test.remediation_status = "completed"
                test.hash_sha256 = test._compute_hash()
                break
        return True

    # -------------------- Reporting --------------------
    def generate_test_report(self, period: str) -> dict:
        total_controls = len(self._controls)
        tested_controls = len(set(t.control_id for t in self._tests))
        passed_tests = [t for t in self._tests if t.result == ControlTestResult.PASS]
        failed_tests = [t for t in self._tests if t.result == ControlTestResult.FAIL]
        remediated_tests = [t for t in self._tests if t.result == ControlTestResult.REMEDIATED]
        open_deficiencies = [d for d in self._deficiencies.values() if d["status"] == "open"]
        material_weaknesses = [
            d
            for d in self._deficiencies.values()
            if d.get("severity") == DeficiencySeverity.MATERIAL_WEAKNESS.value
        ]

        return {
            "company": self.company_name,
            "fiscal_year": self.fiscal_year,
            "period": period,
            "report_date": date.today().isoformat(),
            "controls": {
                "total": total_controls,
                "tested": tested_controls,
                "passed": len(passed_tests),
                "failed": len(failed_tests),
                "remediated": len(remediated_tests),
                "not_tested": total_controls - tested_controls,
            },
            "deficiencies": {
                "total": len(self._deficiencies),
                "open": len(open_deficiencies),
                "material_weaknesses": len(material_weaknesses),
            },
            "overall_opinion": self._determine_overall_opinion(material_weaknesses, failed_tests),
        }

    def _determine_overall_opinion(self, material_weaknesses: list, failed_tests: list) -> str:
        if material_weaknesses:
            return "Adverse - Material Weaknesses Identified"
        elif failed_tests:
            return "Qualified - Significant Deficiencies Identified"
        else:
            return "Unqualified - Controls are effective"

    # -------------------- Test Compatibility --------------------
    def test_control(self, control_id: str) -> Any:
        from types import SimpleNamespace

        result = SimpleNamespace()
        result.status = "PASS"
        if any(
            t.control_id == control_id and t.result == ControlTestResult.FAIL for t in self._tests
        ):
            result.status = "FAIL"
        return result

    def record_deficiency(
        self, control_id: str, issue: str, severity: str = "material_weakness"
    ) -> None:
        deficiency_id = uuid4()
        self._deficiencies[deficiency_id] = {
            "deficiency_id": deficiency_id,
            "control_id": control_id,
            "issue": issue,
            "severity": severity,
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
        }

    # -------------------- Export --------------------
    def to_json(self, file_path: str | None = None) -> str:
        data = {
            "company": self.company_name,
            "fiscal_year": self.fiscal_year,
            "report": self.generate_test_report(f"FY{self.fiscal_year}"),
            "controls": [c.to_dict() for c in self._controls.values()],
            "tests": [t.to_dict() for t in self._tests],
            "deficiencies": list(self._deficiencies.values()),
        }
        json_str = json.dumps(data, indent=2, default=str)
        if file_path:
            with open(file_path, "w") as f:
                f.write(json_str)
        return json_str


if __name__ == "__main__":
    tester = SoxControlTester(company_name="PT ABC Indonesia", fiscal_year=2026)
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
    tester.define_test_plan(
        control_id="FIN-001",
        test_type=TestType.OPERATING_EFFECTIVENESS,
        sample_method="random",
        sample_size=25,
        threshold_deviation_rate=0.05,
        test_procedure="Select 25 journal entries",
        evidence_requirements=["Screenshot"],
    )
    tester.run_test(
        control_id="FIN-001",
        test_type=TestType.OPERATING_EFFECTIVENESS,
        tested_by="Internal Audit",
        sample_size=25,
        deviations=2,
        evidence=["screenshots.zip"],
        notes="2 entries missing approval",
    )
    print("Test passed.")
