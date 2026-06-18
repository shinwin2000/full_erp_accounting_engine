#!/usr/bin/env python3
"""
Module: test_coretax_djp_2026_api.py
Layer: Compliance
Responsibility: Menguji kepatuhan terhadap API Coretax DJP 2026.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from adapters.coretax_djp.e_bupot_generator import EBupotGenerator
from adapters.coretax_djp.e_meterai_integrator import EMeteraiIntegrator
from adapters.coretax_djp.faktur_keluaran_generator import FakturKeluaranGenerator
from adapters.coretax_djp.faktur_masukan_processor import FakturMasukanProcessor
from adapters.coretax_djp.health_dashboard import CoreTaxHealthDashboard
from adapters.coretax_djp.nsfp_manager import NSFPManager
from adapters.coretax_djp.ntpn_validator import NTPNValidator
from adapters.coretax_djp.spt_masa_ppn_builder import SPTMasaPPNBuilder
from adapters.coretax_djp.spt_tahunan_badan_builder import SPTTahunanBadanBuilder
from compliance.coretax_validator import CoreTaxValidator


# -------------------------------------------------------------------------
# Fixtures (tanpa argumen)
# -------------------------------------------------------------------------
@pytest.fixture
def faktur_generator() -> FakturKeluaranGenerator:
    return FakturKeluaranGenerator()

    @pytest.fixture
    def faktur_processor() -> FakturMasukanProcessor:
        return FakturMasukanProcessor()

        @pytest.fixture
        def e_bupot_generator() -> EBupotGenerator:
            return EBupotGenerator()

            @pytest.fixture
            def e_meterai_integrator() -> EMeteraiIntegrator:
                return EMeteraiIntegrator()

                @pytest.fixture
                def nsfp_manager() -> NSFPManager:
                    return NSFPManager()

                    @pytest.fixture
                    def ntpn_validator() -> NTPNValidator:
                        return NTPNValidator()

                        # -------------------------------------------------------------------------
                        # Tests
                        # -------------------------------------------------------------------------
                        class TestCoreTaxFakturKeluaran:
                            def test_generate_faktur_keluaran_success(self, faktur_generator):
                                data = {
                                    "penjual_npwp": "123456789012345",
                                    "penjual_nama": "PT Maju Jaya",
                                    "pembeli_npwp": "987654321098765",
                                    "pembeli_nama": "CV Sejahtera",
                                    "jenis_transaksi": "01",
                                    "tanggal_faktur": date.today(),
                                    "dasar_pengenaan_pajak": Decimal("100000000"),
                                    "ppn": Decimal("11000000"),
                                    "ppnbm": Decimal("0"),
                                }
                                faktur = faktur_generator.generate(data)
                                assert faktur.kode_faktur is not None
                                assert faktur.nomor_faktur.startswith("010")
                                assert faktur.status == "SUBMITTED"

                                def test_faktur_keluaran_harus_memiliki_qr_code(
                                    self, faktur_generator
                                ):
                                    faktur = faktur_generator.generate_example()
                                    assert faktur.qr_code is not None
                                    assert len(faktur.qr_code) > 50

                                    @pytest.mark.skip(
                                        reason="Validasi PPN belum diimplementasikan di generator"
                                    )
                                    def test_faktur_keluaran_ditolak_jika_ppn_kurang(
                                        self, faktur_generator
                                    ):
                                        data = {
                                            "dasar_pengenaan_pajak": Decimal("100000000"),
                                            "ppn": Decimal("10000000"),
                                        }
                                        with pytest.raises(
                                            ValueError, match="PPN tidak sesuai dengan tarif 11%"
                                        ):
                                            faktur_generator.generate(data)

                                            class TestCoreTaxFakturMasukan:
                                                def test_proses_faktur_masukan_approve(
                                                    self, faktur_processor
                                                ):
                                                    faktur_data = {
                                                        "nomor_faktur": "010.123-22.12345678",
                                                        "tanggal_faktur": date(2026, 5, 15),
                                                        "ppn": Decimal("1100000"),
                                                    }
                                                    result = faktur_processor.approve(faktur_data)
                                                    assert result.status == "APPROVED"
                                                    assert result.pengkreditan_allowed is True

                                                    def test_faktur_masukan_kedaluwarsa_ditolak(
                                                        self, faktur_processor
                                                    ):
                                                        faktur_lama = {
                                                            "nomor_faktur": "010.123-21.12345678",
                                                            "tanggal_faktur": date(2021, 12, 31),
                                                        }
                                                        with pytest.raises(
                                                            ValueError,
                                                            match="Faktur sudah melebihi batas waktu 3 bulan",
                                                        ):
                                                            faktur_processor.approve(faktur_lama)

                                                            class TestCoreTaxEBupot:
                                                                def test_generate_bupot_pph23(
                                                                    self, e_bupot_generator
                                                                ):
                                                                    data = {
                                                                        "jenis_pajak": "PPh 23",
                                                                        "npwp_pemotong": "123456789012345",
                                                                        "npwp_penerima": "987654321098765",
                                                                        "bruto": Decimal(
                                                                            "50000000"
                                                                        ),
                                                                        "tarif": Decimal("2"),
                                                                        "pph_dipotong": Decimal(
                                                                            "1000000"
                                                                        ),
                                                                        "masa_pajak": (2026, 5),
                                                                    }
                                                                    bupot = (
                                                                        e_bupot_generator.generate(
                                                                            data
                                                                        )
                                                                    )
                                                                    assert (
                                                                        bupot.kode_billing
                                                                        is not None
                                                                    )
                                                                    assert bupot.is_valid() is True

                                                                    def test_bupot_pph21_wajib_ada_npwp_penerima(
                                                                        self, e_bupot_generator
                                                                    ):
                                                                        data = {
                                                                            "jenis_pajak": "PPh 21",
                                                                            "npwp_pemotong": "123456789012345",
                                                                            "bruto": Decimal(
                                                                                "10000000"
                                                                            ),
                                                                        }
                                                                        with pytest.raises(
                                                                            ValueError,
                                                                            match="NPWP penerima wajib diisi untuk PPh 21",
                                                                        ):
                                                                            e_bupot_generator.generate(
                                                                                data
                                                                            )

                                                                            class TestCoreTaxEMeterai:
                                                                                def test_integrasi_e_meterai_berhasil(
                                                                                    self,
                                                                                    e_meterai_integrator,
                                                                                ):
                                                                                    dokumen = {
                                                                                        "id": "DOC-001",
                                                                                        "nilai": Decimal(
                                                                                            "10000000"
                                                                                        ),
                                                                                    }
                                                                                    meterai = e_meterai_integrator.terapkan(
                                                                                        dokumen
                                                                                    )
                                                                                    assert meterai.kode_unik.startswith(
                                                                                        "EMT-"
                                                                                    )
                                                                                    assert (
                                                                                        meterai.nominal
                                                                                        == Decimal(
                                                                                            "10000"
                                                                                        )
                                                                                    )

                                                                                    def test_e_meterai_tidak_bisa_duplikat(
                                                                                        self,
                                                                                        e_meterai_integrator,
                                                                                    ):
                                                                                        dokumen = {
                                                                                            "id": "DOC-001",
                                                                                            "nilai": Decimal(
                                                                                                "10000000"
                                                                                            ),
                                                                                        }
                                                                                        e_meterai_integrator.terapkan(
                                                                                            dokumen
                                                                                        )
                                                                                        with pytest.raises(
                                                                                            ValueError,
                                                                                            match="Dokumen sudah bermeterai",
                                                                                        ):
                                                                                            e_meterai_integrator.terapkan(
                                                                                                dokumen
                                                                                            )

                                                                                            class TestCoreTaxNSFP:
                                                                                                def test_ambil_nsfp_dari_djp(
                                                                                                    self,
                                                                                                    nsfp_manager,
                                                                                                ):
                                                                                                    nsfp_range = nsfp_manager.request_new_range(
                                                                                                        100
                                                                                                    )
                                                                                                    assert (
                                                                                                        nsfp_range.start
                                                                                                        >= 1
                                                                                                    )
                                                                                                    assert (
                                                                                                        nsfp_range.end
                                                                                                        - nsfp_range.start
                                                                                                        + 1
                                                                                                        == 100
                                                                                                    )

                                                                                                    def test_nsfp_yang_digunakan_tidak_bisa_dipakai_ulang(
                                                                                                        self,
                                                                                                        nsfp_manager,
                                                                                                    ):
                                                                                                        nsfp = nsfp_manager.get_next()
                                                                                                        used = nsfp_manager.use(
                                                                                                            nsfp
                                                                                                        )
                                                                                                        assert (
                                                                                                            used
                                                                                                            is True
                                                                                                        )
                                                                                                        with pytest.raises(
                                                                                                            ValueError,
                                                                                                            match="NSFP sudah digunakan",
                                                                                                        ):
                                                                                                            nsfp_manager.use(
                                                                                                                nsfp
                                                                                                            )

                                                                                                            class TestCoreTaxNTPN:
                                                                                                                def test_validasi_ntpn_yang_sah(
                                                                                                                    self,
                                                                                                                    ntpn_validator,
                                                                                                                ):
                                                                                                                    ntpn = "1234567890123456"
                                                                                                                    valid = ntpn_validator.validate(
                                                                                                                        ntpn
                                                                                                                    )
                                                                                                                    assert (
                                                                                                                        valid
                                                                                                                        is True
                                                                                                                    )

                                                                                                                    def test_ntpn_palsu_ditolak(
                                                                                                                        self,
                                                                                                                        ntpn_validator,
                                                                                                                    ):
                                                                                                                        with pytest.raises(
                                                                                                                            ValueError,
                                                                                                                            match="NTPN tidak terdaftar",
                                                                                                                        ):
                                                                                                                            ntpn_validator.validate(
                                                                                                                                "0000000000000000"
                                                                                                                            )

                                                                                                                            class TestCoreTaxSPT:
                                                                                                                                def test_build_spt_masa_ppn(
                                                                                                                                    self,
                                                                                                                                ):
                                                                                                                                    builder = SPTMasaPPNBuilder()
                                                                                                                                    faktur_list = []
                                                                                                                                    spt = builder.build(
                                                                                                                                        faktur_list,
                                                                                                                                        masa=5,
                                                                                                                                        tahun=2026,
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        spt.kode_formulir
                                                                                                                                        == "1111"
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        spt.total_ppn_keluaran
                                                                                                                                        == sum(
                                                                                                                                            f.ppn
                                                                                                                                            for f in faktur_list
                                                                                                                                            if f.jenis
                                                                                                                                            == "keluaran"
                                                                                                                                        )
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        spt.total_ppn_masukan
                                                                                                                                        == sum(
                                                                                                                                            f.ppn
                                                                                                                                            for f in faktur_list
                                                                                                                                            if f.jenis
                                                                                                                                            == "masukan"
                                                                                                                                        )
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        spt.lebih_bayar
                                                                                                                                        is not None
                                                                                                                                    )

                                                                                                                                    def test_build_spt_tahunan_badan_harus_memiliki_lampiran(
                                                                                                                                        self,
                                                                                                                                    ):
                                                                                                                                        builder = SPTTahunanBadanBuilder()
                                                                                                                                        data_keuangan = {
                                                                                                                                            "penghasilan_bruto": Decimal(
                                                                                                                                                "10e9"
                                                                                                                                            ),
                                                                                                                                            "beban": Decimal(
                                                                                                                                                "7e9"
                                                                                                                                            ),
                                                                                                                                        }
                                                                                                                                        spt = builder.build(
                                                                                                                                            data_keuangan,
                                                                                                                                            tahun_buku=2025,
                                                                                                                                        )
                                                                                                                                        assert (
                                                                                                                                            spt.has_attachment(
                                                                                                                                                "laporan_keuangan"
                                                                                                                                            )
                                                                                                                                            is True
                                                                                                                                        )
                                                                                                                                        assert (
                                                                                                                                            spt.has_attachment(
                                                                                                                                                "daftar_susunan_pemegang_saham"
                                                                                                                                            )
                                                                                                                                            is True
                                                                                                                                        )

                                                                                                                                        class TestCoreTaxHealth:
                                                                                                                                            def test_health_dashboard_menampilkan_ok(
                                                                                                                                                self,
                                                                                                                                            ):
                                                                                                                                                dashboard = CoreTaxHealthDashboard()
                                                                                                                                                health = dashboard.check()
                                                                                                                                                assert (
                                                                                                                                                    health[
                                                                                                                                                        "api_status"
                                                                                                                                                    ]
                                                                                                                                                    in (
                                                                                                                                                        "UP",
                                                                                                                                                        "DEGRADED",
                                                                                                                                                    )
                                                                                                                                                )
                                                                                                                                                assert (
                                                                                                                                                    "last_successful_call"
                                                                                                                                                    in health
                                                                                                                                                )

                                                                                                                                                class TestCoreTaxValidator:
                                                                                                                                                    def test_validasi_faktur_sebelum_submit(
                                                                                                                                                        self,
                                                                                                                                                    ):
                                                                                                                                                        validator = CoreTaxValidator()
                                                                                                                                                        faktur = {
                                                                                                                                                            "nomor": "010.123-22.00000001",
                                                                                                                                                            "ppn": Decimal(
                                                                                                                                                                "11000000"
                                                                                                                                                            ),
                                                                                                                                                        }
                                                                                                                                                        (
                                                                                                                                                            is_valid,
                                                                                                                                                            errors,
                                                                                                                                                        ) = validator.validate_faktur(
                                                                                                                                                            faktur
                                                                                                                                                        )
                                                                                                                                                        assert (
                                                                                                                                                            is_valid
                                                                                                                                                            is True
                                                                                                                                                        )
                                                                                                                                                        assert (
                                                                                                                                                            errors
                                                                                                                                                            == []
                                                                                                                                                        )

                                                                                                                                                        def test_validasi_faktur_tanpa_ntpn_ditolak(
                                                                                                                                                            self,
                                                                                                                                                        ):
                                                                                                                                                            validator = CoreTaxValidator()
                                                                                                                                                            faktur = {
                                                                                                                                                                "nomor": "010.123-22.00000002",
                                                                                                                                                                "ntpn": None,
                                                                                                                                                            }
                                                                                                                                                            (
                                                                                                                                                                is_valid,
                                                                                                                                                                errors,
                                                                                                                                                            ) = validator.validate_faktur(
                                                                                                                                                                faktur
                                                                                                                                                            )
                                                                                                                                                            assert (
                                                                                                                                                                is_valid
                                                                                                                                                                is False
                                                                                                                                                            )
                                                                                                                                                            assert any(
                                                                                                                                                                "NTPN"
                                                                                                                                                                in err
                                                                                                                                                                for err in errors
                                                                                                                                                            )
