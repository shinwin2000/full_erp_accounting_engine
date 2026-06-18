#!/usr/bin/env python3
"""
Module: test_aml_risk_scoring.py
Layer: Compliance

Responsibility:
    Menguji kepatuhan terhadap regulasi AML (Anti Money Laundering):
    - Skoring risiko transaksi
    - Screening nama terhadap daftar sanksi (Sanctions List)
    - Pelaporan transaksi mencurigakan (STR)
    - KYC enhanced due diligence (EDD)
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from compliance.aml_risk_scorer import AMLRiskScorer, RiskLevel
from compliance.compliance_exceptions import SuspiciousTransactionReported
from compliance.legal.sanction_list_checker import SanctionListChecker


@pytest.fixture
def risk_scorer() -> AMLRiskScorer:
    return AMLRiskScorer()


@pytest.fixture
def sanction_checker() -> SanctionListChecker:
    return SanctionListChecker()


class TestAMLRiskScoring:
    """Uji skoring risiko AML."""

    def test_transaksi_kurang_dari_100_juta_skor_rendah(self, risk_scorer):
        skor = risk_scorer.calculate(
            amount=Decimal("50000000"), country="ID", customer_tenure_years=5
        )
        assert skor.risk_level == RiskLevel.LOW
        assert skor.score < 30

    def test_transaksi_diatas_1_miliar_dengan_negara_berisiko_tinggi(self, risk_scorer):
        skor = risk_scorer.calculate(
            amount=Decimal("2_000_000_000"), country="KY", customer_tenure_years=1
        )
        assert skor.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        assert skor.score > 70

    def test_customer_baru_langsung_transaksi_besar_memicu_edd(self, risk_scorer):
        skor = risk_scorer.calculate(
            amount=Decimal("800_000_000"), country="ID", customer_tenure_years=0
        )
        assert skor.requires_edd is True

    def test_skor_ditambah_50_persen_jika_menggunakan_cash(self, risk_scorer):
        skor_cash = risk_scorer.calculate(amount=Decimal("200_000_000"), payment_method="cash")
        skor_transfer = risk_scorer.calculate(
            amount=Decimal("200_000_000"), payment_method="wire_transfer"
        )
        assert skor_cash.score > skor_transfer.score


class TestSanctionList:
    """Uji screening terhadap daftar sanksi nasional & internasional."""

    def test_nama_yang_terdaftar_ditolak(self, sanction_checker):
        nama = "OSAMA BIN LADEN"  # contoh
        result = sanction_checker.check(nama)
        assert result.is_matched is True
        assert result.sanction_reason == "UNSC 1267"

    def test_nama_tidak_terdaftar_aman(self, sanction_checker):
        nama = "Joko Widodo"
        result = sanction_checker.check(nama)
        assert result.is_matched is False

    def test_screening_alias_juga_dicek(self, sanction_checker):
        nama = "Usamah Bin Laden"
        result = sanction_checker.check(nama, check_aliases=True)
        assert result.is_matched is True


class TestSuspiciousTransactionReport:
    """Uji pelaporan transaksi mencurigakan ke PPATK."""

    def test_transaksi_diatas_500_juta_tanpa_alasan_jelas_memicu_str(self, risk_scorer):
        transaksi = {
            "amount": Decimal("600_000_000"),
            "customer": "PT Fiktif",
            "country": "ID",
            "business_justification": None,
        }
        with pytest.raises(SuspiciousTransactionReported) as exc:
            risk_scorer.process_transaction(transaksi)
        assert exc.value.report_id is not None
        assert exc.value.destination == "PPATK"

    def test_str_harus_dikirim_dalam_waktu_3_hari(self, risk_scorer):
        # Simulasi
        report = risk_scorer.report_suspicious(
            transaction_id="TXN-001",
            reason="Structuring",
        )
        assert report.submission_deadline - date.today() <= timedelta(days=3)
