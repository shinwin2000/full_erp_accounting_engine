#!/usr/bin/env python3
"""
Comprehensive tests for compliance/coretax_validator.py

Covers:
- All enums and exceptions
- Data classes (FakturValidationResult, BupotValidationResult, SPTValidationResult)
- CoreTaxValidator:
  - Initialization and session setup
  - Faktur validation (both dict and positional signatures)
  - NTPN validation (format, checksum, API)
  - NSFP validation (single and range)
  - Bupot PPh 21, 23, 4(2)
  - SPT Masa PPN and Tahunan Badan
  - e-Meterai validation
  - Audit trail (record, summary, clear)
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
# CoreTaxValidator
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


class TestValidateFakturNumber:
    def test_valid_format(self, validator):
        assert validator.validate_faktur_number("010.123-22.12345678") is True

    def test_invalid_format(self, validator):
        assert validator.validate_faktur_number("12345678") is False
        assert validator.validate_faktur_number("010.123-22.1234567") is False
        assert validator.validate_faktur_number("010.123-22.123456789") is False


class TestValidateFaktur:
    # ---- Positional signature ----
    def test_validate_faktur_positional_valid(self, validator, mock_date_today):
        is_valid, errors = validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert is_valid is True
        assert errors == []

    def test_validate_faktur_positional_ppn_mismatch(self, validator):
        is_valid, errors = validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1000000"),
        )
        assert is_valid is False
        assert any("PPN amount mismatch" in e for e in errors)

    def test_validate_faktur_positional_invalid_format(self, validator):
        is_valid, errors = validator.validate_faktur(
            faktur_number="invalid",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
        )
        assert is_valid is False
        assert any("Invalid faktur number format" in e for e in errors)

    def test_validate_faktur_positional_future_date(self, validator):
        future = date.today() + timedelta(days=10)
        is_valid, errors = validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=future,
        )
        assert is_valid is False
        assert any("cannot be in the future" in e for e in errors)

    def test_validate_faktur_positional_masukan_old(self, validator, mock_date_today):
        old_date = mock_date_today - timedelta(days=100)
        is_valid, errors = validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=old_date,
            faktur_type=FakturType.MASUKAN,
        )
        # Should have error and maybe warning
        assert is_valid is False
        # Check that we have an error about older than 3 months (90 days)
        assert any("older than 3 months" in e for e in errors)

    def test_validate_faktur_positional_masukan_old_warning(self, validator, mock_date_today):
        old_date = mock_date_today - timedelta(days=70)
        is_valid, errors = validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=old_date,
            faktur_type=FakturType.MASUKAN,
        )
        # Should be valid but have warning
        assert is_valid is True
        # But we can't directly access warnings from positional return
        # Actually the positional returns (is_valid, errors) only errors,
        # warnings are inside the FakturValidationResult but not returned.
        # The test currently doesn't check warnings, but we can test via _validate_faktur_full later.

    def test_validate_faktur_positional_invalid_npwp(self, validator):
        is_valid, errors = validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            npwp_penjual="123",  # invalid
            npwp_pembeli="456",
        )
        assert is_valid is False
        # Should have two errors
        assert any("Invalid NPWP penjual" in e for e in errors)
        assert any("Invalid NPWP pembeli" in e for e in errors)

    # ---- Dict signature ----
    def test_validate_faktur_dict_valid(self, validator):
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
            "ntpn": "1234567890123456",  # NTPN present and non-None
        }
        is_valid, errors = validator.validate_faktur(faktur_dict)
        assert is_valid is True
        assert errors == []

    def test_validate_faktur_dict_invalid_format(self, validator):
        faktur_dict = {
            "nomor": "invalid",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
        }
        is_valid, errors = validator.validate_faktur(faktur_dict)
        assert is_valid is False
        assert any("Format nomor faktur tidak valid" in e for e in errors)

    def test_validate_faktur_dict_ppn_mismatch(self, validator):
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1000000"),
        }
        is_valid, errors = validator.validate_faktur(faktur_dict)
        assert is_valid is False
        assert any("PPN tidak sesuai" in e for e in errors)

    def test_validate_faktur_dict_missing_ntpn_required(self, validator):
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
            "ntpn": None,  # explicitly present but None => error
        }
        is_valid, errors = validator.validate_faktur(faktur_dict)
        assert is_valid is False
        assert any("NTPN tidak ditemukan" in e for e in errors)

    def test_validate_faktur_dict_ntpn_not_present(self, validator):
        # If key doesn't exist, no error
        faktur_dict = {
            "nomor": "010.123-22.12345678",
            "dpp": Decimal("10000000"),
            "ppn": Decimal("1100000"),
        }
        is_valid, errors = validator.validate_faktur(faktur_dict)
        assert is_valid is True
        assert errors == []

    # ---- Full validation (returns FakturValidationResult) ----
    def test_validate_faktur_full(self, validator, mock_date_today):
        result = validator._validate_faktur_full(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        assert isinstance(result, FakturValidationResult)
        assert result.is_valid is True
        assert result.status == FakturStatus.VALID

    def test_validate_faktur_full_with_warning_for_unusual_code(self, validator):
        result = validator._validate_faktur_full(
            faktur_number="999.123-22.12345678",  # unusual code
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

    # ---- API check integration ----
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

        # Should be valid but with warning about API unavailable
        is_valid, errors = v.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
            tanggal=mock_date_today,
        )
        # The method catches exception and adds warning, not error.
        # The positional return only gives errors, not warnings, so is_valid remains True.
        assert is_valid is True
        assert errors == []


class TestValidateNTPN:
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
        # Sum of digits = 1+2+...+6 = 56? Actually checksum invalid.
        # Using a known bad sum that doesn't mod 10 to 0.
        valid, errors = validator.validate_ntpn("1111111111111111")  # sum=16, mod 10=6
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


class TestValidateNSFP:
    def test_valid_nsfp(self, validator):
        assert validator.validate_nsfp("010.123-22.12345678") is True

    def test_invalid_nsfp(self, validator):
        assert validator.validate_nsfp("010.123-22.1234567") is False


class TestValidateNSFPRange:
    def test_valid_range(self, validator):
        is_valid, errors = validator.validate_nsfp_range(
            "010.123-22.00000001", "010.123-22.00000100"
        )
        assert is_valid is True
        assert errors == []

    def test_start_greater_than_end(self, validator):
        is_valid, errors = validator.validate_nsfp_range(
            "010.123-22.00000100", "010.123-22.00000001"
        )
        assert is_valid is False
        assert any("Start NSFP greater than end NSFP" in e for e in errors)

    def test_range_exceeds_1000(self, validator):
        is_valid, errors = validator.validate_nsfp_range(
            "010.123-22.00000001", "010.123-22.00001000"
        )
        assert is_valid is False
        assert any("exceeds 1000 numbers" in e for e in errors)

    def test_invalid_format(self, validator):
        is_valid, errors = validator.validate_nsfp_range("invalid", "010.123-22.00000100")
        assert is_valid is False
        assert any("Invalid start NSFP" in e for e in errors)


class TestValidateBupotPPH21:
    def test_valid_bupot_21(self, validator):
        result = validator.validate_bupot_pph21(
            bupot_number="B.21.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("0"),  # Actually should compute based on PTKP, but we'll test
            npwp_pemotong="123456789012345",
            npwp_penerima="123456789012345",
            masa_pajak=1,
            tahun_pajak=2026,
        )
        # The validation may have warnings, but should be valid if format correct
        # However due to tax calculation, might have warning, but not error.
        assert result.is_valid is True
        assert result.errors == []
        # Check warnings about tax amount mismatch (since we passed 0)
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
        # For gross 10,000,000 monthly, annual = 120,000,000, PTKP 54,000,000, PKP = 66,000,000
        # Tax 5% for first 60,000,000 = 3,000,000; 15% for remaining 6,000,000 = 900,000; total 3,900,000
        # Monthly = 325,000
        result = validator.validate_bupot_pph21(
            bupot_number="B.21.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("325000"),
            npwp_pemotong="123456789012345",
            npwp_penerima="123456789012345",
            masa_pajak=1,
            tahun_pajak=2026,
        )
        # Should be valid with no warnings about tax amount (since it matches expected)
        assert result.is_valid is True
        # Check no warnings about tax discrepancy
        assert all("Tax amount discrepancy" not in w for w in result.warnings)


class TestValidateBupotPPH23:
    def test_valid_bupot_23_with_npwp(self, validator):
        result = validator.validate_bupot_pph23(
            bupot_number="B.23.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("200000"),  # 2% of 10,000,000
            rate=Decimal("2"),
            has_npwp=True,
        )
        assert result.is_valid is True
        assert result.errors == []

    def test_valid_bupot_23_without_npwp(self, validator):
        result = validator.validate_bupot_pph23(
            bupot_number="B.23.01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("400000"),  # 4% (2% * 2) of 10,000,000
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


class TestValidateBupotPPH42:
    def test_valid_bupot_4_2(self, validator):
        result = validator.validate_bupot_pph4_2(
            bupot_number="B.4(2).01.12345678.0001",
            gross_amount=Decimal("10000000"),
            tax_amount=Decimal("100000"),  # 1% of 10,000,000
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


class TestValidateSPTMasaPPN:
    def test_valid_spt_masa_ppn(self, validator):
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

    def test_spt_masa_ppn_past_due_warning(self, validator, mock_date_today):
        # Due date 20/5/2026, today = 2026-01-15, so not past due, but we can test by setting year earlier
        # Use 2025 to simulate past due
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
            ntpn="123",  # invalid
        )
        assert result.is_valid is False
        assert any("NTPN must be exactly 16 characters" in e for e in result.errors)


class TestValidateSPTTahunanBadan:
    def test_valid_spt_tahunan(self, validator):
        result = validator.validate_spt_tahunan_badan(
            tahun=2026,
            gross_revenue=Decimal("1000000000"),
            taxable_income=Decimal("100000000"),
            tax_payable=Decimal("22000000"),  # 22% of 100,000,000
            tax_credit=Decimal("5000000"),
            underpayment=Decimal("17000000"),
        )
        assert result.is_valid is True
        assert result.errors == []

    def test_spt_tahunan_tax_payable_mismatch(self, validator):
        result = validator.validate_spt_tahunan_badan(
            tahun=2026,
            gross_revenue=Decimal("1000000000"),
            taxable_income=Decimal("100000000"),
            tax_payable=Decimal("20000000"),
            tax_credit=Decimal("5000000"),
            underpayment=Decimal("15000000"),
        )
        assert result.is_valid is False
        assert any("Underpayment mismatch" in e for e in result.errors)
        # Also warning about tax payable mismatch
        assert any("Tax payable mismatch" in w for w in result.warnings)

    def test_spt_tahunan_invalid_year(self, validator):
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


class TestValidateEMeterai:
    def test_valid_emeterai(self, validator):
        valid, errors = validator.validate_emeterai(
            meterai_code="12345678901234567890123",  # 23 chars
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


class TestAuditTrail:
    def test_record_and_summary(self, validator):
        # Initially empty
        assert validator.get_validation_summary()["total"] == 0
        # Perform a validation
        validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
        )
        summary = validator.get_validation_summary()
        assert summary["total_validations"] == 1
        assert "faktur_valid" in summary
        assert summary["faktur_valid"] == 1
        # Ensure recent is in summary
        assert len(summary["recent"]) == 1

    def test_clear_history(self, validator):
        validator.validate_faktur(
            faktur_number="010.123-22.12345678",
            dpp=Decimal("10000000"),
            ppn=Decimal("1100000"),
        )
        assert len(validator._validation_history) == 1
        validator.clear_history()
        assert len(validator._validation_history) == 0


class TestPrivateMethods:
    def test_check_faktur_via_api_disabled(self, validator):
        # Should return dict with valid None and message disabled
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