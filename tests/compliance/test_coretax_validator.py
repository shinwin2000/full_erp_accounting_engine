#!/usr/bin/env python3
"""
Comprehensive tests for compliance/coretax_validator.py

Covers:
- All enums and exceptions
- Data classes (FakturValidationResult, BupotValidationResult, SPTValidationResult)
- CoreTaxValidator:
  - Initialization and session setup (including _init_session)
  - Faktur validation (both dict and positional signatures, including private methods)
  - NTPN validation (format, checksum, API)
  - NSFP validation (single and range)
  - Bupot PPh 21, 23, 4(2)
  - SPT Masa PPN and Tahunan Badan
  - e-Meterai validation
  - Audit trail (record, summary, clear) including direct _record_validation
- Mocked API calls (requests) to avoid live network
- All edge cases and error messages
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from compliance.coretax_validator import (
    BupotType,
    BupotValidationResult,
    CoretaxAPIError,
    CoretaxValidationError,
    CoreTaxValidator,
    FakturStatus,
    FakturType,
    FakturValidationResult,
    SPTType,
    SPTValidationResult,
    ValidationSeverity,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def validator() -> CoreTaxValidator:
    """Create a CoreTaxValidator with API checks disabled by default."""
    return CoreTaxValidator(enable_api_check=False)


@pytest.fixture
def validator_with_api() -> CoreTaxValidator:
    """Create a CoreTaxValidator with API checks enabled."""
    return CoreTaxValidator(enable_api_check=True, api_base_url="https://test.api")


@pytest.fixture
def mock_session() -> MagicMock:
    """Mock requests.Session."""
    with patch("compliance.coretax_validator.requests.Session") as mock:
        session = MagicMock()
        mock.return_value = session
        yield session


@pytest.fixture
def mock_date_today() -> date:
    """Return a fixed date for today to avoid flaky tests."""
    with patch("compliance.coretax_validator.date") as mock_date:
        fixed_today = date(2026, 1, 15)
        mock_date.today.return_value = fixed_today
        yield fixed_today


# =============================================================================
# Enums
# =============================================================================

class TestEnums:
    def test_faktur_status_members(self):
        assert FakturStatus.VALID.value == "valid"
        assert FakturStatus.INVALID.value == "invalid"
        assert FakturStatus.PENDING.value == "pending"
        assert FakturStatus.REJECTED.value == "rejected"
        assert FakturStatus.EXPIRED.value == "expired"

    def test_faktur_type_members(self):
        assert FakturType.KELUARAN.value == "keluaran"
        assert FakturType.MASUKAN.value == "masukan"

    def test_bupot_type_members(self):
        assert BupotType.PPH_21.value == "pph21"
        assert BupotType.PPH_23.value == "pph23"
        assert BupotType.PPH_4_2.value == "pph4_2"
        assert BupotType.PPH_26.value == "pph26"

    def test_spt_type_members(self):
        assert SPTType.MASA_PPN.value == "masa_ppn"
        assert SPTType.MASA_PPH_21.value == "masa_pph21"
        assert SPTType.MASA_PPH_23.value == "masa_pph23"
        assert SPTType.TAHUNAN_BADAN.value == "tahunan_badan"
        assert SPTType.TAHUNAN_OP.value == "tahunan_op"

    def test_validation_severity_members(self):
        assert ValidationSeverity.INFO.value == "info"
        assert ValidationSeverity.WARNING.value == "warning"
        assert ValidationSeverity.ERROR.value == "error"
        assert ValidationSeverity.CRITICAL.value == "critical"


# =============================================================================
# Exceptions
# =============================================================================

class TestExceptions:
    def test_coretax_validation_error(self):
        with pytest.raises(CoretaxValidationError):
            raise CoretaxValidationError("test")

    def test_coretax_api_error(self):
        with pytest.raises(CoretaxAPIError):
            raise CoretaxAPIError("test")


# =============================================================================
# Data Classes
# =============================================================================

class TestFakturValidationResult:
    def test_creation_and_hash(self):
        now = datetime(2026, 1, 15, 12, 0, 0)
        result = FakturValidationResult(
            faktur_number="010.123-22.12345678",
            is_valid=True,
            errors=[],
            warnings=[],
            status=FakturStatus.VALID,
            validation_timestamp=now,
        )
        assert result.faktur_number == "010.123-22.12345678"
        assert result.is_valid is True
        assert result.status == FakturStatus.VALID
        assert result.hash_sha256 is not None
        assert isinstance(result.hash_sha256, str)
        # to_dict
        d = result.to_dict()
        assert d["faktur_number"] == "010.123-22.12345678"
        assert d["is_valid"] is True
        assert d["status"] == "valid"
        assert "hash" in d


class TestBupotValidationResult:
    def test_creation(self):
        result = BupotValidationResult(
            bupot_number="B.21.01.12345678.0001",
            is_valid=True,
            errors=[],
            warnings=["check tax"],
        )
        assert result.bupot_number == "B.21.01.12345678.0001"
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == ["check tax"]
        assert result.timestamp is not None


class TestSPTValidationResult:
    def test_creation(self):
        result = SPTValidationResult(
            spt_id="PPN-5-2026",
            is_valid=False,
            errors=["error1"],
            warnings=["warning1"],
        )
        assert result.spt_id == "PPN-5-2026"
        assert result.is_valid is False
        assert result.errors == ["error1"]
        assert result.warnings == ["warning1"]


# =============================================================================
# CoreTaxValidator - Initialization
# =============================================================================

class TestCoreTaxValidatorInit:
    def test_default_init(self):
        v = CoreTaxValidator()
        assert v.enable_api_check is False
        assert v.api_base_url == "https://api.coretax.djp.go.id/v1"
        assert v._session is None

    def test_with_api_enabled(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        assert v.enable_api_check is True
        assert v._session is not None
        # Verify session was configured with retries
        mock_session.assert_called_once()
        # Check mount calls (at least two)
        mount_calls = mock_session.return_value.mount.call_args_list
        assert len(mount_calls) >= 2

    def test_init_session_direct(self, mock_session):
        """Direct test for _init_session private method."""
        v = CoreTaxValidator(enable_api_check=False)
        # Manually call _init_session
        v._init_session()
        assert v._session is not None
        mock_session.assert_called_once()
        # Check that mounts are set
        mock_session.return_value.mount.assert_called()
        # Check headers update
        mock_session.return_value.headers.update.assert_called_once_with({"User-Agent": "ERP-Accounting-Engine/1.0"})


# =============================================================================
# CoreTaxValidator - Faktur Validation (private methods)
# =============================================================================

class TestCoreTaxValidatorFakturPrivate:
    def test_validate_faktur_positional_valid(self, validator, mock_date_today):
        is_valid, errors = validator._validate_faktur_positional(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert is_valid is True
        assert errors == []

    def test_validate_faktur_positional_ppn_mismatch(self, validator):
        is_valid, errors = validator._validate_faktur_positional(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1000000"),
        )
        assert is_valid is False
        assert any("PPN amount mismatch" in e for e in errors)

    def test_validate_faktur_positional_invalid_format(self, validator):
        is_valid, errors = validator._validate_faktur_positional(
            faktur_number="invalid",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
        )
        assert is_valid is False
        assert any("Invalid faktur number format" in e for e in errors)

    def test_validate_faktur_positional_future_date(self, validator):
        future = date.today() + timedelta(days=10)
        is_valid, errors = validator._validate_faktur_positional(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=future,
        )
        assert is_valid is False
        assert any("cannot be in the future" in e for e in errors)

    def test_validate_faktur_positional_masukan_old(self, validator, mock_date_today):
        old_date = mock_date_today - timedelta(days=100)
        is_valid, errors = validator._validate_faktur_positional(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=old_date,
            faktur_type=FakturType.MASUKAN,
        )
        assert is_valid is False
        assert any("older than 3 months" in e for e in errors)

    def test_validate_faktur_positional_invalid_npwp(self, validator):
        is_valid, errors = validator._validate_faktur_positional(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            npwp_penjual="123",
            npwp_pembeli="456",
        )
        assert is_valid is False
        assert any("Invalid NPWP penjual" in e for e in errors)
        assert any("Invalid NPWP pembeli" in e for e in errors)

    # ---- Dict signature ----
    def test_validate_faktur_dict_valid(self, validator):
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
            "ntpn": "1234567890123456",
        }
        is_valid, errors = validator._validate_faktur_dict(faktur_dict)
        assert is_valid is True
        assert errors == []

    def test_validate_faktur_dict_invalid_format(self, validator):
        faktur_dict = {
            "nomor": "invalid",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
        }
        is_valid, errors = validator._validate_faktur_dict(faktur_dict)
        assert is_valid is False
        assert any("Format nomor faktur tidak valid" in e for e in errors)

    def test_validate_faktur_dict_ppn_mismatch(self, validator):
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1000000"),
        }
        is_valid, errors = validator._validate_faktur_dict(faktur_dict)
        assert is_valid is False
        assert any("PPN tidak sesuai" in e for e in errors)

    def test_validate_faktur_dict_missing_ntpn_required(self, validator):
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
            "ntpn": None,
        }
        is_valid, errors = validator._validate_faktur_dict(faktur_dict)
        assert is_valid is False
        assert any("NTPN tidak ditemukan" in e for e in errors)

    def test_validate_faktur_dict_ntpn_not_present(self, validator):
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
        }
        is_valid, errors = validator._validate_faktur_dict(faktur_dict)
        assert is_valid is True
        assert errors == []


# =============================================================================
# CoreTaxValidator - Faktur Validation (public interface)
# =============================================================================

class TestCoreTaxValidatorFakturPublic:
    def test_validate_faktur_positional_public(self, validator, mock_date_today):
        """Public validate_faktur with positional args - should call _validate_faktur_positional."""
        is_valid, errors = validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert is_valid is True
        assert errors == []

    def test_validate_faktur_dict_public(self, validator):
        """Public validate_faktur with dict - should call _validate_faktur_dict."""
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
        }
        is_valid, errors = validator.validate_faktur(faktur_dict)
        assert is_valid is True
        assert errors == []

    def test_validate_faktur_full_result(self, validator, mock_date_today):
        result = validator._validate_faktur_full(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert isinstance(result, FakturValidationResult)
        assert result.is_valid is True
        assert result.status == FakturStatus.VALID

    def test_validate_faktur_full_with_warning(self, validator):
        result = validator._validate_faktur_full(
            faktur_number="999.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
        )
        assert result.is_valid is True
        assert any("Unusual transaction code" in w for w in result.warnings)

    def test_validate_faktur_full_masukan_warning(self, validator, mock_date_today):
        old_date = mock_date_today - timedelta(days=70)
        result = validator._validate_faktur_full(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=old_date,
            faktur_type=FakturType.MASUKAN,
        )
        assert result.is_valid is True
        assert any("more than 60 days old" in w for w in result.warnings)

    def test_validate_faktur_api_check_ok(self, mock_session, mock_date_today):
        v = CoreTaxValidator(enable_api_check=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"valid": True, "message": "OK"}
        mock_response.raise_for_status.return_value = None
        mock_session.post.return_value = mock_response

        is_valid, errors = v.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert is_valid is True
        assert errors == []
        mock_session.post.assert_called_once()

    def test_validate_faktur_api_check_fails(self, mock_session, mock_date_today):
        v = CoreTaxValidator(enable_api_check=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"valid": False, "message": "Invalid faktur"}
        mock_response.raise_for_status.return_value = None
        mock_session.post.return_value = mock_response

        is_valid, errors = v.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert is_valid is False
        assert any("API validation failed" in e for e in errors)

    def test_validate_faktur_api_check_exception(self, mock_session, mock_date_today):
        v = CoreTaxValidator(enable_api_check=True)
        mock_session.post.side_effect = Exception("Network error")
        is_valid, errors = v.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert is_valid is True
        assert errors == []


# =============================================================================
# CoreTaxValidator - NTPN Validation
# =============================================================================

class TestCoreTaxValidatorNTPN:
    def test_valid_ntpn(self, validator):
        valid, errors = validator.validate_ntpn("1234567890123456")
        assert valid is True
        assert errors == []

    def test_ntpn_too_short(self, validator):
        valid, errors = validator.validate_ntpn("123456789012345")
        assert valid is False
        assert any("exactly 16 characters" in e for e in errors)

    def test_ntpn_non_digit(self, validator):
        valid, errors = validator.validate_ntpn("123456789012345a")
        assert valid is False
        assert any("only digits" in e for e in errors)

    def test_ntpn_checksum_fail(self, validator):
        valid, errors = validator.validate_ntpn("1111111111111111")
        assert valid is False
        assert any("checksum invalid" in e for e in errors)

    def test_ntpn_api_check_ok(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"valid": True, "message": "OK"}
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        valid, errors = v.validate_ntpn("1234567890123456")
        assert valid is True
        assert errors == []
        mock_session.get.assert_called_once()

    def test_ntpn_api_check_fails(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"valid": False, "message": "Not found"}
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        valid, errors = v.validate_ntpn("1234567890123456")
        assert valid is False
        assert any("NTPN not found" in e for e in errors)

    def test_ntpn_api_check_exception(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        mock_session.get.side_effect = Exception("API error")
        valid, errors = v.validate_ntpn("1234567890123456")
        assert valid is False
        assert any("Unable to verify NTPN" in e for e in errors)


# =============================================================================
# CoreTaxValidator - NSFP Validation
# =============================================================================

class TestCoreTaxValidatorNSFP:
    def test_valid_nsfp(self, validator):
        assert validator.validate_nsfp("010.123-22.12345678") is True

    def test_invalid_nsfp(self, validator):
        assert validator.validate_nsfp("010.123-22.1234567") is False

    def test_valid_nsfp_range(self, validator):
        is_valid, errors = validator.validate_nsfp_range(
            "010.123-22.00000001", "010.123-22.00000100"
        )
        assert is_valid is True
        assert errors == []

    def test_nsfp_range_start_greater_than_end(self, validator):
        is_valid, errors = validator.validate_nsfp_range(
            "010.123-22.00000100", "010.123-22.00000001"
        )
        assert is_valid is False
        assert any("Start NSFP greater than end NSFP" in e for e in errors)

    def test_nsfp_range_exceeds_1000(self, validator):
        is_valid, errors = validator.validate_nsfp_range(
            "010.123-22.00000001", "010.123-22.00001000"
        )
        assert is_valid is False
        assert any("exceeds 1000 numbers" in e for e in errors)

    def test_nsfp_range_invalid_format(self, validator):
        is_valid, errors = validator.validate_nsfp_range("invalid", "010.123-22.00000100")
        assert is_valid is False
        assert any("Invalid start NSFP" in e for e in errors)


# =============================================================================
# CoreTaxValidator - Bupot Validation
# =============================================================================

class TestCoreTaxValidatorBupot:
    def test_bupot_21_valid(self, validator):
        result = validator.validate_bupot_pph21(
            bupot_number="B.21.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("0"),
            npwp_pemotong="123456789012345",
            npwp_penerima="123456789012345",
            masa_pajak=1,
            tahun_pajak=2026,
        )
        assert result.is_valid is True
        assert result.errors == []
        assert any("Tax amount discrepancy" in w for w in result.warnings)

    def test_bupot_21_invalid_format(self, validator):
        result = validator.validate_bupot_pph21(
            bupot_number="invalid",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("0"),
            npwp_pemotong="123456789012345",
            npwp_penerima="123456789012345",
            masa_pajak=1,
            tahun_pajak=2026,
        )
        assert result.is_valid is False
        assert any("Invalid bupot 21 number format" in e for e in result.errors)

    def test_bupot_21_invalid_masa(self, validator):
        result = validator.validate_bupot_pph21(
            bupot_number="B.21.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("0"),
            npwp_pemotong="123456789012345",
            npwp_penerima="123456789012345",
            masa_pajak=13,
            tahun_pajak=2026,
        )
        assert result.is_valid is False
        assert any("Invalid masa pajak" in e for e in result.errors)

    def test_bupot_21_tax_calculation(self, validator):
        result = validator.validate_bupot_pph21(
            bupot_number="B.21.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("325000"),
            npwp_pemotong="123456789012345",
            npwp_penerima="123456789012345",
            masa_pajak=1,
            tahun_pajak=2026,
        )
        assert result.is_valid is True
        assert all("Tax amount discrepancy" not in w for w in result.warnings)

    def test_bupot_23_valid_with_npwp(self, validator):
        result = validator.validate_bupot_pph23(
            bupot_number="B.23.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("200000"),
            rate=Decimal("2"),
            has_npwp=True,
        )
        assert result.is_valid is True
        assert result.errors == []

    def test_bupot_23_without_npwp(self, validator):
        result = validator.validate_bupot_pph23(
            bupot_number="B.23.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("400000"),
            rate=Decimal("2"),
            has_npwp=False,
        )
        assert result.is_valid is True

    def test_bupot_23_tax_mismatch(self, validator):
        result = validator.validate_bupot_pph23(
            bupot_number="B.23.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("100000"),
            rate=Decimal("2"),
            has_npwp=True,
        )
        assert result.is_valid is False
        assert any("Tax amount mismatch" in e for e in result.errors)

    def test_bupot_23_invalid_format(self, validator):
        result = validator.validate_bupot_pph23(
            bupot_number="invalid",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("200000"),
            rate=Decimal("2"),
        )
        assert result.is_valid is False
        assert any("Invalid bupot 23 number format" in e for e in result.errors)

    def test_bupot_4_2_valid(self, validator):
        result = validator.validate_bupot_pph4_2(
            bupot_number="B.4(2).01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("100000"),
            rate=Decimal("1"),
        )
        assert result.is_valid is True
        assert result.errors == []

    def test_bupot_4_2_tax_mismatch(self, validator):
        result = validator.validate_bupot_pph4_2(
            bupot_number="B.4(2).01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("50000"),
            rate=Decimal("1"),
        )
        assert result.is_valid is False
        assert any("Tax amount mismatch" in e for e in result.errors)

    def test_bupot_4_2_invalid_format(self, validator):
        result = validator.validate_bupot_pph4_2(
            bupot_number="invalid",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("100000"),
            rate=Decimal("1"),
        )
        assert result.is_valid is False
        assert any("Invalid bupot 4(2) number format" in e for e in result.errors)


# =============================================================================
# CoreTaxValidator - SPT Validation
# =============================================================================

class TestCoreTaxValidatorSPT:
    def test_spt_masa_ppn_valid(self, validator):
        result = validator.validate_spt_masa_ppn(
            masa=5,
            tahun=2026,
            total_ppn_keluaran=Decimal("11000000"),
            total_ppn_masukan=Decimal("5500000"),
            ppn_kurang_bayar=Decimal("5500000"),
            ntpn="1234567890123456",
        )
        assert result.is_valid is True
        assert result.errors == []

    def test_spt_masa_ppn_kurang_bayar_mismatch(self, validator):
        result = validator.validate_spt_masa_ppn(
            masa=5,
            tahun=2026,
            total_ppn_keluaran=Decimal("11000000"),
            total_ppn_masukan=Decimal("5500000"),
            ppn_kurang_bayar=Decimal("1000000"),
            ntpn=None,
        )
        assert result.is_valid is False
        assert any("PPN kurang bayar mismatch" in e for e in result.errors)

    def test_spt_masa_ppn_past_due_warning(self, validator):
        result = validator.validate_spt_masa_ppn(
            masa=5,
            tahun=2025,
            total_ppn_keluaran=Decimal("11000000"),
            total_ppn_masukan=Decimal("5500000"),
            ppn_kurang_bayar=Decimal("5500000"),
            ntpn=None,
        )
        assert result.is_valid is True
        assert any("past due date" in w for w in result.warnings)

    def test_spt_masa_ppn_invalid_masa(self, validator):
        result = validator.validate_spt_masa_ppn(
            masa=13,
            tahun=2026,
            total_ppn_keluaran=Decimal("11000000"),
            total_ppn_masukan=Decimal("5500000"),
            ppn_kurang_bayar=Decimal("5500000"),
        )
        assert result.is_valid is False
        assert any("Invalid masa" in e for e in result.errors)

    def test_spt_masa_ppn_ntpn_invalid(self, validator):
        result = validator.validate_spt_masa_ppn(
            masa=5,
            tahun=2026,
            total_ppn_keluaran=Decimal("11000000"),
            total_ppn_masukan=Decimal("5500000"),
            ppn_kurang_bayar=Decimal("5500000"),
            ntpn="123",
        )
        assert result.is_valid is False
        assert any("NTPN must be exactly 16 characters" in e for e in result.errors)

    def test_spt_tahunan_badan_valid(self, validator):
        result = validator.validate_spt_tahunan_badan(
            tahun=2026,
            gross_revenue=Decimal("1000000000"),
            taxable_income=Decimal("100000000"),
            tax_payable=Decimal("22000000"),
            tax_credit=Decimal("5000000"),
            underpayment=Decimal("17000000"),
        )
        assert result.is_valid is True
        assert result.errors == []

    def test_spt_tahunan_badan_underpayment_mismatch(self, validator):
        result = validator.validate_spt_tahunan_badan(
            tahun=2026,
            gross_revenue=Decimal("1000000000"),
            taxable_income=Decimal("100000000"),
            tax_payable=Decimal("22000000"),
            tax_credit=Decimal("5000000"),
            underpayment=Decimal("15000000"),
        )
        assert result.is_valid is False
        assert any("Underpayment mismatch" in e for e in result.errors)

    def test_spt_tahunan_badan_invalid_year(self, validator):
        result = validator.validate_spt_tahunan_badan(
            tahun=1999,
            gross_revenue=Decimal("1000000000"),
            taxable_income=Decimal("100000000"),
            tax_payable=Decimal("22000000"),
            tax_credit=Decimal("5000000"),
            underpayment=Decimal("17000000"),
        )
        assert result.is_valid is False
        assert any("Invalid year" in e for e in result.errors)


# =============================================================================
# CoreTaxValidator - e-Meterai Validation
# =============================================================================

class TestCoreTaxValidatorEMeterai:
    def test_valid_emeterai(self, validator):
        valid, errors = validator.validate_emeterai(
            meterai_code="12345678901234567890123",
            document_value=Decimal("15000000"),
        )
        assert valid is True
        assert errors == []

    def test_emeterai_too_short(self, validator):
        valid, errors = validator.validate_emeterai(
            meterai_code="123",
            document_value=Decimal("15000000"),
        )
        assert valid is False
        assert any("must be 23 characters" in e for e in errors)

    def test_emeterai_not_required(self, validator):
        valid, errors = validator.validate_emeterai(
            meterai_code="12345678901234567890123",
            document_value=Decimal("5000000"),
        )
        assert valid is False
        assert any("e-Meterai not required" in e for e in errors)


# =============================================================================
# CoreTaxValidator - Audit Trail
# =============================================================================

class TestCoreTaxValidatorAudit:
    def test_record_validation_direct(self, validator):
        """Direct test for _record_validation private method."""
        data = {"test": "data"}
        validator._record_validation("test_type", data)
        assert len(validator._validation_history) == 1
        record = validator._validation_history[0]
        assert record["validation_type"] == "test_type"
        assert record["data"] == data
        assert "timestamp" in record

    def test_record_validation_truncation(self, validator):
        """Test that history is limited to 10000 and trimmed."""
        # Fill with more than 10000 records
        for i in range(10001):
            validator._record_validation("test", {"i": i})
        assert len(validator._validation_history) == 5000  # trimmed to last 5000

    def test_validation_summary(self, validator):
        validator._record_validation("faktur", {"is_valid": True})
        validator._record_validation("faktur", {"is_valid": False})
        summary = validator.get_validation_summary()
        assert summary["total_validations"] == 2
        assert summary["faktur_valid"] == 1
        assert summary["faktur_invalid"] == 1
        assert len(summary["recent"]) == 2

    def test_validation_summary_empty(self, validator):
        summary = validator.get_validation_summary()
        assert summary == {"total": 0}

    def test_clear_history(self, validator):
        validator._record_validation("test", {})
        assert len(validator._validation_history) == 1
        validator.clear_history()
        assert len(validator._validation_history) == 0

    def test_record_validation_integration(self, validator, mock_date_today):
        """Test that public validate_faktur calls _record_validation."""
        validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert len(validator._validation_history) == 1
        record = validator._validation_history[0]
        assert record["validation_type"] == "faktur"
        assert record["data"]["is_valid"] is True


# =============================================================================
# CoreTaxValidator - Private API check methods
# =============================================================================

class TestCoreTaxValidatorPrivateAPI:
    def test_check_faktur_via_api_disabled(self, validator):
        result = validator._check_faktur_via_api("010.123-22.12345678")
        assert result == {"valid": None, "message": "API disabled"}

    def test_check_faktur_via_api_enabled_success(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"valid": True, "message": "OK"}
        mock_response.raise_for_status.return_value = None
        mock_session.post.return_value = mock_response

        result = v._check_faktur_via_api("010.123-22.12345678")
        assert result == {"valid": True, "message": "OK"}

    def test_check_faktur_via_api_enabled_exception(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        mock_session.post.side_effect = Exception("Network error")
        with pytest.raises(CoretaxAPIError, match="API call failed"):
            v._check_faktur_via_api("010.123-22.12345678")

    def test_check_ntpn_via_api_disabled(self, validator):
        result = validator._check_ntpn_via_api("1234567890123456")
        assert result == {"valid": None}

    def test_check_ntpn_via_api_enabled_success(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        mock_response = MagicMock()
        mock_response.json.return_value = {"valid": True, "message": "OK"}
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        result = v._check_ntpn_via_api("1234567890123456")
        assert result == {"valid": True, "message": "OK"}

    def test_check_ntpn_via_api_enabled_exception(self, mock_session):
        v = CoreTaxValidator(enable_api_check=True)
        mock_session.get.side_effect = Exception("API error")
        with pytest.raises(CoretaxAPIError, match="NTPN API failed"):
            v._check_ntpn_via_api("1234567890123456")