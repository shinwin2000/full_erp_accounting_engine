#!/usr/bin/env python3
"""
E2E: Coretax DJP Submission with NTPN
Alur: Buat faktur pajak keluaran → submit ke Coretax → terima NTPN → validasi pembayaran.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from adapters.coretax_djp.api_oauth2_client import CoreTaxOAuth2Client
from adapters.coretax_djp.faktur_keluaran_generator import FakturKeluaranGenerator
from adapters.coretax_djp.ntpn_validator import NTPNValidator
from adapters.coretax_djp.spt_masa_ppn_builder import SPTMasaPpnBuilder
from compliance.coretax_validator import CoreTaxValidator


@pytest.fixture
def oauth_client():
    # Gunakan kredensial test dari env
    return CoreTaxOAuth2Client(env="sandbox")

    def test_coretax_submit_and_ntpn(oauth_client):
        generator = FakturKeluaranGenerator(oauth_client)
        CoreTaxValidator()
        ntpn_validator = NTPNValidator(oauth_client)

        # 1. Generate faktur pajak
        faktur_data = {
            "penjual_npwp": "123456789012345",
            "penjual_nama": "PT Maju",
            "pembeli_npwp": "987654321098765",
            "tanggal_faktur": date.today(),
            "dpp": Decimal("100000000"),
            "ppn": Decimal("11000000"),
        }
        faktur = generator.generate(faktur_data)
        assert faktur.is_valid

        # 2. Submit faktur ke DJP
        submission_result = generator.submit(faktur)
        assert submission_result.status_code == 201
        assert submission_result.approval_code is not None

        # 3. SPT Masa PPN
        builder = SPTMasaPpnBuilder()
        spt = builder.build([faktur], masa=5, tahun=2026)
        assert spt.total_ppn_terutang == Decimal("11000000")

        # 4. Bayar pajak melalui sistem (simulasi dapat NTPN)
        payment_ref = spt.pay(amount=Decimal("11000000"), bank_code="BCA")
        ntpn = payment_ref.ntpn
        assert ntpn is not None
        assert len(ntpn) == 16

        # 5. Validasi NTPN ke Coretax
        is_valid = ntpn_validator.validate(ntpn)
        assert is_valid is True

        # 6. Lapor SPT
        reporting = spt.submit(ntpn=ntpn)
        assert reporting.is_submitted
        assert reporting.receipt_number.startswith("SPT-")
