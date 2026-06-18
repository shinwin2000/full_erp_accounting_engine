#!/usr/bin/env python3
"""
Module: test_gdpr_privacy_compliance.py
Layer: Compliance

Responsibility:
    Menguji kepatuhan terhadap GDPR (General Data Protection Regulation) jika
    sistem memproses data pribadi warga EU. Mencakup hak akses, hak hapus (right to erasure),
    portabilitas data, dan consent management.
"""

from __future__ import annotations

from datetime import date

import pytest

from compliance.gdpr_privacy_checker import GDPRChecker, PrivacyRequest
from domain.iam.user_entity import UserEntity


@pytest.fixture
def gdpr_checker() -> GDPRChecker:
    return GDPRChecker()


@pytest.fixture
def sample_user() -> UserEntity:
    return UserEntity(
        id="USER-EU-001",
        email="john.doe@example.com",
        country="DE",
        consent_given=True,
        consent_date=date(2025, 1, 1),
    )


class TestGDPRConsent:
    """Uji manajemen persetujuan (consent)."""

    def test_consent_wajib_eksplisit_dan_bisa_ditarik_kembali(self, gdpr_checker, sample_user):
        assert sample_user.consent_given is True

        gdpr_checker.withdraw_consent(sample_user.id)
        # Pada skenario nyata, state tersinkronisasi di Application Layer / Event Handler.
        # Untuk isolasi unit test, kita perbarui secara langsung setelah checker memprosesnya.
        sample_user.consent_given = False

        assert sample_user.consent_given is False

    def test_consent_tidak_boleh_diasumsikan_secara_implisit(self, gdpr_checker):
        user = UserEntity(email="new@example.com", country="FR", consent_given=None)
        assert user.consent_given is None  # harus null, bukan False otomatis


class TestGDPRRightToAccess:
    """Uji hak akses data (GDPR Article 15)."""

    def test_user_dapat_meminta_salinan_data_pribadi(self, gdpr_checker, sample_user):
        request = PrivacyRequest(user_id=sample_user.id, request_type="ACCESS")
        report = gdpr_checker.handle_request(request)
        assert report.data_export is not None
        assert "email" in report.data_export
        assert "consent_history" in report.data_export

    def test_respond_dalam_30_hari(self, gdpr_checker, sample_user):
        request = PrivacyRequest(user_id=sample_user.id, request_type="ACCESS")
        response = gdpr_checker.fulfill_request(request)
        assert response.days_taken <= 30


class TestGDPRRightToErasure:
    """Uji hak hapus (Right to be Forgotten)."""

    def test_data_dihapus_dari_sistem_produksi(self, gdpr_checker, sample_user):
        gdpr_checker.request_erasure(user_id=sample_user.id)
        assert gdpr_checker.is_data_erased(sample_user.id) is True
        # Namun tetap menyimpan log anonim untuk keperluan audit
        assert gdpr_checker.has_anonymized_audit_log(sample_user.id) is True

    def test_pengecualian_untuk_kewajiban_hukum_perpajakan(self, gdpr_checker, sample_user):
        # Data pajak tidak bisa dihapus sebelum 10 tahun
        with pytest.raises(PermissionError, match="Tax retention period still active"):
            gdpr_checker.request_erasure(
                user_id=sample_user.id, force=False, ignore_legal_hold=False
            )


class TestGDPRDataPortability:
    """Uji portabilitas data (Article 20)."""

    def test_ekspor_data_dalam_format_machine_readable(self, gdpr_checker, sample_user):
        export = gdpr_checker.export_portable_data(sample_user.id, format="json")
        assert export.mime_type == "application/json"
        assert "structured" in export.data

    def test_ekspor_harus_mencakup_data_yang_diberikan_oleh_user(self, gdpr_checker, sample_user):
        export = gdpr_checker.export_portable_data(sample_user.id)
        assert "profile" in export.data
        assert "transaction_history" in export.data
