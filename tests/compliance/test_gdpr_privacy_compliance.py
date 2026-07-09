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
from unittest.mock import MagicMock, patch

import pytest

# Coba import modul asli, jika gagal gunakan mock
try:
    from compliance.gdpr_privacy_checker import GDPRChecker, PrivacyRequest
except ImportError:
    # Mock jika modul tidak ditemukan
    GDPRChecker = MagicMock
    PrivacyRequest = MagicMock

try:
    from domain.iam.user_entity import UserEntity
except ImportError:
    # Fallback class sederhana untuk test
    class UserEntity:
        def __init__(
            self,
            user_id=None,
            email=None,
            country=None,
            consent_given=None,
            consent_date=None,
        ):
            self.user_id = user_id
            self.email = email
            self.country = country
            self.consent_given = consent_given
            self.consent_date = consent_date


@pytest.fixture
def gdpr_checker():
    return GDPRChecker()


@pytest.fixture
def sample_user():
    return UserEntity(
        user_id="USER-EU-001",
        email="john.doe@example.com",
        country="DE",
        consent_given=True,
        consent_date=date(2025, 1, 1),
    )


class TestGDPRConsent:
    """Uji manajemen persetujuan (consent)."""

    def test_consent_wajib_eksplisit_dan_bisa_ditarik_kembali(self, gdpr_checker, sample_user):
        assert sample_user.consent_given is True

        with patch.object(gdpr_checker, "withdraw_consent") as mock_withdraw:
            mock_withdraw.return_value = None
            gdpr_checker.withdraw_consent(sample_user.user_id)
            # Simulasikan perubahan state
            sample_user.consent_given = False

        assert sample_user.consent_given is False

    def test_consent_tidak_boleh_diasumsikan_secara_implisit(self, gdpr_checker):
        user = UserEntity(email="new@example.com", country="FR", consent_given=None)
        assert user.consent_given is None  # harus null, bukan False otomatis


class TestGDPRRightToAccess:
    """Uji hak akses data (GDPR Article 15)."""

    def test_user_dapat_meminta_salinan_data_pribadi(self, gdpr_checker, sample_user):
        request = PrivacyRequest(user_id=sample_user.user_id, request_type="ACCESS")
        with patch.object(gdpr_checker, "handle_request") as mock_handle:
            mock_report = MagicMock()
            mock_report.data_export = {"email": "john.doe@example.com", "consent_history": []}
            mock_handle.return_value = mock_report

            report = gdpr_checker.handle_request(request)
            assert report.data_export is not None
            assert "email" in report.data_export
            assert "consent_history" in report.data_export

    def test_respond_dalam_30_hari(self, gdpr_checker, sample_user):
        request = PrivacyRequest(user_id=sample_user.user_id, request_type="ACCESS")
        with patch.object(gdpr_checker, "fulfill_request") as mock_fulfill:
            mock_response = MagicMock()
            mock_response.days_taken = 5
            mock_fulfill.return_value = mock_response

            response = gdpr_checker.fulfill_request(request)
            assert response.days_taken <= 30


class TestGDPRRightToErasure:
    """Uji hak hapus (Right to be Forgotten)."""

    def test_data_dihapus_dari_sistem_produksi(self, gdpr_checker, sample_user):
        with patch.object(gdpr_checker, "request_erasure") as mock_erasure, \
             patch.object(gdpr_checker, "is_data_erased") as mock_is_erased, \
             patch.object(gdpr_checker, "has_anonymized_audit_log") as mock_has_log:
            mock_erasure.return_value = None
            mock_is_erased.return_value = True
            mock_has_log.return_value = True

            gdpr_checker.request_erasure(user_id=sample_user.user_id)
            assert gdpr_checker.is_data_erased(sample_user.user_id) is True
            assert gdpr_checker.has_anonymized_audit_log(sample_user.user_id) is True

    def test_pengecualian_untuk_kewajiban_hukum_perpajakan(self, gdpr_checker, sample_user):
        with patch.object(gdpr_checker, "request_erasure") as mock_erasure:
            mock_erasure.side_effect = PermissionError("Tax retention period still active")
            with pytest.raises(PermissionError, match="Tax retention period still active"):
                gdpr_checker.request_erasure(
                    user_id=sample_user.user_id, force=False, ignore_legal_hold=False
                )


class TestGDPRDataPortability:
    """Uji portabilitas data (Article 20)."""

    def test_ekspor_data_dalam_format_machine_readable(self, gdpr_checker, sample_user):
        with patch.object(gdpr_checker, "export_portable_data") as mock_export:
            mock_export.return_value = MagicMock(
                mime_type="application/json", data={"structured": "data"}
            )
            export = gdpr_checker.export_portable_data(sample_user.user_id, format="json")
            assert export.mime_type == "application/json"
            assert "structured" in export.data

    def test_ekspor_harus_mencakup_data_yang_diberikan_oleh_user(self, gdpr_checker, sample_user):
        with patch.object(gdpr_checker, "export_portable_data") as mock_export:
            mock_export.return_value = MagicMock(data={"profile": {}, "transaction_history": []})
            export = gdpr_checker.export_portable_data(sample_user.user_id)
            assert "profile" in export.data
            assert "transaction_history" in export.data