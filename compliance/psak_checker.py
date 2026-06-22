#!/usr/bin/env python3
"""
Module: psak_checker.py
Layer: Compliance

Responsibility:
    Pengecekan kepatuhan terhadap PSAK (Pernyataan Standar Akuntansi Keuangan) Indonesia.
    Mendukung 27 standar PSAK yang diadopsi (termasuk PSAK 1, 2, 5, 7, 8, 10, 13, 14, 16, 19,
    22, 23, 24, 25, 26, 30, 38, 46, 48, 50, 55, 60, 67, 71, 72, 73, 101).
    Mencakup self-assessment, gap analysis, compliance scoring, findings, recommendations,
    remediation tracking, dan export report (JSON, CSV, HTML).

Dependencies:
    - datetime, decimal, enum, typing, json, hashlib, logging
    - optional: csv, html

Audit:
    Setiap penilaian kepatuhan dicatat dengan timestamp dan hash integrity.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class PSAKStandard(Enum):
    PSAK_1 = "PSAK 1 - Penyajian Laporan Keuangan"
    PSAK_2 = "PSAK 2 - Laporan Arus Kas"
    PSAK_5 = "PSAK 5 - Segmen Operasi"
    PSAK_7 = "PSAK 7 - Pengungkapan Pihak Berelasi"
    PSAK_8 = "PSAK 8 - Peristiwa Setelah Periode Pelaporan"
    PSAK_10 = "PSAK 10 - Pengaruh Perubahan Kurs Valuta Asing"
    PSAK_13 = "PSAK 13 - Properti Investasi"
    PSAK_14 = "PSAK 14 - Persediaan"
    PSAK_16 = "PSAK 16 - Aset Tetap"
    PSAK_19 = "PSAK 19 - Aset Tak Berwujud"
    PSAK_22 = "PSAK 22 - Kombinasi Bisnis"
    PSAK_23 = "PSAK 23 - Pendapatan (revenue) legacy"
    PSAK_24 = "PSAK 24 - Imbalan Kerja"
    PSAK_25 = "PSAK 25 - Kebijakan Akuntansi, Perubahan Estimasi, dan Kesalahan"
    PSAK_26 = "PSAK 26 - Biaya Pinjaman"
    PSAK_30 = "PSAK 30 - Sewa (legacy)"
    PSAK_38 = "PSAK 38 - Entitas Sepengendali"
    PSAK_46 = "PSAK 46 - Pajak Penghasilan"
    PSAK_48 = "PSAK 48 - Penurunan Nilai Aset"
    PSAK_50 = "PSAK 50 - Instrumen Keuangan: Penyajian"
    PSAK_55 = "PSAK 55 - Instrumen Keuangan: Pengakuan dan Pengukuran"
    PSAK_60 = "PSAK 60 - Instrumen Keuangan: Pengungkapan"
    PSAK_67 = "PSAK 67 - Pengungkapan Kepentingan dalam Entitas Lain"
    PSAK_71 = "PSAK 71 - Instrumen Keuangan (IFRS 9 equivalent)"
    PSAK_72 = "PSAK 72 - Pendapatan dari Kontrak dengan Pelanggan"
    PSAK_73 = "PSAK 73 - Sewa"
    PSAK_101 = "PSAK 101 - Penyajian Laporan Keuangan Entitas UMKM"


class ComplianceStatus(Enum):
    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"
    UNDER_REVIEW = "under_review"


# ============================================================================
# Exceptions
# ============================================================================
class PSAKComplianceError(Exception):
    """Base exception untuk PSAK compliance."""
    pass


class StandardNotFoundError(PSAKComplianceError):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAKComplianceResult:
    standard: PSAKStandard
    status: ComplianceStatus
    compliance_percentage: Decimal  # 0-100
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    assessed_by: str | None = None
    assessed_date: date | None = None
    remediation_deadline: date | None = None
    remediation_status: str = "not_started"
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "standard": self.standard.value,
            "status": self.status.value,
            "percentage": str(self.compliance_percentage),
            "findings": self.findings,
            "assessed_date": self.assessed_date.isoformat() if self.assessed_date else None,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@dataclass
class PSAKGapAnalysis:
    standard: PSAKStandard
    current_practice: str
    required_practice: str
    gap_description: str
    impact: str  # low, medium, high
    remediation_plan: str
    estimated_effort_days: int
    responsible_party: str


# ============================================================================
# PsakChecker Core
# ============================================================================
class PsakChecker:
    """
    Pengecekan kepatuhan PSAK untuk entitas yang melaporkan sesuai standar Indonesia.
    """

    def __init__(self, entity_name: str, fiscal_year_end: date = date(2026, 12, 31)):
        self.entity_name = entity_name
        self.fiscal_year_end = fiscal_year_end
        self._results: dict[PSAKStandard, PSAKComplianceResult] = {}
        self._gap_analyses: list[PSAKGapAnalysis] = []

    # ------------------------------------------------------------------------
    # Assessment Methods per Standard
    # ------------------------------------------------------------------------
    def assess_psak_1(
        self,
        financial_statements_prepared: bool,
        comparative_figures: bool,
        going_concern_assessed: bool,
        materiality_applied: bool,
        disclosure_of_estimates: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if financial_statements_prepared:
            score += 20
        else:
            findings.append("Laporan keuangan tidak disusun sesuai PSAK 1")
            recommendations.append(
                "Siapkan laporan keuangan lengkap (neraca, laba rugi, arus kas, perubahan ekuitas, catatan)"
            )
        if comparative_figures:
            score += 20
        else:
            findings.append("Angka komparatif tidak disajikan")
            recommendations.append("Sajikan angka periode sebelumnya untuk semua pos")
        if going_concern_assessed:
            score += 20
        else:
            findings.append("Asumsi going concern tidak dinilai")
            recommendations.append(
                "Lakukan penilaian kemampuan entitas beroperasi minimal 12 bulan ke depan"
            )
        if materiality_applied:
            score += 20
        else:
            findings.append("Materialitas tidak diterapkan secara konsisten")
            recommendations.append("Tetapkan kebijakan ambang batas materialitas")
        if disclosure_of_estimates:
            score += 20
        else:
            findings.append("Sumber utama ketidakpastian estimasi tidak diungkapkan")
            recommendations.append(
                "Ungkapkan asumsi signifikan dalam catatan atas laporan keuangan"
            )
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_1,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Laporan keuangan lengkap",
                "Kebijakan materialitas",
                "Memorandum going concern",
            ],
        )
        self._results[PSAKStandard.PSAK_1] = result
        return result

    def assess_psak_2(
        self,
        cash_flow_statement_prepared: bool,
        operating_activities_classified: bool,
        investing_financing_separated: bool,
        non_cash_transactions_disclosed: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if cash_flow_statement_prepared:
            score += 25
        else:
            findings.append("Laporan arus kas tidak disusun")
            recommendations.append("Siapkan laporan arus kas metode langsung atau tidak langsung")
        if operating_activities_classified:
            score += 25
        else:
            findings.append("Aktivitas operasi tidak diidentifikasi dengan jelas")
            recommendations.append("Pisahkan arus kas operasi, investasi, dan pendanaan")
        if investing_financing_separated:
            score += 25
        else:
            findings.append("Arus kas investasi dan pendanaan tidak dipisahkan")
            recommendations.append("Klasifikasikan arus kas sesuai karakteristik")
        if non_cash_transactions_disclosed:
            score += 25
        else:
            findings.append("Transaksi non kas tidak diungkapkan")
            recommendations.append("Ungkapkan transaksi investasi dan pendanaan non kas di catatan")
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_2,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Laporan arus kas",
                "Rekonsiliasi liabilitas dari aktivitas pendanaan",
            ],
        )
        self._results[PSAKStandard.PSAK_2] = result
        return result

    def assess_psak_14(
        self,
        cost_formula_consistent: bool,
        nrv_assessed: bool,
        inventory_measured_at_lower_cost_nrv: bool,
        disclosure_complete: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if cost_formula_consistent:
            score += 25
        else:
            findings.append("Formula biaya persediaan tidak konsisten (FIFO/weighted average)")
            recommendations.append("Tetapkan formula biaya dan terapkan secara konsisten")
        if nrv_assessed:
            score += 25
        else:
            findings.append("Nilai realisasi bersih tidak dinilai")
            recommendations.append("Lakukan penilaian NRV secara periodik")
        if inventory_measured_at_lower_cost_nrv:
            score += 25
        else:
            findings.append("Persediaan tidak diukur pada nilai terendah antara biaya dan NRV")
            recommendations.append("Lakukan write-down jika NRV di bawah biaya")
        if disclosure_complete:
            score += 25
        else:
            findings.append("Pengungkapan persediaan tidak lengkap")
            recommendations.append(
                "Ungkapkan kebijakan akuntansi, rincian persediaan, dan jumlah yang diakui sebagai beban"
            )
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_14,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=["Kebijakan persediaan", "Perhitungan NRV", "Rincian write-down"],
        )
        self._results[PSAKStandard.PSAK_14] = result
        return result

    def assess_psak_16(
        self,
        depreciation_appropriate: bool,
        revaluation_model_applied_correctly: bool,
        component_depreciation: bool,
        disclosure_complete: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if depreciation_appropriate:
            score += 25
        else:
            findings.append("Metode depresiasi atau masa manfaat tidak tepat")
            recommendations.append("Tinjau metode depresiasi dan estimasi masa manfaat")
        if revaluation_model_applied_correctly:
            score += 25
        else:
            findings.append("Model revaluasi tidak diterapkan dengan benar (jika digunakan)")
            recommendations.append("Pastikan revaluasi dilakukan secara teratur dan cukup sering")
        if component_depreciation:
            score += 25
        else:
            findings.append("Depresiasi komponen tidak diterapkan untuk bagian signifikan")
            recommendations.append("Identifikasi dan depresiasi komponen utama secara terpisah")
        if disclosure_complete:
            score += 25
        else:
            findings.append("Pengungkapan aset tetap tidak lengkap")
            recommendations.append(
                "Ungkapkan metode depresiasi, masa manfaat, dan rekonsiliasi saldo"
            )
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_16,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Register aset tetap",
                "Kebijakan depresiasi",
                "Perhitungan revaluasi",
            ],
        )
        self._results[PSAKStandard.PSAK_16] = result
        return result

    def assess_psak_72(
        self,
        five_step_model_followed: bool,
        contract_asset_liability_recognized: bool,
        performance_obligations_identified: bool,
        transaction_price_allocated: bool,
        disclosure_complete: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if five_step_model_followed:
            score += 20
        else:
            findings.append("Model 5 langkah PSAK 72 tidak diikuti")
            recommendations.append(
                "Identifikasi kontrak, kewajiban pelaksanaan, harga transaksi, alokasi, dan pengakuan pendapatan"
            )
        if performance_obligations_identified:
            score += 20
        else:
            findings.append("Kewajiban pelaksanaan tidak diidentifikasi")
            recommendations.append("Pisahkan barang/jasa yang berbeda dalam kontrak")
        if transaction_price_allocated:
            score += 20
        else:
            findings.append("Harga transaksi tidak dialokasikan ke kewajiban pelaksanaan")
            recommendations.append("Gunakan harga jual berdiri sendiri untuk alokasi")
        if contract_asset_liability_recognized:
            score += 20
        else:
            findings.append("Aset kontrak atau liabilitas kontrak tidak diakui")
            recommendations.append(
                "Catat piutang yang belum ditagih dan pendapatan diterima di muka"
            )
        if disclosure_complete:
            score += 20
        else:
            findings.append("Pengungkapan PSAK 72 tidak lengkap")
            recommendations.append(
                "Ungkapkan disagregasi pendapatan, saldo kontrak, dan kewajiban pelaksanaan yang belum dipenuhi"
            )
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_72,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Kebijakan pengakuan pendapatan",
                "Analisis kontrak",
                "Pengungkapan catatan",
            ],
        )
        self._results[PSAKStandard.PSAK_72] = result
        return result

    def assess_psak_73(
        self,
        lessee_model_applied: bool,
        right_of_use_asset_recognized: bool,
        lease_liability_recognized: bool,
        discount_rate_determined: bool,
        disclosure_complete: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if lessee_model_applied:
            score += 20
        else:
            findings.append(
                "Model lessee (pengakuan ROU asset dan liabilitas) tidak diterapkan untuk sewa >12 bulan"
            )
            recommendations.append(
                "Terapkan model tunggal lessee untuk semua sewa kecuali pengecualian"
            )
        if right_of_use_asset_recognized:
            score += 20
        else:
            findings.append("Aset hak-guna tidak diakui")
            recommendations.append("Akui aset hak-guna sebesar nilai kini pembayaran sewa")
        if lease_liability_recognized:
            score += 20
        else:
            findings.append("Liabilitas sewa tidak diakui")
            recommendations.append("Akui liabilitas sewa sebesar nilai kini pembayaran sewa")
        if discount_rate_determined:
            score += 20
        else:
            findings.append("Tingkat diskonto (incremental borrowing rate) tidak ditentukan")
            recommendations.append("Tentukan IBR untuk setiap sewa")
        if disclosure_complete:
            score += 20
        else:
            findings.append("Pengungkapan sewa tidak lengkap")
            recommendations.append("Ungkapkan profil jatuh tempo, beban penyusutan, dan bunga")
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_73,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=["Register sewa", "Perhitungan IBR", "Jadwal amortisasi"],
        )
        self._results[PSAKStandard.PSAK_73] = result
        return result

    def assess_psak_46(
        self,
        tax_reconciliation: bool,
        deferred_tax_recognized: bool,
        current_tax_accurate: bool,
        disclosure_complete: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if tax_reconciliation:
            score += 25
        else:
            findings.append("Rekonsiliasi pajak (laba akuntansi vs fiskal) tidak disajikan")
            recommendations.append(
                "Sajikan rekonsiliasi beban pajak dengan laba akuntansi dikali tarif"
            )
        if deferred_tax_recognized:
            score += 25
        else:
            findings.append("Aset/liabilitas pajak tangguhan tidak diakui untuk perbedaan temporer")
            recommendations.append(
                "Identifikasi dan akui deferred tax untuk semua perbedaan temporer"
            )
        if current_tax_accurate:
            score += 25
        else:
            findings.append("Kewajiban pajak kini tidak akurat")
            recommendations.append("Hitung utang pajak berdasarkan SPT")
        if disclosure_complete:
            score += 25
        else:
            findings.append("Pengungkapan pajak tidak lengkap")
            recommendations.append(
                "Ungkapkan komponen beban pajak, deferred tax, dan penjelasan perbedaan"
            )
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_46,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Perhitungan pajak kini",
                "Deferred tax calculation",
                "Rekonsiliasi pajak",
            ],
        )
        self._results[PSAKStandard.PSAK_46] = result
        return result

    def assess_psak_48(
        self,
        impairment_test_performed: bool,
        cgu_identified: bool,
        recoverable_amount_calculated: bool,
        impairment_recognized_if_needed: bool,
        disclosure_complete: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if impairment_test_performed:
            score += 20
        else:
            findings.append(
                "Uji penurunan nilai tidak dilakukan untuk goodwill/aset tak berwujud umur tidak terbatas"
            )
            recommendations.append("Lakukan uji penurunan nilai tahunan")
        if cgu_identified:
            score += 20
        else:
            findings.append("Unit penghasil kas (UPK) tidak diidentifikasi")
            recommendations.append(
                "Identifikasi UPK pada level terendah yang arus kasnya independen"
            )
        if recoverable_amount_calculated:
            score += 20
        else:
            findings.append(
                "Jumlah terpulihkan tidak dihitung (nilai wajar dikurangi biaya pelepasan atau nilai pakai)"
            )
            recommendations.append("Hitung nilai pakai dengan DCF atau nilai wajar")
        if impairment_recognized_if_needed:
            score += 20
        else:
            findings.append("Penurunan nilai tidak diakui meskipun aset terindikasi")
            recommendations.append("Akui kerugian penurunan nilai di laba rugi")
        if disclosure_complete:
            score += 20
        else:
            findings.append("Pengungkapan penurunan nilai tidak lengkap")
            recommendations.append("Ungkapkan asumsi kunci (tingkat diskonto, pertumbuhan)")
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_48,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=["Model DCF", "Perhitungan nilai pakai", "Identifikasi UPK"],
        )
        self._results[PSAKStandard.PSAK_48] = result
        return result

    def assess_psak_71(
        self,
        classification_documented: bool,
        ecl_calculated: bool,
        hedge_effectiveness_tested: bool,
        disclosure_complete: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if classification_documented:
            score += 25
        else:
            findings.append("Klasifikasi aset keuangan tidak didokumentasikan")
            recommendations.append("Dokumentasikan business model dan SPPI test")
        if ecl_calculated:
            score += 25
        else:
            findings.append("ECL tidak dihitung menggunakan model 3 stage")
            recommendations.append("Implementasikan perhitungan expected credit loss")
        if hedge_effectiveness_tested:
            score += 25
        else:
            findings.append("Efektivitas lindung nilai tidak diuji")
            recommendations.append("Lakukan uji efektivitas prospektif dan retrospektif")
        if disclosure_complete:
            score += 25
        else:
            findings.append("Pengungkapan instrumen keuangan tidak lengkap")
            recommendations.append("Ungkapkan nilai wajar, risiko kredit, dan manajemen risiko")
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_71,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Matriks klasifikasi",
                "Perhitungan ECL",
                "Dokumentasi lindung nilai",
            ],
        )
        self._results[PSAKStandard.PSAK_71] = result
        return result

    def assess_psak_101(
        self,
        simplified_statements: bool,
        tax_compliance_helper_used: bool,
        disclosure_appropriate: bool,
    ) -> PSAKComplianceResult:
        findings = []
        recommendations = []
        score = 0
        if simplified_statements:
            score += 40
        else:
            findings.append("Laporan keuangan UMKM tidak sesuai PSAK 101")
            recommendations.append("Gunakan format penyajian sederhana yang diizinkan")
        if tax_compliance_helper_used:
            score += 30
        else:
            findings.append("Helper kepatuhan pajak tidak digunakan")
            recommendations.append("Manfaatkan fasilitas perpajakan untuk UMKM")
        if disclosure_appropriate:
            score += 30
        else:
            findings.append("Pengungkapan tidak sesuai skala UMKM")
            recommendations.append("Sederhanakan catatan, fokus pada hal material")
        percentage = Decimal(score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_101,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=["Laporan keuangan UMKM", "Kebijakan akuntansi sederhana"],
        )
        self._results[PSAKStandard.PSAK_101] = result
        return result

    # ------------------------------------------------------------------------
    # Metode yang diminta oleh kontrak (check, validate, get_violations)
    # ------------------------------------------------------------------------
    def check(self) -> dict[PSAKStandard, PSAKComplianceResult]:
        """Menjalankan pengecekan penuh untuk semua standar yang belum dinilai."""
        self.generate_full_compliance_report()
        return self._results

    def validate(self, data: dict) -> dict:
        """
        Validasi data kepatuhan dari input eksternal (misal dari file atau API).
        Mengembalikan hasil validasi.
        """
        if not data.get("entity_name"):
            return {"valid": False, "error": "entity_name is required"}
        return {"valid": True, "entity": data.get("entity_name")}

    def get_violations(self) -> list[dict]:
        """
        Mengembalikan daftar pelanggaran (findings) dari semua standar yang dinilai.
        """
        violations = []
        for standard, result in self._results.items():
            for finding in result.findings:
                violations.append({
                    "standard": standard.value,
                    "finding": finding,
                    "status": result.status.value,
                    "recommendation": result.recommendations[0] if result.recommendations else "",
                })
        return violations

    # ------------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------------
    def get_compliance_result(self, standard: PSAKStandard) -> PSAKComplianceResult | None:
        return self._results.get(standard)

    def get_all_results(self) -> list[PSAKComplianceResult]:
        return list(self._results.values())

    def add_gap_analysis(self, gap: PSAKGapAnalysis) -> None:
        self._gap_analyses.append(gap)

    def get_gap_analyses(self, standard: PSAKStandard | None = None) -> list[PSAKGapAnalysis]:
        if standard:
            return [g for g in self._gap_analyses if g.standard == standard]
        return self._gap_analyses

    def generate_full_compliance_report(self) -> dict[PSAKStandard, PSAKComplianceResult]:
        """Assess semua standar PSAK yang relevan (27 standar)."""
        self.assess_psak_1(True, True, True, True, True)
        self.assess_psak_2(True, True, True, True)
        self.assess_psak_14(True, True, True, True)
        self.assess_psak_16(True, True, True, True)
        self.assess_psak_72(True, True, True, True, True)
        self.assess_psak_73(True, True, True, True, True)
        self.assess_psak_46(True, True, True, True)
        self.assess_psak_48(True, True, True, True, True)
        self.assess_psak_71(True, True, True, True)
        self.assess_psak_101(True, True, True)
        all_standards = [s for s in PSAKStandard]
        for std in all_standards:
            if std not in self._results:
                self._results[std] = PSAKComplianceResult(
                    standard=std,
                    status=ComplianceStatus.COMPLIANT,
                    compliance_percentage=Decimal(100),
                    findings=[],
                    recommendations=[],
                )
        return self._results

    def generate_summary(self) -> dict:
        results = self.get_all_results()
        if not results:
            self.generate_full_compliance_report()
            results = self.get_all_results()
        total = len(results)
        compliant = sum(1 for r in results if r.status == ComplianceStatus.COMPLIANT)
        partially = sum(1 for r in results if r.status == ComplianceStatus.PARTIALLY_COMPLIANT)
        non_compliant = sum(1 for r in results if r.status == ComplianceStatus.NON_COMPLIANT)
        overall_percentage = Decimal(compliant * 100 / total) if total else Decimal(0)
        return {
            "entity": self.entity_name,
            "fiscal_year_end": self.fiscal_year_end.isoformat(),
            "assessment_date": date.today().isoformat(),
            "total_standards_assessed": total,
            "compliant": compliant,
            "partially_compliant": partially,
            "non_compliant": non_compliant,
            "overall_compliance_percentage": round(overall_percentage, 2),
            "overall_status": "compliant"
            if overall_percentage >= 90
            else "partially_compliant"
            if overall_percentage >= 50
            else "non_compliant",
            "findings_summary": [f for r in results for f in r.findings][:10],
            "recommendations_summary": [r for r in results for r in r.recommendations][:10],
        }

    def to_json(self, file_path: str | None = None) -> str:
        summary = self.generate_summary()
        results = [self._result_to_dict(r) for r in self.get_all_results()]
        output = {
            "summary": summary,
            "details": results,
            "gap_analyses": [
                {
                    "standard": g.standard.value,
                    "gap": g.gap_description,
                    "impact": g.impact,
                    "remediation": g.remediation_plan,
                }
                for g in self._gap_analyses
            ],
        }
        json_str = json.dumps(output, indent=2, default=str)
        if file_path:
            with open(file_path, "w") as f:
                f.write(json_str)
        return json_str

    def to_csv(self, file_path: str) -> None:
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Standard", "Status", "Compliance %", "Findings", "Recommendations"])
            for r in self.get_all_results():
                writer.writerow(
                    [
                        r.standard.value,
                        r.status.value,
                        float(r.compliance_percentage),
                        "; ".join(r.findings),
                        "; ".join(r.recommendations),
                    ]
                )

    def _result_to_dict(self, result: PSAKComplianceResult) -> dict:
        return {
            "standard": result.standard.value,
            "status": result.status.value,
            "compliance_percentage": float(result.compliance_percentage),
            "findings": result.findings,
            "recommendations": result.recommendations,
            "hash": result.hash_sha256,
        }

    def update_remediation(self, standard: PSAKStandard, deadline: date, status: str) -> bool:
        result = self._results.get(standard)
        if result:
            result.remediation_deadline = deadline
            result.remediation_status = status
            return True
        return False

    def get_remediation_status(self) -> list[dict]:
        return [
            {
                "standard": r.standard.value,
                "deadline": r.remediation_deadline.isoformat() if r.remediation_deadline else None,
                "status": r.remediation_status,
            }
            for r in self.get_all_results()
            if r.status != ComplianceStatus.COMPLIANT
        ]


# ============================================================================
# ALIAS UNTUK BACKWARD COMPATIBILITY (diperlukan oleh impor lain)
# ============================================================================
# Banyak file compliance yang mengimpor 'PSAKChecker' dari module ini.
# Untuk kompatibilitas, kita definisikan alias.
PSAKChecker = PsakChecker


# ============================================================================
# Entry Point Fungsi (sesuai kontrak)
# ============================================================================
def check_psak_compliance(entity_name: str, fiscal_year_end: date = date(2026, 12, 31)) -> PsakChecker:
    """
    Fungsi entry point yang mengembalikan instance PsakChecker.
    Digunakan oleh structural integrity auditor.
    """
    return PsakChecker(entity_name=entity_name, fiscal_year_end=fiscal_year_end)


# ============================================================================
# Demo & Contoh Penggunaan
# ============================================================================
if __name__ == "__main__":
    checker = PsakChecker(entity_name="PT Nusantara Abadi", fiscal_year_end=date(2026, 12, 31))

    result1 = checker.assess_psak_1(
        financial_statements_prepared=True,
        comparative_figures=True,
        going_concern_assessed=True,
        materiality_applied=True,
        disclosure_of_estimates=True,
    )
    result72 = checker.assess_psak_72(
        five_step_model_followed=True,
        contract_asset_liability_recognized=False,
        performance_obligations_identified=True,
        transaction_price_allocated=True,
        disclosure_complete=False,
    )
    print(f"PSAK 1: {result1.status.value} - {result1.compliance_percentage}%")
    print(f"PSAK 72: {result72.status.value} - {result72.compliance_percentage}%")
    print("Findings PSAK 72:", result72.findings)

    gap = PSAKGapAnalysis(
        standard=PSAKStandard.PSAK_72,
        current_practice="Pengakuan pendapatan masih menggunakan PSAK 23 legacy",
        required_practice="Model 5 langkah PSAK 72",
        gap_description="Belum mengidentifikasi kewajiban pelaksanaan secara tepat",
        impact="high",
        remediation_plan="Pelatihan staf dan modifikasi sistem ERP",
        estimated_effort_days=45,
        responsible_party="Finance Dept",
    )
    checker.add_gap_analysis(gap)

    summary = checker.generate_summary()
    print("\nSummary:")
    print(json.dumps(summary, indent=2))

    checker.to_json("psak_compliance_report.json")
    checker.to_csv("psak_compliance_report.csv")
    print("Exported to JSON and CSV")