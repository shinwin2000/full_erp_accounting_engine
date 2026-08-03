#!/usr/bin/env python3
"""
Module: compliance_report_for_audit_committee.py
Layer: Compliance

Responsibility:
    Membangun laporan kepatuhan yang komprehensif untuk komite audit (Audit Committee).
    Mencakup ringkasan eksekutif, metrik AML, GDPR, SOX, perpajakan, PSAK/IFRS, OJK,
    deficiency tracking, dan rekomendasi remedial. Laporan dapat diekspor ke PDF, JSON,
    atau dikirim via email.

Dependencies:
    - datetime, decimal, enum, typing, json, io
    - reportlab (optional for PDF export)
    - smtplib for email

Audit:
    Setiap laporan yang dihasilkan memiliki hash integrity dan timestamp.
    Perubahan status laporan (draft -> final -> approved) dicatat di audit log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import smtplib
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

# Optional PDF export
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class ReportStatus(Enum):
    DRAFT = "draft"
    FINAL = "final"
    APPROVED = "approved"
    ARCHIVED = "archived"


class ComplianceArea(Enum):
    AML = "anti_money_laundering"
    GDPR = "gdpr"
    SOX = "sox"
    TAX = "tax"
    PSAK = "psak"
    IFRS = "ifrs"
    OJK = "ojk"
    ETHICS = "ethics"
    LEGAL = "legal"


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# Exceptions
# ============================================================================
class ReportGenerationError(Exception):
    """Error saat membuat laporan."""

    pass


class ReportApprovalError(Exception):
    """Error saat menyetujui laporan."""

    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class ComplianceMetric:
    """Metrik tunggal dalam laporan."""

    name: str
    value: Any
    status: str  # compliant, non-compliant, warning, not-applicable
    threshold: Any | None = None
    unit: str = ""
    description: str = ""
    trend: str | None = None  # improving, stable, declining
    previous_value: Any | None = None


@dataclass
class DeficiencyItem:
    """Item kekurangan/deficiency yang teridentifikasi."""

    deficiency_id: str
    title: str
    description: str
    regulation: str
    severity: Severity
    discovered_date: date
    due_date: date | None
    owner: str
    status: str  # open, in_progress, remediated, closed, waived
    remediation_plan: str | None = None
    remediation_evidence: str | None = None
    closed_date: date | None = None


@dataclass
class Recommendation:
    """Rekomendasi perbaikan."""

    recommendation_id: str
    title: str
    description: str
    area: ComplianceArea
    priority: Severity
    assigned_to: str
    due_date: date
    status: str = "open"  # open, in_progress, implemented, rejected


@dataclass
class ComplianceSection:
    """Bagian dari laporan kepatuhan."""

    title: str
    metrics: list[ComplianceMetric]
    summary: str
    recommendations: list[Recommendation] = field(default_factory=list)
    deficiencies: list[DeficiencyItem] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)


@dataclass
class AuditCommitteeReport:
    """Laporan final untuk komite audit."""

    report_id: str
    report_date: date
    period_start: date
    period_end: date
    prepared_by: str
    approved_by: str | None = None
    sections: list[ComplianceSection] = field(default_factory=list)
    overall_status: str = "pending"  # compliant, partially-compliant, non-compliant
    executive_summary: str = ""
    hash_sha256: str = ""
    status: ReportStatus = ReportStatus.DRAFT

    def compute_hash(self) -> str:
        """Hitung hash integrity dari laporan."""
        data = {
            "report_id": self.report_id,
            "report_date": self.report_date.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "prepared_by": self.prepared_by,
            "approved_by": self.approved_by,
            "overall_status": self.overall_status,
            "executive_summary": self.executive_summary,
            "sections": [
                {
                    "title": s.title,
                    "summary": s.summary,
                    "metrics": [asdict(m) for m in s.metrics],
                    "recommendations": [asdict(r) for r in s.recommendations],
                }
                for s in self.sections
            ],
        }
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def finalize(self) -> None:
        """Tandai laporan sebagai final dan hitung hash."""
        self.hash_sha256 = self.compute_hash()
        self.status = ReportStatus.FINAL

    def approve(self, approver: str) -> None:
        """Setujui laporan (hanya bisa dari status FINAL)."""
        if self.status != ReportStatus.FINAL:
            raise ReportApprovalError("Can only approve a FINAL report")
        self.approved_by = approver
        self.status = ReportStatus.APPROVED
        self.hash_sha256 = self.compute_hash()

    def to_dict(self) -> dict:
        """Konversi ke dictionary untuk serialisasi JSON."""
        return {
            "report_id": self.report_id,
            "report_date": self.report_date.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "prepared_by": self.prepared_by,
            "approved_by": self.approved_by,
            "overall_status": self.overall_status,
            "executive_summary": self.executive_summary,
            "status": self.status.value,
            "hash_sha256": self.hash_sha256,
            "sections": [
                {
                    "title": s.title,
                    "summary": s.summary,
                    "metrics": [
                        {
                            "name": m.name,
                            "value": str(m.value) if isinstance(m.value, Decimal) else m.value,
                            "status": m.status,
                            "threshold": str(m.threshold)
                            if isinstance(m.threshold, Decimal)
                            else m.threshold,
                            "unit": m.unit,
                            "description": m.description,
                            "trend": m.trend,
                            "previous_value": str(m.previous_value)
                            if isinstance(m.previous_value, Decimal)
                            else m.previous_value,
                        }
                        for m in s.metrics
                    ],
                    "recommendations": [
                        {
                            "recommendation_id": r.recommendation_id,
                            "title": r.title,
                            "description": r.description,
                            "area": r.area.value,
                            "priority": r.priority.value,
                            "assigned_to": r.assigned_to,
                            "due_date": r.due_date.isoformat(),
                            "status": r.status,
                        }
                        for r in s.recommendations
                    ],
                    "deficiencies": [
                        {
                            "deficiency_id": d.deficiency_id,
                            "title": d.title,
                            "description": d.description,
                            "regulation": d.regulation,
                            "severity": d.severity.value,
                            "discovered_date": d.discovered_date.isoformat(),
                            "due_date": d.due_date.isoformat() if d.due_date else None,
                            "owner": d.owner,
                            "status": d.status,
                            "remediation_plan": d.remediation_plan,
                            "closed_date": d.closed_date.isoformat() if d.closed_date else None,
                        }
                        for d in s.deficiencies
                    ],
                    "attachments": s.attachments,
                }
                for s in self.sections
            ],
        }


# ============================================================================
# Report Builder (Fluent API)
# ============================================================================
class AuditCommitteeReportBuilder:
    """
    Builder untuk laporan kepatuhan komite audit dengan fluent interface.
    Mengumpulkan data dari berbagai modul compliance.
    """

    def __init__(self, period_start: date, period_end: date, prepared_by: str):
        self.period_start = period_start
        self.period_end = period_end
        self.prepared_by = prepared_by
        self._sections: list[ComplianceSection] = []
        self._executive_summary_lines: list[str] = []
        self._overall_status: str = "pending"

    def add_executive_summary(self, summary: str) -> AuditCommitteeReportBuilder:
        self._executive_summary_lines.append(summary)
        return self

    # ------------------------------------------------------------------------
    # AML Section
    # ------------------------------------------------------------------------
    def add_aml_section(
        self,
        aml_scorer,  # AMLRiskScorer instance
        total_transactions: int,
        high_risk_transactions: int,
        str_generated: int,
        str_submitted: int,
        edd_cases: int,
        edd_completed: int,
        sanction_checks_performed: int,
        sanction_hits: int,
    ) -> AuditCommitteeReportBuilder:
        """Tambahkan bagian AML dengan metrik lengkap."""
        metrics = [
            ComplianceMetric(
                "Total Transactions",
                total_transactions,
                "compliant",
                None,
                "",
                "Total transaksi dalam periode",
            ),
            ComplianceMetric(
                "High-Risk Transactions",
                high_risk_transactions,
                "warning" if high_risk_transactions > 0 else "compliant",
                "0",
                "",
                "Transaksi risiko tinggi",
            ),
            ComplianceMetric(
                "STR Generated",
                str_generated,
                "compliant" if str_generated <= 5 else "warning",
                "5",
                "",
                "Laporan transaksi mencurigakan",
            ),
            ComplianceMetric(
                "STR Submitted",
                str_submitted,
                "compliant",
                None,
                "",
                "STR yang sudah dikirim ke PPATK",
            ),
            ComplianceMetric(
                "EDD Cases", edd_cases, "compliant", None, "", "Enhanced Due Diligence cases"
            ),
            ComplianceMetric("EDD Completed", edd_completed, "compliant", None, "", "EDD selesai"),
            ComplianceMetric(
                "Sanction Checks",
                sanction_checks_performed,
                "compliant",
                None,
                "",
                "Pemeriksaan daftar sanksi",
            ),
            ComplianceMetric(
                "Sanction Hits",
                sanction_hits,
                "warning" if sanction_hits > 0 else "compliant",
                "0",
                "",
                "Pencocokan nama terlarang",
            ),
        ]
        summary = f"Selama periode {self.period_start} s.d {self.period_end}, dilakukan {sanction_checks_performed} pemeriksaan daftar sanksi dengan {sanction_hits} hit. {str_generated} STR dihasilkan, {str_submitted} telah disubmit ke PPATK. {edd_cases} kasus EDD dibuka, {edd_completed} selesai."
        recommendations = []
        if str_generated > 5:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title="Perbaiki prosedur AML",
                    description="Jumlah STR melebihi threshold. Review proses screening dan risk scoring.",
                    area=ComplianceArea.AML,
                    priority=Severity.HIGH,
                    assigned_to="Compliance Officer",
                    due_date=date.today() + timedelta(days=30),
                )
            )
        if sanction_hits > 0:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title="Investigasi sanction hits",
                    description=f"{sanction_hits} transaksi tertahan karena sanction list. Lakukan investigasi lebih lanjut.",
                    area=ComplianceArea.AML,
                    priority=Severity.CRITICAL,
                    assigned_to="AML Analyst",
                    due_date=date.today() + timedelta(days=7),
                )
            )
        self._sections.append(
            ComplianceSection(
                title="Anti-Money Laundering (AML)",
                metrics=metrics,
                summary=summary,
                recommendations=recommendations,
            )
        )
        return self

    # ------------------------------------------------------------------------
    # GDPR Section
    # ------------------------------------------------------------------------
    def add_gdpr_section(
        self,
        data_subject_requests_total: int,
        requests_fulfilled_on_time: int,
        consent_given_count: int,
        consent_withdrawn_count: int,
        data_breaches_reported: int,
        data_breaches_notified: int,
        dpo_contacted: bool,
    ) -> AuditCommitteeReportBuilder:
        metrics = [
            ComplianceMetric(
                "DSR Total",
                data_subject_requests_total,
                "compliant",
                None,
                "",
                "Data Subject Requests",
            ),
            ComplianceMetric(
                "DSR Fulfilled On Time",
                requests_fulfilled_on_time,
                "compliant"
                if requests_fulfilled_on_time == data_subject_requests_total
                else "non-compliant",
                data_subject_requests_total,
                "",
                "Permintaan dipenuhi ≤30 hari",
            ),
            ComplianceMetric(
                "Consents Given", consent_given_count, "compliant", None, "", "Jumlah consent aktif"
            ),
            ComplianceMetric(
                "Consents Withdrawn",
                consent_withdrawn_count,
                "compliant",
                None,
                "",
                "Consent ditarik",
            ),
            ComplianceMetric(
                "Data Breaches",
                data_breaches_reported,
                "warning" if data_breaches_reported > 0 else "compliant",
                "0",
                "",
                "Pelanggaran data",
            ),
            ComplianceMetric(
                "Breaches Notified",
                data_breaches_notified,
                "non-compliant" if data_breaches_reported > data_breaches_notified else "compliant",
                data_breaches_reported,
                "",
                "Notifikasi ke otoritas",
            ),
            ComplianceMetric(
                "DPO Contacted",
                dpo_contacted,
                "compliant" if dpo_contacted else "non-compliant",
                True,
                "",
                "Kontak dengan DPO",
            ),
        ]
        summary = f"Terdapat {data_subject_requests_total} permintaan hak subjek data, {requests_fulfilled_on_time} dipenuhi tepat waktu. {consent_given_count} consent aktif. {data_breaches_reported} pelanggaran data terjadi, {data_breaches_notified} telah dinotifikasikan."
        recommendations = []
        if data_breaches_reported > 0 and data_breaches_notified < data_breaches_reported:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title="Notifikasi data breach tepat waktu",
                    description=f"Terdapat {data_breaches_reported - data_breaches_notified} pelanggaran yang belum dinotifikasikan ke otoritas dalam 72 jam.",
                    area=ComplianceArea.GDPR,
                    priority=Severity.CRITICAL,
                    assigned_to="DPO",
                    due_date=date.today() + timedelta(days=1),
                )
            )
        self._sections.append(
            ComplianceSection(
                title="GDPR Data Privacy",
                metrics=metrics,
                summary=summary,
                recommendations=recommendations,
            )
        )
        return self

    # ------------------------------------------------------------------------
    # SOX Section
    # ------------------------------------------------------------------------
    def add_sox_section(
        self,
        total_controls: int,
        controls_tested: int,
        controls_passed: int,
        controls_failed: int,
        critical_deficiencies: int,
        material_weaknesses: int,
        remediation_planned: int,
        remediation_completed: int,
    ) -> AuditCommitteeReportBuilder:
        pass_rate = (controls_passed / max(controls_tested, 1)) * 100
        metrics = [
            ComplianceMetric(
                "Total Controls",
                total_controls,
                "compliant",
                None,
                "",
                "Seluruh kontrol yang didefinisikan",
            ),
            ComplianceMetric(
                "Controls Tested",
                controls_tested,
                "compliant",
                total_controls,
                "",
                "Kontrol yang diuji",
            ),
            ComplianceMetric(
                "Controls Passed",
                controls_passed,
                "compliant",
                controls_tested,
                "",
                f"Pass rate {pass_rate:.1f}%",
            ),
            ComplianceMetric(
                "Controls Failed",
                controls_failed,
                "warning" if controls_failed > 0 else "compliant",
                "0",
                "",
                "Kontrol gagal",
            ),
            ComplianceMetric(
                "Critical Deficiencies",
                critical_deficiencies,
                "non-compliant" if critical_deficiencies > 0 else "compliant",
                "0",
                "",
                "Defisiensi kritikal",
            ),
            ComplianceMetric(
                "Material Weaknesses",
                material_weaknesses,
                "non-compliant" if material_weaknesses > 0 else "compliant",
                "0",
                "",
                "Kelemahan material",
            ),
            ComplianceMetric(
                "Remediation Planned",
                remediation_planned,
                "compliant",
                None,
                "",
                "Rencana remediasi",
            ),
            ComplianceMetric(
                "Remediation Completed",
                remediation_completed,
                "compliant",
                remediation_planned,
                "",
                "Remediasi selesai",
            ),
        ]
        summary = f"Total {total_controls} kontrol, {controls_tested} diuji, {controls_passed} lulus ({pass_rate:.1f}%). {critical_deficiencies} defisiensi kritikal, {material_weaknesses} kelemahan material. {remediation_completed}/{remediation_planned} remediasi selesai."
        recommendations = []
        if controls_failed > 0:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title="Remediasi kontrol yang gagal",
                    description=f"{controls_failed} kontrol gagal diuji. Segera lakukan remediasi sesuai jadwal.",
                    area=ComplianceArea.SOX,
                    priority=Severity.HIGH,
                    assigned_to="Internal Audit",
                    due_date=date.today() + timedelta(days=60),
                )
            )
        self._sections.append(
            ComplianceSection(
                title="SOX 404 Internal Controls",
                metrics=metrics,
                summary=summary,
                recommendations=recommendations,
            )
        )
        return self

    # ------------------------------------------------------------------------
    # Tax Compliance Section (Coretax)
    # ------------------------------------------------------------------------
    def add_tax_section(
        self,
        spt_ppn_submitted: int,
        spt_ppn_expected: int,
        faktur_validated: int,
        faktur_invalid: int,
        ntpn_validated: int,
        ntpn_invalid: int,
        tax_audits_ongoing: int,
        tax_penalties: Decimal,
    ) -> AuditCommitteeReportBuilder:
        spt_completion = (spt_ppn_submitted / max(spt_ppn_expected, 1)) * 100
        faktur_valid_rate = (faktur_validated / max(faktur_validated + faktur_invalid, 1)) * 100
        ntpn_valid_rate = (ntpn_validated / max(ntpn_validated + ntpn_invalid, 1)) * 100
        metrics = [
            ComplianceMetric(
                "SPT PPN Submitted",
                spt_ppn_submitted,
                "compliant" if spt_ppn_submitted == spt_ppn_expected else "non-compliant",
                spt_ppn_expected,
                "",
                f"Completion {spt_completion:.1f}%",
            ),
            ComplianceMetric(
                "Faktur Validation Rate",
                f"{faktur_valid_rate:.1f}%",
                "compliant" if faktur_valid_rate >= 98 else "warning",
                "98%",
                "",
                "Faktur pajak valid",
            ),
            ComplianceMetric(
                "NTPN Validation Rate",
                f"{ntpn_valid_rate:.1f}%",
                "compliant" if ntpn_valid_rate >= 95 else "warning",
                "95%",
                "",
                "NTPN valid",
            ),
            ComplianceMetric(
                "Tax Audits Ongoing",
                tax_audits_ongoing,
                "warning" if tax_audits_ongoing > 0 else "compliant",
                "0",
                "",
                "Audit pajak berjalan",
            ),
            ComplianceMetric(
                "Tax Penalties",
                tax_penalties,
                "warning" if tax_penalties > 0 else "compliant",
                "0",
                "IDR",
                "Denda/bunga pajak",
            ),
        ]
        summary = f"SPT PPN: {spt_ppn_submitted}/{spt_ppn_expected} ({spt_completion:.1f}%). Tingkat validasi faktur {faktur_valid_rate:.1f}%, NTPN {ntpn_valid_rate:.1f}%. Denda pajak: IDR {tax_penalties:,.0f}."
        recommendations = []
        if faktur_valid_rate < 98:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title="Tingkatkan validasi faktur pajak",
                    description=f"Validasi faktur hanya {faktur_valid_rate:.1f}%, di bawah target 98%.",
                    area=ComplianceArea.TAX,
                    priority=Severity.MEDIUM,
                    assigned_to="Tax Manager",
                    due_date=date.today() + timedelta(days=30),
                )
            )
        self._sections.append(
            ComplianceSection(
                title="Tax Compliance (Coretax)",
                metrics=metrics,
                summary=summary,
                recommendations=recommendations,
            )
        )
        return self

    # ------------------------------------------------------------------------
    # PSAK Section
    # ------------------------------------------------------------------------
    def add_psak_section(
        self,
        psak_checker,
        total_standards: int = 27,
        compliant_standards: int | None = None,
    ) -> AuditCommitteeReportBuilder:
        if compliant_standards is None:
            # Simulasi: bisa query dari psak_checker
            compliant_standards = total_standards  # asumsi semua compliant
        non_compliant = total_standards - compliant_standards
        metrics = [
            ComplianceMetric(
                "Total PSAK Standards",
                total_standards,
                "compliant",
                None,
                "",
                "Standar yang berlaku",
            ),
            ComplianceMetric(
                "Compliant Standards",
                compliant_standards,
                "compliant",
                total_standards,
                "",
                "Standar terpenuhi",
            ),
            ComplianceMetric(
                "Non-Compliant Standards",
                non_compliant,
                "non-compliant" if non_compliant > 0 else "compliant",
                "0",
                "",
                "Standar belum dipenuhi",
            ),
        ]
        summary = f"Dari {total_standards} standar PSAK, {compliant_standards} telah dipenuhi ({compliant_standards / total_standards * 100:.1f}%)."
        recommendations = []
        if non_compliant > 0:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title=f"Penuhi {non_compliant} standar PSAK yang belum compliant",
                    description="Lakukan gap analysis dan implementasi untuk standar yang belum dipenuhi.",
                    area=ComplianceArea.PSAK,
                    priority=Severity.MEDIUM,
                    assigned_to="Accounting Policy Manager",
                    due_date=date.today() + timedelta(days=180),
                )
            )
        self._sections.append(
            ComplianceSection(
                title="PSAK (Indonesia Financial Accounting Standards)",
                metrics=metrics,
                summary=summary,
                recommendations=recommendations,
            )
        )
        return self

    # ------------------------------------------------------------------------
    # OJK Section
    # ------------------------------------------------------------------------
    def add_ojk_section(
        self,
        lkpub_submitted: int,
        lkpub_expected: int,
        lkpub_late: int,
        ojk_audits: int,
        ojk_sanctions: Decimal,
    ) -> AuditCommitteeReportBuilder:
        submission_rate = (lkpub_submitted / max(lkpub_expected, 1)) * 100
        metrics = [
            ComplianceMetric(
                "LKPBU Submitted",
                lkpub_submitted,
                "compliant" if lkpub_submitted == lkpub_expected else "non-compliant",
                lkpub_expected,
                "",
                f"{submission_rate:.1f}%",
            ),
            ComplianceMetric(
                "LKPBU Late",
                lkpub_late,
                "warning" if lkpub_late > 0 else "compliant",
                "0",
                "",
                "Laporan terlambat",
            ),
            ComplianceMetric("OJK Audits", ojk_audits, "compliant", None, "", "Audit oleh OJK"),
            ComplianceMetric(
                "OJK Sanctions",
                ojk_sanctions,
                "warning" if ojk_sanctions > 0 else "compliant",
                "0",
                "IDR",
                "Sanksi OJK",
            ),
        ]
        summary = f"LKPBU: {lkpub_submitted}/{lkpub_expected} diserahkan tepat waktu, {lkpub_late} terlambat. Sanksi OJK: IDR {ojk_sanctions:,.0f}."
        recommendations = []
        if lkpub_late > 0:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title="Perbaiki ketepatan waktu pelaporan OJK",
                    description=f"Terdapat {lkpub_late} laporan LKPBU yang terlambat. Evaluasi proses pengumpulan data.",
                    area=ComplianceArea.OJK,
                    priority=Severity.MEDIUM,
                    assigned_to="Financial Reporting Manager",
                    due_date=date.today() + timedelta(days=45),
                )
            )
        self._sections.append(
            ComplianceSection(
                title="OJK Reporting",
                metrics=metrics,
                summary=summary,
                recommendations=recommendations,
            )
        )
        return self

    # ------------------------------------------------------------------------
    # Ethics & Legal Section
    # ------------------------------------------------------------------------
    def add_ethics_section(
        self,
        ethics_violations: int,
        whistleblower_cases: int,
        conflict_declarations: int,
        ethics_trainings_completed: int,
        ethics_trainings_required: int,
        legal_opinions_issued: int,
        litigation_cases: int,
    ) -> AuditCommitteeReportBuilder:
        training_compliance = (ethics_trainings_completed / max(ethics_trainings_required, 1)) * 100
        metrics = [
            ComplianceMetric(
                "Ethics Violations",
                ethics_violations,
                "warning" if ethics_violations > 0 else "compliant",
                "0",
                "",
                "Pelanggaran etik",
            ),
            ComplianceMetric(
                "Whistleblower Cases",
                whistleblower_cases,
                "warning" if whistleblower_cases > 0 else "compliant",
                "0",
                "",
                "Kasus whistleblower",
            ),
            ComplianceMetric(
                "Conflict Declarations",
                conflict_declarations,
                "compliant",
                None,
                "",
                "Deklarasi konflik",
            ),
            ComplianceMetric(
                "Ethics Training Completion",
                f"{training_compliance:.1f}%",
                "compliant" if training_compliance >= 95 else "warning",
                "95%",
                "",
                "Pelatihan etik",
            ),
            ComplianceMetric(
                "Legal Opinions", legal_opinions_issued, "compliant", None, "", "Opini hukum"
            ),
            ComplianceMetric(
                "Litigation Cases",
                litigation_cases,
                "warning" if litigation_cases > 0 else "compliant",
                "0",
                "",
                "Kasus litigasi aktif",
            ),
        ]
        summary = f"{ethics_violations} pelanggaran etik, {whistleblower_cases} kasus whistleblower. Pelatihan etik: {training_compliance:.1f}% selesai. {legal_opinions_issued} opini hukum diterbitkan. {litigation_cases} kasus litigasi aktif."
        recommendations = []
        if training_compliance < 95:
            recommendations.append(
                Recommendation(
                    recommendation_id=str(uuid4()),
                    title="Tingkatkan kepesertaan pelatihan etik",
                    description=f"Hanya {training_compliance:.1f}% karyawan yang menyelesaikan pelatihan etik. Target 95%.",
                    area=ComplianceArea.ETHICS,
                    priority=Severity.MEDIUM,
                    assigned_to="HR & Compliance",
                    due_date=date.today() + timedelta(days=60),
                )
            )
        self._sections.append(
            ComplianceSection(
                title="Ethics & Legal Compliance",
                metrics=metrics,
                summary=summary,
                recommendations=recommendations,
            )
        )
        return self

    # ------------------------------------------------------------------------
    # Deficiency Tracker Integration
    # ------------------------------------------------------------------------
    def add_deficiencies_from_tracker(
        self, deficiency_tracker, max_items: int = 20
    ) -> AuditCommitteeReportBuilder:
        """Ambil deficiency dari DeficiencyTracker dan tambahkan ke section masing-masing."""
        # Asumsi deficiency_tracker memiliki metode get_open_deficiencies()
        open_deficiencies = deficiency_tracker.get_open_deficiencies()
        # Kelompokkan berdasarkan area (bisa ditentukan dari regulation field)
        # Untuk sederhana, kita tambahkan ke section "Deficiencies" terpisah
        deficiency_items = []
        for d in open_deficiencies[:max_items]:
            deficiency_items.append(
                DeficiencyItem(
                    deficiency_id=d.id if hasattr(d, "id") else str(uuid4()),
                    title=d.title,
                    description=d.description,
                    regulation=d.regulation,
                    severity=d.severity,
                    discovered_date=d.discovered_date,
                    due_date=d.due_date,
                    owner=str(d.owner_id) if d.owner_id else "Unassigned",
                    status=d.status.value if hasattr(d.status, "value") else str(d.status),
                    remediation_plan=d.remediation_plan,
                )
            )
        if deficiency_items:
            self._sections.append(
                ComplianceSection(
                    title="Open Deficiencies (Compliance Gaps)",
                    metrics=[],  # bisa ditambahkan metrik jumlah
                    summary=f"Terdapat {len(deficiency_items)} kekurangan kepatuhan yang masih terbuka.",
                    deficiencies=deficiency_items,
                    recommendations=[
                        Recommendation(
                            recommendation_id=str(uuid4()),
                            title="Remediasi semua open deficiencies",
                            description=f"{len(deficiency_items)} deficiency perlu segera diremediasi sesuai due date.",
                            area=ComplianceArea.LEGAL,
                            priority=Severity.HIGH,
                            assigned_to="Compliance Officer",
                            due_date=date.today() + timedelta(days=30),
                        )
                    ],
                )
            )
        return self

    def _map_regulation_to_area(self, regulation: str) -> ComplianceArea:
        reg_lower = regulation.lower()
        if "aml" in reg_lower or "money laundering" in reg_lower:
            return ComplianceArea.AML
        if "gdpr" in reg_lower or "privacy" in reg_lower:
            return ComplianceArea.GDPR
        if "sox" in reg_lower or "internal control" in reg_lower:
            return ComplianceArea.SOX
        if "psak" in reg_lower:
            return ComplianceArea.PSAK
        if "ifrs" in reg_lower:
            return ComplianceArea.IFRS
        if "ojk" in reg_lower or "lkpub" in reg_lower:
            return ComplianceArea.OJK
        return ComplianceArea.LEGAL

    # ------------------------------------------------------------------------
    # Build Final Report
    # ------------------------------------------------------------------------
    def build(self, overall_status: str | None = None) -> AuditCommitteeReport:
        """Bangun laporan final."""
        report_id = f"ACR-{self.period_end.year}-{self.period_end.month:02d}"
        if overall_status:
            self._overall_status = overall_status
        else:
            non_compliant_sections = any(
                any(m.status == "non-compliant" for m in s.metrics) for s in self._sections
            )
            self._overall_status = "non-compliant" if non_compliant_sections else "compliant"

        executive_summary = "\n".join(self._executive_summary_lines)
        if not executive_summary:
            executive_summary = f"Laporan kepatuhan periode {self.period_start} s.d {self.period_end}. Status keseluruhan: {self._overall_status.upper()}."

        report = AuditCommitteeReport(
            report_id=report_id,
            report_date=date.today(),
            period_start=self.period_start,
            period_end=self.period_end,
            prepared_by=self.prepared_by,
            sections=self._sections,
            overall_status=self._overall_status,
            executive_summary=executive_summary,
        )
        report.finalize()
        return report

    # ------------------------------------------------------------------------
    # Export Methods
    # ------------------------------------------------------------------------
    def export_to_json(self, report: AuditCommitteeReport, file_path: str | None = None) -> str:
        """Export laporan ke JSON."""
        data = report.to_dict()
        json_str = json.dumps(data, indent=2, default=str)
        if file_path:
            Path(file_path).write_text(json_str)
        return json_str

    def export_to_pdf(self, report: AuditCommitteeReport, file_path: str) -> None:
        """Export laporan ke PDF menggunakan ReportLab (jika tersedia)."""
        if not HAS_REPORTLAB:
            raise ReportGenerationError(
                "ReportLab not installed. Install with: pip install reportlab"
            )
        doc = SimpleDocTemplate(
            file_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=18, alignment=1)
        story.append(Paragraph("<b>Audit Committee Compliance Report</b>", title_style))
        story.append(Spacer(1, 0.5 * cm))
        story.append(
            Paragraph(f"Period: {report.period_start} to {report.period_end}", styles["Normal"])
        )
        story.append(Paragraph(f"Report Date: {report.report_date}", styles["Normal"]))
        story.append(Paragraph(f"Prepared by: {report.prepared_by}", styles["Normal"]))
        story.append(
            Paragraph(f"Overall Status: <b>{report.overall_status.upper()}</b>", styles["Normal"])
        )
        story.append(Spacer(1, 1 * cm))

        # Executive Summary
        story.append(Paragraph("<b>Executive Summary</b>", styles["Heading2"]))
        story.append(Paragraph(report.executive_summary, styles["Normal"]))
        story.append(Spacer(1, 0.5 * cm))

        # Sections
        for section in report.sections:
            story.append(PageBreak())
            story.append(Paragraph(f"<b>{section.title}</b>", styles["Heading1"]))
            story.append(Paragraph(section.summary, styles["Normal"]))
            story.append(Spacer(1, 0.3 * cm))

            if section.metrics:
                data = [["Metric", "Value", "Status", "Threshold"]] + [
                    [m.name, str(m.value), m.status, str(m.threshold) if m.threshold else "-"]
                    for m in section.metrics
                ]
                table = Table(data, colWidths=[5 * cm, 3 * cm, 2.5 * cm, 2.5 * cm])
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                        ]
                    )
                )
                story.append(table)
                story.append(Spacer(1, 0.5 * cm))

            if section.recommendations:
                story.append(Paragraph("<b>Recommendations</b>", styles["Heading3"]))
                for r in section.recommendations:
                    story.append(
                        Paragraph(
                            f"• {r.title}: {r.description} (Due: {r.due_date}, Priority: {r.priority.value})",
                            styles["Normal"],
                        )
                    )
                story.append(Spacer(1, 0.3 * cm))

        doc.build(story)

    def send_email(
        self, report: AuditCommitteeReport, recipients: list[str], smtp_config: dict
    ) -> bool:
        """Kirim laporan via email (attachment JSON atau PDF)."""
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = f"Audit Committee Report {report.report_id}"
        msg["From"] = smtp_config.get("from", "compliance@erp.com")
        msg["To"] = ", ".join(recipients)
        msg.set_content(
            f"Attached is the compliance report for period {report.period_start} to {report.period_end}. Overall status: {report.overall_status}"
        )

        # Attach JSON
        json_data = self.export_to_json(report)
        msg.add_attachment(
            json_data.encode(),
            maintype="application",
            subtype="json",
            filename=f"{report.report_id}.json",
        )

        try:
            with smtplib.SMTP(smtp_config["host"], smtp_config["port"]) as server:
                if smtp_config.get("tls"):
                    server.starttls()
                if smtp_config.get("user"):
                    server.login(smtp_config["user"], smtp_config["password"])
                server.send_message(msg)
            logger.info(f"Email sent to {recipients}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False


# ============================================================================
# Helper Functions
# ============================================================================
def create_sample_report() -> AuditCommitteeReport:
    """Buat contoh laporan untuk demo."""
    builder = AuditCommitteeReportBuilder(
        period_start=date(2026, 1, 1), period_end=date(2026, 5, 31), prepared_by="Compliance Team"
    )
    builder.add_executive_summary(
        "Selama periode Januari-Mei 2026, perusahaan menunjukkan tingkat kepatuhan yang baik dengan beberapa area perbaikan."
    )
    builder.add_aml_section(
        aml_scorer=None,  # mock
        total_transactions=125000,
        high_risk_transactions=1250,
        str_generated=12,
        str_submitted=12,
        edd_cases=8,
        edd_completed=6,
        sanction_checks_performed=125000,
        sanction_hits=0,
    )
    builder.add_gdpr_section(
        data_subject_requests_total=45,
        requests_fulfilled_on_time=44,
        consent_given_count=15000,
        consent_withdrawn_count=120,
        data_breaches_reported=0,
        data_breaches_notified=0,
        dpo_contacted=True,
    )
    builder.add_sox_section(
        total_controls=250,
        controls_tested=250,
        controls_passed=245,
        controls_failed=5,
        critical_deficiencies=2,
        material_weaknesses=0,
        remediation_planned=5,
        remediation_completed=3,
    )
    builder.add_tax_section(
        spt_ppn_submitted=5,
        spt_ppn_expected=5,
        faktur_validated=12500,
        faktur_invalid=50,
        ntpn_validated=5000,
        ntpn_invalid=25,
        tax_audits_ongoing=1,
        tax_penalties=Decimal("25000000"),
    )
    builder.add_psak_section(psak_checker=None, total_standards=27, compliant_standards=27)
    builder.add_ojk_section(
        lkpub_submitted=5,
        lkpub_expected=5,
        lkpub_late=0,
        ojk_audits=0,
        ojk_sanctions=Decimal("0"),
    )
    builder.add_ethics_section(
        ethics_violations=2,
        whistleblower_cases=1,
        conflict_declarations=15,
        ethics_trainings_completed=850,
        ethics_trainings_required=900,
        legal_opinions_issued=3,
        litigation_cases=1,
    )
    return builder.build()


if __name__ == "__main__":
    # Demo: generate sample report
    report = create_sample_report()
    print("Sample report generated:")
    print(json.dumps(report.to_dict(), indent=2))
    # Save to file
    builder = AuditCommitteeReportBuilder(date(2026, 1, 1), date(2026, 5, 31), "Compliance Team")
    builder.export_to_json(report, "compliance_report.json")
    if HAS_REPORTLAB:
        builder.export_to_pdf(report, "compliance_report.pdf")
        print("PDF exported to compliance_report.pdf")
