# tests/compliance/test_compliance_report_for_audit_committee.py
# Comprehensive tests for compliance_report_for_audit_committee.py

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from compliance.compliance_report_for_audit_committee import (
    HAS_REPORTLAB,
    AuditCommitteeReport,
    AuditCommitteeReportBuilder,
    ComplianceArea,
    ComplianceMetric,
    ComplianceSection,
    DeficiencyItem,
    Recommendation,
    ReportApprovalError,
    ReportGenerationError,
    ReportStatus,
    Severity,
    create_sample_report,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_metric():
    return ComplianceMetric(
        name="Test Metric",
        value=100,
        status="compliant",
        threshold=90,
        unit="%",
        description="A test metric",
        trend="improving",
        previous_value=95,
    )


@pytest.fixture
def sample_deficiency():
    return DeficiencyItem(
        deficiency_id="DEF-001",
        title="Missing documentation",
        description="Some documents are missing",
        regulation="SOX 404",
        severity=Severity.MEDIUM,
        discovered_date=date(2026, 1, 15),
        due_date=date(2026, 3, 15),
        owner="John Doe",
        status="open",
        remediation_plan="Collect documents",
        remediation_evidence="",
        closed_date=None,
    )


@pytest.fixture
def sample_recommendation():
    return Recommendation(
        recommendation_id="REC-001",
        title="Improve controls",
        description="Implement additional controls",
        area=ComplianceArea.SOX,
        priority=Severity.HIGH,
        assigned_to="Internal Audit",
        due_date=date(2026, 6, 30),
        status="open",
    )


@pytest.fixture
def sample_section(sample_metric, sample_deficiency, sample_recommendation):
    return ComplianceSection(
        title="Test Section",
        metrics=[sample_metric],
        summary="Test summary",
        recommendations=[sample_recommendation],
        deficiencies=[sample_deficiency],
        attachments=["attachment1.pdf"],
    )


@pytest.fixture
def sample_report(sample_section):
    return AuditCommitteeReport(
        report_id="ACR-2026-05",
        report_date=date(2026, 5, 31),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 5, 31),
        prepared_by="Compliance Team",
        approved_by=None,
        sections=[sample_section],
        overall_status="compliant",
        executive_summary="Executive summary",
        hash_sha256="",
        status=ReportStatus.DRAFT,
    )


@pytest.fixture
def builder():
    return AuditCommitteeReportBuilder(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 5, 31),
        prepared_by="Compliance Team",
    )


# ============================================================================
# Tests for Enums (already present, we keep them)
# ============================================================================

class TestReportStatus:
    def test_members_exist(self):
        assert hasattr(ReportStatus, 'DRAFT')
        assert hasattr(ReportStatus, 'FINAL')
        assert hasattr(ReportStatus, 'APPROVED')
        assert hasattr(ReportStatus, 'ARCHIVED')

    def test_member_is_instance(self):
        assert isinstance(ReportStatus.DRAFT, ReportStatus)


class TestComplianceArea:
    def test_members_exist(self):
        assert hasattr(ComplianceArea, 'AML')
        assert hasattr(ComplianceArea, 'GDPR')
        assert hasattr(ComplianceArea, 'SOX')
        assert hasattr(ComplianceArea, 'TAX')
        assert hasattr(ComplianceArea, 'PSAK')
        assert hasattr(ComplianceArea, 'IFRS')
        assert hasattr(ComplianceArea, 'OJK')
        assert hasattr(ComplianceArea, 'ETHICS')
        assert hasattr(ComplianceArea, 'LEGAL')

    def test_member_is_instance(self):
        assert isinstance(ComplianceArea.AML, ComplianceArea)


class TestSeverity:
    def test_members_exist(self):
        assert hasattr(Severity, 'LOW')
        assert hasattr(Severity, 'MEDIUM')
        assert hasattr(Severity, 'HIGH')
        assert hasattr(Severity, 'CRITICAL')

    def test_member_is_instance(self):
        assert isinstance(Severity.LOW, Severity)


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestReportGenerationError:
    def test_raise(self):
        with pytest.raises(ReportGenerationError):
            raise ReportGenerationError("test")


class TestReportApprovalError:
    def test_raise(self):
        with pytest.raises(ReportApprovalError):
            raise ReportApprovalError("test")


# ============================================================================
# Tests for Data Classes
# ============================================================================

class TestComplianceMetric:
    def test_construction(self, sample_metric):
        assert sample_metric.name == "Test Metric"
        assert sample_metric.value == 100
        assert sample_metric.status == "compliant"

    def test_with_decimal_value(self):
        metric = ComplianceMetric(
            name="Tax Rate",
            value=Decimal("11.0"),
            status="compliant",
            threshold=Decimal("11.0"),
            unit="%",
        )
        # to_dict will convert Decimal to str
        assert isinstance(metric.value, Decimal)


class TestDeficiencyItem:
    def test_construction(self, sample_deficiency):
        assert sample_deficiency.deficiency_id == "DEF-001"
        assert sample_deficiency.severity == Severity.MEDIUM
        assert sample_deficiency.status == "open"


class TestRecommendation:
    def test_construction(self, sample_recommendation):
        assert sample_recommendation.recommendation_id == "REC-001"
        assert sample_recommendation.area == ComplianceArea.SOX
        assert sample_recommendation.priority == Severity.HIGH


class TestComplianceSection:
    def test_construction(self, sample_section):
        assert sample_section.title == "Test Section"
        assert len(sample_section.metrics) == 1
        assert len(sample_section.recommendations) == 1
        assert len(sample_section.deficiencies) == 1


# ============================================================================
# Tests for AuditCommitteeReport
# ============================================================================

class TestAuditCommitteeReport:
    def test_construction(self, sample_report):
        assert sample_report.report_id == "ACR-2026-05"
        assert sample_report.status == ReportStatus.DRAFT
        assert sample_report.hash_sha256 == ""  # not computed yet

    def test_compute_hash(self, sample_report):
        h = sample_report.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64  # SHA256
        # Same data yields same hash
        h2 = sample_report.compute_hash()
        assert h == h2
        # Different data yields different hash
        sample_report.executive_summary = "Different summary"
        h3 = sample_report.compute_hash()
        assert h != h3

    def test_finalize(self, sample_report):
        sample_report.finalize()
        assert sample_report.status == ReportStatus.FINAL
        assert sample_report.hash_sha256 != ""
        # Hash should match compute_hash
        expected = sample_report.compute_hash()
        assert sample_report.hash_sha256 == expected

    def test_approve_from_final(self, sample_report):
        sample_report.finalize()
        sample_report.approve("Audit Committee Chair")
        assert sample_report.status == ReportStatus.APPROVED
        assert sample_report.approved_by == "Audit Committee Chair"
        # Hash should be recomputed after approval
        expected = sample_report.compute_hash()
        assert sample_report.hash_sha256 == expected

    def test_approve_from_draft_raises(self, sample_report):
        # Report is DRAFT, not FINAL
        with pytest.raises(ReportApprovalError, match="Can only approve a FINAL report"):
            sample_report.approve("Approver")

    def test_to_dict(self, sample_report, sample_section):
        d = sample_report.to_dict()
        assert d["report_id"] == "ACR-2026-05"
        assert d["status"] == "draft"
        assert len(d["sections"]) == 1
        section = d["sections"][0]
        assert section["title"] == "Test Section"
        assert len(section["metrics"]) == 1
        assert len(section["recommendations"]) == 1
        assert len(section["deficiencies"]) == 1
        assert section["attachments"] == ["attachment1.pdf"]
        # Check metric with Decimal conversion
        metric = section["metrics"][0]
        assert metric["name"] == "Test Metric"


# ============================================================================
# Tests for AuditCommitteeReportBuilder
# ============================================================================

class TestAuditCommitteeReportBuilder:
    def test_construction(self, builder):
        assert builder.period_start == date(2026, 1, 1)
        assert builder.period_end == date(2026, 5, 31)
        assert builder.prepared_by == "Compliance Team"

    def test_add_executive_summary(self, builder):
        builder.add_executive_summary("First line")
        builder.add_executive_summary("Second line")
        assert builder._executive_summary_lines == ["First line", "Second line"]

    def test_build_without_sections(self, builder):
        report = builder.build()
        assert report.report_id == "ACR-2026-05"
        assert report.overall_status == "compliant"  # default
        assert report.status == ReportStatus.FINAL
        assert report.hash_sha256 != ""
        assert "Laporan kepatuhan periode" in report.executive_summary

    def test_build_with_overall_status(self, builder):
        report = builder.build(overall_status="non-compliant")
        assert report.overall_status == "non-compliant"

    def test_build_with_non_compliant_section(self, builder):
        # Add a section with non-compliant metric
        metric = ComplianceMetric(
            name="Test",
            value=0,
            status="non-compliant",
            threshold=1,
        )
        section = ComplianceSection(
            title="Test",
            metrics=[metric],
            summary="Test",
        )
        builder._sections.append(section)
        report = builder.build()
        assert report.overall_status == "non-compliant"

    # ---- add_aml_section ----
    def test_add_aml_section(self, builder):
        builder.add_aml_section(
            aml_scorer=None,
            total_transactions=1000,
            high_risk_transactions=10,
            str_generated=3,
            str_submitted=2,
            edd_cases=5,
            edd_completed=4,
            sanction_checks_performed=1000,
            sanction_hits=0,
        )
        assert len(builder._sections) == 1
        section = builder._sections[0]
        assert section.title == "Anti-Money Laundering (AML)"
        assert len(section.metrics) == 8
        assert section.metrics[0].name == "Total Transactions"
        # Check recommendations
        assert len(section.recommendations) == 0  # STR <=5, sanctions=0

    def test_add_aml_section_with_recommendations(self, builder):
        builder.add_aml_section(
            aml_scorer=None,
            total_transactions=1000,
            high_risk_transactions=10,
            str_generated=6,  # >5 triggers recommendation
            str_submitted=2,
            edd_cases=5,
            edd_completed=4,
            sanction_checks_performed=1000,
            sanction_hits=2,  # >0 triggers recommendation
        )
        section = builder._sections[0]
        assert len(section.recommendations) == 2
        assert "Perbaiki prosedur AML" in section.recommendations[0].title
        assert "Investigasi sanction hits" in section.recommendations[1].title

    # ---- add_gdpr_section ----
    def test_add_gdpr_section(self, builder):
        builder.add_gdpr_section(
            data_subject_requests_total=10,
            requests_fulfilled_on_time=10,
            consent_given_count=100,
            consent_withdrawn_count=5,
            data_breaches_reported=0,
            data_breaches_notified=0,
            dpo_contacted=True,
        )
        section = builder._sections[0]
        assert section.title == "GDPR Data Privacy"
        assert len(section.metrics) == 7
        assert section.metrics[0].name == "DSR Total"
        assert len(section.recommendations) == 0

    def test_add_gdpr_section_with_breach_notification_issue(self, builder):
        builder.add_gdpr_section(
            data_subject_requests_total=10,
            requests_fulfilled_on_time=8,
            consent_given_count=100,
            consent_withdrawn_count=5,
            data_breaches_reported=3,
            data_breaches_notified=1,
            dpo_contacted=True,
        )
        section = builder._sections[0]
        assert len(section.recommendations) == 1
        assert "Notifikasi data breach tepat waktu" in section.recommendations[0].title

    # ---- add_sox_section ----
    def test_add_sox_section(self, builder):
        builder.add_sox_section(
            total_controls=100,
            controls_tested=100,
            controls_passed=98,
            controls_failed=2,
            critical_deficiencies=0,
            material_weaknesses=0,
            remediation_planned=2,
            remediation_completed=1,
        )
        section = builder._sections[0]
        assert section.title == "SOX 404 Internal Controls"
        assert len(section.metrics) == 8
        assert len(section.recommendations) == 1  # controls_failed > 0
        assert "Remediasi kontrol yang gagal" in section.recommendations[0].title

    def test_add_sox_section_all_passed(self, builder):
        builder.add_sox_section(
            total_controls=100,
            controls_tested=100,
            controls_passed=100,
            controls_failed=0,
            critical_deficiencies=0,
            material_weaknesses=0,
            remediation_planned=0,
            remediation_completed=0,
        )
        section = builder._sections[0]
        assert len(section.recommendations) == 0

    # ---- add_tax_section ----
    def test_add_tax_section(self, builder):
        builder.add_tax_section(
            spt_ppn_submitted=5,
            spt_ppn_expected=5,
            faktur_validated=1000,
            faktur_invalid=10,
            ntpn_validated=500,
            ntpn_invalid=5,
            tax_audits_ongoing=0,
            tax_penalties=Decimal(0),
        )
        section = builder._sections[0]
        assert section.title == "Tax Compliance (Coretax)"
        assert len(section.metrics) == 5
        # Check metric values
        assert section.metrics[0].name == "SPT PPN Submitted"
        assert section.metrics[0].status == "compliant"  # submitted == expected
        # faktur validation rate should be ~99%, so compliant
        assert section.metrics[1].status == "compliant"
        # ntpn validation rate ~99%, compliant
        assert section.metrics[2].status == "compliant"
        assert len(section.recommendations) == 0

    def test_add_tax_section_with_issues(self, builder):
        builder.add_tax_section(
            spt_ppn_submitted=4,
            spt_ppn_expected=5,
            faktur_validated=900,
            faktur_invalid=100,  # 90% valid
            ntpn_validated=400,
            ntpn_invalid=100,  # 80% valid
            tax_audits_ongoing=1,
            tax_penalties=Decimal("50000000"),
        )
        section = builder._sections[0]
        # Non-compliant SPT
        assert section.metrics[0].status == "non-compliant"
        # Faktur validation rate = 90%, warning
        assert section.metrics[1].status == "warning"
        # NTPN validation 80%, warning
        assert section.metrics[2].status == "warning"
        # Recommendations
        assert len(section.recommendations) == 1
        assert "Tingkatkan validasi faktur pajak" in section.recommendations[0].title

    # ---- add_psak_section ----
    def test_add_psak_section(self, builder):
        builder.add_psak_section(psak_checker=None, total_standards=27, compliant_standards=27)
        section = builder._sections[0]
        assert section.title == "PSAK (Indonesia Financial Accounting Standards)"
        assert len(section.metrics) == 3
        assert section.metrics[0].value == 27
        assert section.metrics[1].value == 27
        assert section.metrics[2].value == 0  # non-compliant
        assert len(section.recommendations) == 0

    def test_add_psak_section_with_non_compliant(self, builder):
        builder.add_psak_section(psak_checker=None, total_standards=27, compliant_standards=25)
        section = builder._sections[0]
        assert section.metrics[2].value == 2
        assert len(section.recommendations) == 1
        assert "Penuhi 2 standar PSAK" in section.recommendations[0].title

    # ---- add_ojk_section ----
    def test_add_ojk_section(self, builder):
        builder.add_ojk_section(
            lkpub_submitted=5,
            lkpub_expected=5,
            lkpub_late=0,
            ojk_audits=0,
            ojk_sanctions=Decimal(0),
        )
        section = builder._sections[0]
        assert section.title == "OJK Reporting"
        assert section.metrics[0].status == "compliant"
        assert len(section.recommendations) == 0

    def test_add_ojk_section_with_late_submissions(self, builder):
        builder.add_ojk_section(
            lkpub_submitted=4,
            lkpub_expected=5,
            lkpub_late=1,
            ojk_audits=1,
            ojk_sanctions=Decimal("10000000"),
        )
        section = builder._sections[0]
        assert section.metrics[0].status == "non-compliant"
        assert section.metrics[1].status == "warning"
        assert section.metrics[3].status == "warning"
        assert len(section.recommendations) == 1
        assert "Perbaiki ketepatan waktu pelaporan OJK" in section.recommendations[0].title

    # ---- add_ethics_section ----
    def test_add_ethics_section(self, builder):
        builder.add_ethics_section(
            ethics_violations=0,
            whistleblower_cases=0,
            conflict_declarations=10,
            ethics_trainings_completed=900,
            ethics_trainings_required=900,
            legal_opinions_issued=2,
            litigation_cases=0,
        )
        section = builder._sections[0]
        assert section.title == "Ethics & Legal Compliance"
        # training completion 100%, compliant
        assert section.metrics[3].status == "compliant"
        assert len(section.recommendations) == 0

    def test_add_ethics_section_with_issues(self, builder):
        builder.add_ethics_section(
            ethics_violations=1,
            whistleblower_cases=1,
            conflict_declarations=10,
            ethics_trainings_completed=800,
            ethics_trainings_required=900,  # 88.9%
            legal_opinions_issued=2,
            litigation_cases=1,
        )
        section = builder._sections[0]
        assert section.metrics[0].status == "warning"  # ethics_violations > 0
        assert section.metrics[3].status == "warning"  # training < 95%
        assert section.metrics[5].status == "warning"  # litigation_cases > 0
        assert len(section.recommendations) == 1
        assert "Tingkatkan kepesertaan pelatihan etik" in section.recommendations[0].title

    # ---- add_deficiencies_from_tracker ----
    def test_add_deficiencies_from_tracker(self, builder):
        # Mock deficiency tracker
        mock_tracker = MagicMock()
        mock_tracker.get_open_deficiencies.return_value = [
            DeficiencyItem(
                deficiency_id="D1",
                title="Missing control",
                description="Control missing",
                regulation="SOX 404",
                severity=Severity.HIGH,
                discovered_date=date(2026, 1, 1),
                due_date=date(2026, 6, 1),
                owner="Owner",
                status="open",
                remediation_plan="Plan",
            ),
            DeficiencyItem(
                deficiency_id="D2",
                title="Data privacy gap",
                description="GDPR issue",
                regulation="GDPR",
                severity=Severity.MEDIUM,
                discovered_date=date(2026, 2, 1),
                due_date=date(2026, 7, 1),
                owner="DPO",
                status="in_progress",
                remediation_plan="Plan2",
            ),
        ]
        builder.add_deficiencies_from_tracker(mock_tracker, max_items=20)
        section = builder._sections[0]
        assert section.title == "Open Deficiencies (Compliance Gaps)"
        assert len(section.deficiencies) == 2
        assert section.deficiencies[0].title == "Missing control"
        assert section.deficiencies[1].title == "Data privacy gap"
        assert len(section.recommendations) == 1
        assert "Remediasi semua open deficiencies" in section.recommendations[0].title

    def test_add_deficiencies_from_tracker_empty(self, builder):
        mock_tracker = MagicMock()
        mock_tracker.get_open_deficiencies.return_value = []
        builder.add_deficiencies_from_tracker(mock_tracker)
        assert len(builder._sections) == 0  # no section added

    def test_add_deficiencies_from_tracker_limits(self, builder):
        mock_tracker = MagicMock()
        deficiencies = []
        for i in range(30):
            deficiencies.append(
                DeficiencyItem(
                    deficiency_id=f"D{i}",
                    title=f"Deficiency {i}",
                    description="desc",
                    regulation="Reg",
                    severity=Severity.MEDIUM,
                    discovered_date=date.today(),
                    due_date=date.today() + timedelta(days=30),
                    owner="Owner",
                    status="open",
                )
            )
        mock_tracker.get_open_deficiencies.return_value = deficiencies
        builder.add_deficiencies_from_tracker(mock_tracker, max_items=5)
        section = builder._sections[0]
        assert len(section.deficiencies) == 5

    # ---- _map_regulation_to_area ----
    def test_map_regulation_to_area(self, builder):
        assert builder._map_regulation_to_area("AML policy") == ComplianceArea.AML
        assert builder._map_regulation_to_area("money laundering") == ComplianceArea.AML
        assert builder._map_regulation_to_area("GDPR privacy") == ComplianceArea.GDPR
        assert builder._map_regulation_to_area("Privacy policy") == ComplianceArea.GDPR
        assert builder._map_regulation_to_area("SOX 404") == ComplianceArea.SOX
        assert builder._map_regulation_to_area("Internal control") == ComplianceArea.SOX
        assert builder._map_regulation_to_area("PSAK 73") == ComplianceArea.PSAK
        assert builder._map_regulation_to_area("IFRS 16") == ComplianceArea.IFRS
        assert builder._map_regulation_to_area("OJK regulation") == ComplianceArea.OJK
        assert builder._map_regulation_to_area("LKPBU") == ComplianceArea.OJK
        assert builder._map_regulation_to_area("Unknown regulation") == ComplianceArea.LEGAL

    # ---- export_to_json ----
    def test_export_to_json(self, builder, tmp_path):
        report = builder.build()
        file_path = tmp_path / "report.json"
        builder.export_to_json(report, str(file_path))
        assert file_path.exists()
        data = json.loads(file_path.read_text())
        assert data["report_id"] == report.report_id
        # Test without file_path
        json_str2 = builder.export_to_json(report)
        assert json.loads(json_str2)["report_id"] == report.report_id

    # ---- export_to_pdf ----
    def test_export_to_pdf_not_installed(self, builder):
        report = builder.build()
        with patch("compliance.compliance_report_for_audit_committee.HAS_REPORTLAB", False):
            with pytest.raises(ReportGenerationError, match="ReportLab not installed"):
                builder.export_to_pdf(report, "report.pdf")

    @pytest.mark.skipif(not HAS_REPORTLAB, reason="ReportLab not installed")
    def test_export_to_pdf_installed(self, builder, tmp_path):
        report = builder.build()
        file_path = tmp_path / "report.pdf"
        builder.export_to_pdf(report, str(file_path))
        assert file_path.exists()
        assert file_path.stat().st_size > 0

    # ---- send_email ----
    def test_send_email(self, builder):
        report = builder.build()
        smtp_config = {
            "host": "smtp.example.com",
            "port": 587,
            "tls": True,
            "user": "user",
            "password": "pass",
            "from": "compliance@erp.com",
        }
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server
            result = builder.send_email(report, ["recipient@example.com"], smtp_config)
            assert result is True
            mock_smtp.assert_called_once_with("smtp.example.com", 587)
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("user", "pass")
            mock_server.send_message.assert_called_once()

    def test_send_email_failure(self, builder):
        report = builder.build()
        smtp_config = {"host": "smtp.example.com", "port": 587}
        with patch("smtplib.SMTP", side_effect=Exception("Connection error")):
            result = builder.send_email(report, ["recipient@example.com"], smtp_config)
            assert result is False


# ============================================================================
# Tests for create_sample_report
# ============================================================================

class TestCreateSampleReport:
    def test_create_sample_report(self):
        report = create_sample_report()
        assert isinstance(report, AuditCommitteeReport)
        assert report.report_id.startswith("ACR-")
        assert len(report.sections) >= 7  # AML, GDPR, SOX, Tax, PSAK, OJK, Ethics
        assert report.status == ReportStatus.FINAL
        assert report.hash_sha256 != ""
        # Check that overall_status is determined from sections
        assert report.overall_status in ("compliant", "non-compliant")
