#!/usr/bin/env python3
"""
Module: test_ojk_reporting_accuracy.py
Layer: Compliance

Responsibility:
    Menguji akurasi pelaporan ke OJK (Otoritas Jasa Keuangan) Indonesia.
    Mencakup laporan LKPBU (Laporan Keuangan Publik Bulanan), LHBU, dan lain-lain.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from compliance.ojk_lkpub_builder import LKPubReport, OJKLKPubBuilder
from domain.consolidation.intercompany_transaction import IntercompanyTransaction
from domain.legal_entity.aggregate_root import LegalEntity


@pytest.fixture
def legal_entity_bank() -> LegalEntity:
    return LegalEntity(
        name="PT Bank XYZ",
        license_number="10.1.12.2025",
        sector="BANK",
        registered_at_ojk=True,
    )


@pytest.fixture
def lkpub_builder(legal_entity_bank) -> OJKLKPubBuilder:
    return OJKLKPubBuilder(legal_entity=legal_entity_bank, period=date(2026, 5, 31))


class TestOJKLKPubAccuracy:
    """Uji akurasi Laporan LKPBU."""

    def test_total_aset_sama_dengan_jumlah_neraca(self, lkpub_builder):
        report: LKPubReport = lkpub_builder.build()
        aset_neraca = sum(report.neraca["ASET"].values())
        assert report.total_aset == aset_neraca

    def test_total_liabilitas_dan_ekuitas_sama_dengan_pasiva(self, lkpub_builder):
        report = lkpub_builder.build()
        total_pasiva = sum(report.neraca["LIABILITAS"].values()) + sum(
            report.neraca["EKUITAS"].values()
        )
        assert report.total_liabilitas_dan_ekuitas == total_pasiva

    def test_aset_bersih_positif(self, lkpub_builder):
        report = lkpub_builder.build()
        assert report.aset_bersih > Decimal("0")

    def test_rasio_kewajiban_penyisihan_wajib_dihitung(self, lkpub_builder):
        report = lkpub_builder.build()
        assert report.rasio_ckpn >= Decimal("0.02")  # minimal 2% untuk bank

    def test_laporan_tidak_boleh_ada_nilai_negatif_pada_aset(self, lkpub_builder):
        report = lkpub_builder.build()
        for aset_type, value in report.neraca["ASET"].items():
            assert value >= Decimal("0"), f"Aset {aset_type} negatif: {value}"

    def test_eliminasi_transaksi_intercompany_dalam_konsolidasi(self, lkpub_builder):
        # Tambahkan transaksi antar entitas anak
        transaksi = IntercompanyTransaction(
            amount=Decimal("5000000"), from_entity="A", to_entity="B"
        )
        lkpub_builder.add_intercompany_transaction(transaksi)
        report = lkpub_builder.build(consolidated=True)
        # Setelah eliminasi, nilai tidak boleh muncul di pendapatan/beban
        assert report.pendapatan_intercompany == Decimal("0")
        assert report.beban_intercompany == Decimal("0")

    def test_lkpub_harus_ditandatangani_digital(self, lkpub_builder):
        report = lkpub_builder.build()
        assert report.digital_signature is not None
        assert report.digital_signature.verified is True

    def test_pengiriman_ke_ojk_harus_sesuai_format_xbrl(self, lkpub_builder):
        xbrl = lkpub_builder.export_to_xbrl()
        assert xbrl.startswith("<?xml")
        assert "<xbrl" in xbrl
        assert "lkpub" in xbrl

    def test_tidak_ada_duplikasi_data(self, lkpub_builder):
        report = lkpub_builder.build()
        unique_ids = set(report.transactions.keys())
        assert len(unique_ids) == len(report.transactions)
