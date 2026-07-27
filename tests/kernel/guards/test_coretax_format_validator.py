# tests/kernel/guards/test_coretax_format_validator.py
"""
Comprehensive unit tests for kernel/guards/coretax_format_validator.py.

Covers:
- CoretaxValidationSeverity enum
- CoretaxDocumentType enum
- CoretaxValidationResult: construction, hash, to_dict, validation
- CoretaxFormatValidator: all static methods
  - validate_npwp
  - validate_ntpn
  - validate_faktur_pajak
  - validate_masa_pajak
  - validate_tahun_pajak
  - validate_nilai_ppn
  - validate_kode_efaktur
  - validate_bukti_potong_type
  - validate_tarif_pph
  - validate_spt_type
- CoretaxFormatGuard:
  - __init__, singleton
  - validate_efaktur_data
  - validate_ebupot_data
  - validate_spt_submission
  - enforce_efaktur, enforce_ebupot, enforce_spt
  - get_validation_history, get_statistics
  - check, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset
- Module-level get_coretax_format_guard
- Edge cases: empty strings, invalid formats, out-of-range values, Decimal vs float
- All exceptions: CoretaxFormatError raised in enforce methods
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kernel.guards.coretax_format_validator import (
    BaseCoretaxFormatGuard,
    CoretaxDocumentType,
    CoretaxFormatGuard,
    CoretaxFormatValidator,
    CoretaxValidationResult,
    CoretaxValidationSeverity,
    get_coretax_format_guard,
)
from kernel.guards.guard_exceptions import CoretaxFormatError, GuardSeverity


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def guard():
    """Fresh CoretaxFormatGuard instance (reset singleton)."""
    CoretaxFormatGuard._instance = None
    return CoretaxFormatGuard()


@pytest.fixture
def sample_validation_result():
    return CoretaxValidationResult(
        validation_id=uuid4(),
        document_type=CoretaxDocumentType.FAKTUR_PAJAK,
        field_name="npwp_penjual",
        field_value="12.345.678.9-012.345",
        is_valid=True,
        severity=CoretaxValidationSeverity.INFO,
        message="OK",
        validated_by="system",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestCoretaxValidationSeverity:
    def test_members(self):
        assert CoretaxValidationSeverity.CRITICAL.value == 80
        assert CoretaxValidationSeverity.HIGH.value == 60
        assert CoretaxValidationSeverity.MEDIUM.value == 40
        assert CoretaxValidationSeverity.LOW.value == 20


class TestCoretaxDocumentType:
    def test_members(self):
        assert CoretaxDocumentType.FAKTUR_PAJAK.value == "faktur_pajak"
        assert CoretaxDocumentType.SPT_MASA_PPN.value == "spt_masa_ppn"
        assert CoretaxDocumentType.SPT_MASA_PPH_21.value == "spt_masa_pph_21"
        assert CoretaxDocumentType.SPT_MASA_PPH_23.value == "spt_masa_pph_23"
        assert CoretaxDocumentType.SPT_TAHUNAN.value == "spt_tahunan"
        assert CoretaxDocumentType.BUKTI_POTONG.value == "bukti_potong"
        assert CoretaxDocumentType.NTPN.value == "ntpn"


# ============================================================================
# Tests for CoretaxValidationResult
# ============================================================================

class TestCoretaxValidationResult:
    def test_construction(self, sample_validation_result):
        assert sample_validation_result.validation_id is not None
        assert sample_validation_result.document_type == CoretaxDocumentType.FAKTUR_PAJAK
        assert sample_validation_result.is_valid is True
        assert sample_validation_result.cryptographic_hash != ""

    def test_compute_hash(self, sample_validation_result):
        h1 = sample_validation_result.compute_hash()
        h2 = sample_validation_result.compute_hash()
        assert h1 == h2
        # Change a field
        sample_validation_result.is_valid = False
        assert sample_validation_result.compute_hash() != h1

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            CoretaxValidationResult(
                validation_id=uuid4(),
                document_type=CoretaxDocumentType.FAKTUR_PAJAK,
                field_name="test",
                field_value="test",
                is_valid=True,
                severity=CoretaxValidationSeverity.INFO,
                message="OK",
                cryptographic_hash="wronghash",
            )

    def test_to_dict(self, sample_validation_result):
        d = sample_validation_result.to_dict()
        assert d["validation_id"] == str(sample_validation_result.validation_id)
        assert d["document_type"] == "faktur_pajak"
        assert d["field_name"] == "npwp_penjual"
        assert d["is_valid"] is True
        assert d["severity"] == "INFO"
        assert "timestamp" in d


# ============================================================================
# Tests for CoretaxFormatValidator (Static Methods)
# ============================================================================

class TestCoretaxFormatValidator:
    # ---- validate_npwp ----
    def test_validate_npwp_valid_formatted(self):
        valid, msg = CoretaxFormatValidator.validate_npwp("12.345.678.9-012.345")
        assert valid is True
        assert msg is None

    def test_validate_npwp_valid_raw(self):
        valid, msg = CoretaxFormatValidator.validate_npwp("123456789012345")
        assert valid is True
        assert msg is None

    def test_validate_npwp_empty(self):
        valid, msg = CoretaxFormatValidator.validate_npwp("")
        assert valid is False
        assert "tidak boleh kosong" in msg

    def test_validate_npwp_invalid_format(self):
        valid, msg = CoretaxFormatValidator.validate_npwp("12.345.678.9-012.34")
        assert valid is False
        assert "Format NPWP tidak valid" in msg

    # ---- validate_ntpn ----
    def test_validate_ntpn_valid(self):
        valid, msg = CoretaxFormatValidator.validate_ntpn("ABC1234567890123")
        assert valid is True
        assert msg is None

    def test_validate_ntpn_empty(self):
        valid, msg = CoretaxFormatValidator.validate_ntpn("")
        assert valid is False
        assert "tidak boleh kosong" in msg

    def test_validate_ntpn_invalid(self):
        valid, msg = CoretaxFormatValidator.validate_ntpn("123")
        assert valid is False
        assert "Format NTPN tidak valid" in msg

    # ---- validate_faktur_pajak ----
    def test_validate_faktur_pajak_valid(self):
        valid, msg = CoretaxFormatValidator.validate_faktur_pajak("010-00-00000001-0000000001")
        assert valid is True
        assert msg is None

    def test_validate_faktur_pajak_valid_raw(self):
        valid, msg = CoretaxFormatValidator.validate_faktur_pajak("1234567890123456")
        assert valid is True

    def test_validate_faktur_pajak_empty(self):
        valid, msg = CoretaxFormatValidator.validate_faktur_pajak("")
        assert valid is False
        assert "tidak boleh kosong" in msg

    def test_validate_faktur_pajak_invalid(self):
        valid, msg = CoretaxFormatValidator.validate_faktur_pajak("invalid")
        assert valid is False
        assert "Format nomor faktur pajak tidak valid" in msg

    def test_validate_faktur_pajak_with_valid_kode(self):
        valid, msg = CoretaxFormatValidator.validate_faktur_pajak("123", kode="010")
        # Faktur string "123" doesn't match pattern, so invalid regardless of kode
        assert valid is False

    def test_validate_faktur_pajak_with_invalid_kode(self):
        valid, msg = CoretaxFormatValidator.validate_faktur_pajak("010-00-00000001-0000000001", kode="999")
        assert valid is False
        assert "Kode faktur pajak '999' tidak valid" in msg

    # ---- validate_masa_pajak ----
    def test_validate_masa_pajak_valid(self):
        valid, msg = CoretaxFormatValidator.validate_masa_pajak("01/2025")
        assert valid is True
        assert msg is None

    def test_validate_masa_pajak_empty(self):
        valid, msg = CoretaxFormatValidator.validate_masa_pajak("")
        assert valid is False
        assert "tidak boleh kosong" in msg

    def test_validate_masa_pajak_invalid_format(self):
        valid, msg = CoretaxFormatValidator.validate_masa_pajak("2025-01")
        assert valid is False
        assert "Format masa pajak tidak valid" in msg

    def test_validate_masa_pajak_invalid_month(self):
        valid, msg = CoretaxFormatValidator.validate_masa_pajak("13/2025")
        assert valid is False

    # ---- validate_tahun_pajak ----
    def test_validate_tahun_pajak_valid(self):
        valid, msg = CoretaxFormatValidator.validate_tahun_pajak("2025")
        assert valid is True
        assert msg is None

    def test_validate_tahun_pajak_empty(self):
        valid, msg = CoretaxFormatValidator.validate_tahun_pajak("")
        assert valid is False
        assert "tidak boleh kosong" in msg

    def test_validate_tahun_pajak_invalid_format(self):
        valid, msg = CoretaxFormatValidator.validate_tahun_pajak("25")
        assert valid is False
        assert "Format tahun pajak tidak valid" in msg

    def test_validate_tahun_pajak_out_of_range(self):
        valid, msg = CoretaxFormatValidator.validate_tahun_pajak("1999")
        assert valid is False
        assert "di luar rentang" in msg

        # Future year > current+1 should be invalid
        future_year = str(datetime.now(UTC).year + 2)
        valid, msg = CoretaxFormatValidator.validate_tahun_pajak(future_year)
        assert valid is False
        assert "di luar rentang" in msg

    # ---- validate_nilai_ppn ----
    def test_validate_nilai_ppn_valid_11_percent(self):
        valid, msg = CoretaxFormatValidator.validate_nilai_ppn(Decimal("110"), Decimal("1000"))
        assert valid is True
        assert msg is None

    def test_validate_nilai_ppn_valid_12_percent(self):
        valid, msg = CoretaxFormatValidator.validate_nilai_ppn(Decimal("120"), Decimal("1000"))
        assert valid is True
        assert msg is None

    def test_validate_nilai_ppn_with_float(self):
        valid, msg = CoretaxFormatValidator.validate_nilai_ppn(110.0, 1000.0)
        assert valid is True

    def test_validate_nilai_ppn_invalid(self):
        valid, msg = CoretaxFormatValidator.validate_nilai_ppn(Decimal("200"), Decimal("1000"))
        assert valid is False
        assert "tidak sesuai dengan DPP" in msg

    def test_validate_nilai_ppn_zero_ppn(self):
        valid, msg = CoretaxFormatValidator.validate_nilai_ppn(Decimal("0"), Decimal("1000"))
        assert valid is False
        assert "Nilai PPN dan DPP harus positif" in msg

    def test_validate_nilai_ppn_zero_dpp(self):
        valid, msg = CoretaxFormatValidator.validate_nilai_ppn(Decimal("100"), Decimal("0"))
        assert valid is False

    # ---- validate_kode_efaktur ----
    def test_validate_kode_efaktur_valid(self):
        for kode in ["010", "011", "020", "030", "040", "050", "060", "070", "080", "090"]:
            valid, msg = CoretaxFormatValidator.validate_kode_efaktur(kode)
            assert valid is True
            assert msg is None

    def test_validate_kode_efaktur_invalid(self):
        valid, msg = CoretaxFormatValidator.validate_kode_efaktur("999")
        assert valid is False
        assert "Kode faktur '999' tidak dikenal" in msg

    # ---- validate_bukti_potong_type ----
    def test_validate_bukti_potong_type_valid(self):
        for tipe in ["21", "22", "23", "26", "4(2)", "15"]:
            valid, msg = CoretaxFormatValidator.validate_bukti_potong_type(tipe)
            assert valid is True
            assert msg is None

    def test_validate_bukti_potong_type_invalid(self):
        valid, msg = CoretaxFormatValidator.validate_bukti_potong_type("99")
        assert valid is False
        assert "Jenis bukti potong '99' tidak valid" in msg

    # ---- validate_tarif_pph ----
    def test_validate_tarif_pph_valid_21(self):
        valid, msg = CoretaxFormatValidator.validate_tarif_pph(Decimal("0.05"), "21")
        assert valid is True
        assert msg is None

    def test_validate_tarif_pph_valid_26(self):
        valid, msg = CoretaxFormatValidator.validate_tarif_pph(Decimal("0.20"), "26")
        assert valid is True

    def test_validate_tarif_pph_with_float(self):
        valid, msg = CoretaxFormatValidator.validate_tarif_pph(0.05, "21")
        assert valid is True

    def test_validate_tarif_pph_invalid_21(self):
        valid, msg = CoretaxFormatValidator.validate_tarif_pph(Decimal("0.50"), "21")
        assert valid is False
        assert "tidak wajar" in msg

    def test_validate_tarif_pph_negative(self):
        valid, msg = CoretaxFormatValidator.validate_tarif_pph(Decimal("-0.05"), "21")
        assert valid is False

    # ---- validate_spt_type ----
    def test_validate_spt_type_valid(self):
        for tipe in ["PPN", "PPH_21", "PPH_22", "PPH_23", "PPH_4_2", "PPH_25", "PPH_26", "PPH_BADAN"]:
            valid, msg = CoretaxFormatValidator.validate_spt_type(tipe)
            assert valid is True
            assert msg is None

    def test_validate_spt_type_invalid(self):
        valid, msg = CoretaxFormatValidator.validate_spt_type("INVALID")
        assert valid is False
        assert "Jenis SPT 'INVALID' tidak dikenal" in msg


# ============================================================================
# Tests for CoretaxFormatGuard
# ============================================================================

class TestCoretaxFormatGuard:
    def test_singleton(self):
        CoretaxFormatGuard._instance = None
        g1 = CoretaxFormatGuard()
        g2 = CoretaxFormatGuard()
        assert g1 is g2

    def test_init(self, guard):
        assert guard._validation_history == []
        assert guard._max_history == 10000
        assert guard._version == 1

    # ---- validate_efaktur_data ----
    @pytest.mark.asyncio
    async def test_validate_efaktur_data_all_valid(self, guard):
        is_valid, results = await guard.validate_efaktur_data(
            npwp_penjual="12.345.678.9-012.345",
            npwp_pembeli="12.345.678.9-012.346",
            kode_faktur="010",
            nomor_faktur="010-00-00000001-0000000001",
            dpp=Decimal("1000"),
            ppn=Decimal("110"),
            masa_pajak="01/2025",
            tahun_pajak="2025",
        )
        assert is_valid is True
        assert len(results) == 8
        assert all(r.is_valid for r in results)
        assert len(guard._validation_history) == 8

    @pytest.mark.asyncio
    async def test_validate_efaktur_data_invalid(self, guard):
        is_valid, results = await guard.validate_efaktur_data(
            npwp_penjual="invalid",
            npwp_pembeli="invalid",
            kode_faktur="999",
            nomor_faktur="invalid",
            dpp=Decimal("1000"),
            ppn=Decimal("50"),
            masa_pajak="13/2025",
            tahun_pajak="1999",
        )
        assert is_valid is False
        invalid_results = [r for r in results if not r.is_valid]
        assert len(invalid_results) >= 6  # most fields invalid
        # Check specific invalid fields
        invalid_fields = {r.field_name for r in invalid_results}
        assert "npwp_penjual" in invalid_fields
        assert "kode_faktur" in invalid_fields
        assert "ppn" in invalid_fields

    # ---- validate_ebupot_data ----
    @pytest.mark.asyncio
    async def test_validate_ebupot_data_all_valid(self, guard):
        is_valid, results = await guard.validate_ebupot_data(
            npwp_pemotong="12.345.678.9-012.345",
            npwp_penerima="12.345.678.9-012.346",
            bukti_type="21",
            tarif=Decimal("0.05"),
            dasar_pemotongan=Decimal("1000000"),
            pph_terutang=Decimal("50000"),
            masa_pajak="01/2025",
        )
        assert is_valid is True
        assert len(results) == 6  # 6 fields validated
        assert all(r.is_valid for r in results)

    @pytest.mark.asyncio
    async def test_validate_ebupot_data_pph_mismatch(self, guard):
        is_valid, results = await guard.validate_ebupot_data(
            npwp_pemotong="12.345.678.9-012.345",
            npwp_penerima="12.345.678.9-012.346",
            bukti_type="21",
            tarif=Decimal("0.05"),
            dasar_pemotongan=Decimal("1000000"),
            pph_terutang=Decimal("60000"),  # should be 50000
            masa_pajak="01/2025",
        )
        assert is_valid is False
        pph_result = next(r for r in results if r.field_name == "pph_terutang")
        assert pph_result.is_valid is False
        assert "Perhitungan PPh tidak sesuai" in pph_result.message

    @pytest.mark.asyncio
    async def test_validate_ebupot_data_invalid_tarif(self, guard):
        is_valid, results = await guard.validate_ebupot_data(
            npwp_pemotong="12.345.678.9-012.345",
            npwp_penerima="12.345.678.9-012.346",
            bukti_type="21",
            tarif=Decimal("0.50"),
            dasar_pemotongan=Decimal("1000000"),
            pph_terutang=Decimal("500000"),
            masa_pajak="01/2025",
        )
        assert is_valid is False
        tarif_result = next(r for r in results if r.field_name == "tarif")
        assert tarif_result.is_valid is False
        assert "tidak wajar" in tarif_result.message

    # ---- validate_spt_submission ----
    @pytest.mark.asyncio
    async def test_validate_spt_submission_all_valid(self, guard):
        is_valid, results = await guard.validate_spt_submission(
            spt_type="PPN",
            npwp="12.345.678.9-012.345",
            masa_pajak="01/2025",
            tahun_pajak="2025",
            total_ppn=Decimal("1000000"),
            total_pph=Decimal("500000"),
        )
        assert is_valid is True
        assert len(results) == 6
        assert all(r.is_valid for r in results)

    @pytest.mark.asyncio
    async def test_validate_spt_submission_negative_ppn(self, guard):
        is_valid, results = await guard.validate_spt_submission(
            spt_type="PPN",
            npwp="12.345.678.9-012.345",
            masa_pajak="01/2025",
            tahun_pajak="2025",
            total_ppn=Decimal("-1000"),
            total_pph=Decimal("-500"),
        )
        assert is_valid is False
        ppn_result = next(r for r in results if r.field_name == "total_ppn")
        assert ppn_result.is_valid is False
        assert "tidak boleh negatif" in ppn_result.message

    # ---- enforce methods ----
    @pytest.mark.asyncio
    async def test_enforce_efaktur_success(self, guard):
        is_valid, results = await guard.enforce_efaktur(
            npwp_penjual="12.345.678.9-012.345",
            npwp_pembeli="12.345.678.9-012.346",
            kode_faktur="010",
            nomor_faktur="010-00-00000001-0000000001",
            dpp=Decimal("1000"),
            ppn=Decimal("110"),
            masa_pajak="01/2025",
            tahun_pajak="2025",
            raise_on_violation=False,
        )
        assert is_valid is True
        assert len(results) == 8

    @pytest.mark.asyncio
    async def test_enforce_efaktur_raises_on_critical(self, guard):
        with pytest.raises(CoretaxFormatError) as exc:
            await guard.enforce_efaktur(
                npwp_penjual="invalid",
                npwp_pembeli="12.345.678.9-012.346",
                kode_faktur="010",
                nomor_faktur="010-00-00000001-0000000001",
                dpp=Decimal("1000"),
                ppn=Decimal("110"),
                masa_pajak="01/2025",
                tahun_pajak="2025",
                raise_on_violation=True,
            )
        assert "Coretax format validation failed" in str(exc.value)
        assert exc.value.field == "npwp_penjual"

    @pytest.mark.asyncio
    async def test_enforce_ebupot_raises(self, guard):
        with pytest.raises(CoretaxFormatError):
            await guard.enforce_ebupot(
                npwp_pemotong="invalid",
                npwp_penerima="12.345.678.9-012.346",
                bukti_type="21",
                tarif=Decimal("0.05"),
                dasar_pemotongan=Decimal("1000000"),
                pph_terutang=Decimal("50000"),
                masa_pajak="01/2025",
                raise_on_violation=True,
            )

    @pytest.mark.asyncio
    async def test_enforce_spt_raises(self, guard):
        with pytest.raises(CoretaxFormatError):
            await guard.enforce_spt(
                spt_type="INVALID",
                npwp="12.345.678.9-012.345",
                masa_pajak="01/2025",
                tahun_pajak="2025",
                raise_on_violation=True,
            )

    # ---- get_validation_history ----
    def test_get_validation_history(self, guard):
        # Add some history
        with patch.object(guard, "_validation_history", [MagicMock()] * 5):
            history = guard.get_validation_history(limit=3)
            assert len(history) == 3
            # Filter by document type
            doc_type = CoretaxDocumentType.FAKTUR_PAJAK
            with patch.object(guard, "_validation_history", [
                MagicMock(document_type=doc_type),
                MagicMock(document_type=CoretaxDocumentType.BUKTI_POTONG),
            ]):
                filtered = guard.get_validation_history(document_type=doc_type)
                assert len(filtered) == 1
            # only_invalid
            with patch.object(guard, "_validation_history", [
                MagicMock(is_valid=False),
                MagicMock(is_valid=True),
            ]):
                invalid = guard.get_validation_history(only_invalid=True)
                assert len(invalid) == 1

    # ---- get_statistics ----
    def test_get_statistics_empty(self, guard):
        stats = guard.get_statistics()
        assert stats["total_validations"] == 0
        assert stats["version"] == 1

    def test_get_statistics_with_data(self, guard):
        # Add some validation results
        with patch.object(guard, "_validation_history", [
            CoretaxValidationResult(
                validation_id=uuid4(),
                document_type=CoretaxDocumentType.FAKTUR_PAJAK,
                field_name="a",
                field_value="v",
                is_valid=True,
                severity=CoretaxValidationSeverity.INFO,
                message="OK",
            ),
            CoretaxValidationResult(
                validation_id=uuid4(),
                document_type=CoretaxDocumentType.BUKTI_POTONG,
                field_name="b",
                field_value="v",
                is_valid=False,
                severity=CoretaxValidationSeverity.CRITICAL,
                message="Error",
            ),
        ]):
            stats = guard.get_statistics()
            assert stats["total_validations"] == 2
            assert stats["invalid_count"] == 1
            assert stats["validity_rate"] == 0.5
            assert stats["by_severity"]["CRITICAL"] == 1
            assert stats["by_document_type"]["faktur_pajak"] == 1

    # ---- check ----
    def test_check_valid_efaktur(self, guard):
        context = {
            "document_type": "efaktur",
            "data": {
                "npwp_penjual": "123",
                "npwp_pembeli": "456",
                "kode_faktur": "010",
                "nomor_faktur": "123",
                "dpp": "100",
                "ppn": "11",
                "masa_pajak": "01/2025",
                "tahun_pajak": "2025",
            }
        }
        errors = guard.check(context)
        assert errors == []

    def test_check_missing_document_type(self, guard):
        errors = guard.check({})
        assert "document_type is required" in errors

    def test_check_invalid_document_type(self, guard):
        errors = guard.check({"document_type": "invalid", "data": {}})
        assert "document_type must be one of" in errors[0]

    def test_check_missing_data(self, guard):
        errors = guard.check({"document_type": "efaktur"})
        assert "data is required" in errors

    def test_check_efaktur_missing_fields(self, guard):
        context = {"document_type": "efaktur", "data": {}}
        errors = guard.check(context)
        assert "efaktur data missing field: npwp_penjual" in errors

    def test_check_ebupot_missing_fields(self, guard):
        context = {"document_type": "ebupot", "data": {}}
        errors = guard.check(context)
        assert "ebupot data missing field: npwp_pemotong" in errors

    def test_check_spt_missing_fields(self, guard):
        context = {"document_type": "spt", "data": {}}
        errors = guard.check(context)
        assert "spt data missing field: spt_type" in errors

    # ---- entity methods ----
    def test_validate(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True

        guard._max_history = 0
        result2 = guard.validate()
        assert result2["is_valid"] is False
        assert "max_history must be positive" in result2["errors"]

    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert "validation_history_count" in d
        assert "max_history" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"max_history": 5000, "version": 3}
        guard = CoretaxFormatGuard.from_dict(data)
        assert guard._max_history == 5000
        assert guard._version == 3

    def test_clone(self, guard):
        guard._max_history = 2000
        clone = guard.clone()
        assert clone is not guard
        assert clone._max_history == guard._max_history
        assert clone._version == guard._version + 1

    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert snap["version"] == 1
        assert "timestamp" in snap

    def test_version(self, guard):
        assert guard.version() == 1
        guard.touch("tester")
        assert guard.version() == 2

    def test_audit_trail(self, guard):
        guard._record_audit("TEST", "user", {"foo": "bar"})
        trail = guard.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, guard):
        old = guard._version
        guard.touch("tester")
        assert guard._version == old + 1
        assert guard._audit_trail[-1]["action"] == "TOUCH"

    def test_reset(self, guard):
        guard._validation_history = [MagicMock()]
        guard._version = 5
        guard._audit_trail = [{"action": "test"}]
        guard.reset()
        assert guard._validation_history == []
        assert guard._version == 6
        assert guard._audit_trail == []


# ============================================================================
# Tests for module-level get_coretax_format_guard
# ============================================================================

def test_get_coretax_format_guard():
    # Reset singleton
    import kernel.guards.coretax_format_validator as module
    module._coretax_format_guard_instance = None
    g1 = get_coretax_format_guard()
    g2 = get_coretax_format_guard()
    assert g1 is g2
    assert isinstance(g1, CoretaxFormatGuard)