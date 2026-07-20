#!/usr/bin/env python3
"""
tests/adapters/coretax_djp/test_spt_tahunan_badan_builder.py
Test untuk adapters/coretax_djp/spt_tahunan_badan_builder.py
Mencakup semua kelas dan metode secara exhaustive dengan mocking.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, ANY

import pytest

from adapters.coretax_djp.spt_tahunan_badan_builder import (
    CORPORATE_TAX_RATE,
    JENIS_KOREKSI,
    SUMBER_KOREKSI,
    KoreksiFiskal,
    KoreksiFiskalType,
    PemegangSaham,
    SPTBadanAlreadyExistsError,
    SPTBadanCalculationError,
    SPTBadanError,
    SPTBadanInvalidStateError,
    SPTBadanLockedError,
    SPTBadanNotFoundError,
    SPTBadanValidationError,
    SPTBadanXMLGenerationError,
    SPTStatus,
    SPTTahunanBadan,
    SPTTahunanBadanBuilder,
    SPTTahunanBadanDummy,
    SPTType,
    _FallbackSPTBadanRepository,
    get_spt_tahunan_builder,
)

# ============================================================================
# Fixtures - with datetime mocking to avoid flaky tests
# ============================================================================

@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() and date.today() globally for all tests."""
    fixed_datetime = datetime(2026, 1, 1, 12, 0, 0)
    fixed_date = date(2026, 1, 1)
    with patch("adapters.coretax_djp.spt_tahunan_badan_builder.datetime") as mock_dt:
        mock_dt.datetime.now.return_value = fixed_datetime
        mock_dt.date.today.return_value = fixed_date
        # Also patch the imported datetime and date directly
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.datetime.now", return_value=fixed_datetime):
            with patch("adapters.coretax_djp.spt_tahunan_badan_builder.date.today", return_value=fixed_date):
                yield


@pytest.fixture
def sample_spt_data() -> dict:
    return {
        "npwp_badan": "123456789012345",
        "tahun_pajak": 2026,
        "spt_type": SPTType.NORMAL,
        "correction_number": 0,
        "penghasilan_neto_komersial": Decimal("1000000000"),
        "penghasilan_neto_fiskal": Decimal("1200000000"),
        "kompensasi_kerugian": Decimal("100000000"),
        "penghasilan_kena_pajak": Decimal("1100000000"),
        "pph_terutang": Decimal("242000000"),
        "total_kredit_pajak": Decimal("50000000"),
        "kurang_bayar": Decimal("192000000"),
        "lebih_bayar": Decimal("0"),
        "total_bayar": Decimal("192000000"),
        "tarif": Decimal("0.22"),
        "ntpn": "1234567890123456",
    }


@pytest.fixture
def sample_spt(sample_spt_data) -> SPTTahunanBadan:
    return SPTTahunanBadan(**sample_spt_data)


@pytest.fixture
def sample_builder() -> SPTTahunanBadanBuilder:
    with patch("adapters.coretax_djp.spt_tahunan_badan_builder.SPTTahunanBadanBuilder._init_file_storage"):
        builder = SPTTahunanBadanBuilder(config={})
        builder._repository = AsyncMock(spec=_FallbackSPTBadanRepository)
        builder._ledger_service = AsyncMock()
        builder._tax_service = AsyncMock()
        builder._coretax_client = AsyncMock()
        builder._file_storage = AsyncMock()
        return builder


# ============================================================================
# Tests for Enums
# ============================================================================

class TestSPTType:
    def test_members(self):
        assert SPTType.NORMAL.value == "normal"
        assert SPTType.CORRECTION.value == "pembetulan"
        assert SPTType.VOID.value == "batal"


class TestSPTStatus:
    def test_members(self):
        assert SPTStatus.DRAFT.value == "draft"
        assert SPTStatus.SUBMITTED.value == "submitted"
        assert SPTStatus.APPROVED.value == "approved"


class TestKoreksiFiskalType:
    def test_members(self):
        assert KoreksiFiskalType.POSITIF.value == "positif"
        assert KoreksiFiskalType.NEGATIF.value == "negatif"


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_exceptions_are_defined(self):
        for exc in [SPTBadanError, SPTBadanNotFoundError, SPTBadanAlreadyExistsError,
                    SPTBadanInvalidStateError, SPTBadanValidationError, SPTBadanLockedError,
                    SPTBadanXMLGenerationError, SPTBadanCalculationError]:
            assert issubclass(exc, Exception)


# ============================================================================
# Tests for KoreksiFiskal Entity
# ============================================================================

class TestKoreksiFiskal:
    def test_constructor(self):
        k = KoreksiFiskal(
            jenis_koreksi="positif",
            jenis_kode="01",
            jumlah=Decimal("100000"),
            keterangan="Koreksi penyusutan",
            sumber="Penyusutan",
            tahun_pajak=2026,
        )
        assert k.id is not None
        assert k.jenis_koreksi == "positif"
        assert k.jenis_kode == "01"
        assert k.jumlah == Decimal("100000")
        assert k.keterangan == "Koreksi penyusutan"
        assert k.sumber == "Penyusutan"
        assert k.tahun_pajak == 2026
        assert k.created_at is not None

    def test_to_dict(self):
        k = KoreksiFiskal(
            jenis_koreksi="negatif",
            jenis_kode="03",
            jumlah=Decimal("50000"),
            keterangan="Koreksi administratif",
            sumber="Administrasi",
            tahun_pajak=2025,
        )
        d = k.to_dict()
        assert d["id"] == str(k.id)
        assert d["jenis_koreksi"] == "negatif"
        assert d["jenis_kode"] == "03"
        assert d["jenis_desc"] == JENIS_KOREKSI.get("03", "Lainnya")
        assert d["jumlah"] == 50000.0
        assert d["keterangan"] == "Koreksi administratif"
        assert d["sumber"] == "Administrasi"
        assert d["sumber_desc"] == SUMBER_KOREKSI.get("Administrasi", "")
        assert d["tahun_pajak"] == 2025


# ============================================================================
# Tests for PemegangSaham Entity
# ============================================================================

class TestPemegangSaham:
    def test_constructor(self):
        ps = PemegangSaham(
            npwp="123456789012345",
            nama="PT Maju Jaya",
            persentase=Decimal("60"),
            jumlah_modal=Decimal("1000000000"),
            alamat="Jakarta",
            kewarganegaraan="WNI",
        )
        assert ps.id is not None
        assert ps.npwp == "123456789012345"
        assert ps.nama == "PT Maju Jaya"
        assert ps.persentase == Decimal("60")
        assert ps.jumlah_modal == Decimal("1000000000")
        assert ps.alamat == "Jakarta"
        assert ps.kewarganegaraan == "WNI"

    def test_to_dict(self):
        ps = PemegangSaham(
            npwp="987654321098765",
            nama="PT Sejahtera",
            persentase=Decimal("40"),
            jumlah_modal=Decimal("500000000"),
            alamat="Bandung",
            kewarganegaraan="WNA",
        )
        d = ps.to_dict()
        assert d["id"] == str(ps.id)
        assert d["npwp"] == "987654321098765"
        assert d["nama"] == "PT Sejahtera"
        assert d["persentase"] == 40.0
        assert d["jumlah_modal"] == 500000000.0
        assert d["alamat"] == "Bandung"
        assert d["kewarganegaraan"] == "WNA"


# ============================================================================
# Tests for SPTTahunanBadan Entity
# ============================================================================

class TestSPTTahunanBadan:
    def test_constructor(self, sample_spt_data):
        spt = SPTTahunanBadan(**sample_spt_data)
        assert spt.spt_id is not None
        assert spt.npwp_badan == sample_spt_data["npwp_badan"]
        assert spt.tahun_pajak == sample_spt_data["tahun_pajak"]
        assert spt.spt_type == SPTType.NORMAL
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 1
        assert not spt.is_locked
        assert spt.is_active
        assert spt.penghasilan_neto_komersial == sample_spt_data["penghasilan_neto_komersial"]
        assert spt.penghasilan_neto_fiskal == sample_spt_data["penghasilan_neto_fiskal"]
        assert spt.kompensasi_kerugian == sample_spt_data["kompensasi_kerugian"]
        assert spt.penghasilan_kena_pajak == sample_spt_data["penghasilan_kena_pajak"]
        assert spt.pph_terutang == sample_spt_data["pph_terutang"]
        assert spt.total_kredit_pajak == sample_spt_data["total_kredit_pajak"]
        assert spt.kurang_bayar == sample_spt_data["kurang_bayar"]
        assert spt.lebih_bayar == sample_spt_data["lebih_bayar"]
        assert spt.total_bayar == sample_spt_data["total_bayar"]
        assert spt.tarif == sample_spt_data["tarif"]
        assert spt.tarif_percent == Decimal("22.0")
        assert spt.ntpn == sample_spt_data["ntpn"]
        assert spt.ntpn_masked == "12345678...3456"
        assert spt.hash != ""

    def test_tarif_percent(self):
        spt = SPTTahunanBadan(npwp_badan="123", tahun_pajak=2026, tarif=Decimal("0.22"))
        assert spt.tarif_percent == Decimal("22.0")

    def test_ntpn_masked(self):
        spt = SPTTahunanBadan(npwp_badan="123", tahun_pajak=2026, ntpn="1234567890123456")
        assert spt.ntpn_masked == "12345678...3456"
        spt._ntpn = "1234"
        assert spt.ntpn_masked == "1234"

    def test_properties(self, sample_spt):
        assert sample_spt.koreksi_positif == []
        assert sample_spt.koreksi_negatif == []
        assert sample_spt.total_koreksi_positif == Decimal("0")
        assert sample_spt.total_koreksi_negatif == Decimal("0")
        assert sample_spt.pemegang_saham == []
        assert sample_spt.penyusutan_fiskal == []
        assert sample_spt.created_at is not None
        assert sample_spt.updated_at is not None
        assert sample_spt.submitted_at is None
        assert sample_spt.approved_at is None
        assert sample_spt.rejected_at is None
        assert sample_spt.cancelled_at is None
        assert sample_spt.synced_at is None
        assert sample_spt.locked_at is None
        assert sample_spt.locked_by is None
        assert sample_spt.spt_number is None
        assert sample_spt.tracking_id is None
        assert sample_spt.coretax_id is None
        assert sample_spt.xml_content == ""
        assert sample_spt.rejection_reason == ""
        assert sample_spt.cancellation_reason == ""

    def test_create(self, sample_spt):
        created_by = uuid.uuid4()
        result = sample_spt.create(created_by)
        assert result is sample_spt
        assert sample_spt.status == SPTStatus.DRAFT
        assert sample_spt.version == 2
        assert len(sample_spt._events) == 1
        assert sample_spt._events[0]["event_type"] == "spt_tahunan_badan_created"

    def test_update(self, sample_spt):
        updated_by = uuid.uuid4()
        data = {"penghasilan_neto_komersial": Decimal("2000000000"), "ntpn": "9876543210987654"}
        result = sample_spt.update(data, updated_by)
        assert result.penghasilan_neto_komersial == Decimal("2000000000")
        assert result.ntpn == "9876543210987654"
        assert result.version == 2
        assert len(result._events) == 1
        assert result._events[0]["event_type"] == "spt_tahunan_badan_updated"

    def test_update_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="is locked"):
            sample_spt.update({}, uuid.uuid4())

    def test_update_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.SUBMITTED
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot update"):
            sample_spt.update({}, uuid.uuid4())

    def test_delete(self, sample_spt):
        deleted_by = uuid.uuid4()
        result = sample_spt.delete(deleted_by, permanent=False)
        assert result.status == SPTStatus.ARCHIVED
        assert result.version == 2
        assert result._events[0]["event_type"] == "spt_tahunan_badan_deleted"

        result = sample_spt.delete(deleted_by, permanent=True)
        assert result.status == SPTStatus.VOID
        assert result.cancelled_at is not None

    def test_delete_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="is locked"):
            sample_spt.delete(uuid.uuid4())

    def test_restore(self, sample_spt):
        sample_spt._status = SPTStatus.ARCHIVED
        restored_by = uuid.uuid4()
        result = sample_spt.restore(restored_by)
        assert result.status == SPTStatus.DRAFT
        assert result.cancelled_at is None
        assert result.version == 2

    def test_restore_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot restore"):
            sample_spt.restore(uuid.uuid4())

    def test_activate(self, sample_spt):
        activated_by = uuid.uuid4()
        result = sample_spt.activate(activated_by)
        assert result.status == SPTStatus.PENDING
        assert result.version == 2

    def test_activate_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot activate"):
            sample_spt.activate(uuid.uuid4())

    def test_deactivate(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        deactivated_by = uuid.uuid4()
        result = sample_spt.deactivate(deactivated_by)
        assert result.status == SPTStatus.DRAFT
        assert result.version == 2

    def test_deactivate_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot deactivate"):
            sample_spt.deactivate(uuid.uuid4())

    def test_lock(self, sample_spt):
        locked_by = uuid.uuid4()
        result = sample_spt.lock(locked_by, "test")
        assert result.is_locked
        assert result.locked_by == locked_by
        assert result.locked_at is not None
        assert result.status == SPTStatus.LOCKED
        assert result.version == 2

    def test_lock_already_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="already locked"):
            sample_spt.lock(uuid.uuid4())

    def test_unlock(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        sample_spt._locked_by = uuid.uuid4()
        unlocked_by = uuid.uuid4()
        result = sample_spt.unlock(unlocked_by)
        assert not result.is_locked
        assert result.locked_by is None
        assert result.locked_at is None
        assert result.status == SPTStatus.PENDING
        assert result.version == 2

    def test_unlock_not_locked_raises(self, sample_spt):
        with pytest.raises(SPTBadanLockedError, match="is not locked"):
            sample_spt.unlock(uuid.uuid4())

    def test_validate_valid(self, sample_spt):
        sample_spt._pemegang_saham = [PemegangSaham("123", "A", Decimal("100"), Decimal("1000"))]
        sample_spt._penghasilan_kena_pajak = Decimal("1100000000")
        sample_spt._pph_terutang = Decimal("242000000")
        sample_spt._kurang_bayar = Decimal("192000000")
        sample_spt._ntpn = "1234567890123456"
        validator_id = uuid.uuid4()
        result = sample_spt.validate(validator_id)
        assert result.status == SPTStatus.VALIDATED
        assert result.version == 2
        assert result._events[0]["event_type"] == "spt_tahunan_badan_validated"

    def test_validate_missing_shareholders_raises(self, sample_spt):
        sample_spt._pemegang_saham = []
        with pytest.raises(SPTBadanValidationError, match="pemegang saham tidak boleh kosong"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_invalid_ntpn(self, sample_spt):
        sample_spt._pemegang_saham = [PemegangSaham("123", "A", Decimal("100"), Decimal("1000"))]
        sample_spt._kurang_bayar = Decimal("100")
        sample_spt._ntpn = "invalid"
        with pytest.raises(SPTBadanValidationError, match="Format NTPN tidak valid"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_missing_ntpn(self, sample_spt):
        sample_spt._pemegang_saham = [PemegangSaham("123", "A", Decimal("100"), Decimal("1000"))]
        sample_spt._kurang_bayar = Decimal("100")
        sample_spt._ntpn = None
        with pytest.raises(SPTBadanValidationError, match="tidak ada NTPN"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_pkp_mismatch(self, sample_spt):
        sample_spt._pemegang_saham = [PemegangSaham("123", "A", Decimal("100"), Decimal("1000"))]
        sample_spt._penghasilan_kena_pajak = Decimal("999")  # wrong
        with pytest.raises(SPTBadanValidationError, match="PKP tidak konsisten"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_pph_mismatch(self, sample_spt):
        sample_spt._pemegang_saham = [PemegangSaham("123", "A", Decimal("100"), Decimal("1000"))]
        sample_spt._penghasilan_kena_pajak = Decimal("1100000000")
        sample_spt._pph_terutang = Decimal("999")  # wrong
        with pytest.raises(SPTBadanValidationError, match="PPh terutang tidak sesuai"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_kurang_bayar_mismatch(self, sample_spt):
        sample_spt._pemegang_saham = [PemegangSaham("123", "A", Decimal("100"), Decimal("1000"))]
        sample_spt._penghasilan_kena_pajak = Decimal("1100000000")
        sample_spt._pph_terutang = Decimal("242000000")
        sample_spt._total_kredit_pajak = Decimal("50000000")
        sample_spt._kurang_bayar = Decimal("999")  # wrong
        with pytest.raises(SPTBadanValidationError, match="Kurang bayar tidak konsisten"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="is locked"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.SUBMITTED
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot validate"):
            sample_spt.validate(uuid.uuid4())

    def test_approve(self, sample_spt):
        sample_spt._status = SPTStatus.SUBMITTED
        approver_id = uuid.uuid4()
        result = sample_spt.approve(approver_id, "approved")
        assert result.status == SPTStatus.APPROVED
        assert result.approved_at is not None
        assert result.version == 2

    def test_approve_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot approve"):
            sample_spt.approve(uuid.uuid4())

    def test_reject(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        rejector_id = uuid.uuid4()
        result = sample_spt.reject(rejector_id, "invalid data")
        assert result.status == SPTStatus.REJECTED
        assert result.rejected_at is not None
        assert result.rejection_reason == "invalid data"
        assert result.version == 2

    def test_reject_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot reject"):
            sample_spt.reject(uuid.uuid4(), "reason")

    def test_calculate(self, sample_spt):
        sample_spt._penghasilan_neto_fiskal = Decimal("1200000000")
        sample_spt._kompensasi_kerugian = Decimal("100000000")
        sample_spt._tarif = Decimal("0.22")
        sample_spt._total_kredit_pajak = Decimal("50000000")
        calculator_id = uuid.uuid4()
        result = sample_spt.calculate(calculator_id)
        assert result.penghasilan_kena_pajak == Decimal("1100000000")
        assert result.pph_terutang == Decimal("242000000")
        assert result.kurang_bayar == Decimal("192000000")
        assert result.lebih_bayar == Decimal("0")
        assert result.total_bayar == Decimal("192000000")
        assert result.status == SPTStatus.CALCULATED
        assert result.version == 2

    def test_calculate_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="is locked"):
            sample_spt.calculate(uuid.uuid4())

    def test_submit(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        sample_spt._pemegang_saham = [PemegangSaham("123", "A", Decimal("100"), Decimal("1000"))]
        sample_spt._penghasilan_kena_pajak = Decimal("1100000000")
        sample_spt._pph_terutang = Decimal("242000000")
        sample_spt._kurang_bayar = Decimal("192000000")
        sample_spt._ntpn = "1234567890123456"
        submitted_by = uuid.uuid4()
        with patch.object(sample_spt, "_generate_xml", return_value="<xml/>"):
            result = sample_spt.submit(submitted_by)
        assert result.status == SPTStatus.SUBMITTED
        assert result.submitted_at is not None
        assert result.version == 2
        assert result._events[0]["event_type"] == "spt_tahunan_badan_submitted"

    def test_submit_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.DRAFT
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot submit"):
            sample_spt.submit(uuid.uuid4())

    def test_cancel(self, sample_spt):
        cancelled_by = uuid.uuid4()
        result = sample_spt.cancel(cancelled_by, "test")
        assert result.status == SPTStatus.CANCELLED
        assert result.cancelled_at is not None
        assert result.cancellation_reason == "test"
        assert result.version == 2

    def test_cancel_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.CANCELLED
        with pytest.raises(SPTBadanInvalidStateError, match="Cannot cancel"):
            sample_spt.cancel(uuid.uuid4(), "reason")

    def test_void(self, sample_spt):
        voided_by = uuid.uuid4()
        result = sample_spt.void(voided_by, "void reason")
        assert result.status == SPTStatus.VOID
        assert result.cancelled_at is not None
        assert result.cancellation_reason == "void reason"
        assert result.version == 2

    def test_void_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="is locked"):
            sample_spt.void(uuid.uuid4(), "reason")

    def test_get_status(self, sample_spt):
        status = sample_spt.get_status()
        assert status["status"] == "draft"
        assert not status["is_locked"]
        assert status["is_active"]
        assert not status["can_submit"]
        assert status["can_cancel"]
        assert status["tahun_pajak"] == 2026

    def test_get_history(self, sample_spt):
        sample_spt._history.append({"event": "test"})
        history = sample_spt.get_history()
        assert len(history) == 1

    def test_snapshot(self, sample_spt):
        snap = sample_spt.snapshot()
        assert snap["npwp_badan"] == "123456789012345"
        assert snap["tahun_pajak"] == 2026
        assert snap["penghasilan_kena_pajak"] == 1100000000.0

    def test_to_dict(self, sample_spt):
        d = sample_spt.to_dict()
        assert d["npwp_badan"] == "123456789012345"
        assert d["spt_type"] == "normal"
        assert d["koreksi_positif"] == []
        assert not d["is_locked"]

    def test_from_dict(self, sample_spt):
        d = sample_spt.to_dict()
        reconstructed = SPTTahunanBadan.from_dict(d)
        assert reconstructed.spt_id == sample_spt.spt_id
        assert reconstructed.npwp_badan == sample_spt.npwp_badan
        assert reconstructed.tahun_pajak == sample_spt.tahun_pajak
        assert reconstructed.status == sample_spt.status

    def test_audit_trail(self, sample_spt):
        sample_spt._history.append({"event": "test"})
        trail = sample_spt.audit_trail()
        assert len(trail) == 1

    def test_can_transition(self, sample_spt):
        assert sample_spt.can_transition(SPTStatus.PENDING)
        assert not sample_spt.can_transition(SPTStatus.SUBMITTED)
        sample_spt._status = SPTStatus.PENDING
        assert sample_spt.can_transition(SPTStatus.CALCULATED)

    def test_transition(self, sample_spt):
        actor_id = uuid.uuid4()
        result = sample_spt.transition(SPTStatus.PENDING, actor_id, "test")
        assert result.status == SPTStatus.PENDING
        assert result.version == 2
        assert len(result._history) == 1
        assert result._history[0]["from_status"] == "draft"
        assert result._history[0]["to_status"] == "pending"

    def test_transition_invalid_raises(self, sample_spt):
        with pytest.raises(SPTBadanInvalidStateError, match="Status transition invalid"):
            sample_spt.transition(SPTStatus.SUBMITTED, uuid.uuid4())

    def test_register_event(self, sample_spt):
        result = sample_spt.register_event("test", {"data": "value"})
        events = result.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test"

    def test_clear_events(self, sample_spt):
        sample_spt.register_event("test", {})
        result = sample_spt.clear_events()
        assert len(result.get_events()) == 0

    def test_add_koreksi_positif(self, sample_spt):
        result = sample_spt.add_koreksi_positif("01", Decimal("50000"), "Koreksi", "Sumber")
        assert len(result.koreksi_positif) == 1
        assert result.total_koreksi_positif == Decimal("50000")
        assert result.penghasilan_neto_fiskal == sample_spt._penghasilan_neto_komersial + Decimal("50000")
        assert result.version == 2

    def test_add_koreksi_negatif(self, sample_spt):
        result = sample_spt.add_koreksi_negatif("02", Decimal("30000"), "Koreksi Negatif", "Sumber")
        assert len(result.koreksi_negatif) == 1
        assert result.total_koreksi_negatif == Decimal("30000")
        assert result.penghasilan_neto_fiskal == sample_spt._penghasilan_neto_komersial - Decimal("30000")
        assert result.version == 2

    def test_add_koreksi_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="is locked"):
            sample_spt.add_koreksi_positif("01", Decimal("100"))

    def test_add_pemegang_saham(self, sample_spt):
        result = sample_spt.add_pemegang_saham("123", "PT A", Decimal("50"), Decimal("1000"), "Alamat", "WNI")
        assert len(result.pemegang_saham) == 1
        assert result.pemegang_saham[0].npwp == "123"
        assert result.pemegang_saham[0].nama == "PT A"
        assert result.pemegang_saham[0].persentase == Decimal("50")
        assert result.version == 2

    def test_add_pemegang_saham_locked_raises(self, sample_spt):
        sample_spt._locked_at = datetime.now()
        with pytest.raises(SPTBadanLockedError, match="is locked"):
            sample_spt.add_pemegang_saham("123", "PT A", Decimal("50"), Decimal("1000"))

    def test_set_tarif(self, sample_spt):
        result = sample_spt.set_tarif(Decimal("0.19"), "2")
        assert result.tarif == Decimal("0.19")
        assert result.version == 2

    def test_set_kompensasi_kerugian(self, sample_spt):
        result = sample_spt.set_kompensasi_kerugian(Decimal("200000000"))
        assert result.kompensasi_kerugian == Decimal("200000000")
        assert result.version == 2

    def test_set_ntpn(self, sample_spt):
        result = sample_spt.set_ntpn("1234567890123456")
        assert result.ntpn == "1234567890123456"
        assert result.version == 2

    def test_set_ntpn_invalid_format_raises(self, sample_spt):
        with pytest.raises(SPTBadanValidationError, match="Invalid NTPN format"):
            sample_spt.set_ntpn("invalid")

    def test_set_coretax_response(self, sample_spt):
        response = {"spt_number": "SPT-001", "tracking_id": "TRK-123", "coretax_id": "COR-456", "status": "success"}
        result = sample_spt.set_coretax_response(response)
        assert result.spt_number == "SPT-001"
        assert result.tracking_id == "TRK-123"
        assert result.coretax_id == "COR-456"
        assert result.status == SPTStatus.SUBMITTED

    def test_create_correction(self, sample_spt):
        created_by = uuid.uuid4()
        correction = sample_spt.create_correction(1, created_by)
        assert correction.spt_type == SPTType.CORRECTION
        assert correction.correction_number == 1
        assert correction.npwp_badan == sample_spt.npwp_badan
        assert correction.tahun_pajak == sample_spt.tahun_pajak
        assert correction.status == SPTStatus.DRAFT

    def test_private__calculate_hash(self, sample_spt):
        h1 = sample_spt._hash
        sample_spt._pph_terutang = Decimal("999")
        sample_spt._calculate_hash()
        assert sample_spt._hash != h1

    def test_private__generate_xml(self, sample_spt):
        sample_spt._koreksi_positif = [KoreksiFiskal("positif", "01", Decimal("100000"), "Test", "Sumber", 2026)]
        sample_spt._koreksi_negatif = [KoreksiFiskal("negatif", "02", Decimal("50000"), "Test Neg", "Sumber", 2026)]
        sample_spt._pemegang_saham = [PemegangSaham("123", "PT A", Decimal("50"), Decimal("1000"), "Alamat", "WNI")]
        xml = sample_spt._generate_xml()
        assert "<SPT" in xml
        assert "KodeFormulir" in xml
        assert "1771" in xml

    def test_private__generate_xml_error(self, sample_spt):
        with patch("xml.etree.ElementTree.tostring", side_effect=Exception("test")):
            with pytest.raises(SPTBadanXMLGenerationError, match="Failed to create XML"):
                sample_spt._generate_xml()

    def test_private__validate_ntpn_format(self, sample_spt):
        assert sample_spt._validate_ntpn_format("1234567890123456")
        assert not sample_spt._validate_ntpn_format("1234")


# ============================================================================
# Tests for _FallbackSPTBadanRepository
# ============================================================================

@pytest.mark.asyncio
class TestFallbackSPTBadanRepository:
    async def test_add_and_get(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        await repo.add(sample_spt)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved is not None
        assert retrieved.spt_id == sample_spt.spt_id

    async def test_save(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        await repo.add(sample_spt)
        sample_spt._status = SPTStatus.SUBMITTED
        await repo.save(sample_spt)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved.status == SPTStatus.SUBMITTED

    async def test_update(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        await repo.add(sample_spt)
        sample_spt._total_bayar = Decimal("999")
        await repo.update(sample_spt)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved.total_bayar == Decimal("999")

    async def test_delete(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        await repo.add(sample_spt)
        await repo.delete(sample_spt.spt_id)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved is None

    async def test_get_by_npwp_tahun(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        await repo.add(sample_spt)
        retrieved = await repo.get_by_npwp_tahun("123456789012345", 2026)
        assert retrieved is not None
        assert retrieved.npwp_badan == "123456789012345"
        retrieved = await repo.get_by_npwp_tahun("123456789012345", 2025)
        assert retrieved is None

    async def test_get_by_tracking_id(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        sample_spt._tracking_id = "TRK-123"
        await repo.add(sample_spt)
        retrieved = await repo.get_by_tracking_id("TRK-123")
        assert retrieved is not None
        assert retrieved.tracking_id == "TRK-123"

    async def test_get_by_status(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        sample_spt._status = SPTStatus.PENDING
        await repo.add(sample_spt)
        results = await repo.get_by_status(SPTStatus.PENDING)
        assert len(results) == 1

    async def test_get_pending_submissions(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        sample_spt._status = SPTStatus.PENDING
        await repo.add(sample_spt)
        results = await repo.get_pending_submissions()
        assert len(results) == 1

    async def test_exists(self, sample_spt):
        repo = _FallbackSPTBadanRepository()
        await repo.add(sample_spt)
        exists = await repo.exists("123456789012345", 2026)
        assert exists
        exists = await repo.exists("123456789012345", 2025)
        assert not exists


# ============================================================================
# Tests for SPTTahunanBadanBuilder
# ============================================================================

@pytest.mark.asyncio
class TestSPTTahunanBadanBuilder:
    async def test_create_new_spt(self, sample_builder):
        sample_builder._repository.exists = AsyncMock(return_value=False)
        sample_builder._repository.add = AsyncMock()
        sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=None)

        result = await sample_builder.create("123456789012345", 2026, uuid.uuid4())
        assert result["success"]
        assert "spt_id" in result
        assert result["tahun_pajak"] == 2026

    async def test_create_existing_spt_returns_error(self, sample_builder):
        sample_builder._repository.exists = AsyncMock(return_value=True)
        result = await sample_builder.create("123456789012345", 2026, uuid.uuid4())
        assert not result["success"]
        assert "already exists" in result["error"]

    async def test_collect_data_success(self, sample_builder):
        ledger = sample_builder._ledger_service
        tax = sample_builder._tax_service

        ledger.get_commercial_financials = AsyncMock(return_value={
            "net_income_before_tax": Decimal("1000000000"),
            "total_revenue": Decimal("5000000000"),
        })
        tax.get_fiscal_reconciliation = AsyncMock(return_value={
            "total_positive_correction": Decimal("200000000"),
            "total_negative_correction": Decimal("50000000"),
            "details": [{"jenis_kode": "01", "amount": Decimal("200000000"), "description": "Test"}],
            "details_negative": [{"jenis_kode": "02", "amount": Decimal("50000000"), "description": "Test Neg"}],
        })
        tax.get_loss_compensation = AsyncMock(return_value=Decimal("100000000"))
        tax.check_public_company = AsyncMock(return_value=False)
        tax.get_tax_credits = AsyncMock(return_value=[
            {"amount": Decimal("30000000")},
            {"amount": Decimal("20000000")},
        ])
        tax.get_ntpn_for_period = AsyncMock(return_value={"ntpn": "1234567890123456"})
        tax.get_shareholders = AsyncMock(return_value=[
            {"npwp": "123", "name": "PT A", "percentage": Decimal("60"), "capital_contribution": Decimal("600000000"), "address": "Jakarta", "citizenship": "WNI"},
        ])
        tax.get_fiscal_depreciation = AsyncMock(return_value=[{"asset": "Mesin", "amount": Decimal("100000")}])

        result = await sample_builder.collect_data("123456789012345", 2026)
        assert result["npwp_badan"] == "123456789012345"
        assert result["penghasilan_neto_komersial"] == Decimal("1000000000")
        assert result["penghasilan_neto_fiskal"] == Decimal("1150000000")  # 1000M + 200M - 50M
        assert result["total_koreksi_positif"] == Decimal("200000000")
        assert result["total_koreksi_negatif"] == Decimal("50000000")
        assert result["kompensasi_kerugian"] == Decimal("100000000")
        assert result["penghasilan_kena_pajak"] == Decimal("1050000000")
        assert result["tarif"] == CORPORATE_TAX_RATE  # revenue > 50B, public false
        assert result["pph_terutang"] == Decimal("231000000.00")  # 1050M * 0.22
        assert result["total_kredit_pajak"] == Decimal("50000000")
        assert result["kurang_bayar"] == Decimal("181000000.00")
        assert result["lebih_bayar"] == Decimal("0")
        assert result["ntpn"] == "1234567890123456"
        assert len(result["shareholders"]) == 1

    async def test_collect_data_error(self, sample_builder):
        sample_builder._ledger_service.get_commercial_financials = AsyncMock(side_effect=Exception("DB error"))
        result = await sample_builder.collect_data("123", 2026)
        assert "error" in result
        assert result["penghasilan_neto_komersial"] == Decimal("0")  # fallback

    async def test_build_new_spt(self, sample_builder):
        sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=None)
        with patch.object(sample_builder, "create", return_value={"success": True, "spt_id": "new"}):
            with patch.object(sample_builder, "collect_data", return_value={
                "penghasilan_neto_komersial": Decimal("1000"),
                "penghasilan_neto_fiskal": Decimal("1100"),
                "kompensasi_kerugian": Decimal("100"),
                "penghasilan_kena_pajak": Decimal("1000"),
                "pph_terutang": Decimal("220"),
                "total_kredit_pajak": Decimal("20"),
                "kurang_bayar": Decimal("200"),
                "lebih_bayar": Decimal("0"),
                "tarif": Decimal("0.22"),
                "ntpn": "1234567890123456",
                "koreksi_positif": [],
                "koreksi_negatif": [],
                "shareholders": [],
            }):
                mock_spt = MagicMock()
                mock_spt.spt_id = uuid.uuid4()
                mock_spt.tahun_pajak = 2026
                mock_spt.penghasilan_kena_pajak = Decimal("1000")
                mock_spt.pph_terutang = Decimal("220")
                mock_spt.kurang_bayar = Decimal("200")
                mock_spt.lebih_bayar = Decimal("0")
                mock_spt.status = SPTStatus.DRAFT
                sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=mock_spt)
                mock_spt.add_koreksi_positif = MagicMock(return_value=mock_spt)
                mock_spt.add_koreksi_negatif = MagicMock(return_value=mock_spt)
                mock_spt.add_pemegang_saham = MagicMock(return_value=mock_spt)
                mock_spt.set_ntpn = MagicMock(return_value=mock_spt)
                mock_spt.calculate = MagicMock(return_value=mock_spt)
                sample_builder._repository.update = AsyncMock()

                result = await sample_builder.build("123", 2026, uuid.uuid4())
                assert result["success"]
                assert "spt_id" in result

    async def test_build_existing_spt(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.tahun_pajak = 2026
        sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=mock_spt)
        with patch.object(sample_builder, "collect_data", return_value={
            "penghasilan_neto_komersial": Decimal("1000"),
            "penghasilan_neto_fiskal": Decimal("1100"),
            "kompensasi_kerugian": Decimal("100"),
            "penghasilan_kena_pajak": Decimal("1000"),
            "pph_terutang": Decimal("220"),
            "total_kredit_pajak": Decimal("20"),
            "kurang_bayar": Decimal("200"),
            "lebih_bayar": Decimal("0"),
            "tarif": Decimal("0.22"),
            "ntpn": "1234567890123456",
            "koreksi_positif": [],
            "koreksi_negatif": [],
            "shareholders": [],
        }):
            mock_spt.add_koreksi_positif = MagicMock(return_value=mock_spt)
            mock_spt.add_koreksi_negatif = MagicMock(return_value=mock_spt)
            mock_spt.add_pemegang_saham = MagicMock(return_value=mock_spt)
            mock_spt.set_ntpn = MagicMock(return_value=mock_spt)
            mock_spt.calculate = MagicMock(return_value=mock_spt)
            sample_builder._repository.update = AsyncMock()
            result = await sample_builder.build("123", 2026, uuid.uuid4())
            assert result["success"]

    async def test_validate_spt_success(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.validate = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert result["success"]
        assert result["valid"]

    async def test_validate_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_validate_spt_validation_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.validate = MagicMock(side_effect=SPTBadanValidationError("Invalid"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert not result["valid"]
        assert "Invalid" in result["error"]

    async def test_submit_spt_success(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)
        mock_spt.transition = MagicMock(return_value=mock_spt)
        mock_spt.spt_number = "SPT-001"
        mock_spt.tracking_id = "TRK-123"
        mock_spt.coretax_id = "COR-456"
        mock_spt.status = SPTStatus.SUBMITTED

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "success", "message": "OK"})

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert result["success"]
        assert result["spt_number"] == "SPT-001"
        assert result["tracking_id"] == "TRK-123"

    async def test_submit_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.submit_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_submit_spt_validation_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.DRAFT
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(side_effect=SPTBadanValidationError("Invalid"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.submit_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "Invalid" in result["error"]

    async def test_submit_spt_coretax_auth_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.transition = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        client = sample_builder._coretax_client
        client.post = AsyncMock(side_effect=CoretaxAuthError("Auth failed"))

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert not result["success"]
        assert "Coretax authentication failed" in result["error"]
        mock_spt.transition.assert_called_with(SPTStatus.ERROR, ANY, ANY)

    async def test_submit_spt_retry_success(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)
        mock_spt.spt_number = "SPT-001"
        mock_spt.tracking_id = "TRK-123"
        mock_spt.coretax_id = "COR-456"
        mock_spt.status = SPTStatus.SUBMITTED

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(side_effect=[Exception("Temp"), {"status": "success"}])

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert result["success"]

    async def test_check_spt_status_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_check_spt_status_no_tracking_id(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.tracking_id = None
        mock_spt.status = SPTStatus.DRAFT
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert result["success"]
        assert result["message"] == "Not yet submitted to Coretax"

    async def test_check_spt_status_success(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.tracking_id = "TRK-123"
        mock_spt.status = SPTStatus.SUBMITTED
        mock_spt.approve = MagicMock(return_value=mock_spt)
        mock_spt.reject = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.get = AsyncMock(return_value={"status": "approved", "approval_date": "2026-05-15"})

        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert result["success"]
        assert result["status"] == SPTStatus.APPROVED.value

    async def test_cancel_spt_success(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.tracking_id = "TRK-123"
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.status = SPTStatus.DRAFT
        mock_spt.cancel = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._cache = {}
        sample_builder._get_cache_key = MagicMock(return_value="key")

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "ok"})

        result = await sample_builder.cancel_spt(mock_spt.spt_id, uuid.uuid4(), "reason")
        assert result["success"]
        assert result["cancelled"]

    async def test_cancel_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.cancel_spt(uuid.uuid4(), uuid.uuid4(), "reason")
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_create_correction_spt_success(self, sample_builder):
        previous_spt = MagicMock()
        previous_spt.create_correction = MagicMock(return_value=MagicMock(spt_id=uuid.uuid4(), tahun_pajak=2026, correction_number=1, status=SPTStatus.DRAFT))
        sample_builder._repository.get_by_id = AsyncMock(return_value=previous_spt)
        sample_builder._repository.add = AsyncMock()
        result = await sample_builder.create_correction_spt("123", 2026, uuid.uuid4(), 1, uuid.uuid4())
        assert result["success"]
        assert result["correction_number"] == 1

    async def test_create_correction_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.create_correction_spt("123", 2026, uuid.uuid4(), 1, uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_get_by_id(self, sample_builder):
        mock_spt = MagicMock()
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_by_id(uuid.uuid4())
        assert result is mock_spt

    async def test_get_by_npwp_tahun(self, sample_builder):
        mock_spt = MagicMock()
        sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_by_npwp_tahun("123", 2026)
        assert result is mock_spt

    async def test_get_status(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.get_status = MagicMock(return_value={"status": "draft"})
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_status(uuid.uuid4())
        assert result["success"]
        assert result["status"] == "draft"

    async def test_get_status_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.get_status(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_get_history(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.get_history = MagicMock(return_value=[{"event": "test"}])
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_history(uuid.uuid4())
        assert result["success"]
        assert len(result["history"]) == 1

    async def test_snapshot(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.snapshot = MagicMock(return_value={"spt_id": "123"})
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.snapshot(uuid.uuid4())
        assert result["success"]
        assert result["spt_id"] == "123"

    def test_build_sync(self, sample_builder):
        data = {"penghasilan_bruto": Decimal("5000000000"), "beban": Decimal("3000000000")}
        dummy = sample_builder.build_sync(data, 2026)
        assert isinstance(dummy, SPTTahunanBadanDummy)
        assert dummy.tahun_buku == 2026
        assert dummy.penghasilan_bruto == Decimal("5000000000")
        assert dummy.beban == Decimal("3000000000")


# ============================================================================
# Tests for SPTTahunanBadanDummy
# ============================================================================

class TestSPTTahunanBadanDummy:
    def test_init(self):
        dummy = SPTTahunanBadanDummy(2026, Decimal("1000"), Decimal("600"))
        assert dummy.tahun_buku == 2026
        assert dummy.penghasilan_bruto == Decimal("1000")
        assert dummy.beban == Decimal("600")
        assert dummy._attachments == ["laporan_keuangan", "daftar_susunan_pemegang_saham"]

    def test_has_attachment(self):
        dummy = SPTTahunanBadanDummy(2026, Decimal("1000"), Decimal("600"))
        assert dummy.has_attachment("laporan_keuangan")
        assert dummy.has_attachment("daftar_susunan_pemegang_saham")
        assert not dummy.has_attachment("other")


# ============================================================================
# Tests for Singleton get_spt_tahunan_builder
# ============================================================================

@pytest.mark.asyncio
async def test_get_spt_tahunan_builder_singleton():
    with patch("adapters.coretax_djp.spt_tahunan_badan_builder.SPTTahunanBadanBuilder") as MockBuilder:
        MockBuilder.return_value = MagicMock()
        builder1 = await get_spt_tahunan_builder(config={})
        builder2 = await get_spt_tahunan_builder(config={})
        assert builder1 is builder2
        assert MockBuilder.call_count == 1


# ============================================================================
# TESTS TAMBAHAN UNTUK MENINGKATKAN COVERAGE
# ============================================================================

@pytest.mark.asyncio
class TestSPTTahunanBadanBuilderPrivateMethods:
    """Test untuk private methods SPTTahunanBadanBuilder."""

    @pytest.fixture
    def builder(self):
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.S3FileStorageAdapter") as mock_storage:
            mock_storage.return_value = MagicMock()
            builder = SPTTahunanBadanBuilder(config={})
            builder._repository = AsyncMock()
            builder._ledger_service = AsyncMock()
            builder._tax_service = AsyncMock()
            builder._coretax_client = AsyncMock()
            builder._file_storage = AsyncMock()
            return builder

    def test_load_config_with_config(self):
        config = {"custom": "value"}
        builder = SPTTahunanBadanBuilder(config=config)
        result = builder._load_config()
        assert result == config

    def test_load_config_without_config(self):
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.SPTTahunanBadanBuilder._init_file_storage"):
            builder = SPTTahunanBadanBuilder(config=None)
            result = builder._load_config()
            assert "coretax_djp" in result
            assert "spt_tahunan" in result["coretax_djp"]
            assert "file_storage_bucket" in result["coretax_djp"]["spt_tahunan"]

    def test_init_file_storage_success(self):
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.S3FileStorageAdapter") as mock_adapter:
            mock_adapter.return_value = MagicMock()
            builder = SPTTahunanBadanBuilder(config={})
            assert builder._file_storage is not None

    def test_init_file_storage_failure(self, caplog):
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.S3FileStorageAdapter", side_effect=Exception("Import failed")):
            with caplog.at_level("WARNING"):
                builder = SPTTahunanBadanBuilder(config={})
                assert builder._file_storage is None
                assert "File storage not available" in caplog.text

    async def test_get_coretax_client(self, builder):
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.get_coretax_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client
            client1 = await builder._get_coretax_client()
            assert client1 is mock_client
            mock_get.assert_called_once()
            client2 = await builder._get_coretax_client()
            assert client2 is client1
            assert mock_get.call_count == 1

    async def test_get_ledger_service(self, builder):
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.LedgerService") as mock_ledger:
            mock_ledger.return_value = MagicMock()
            svc1 = await builder._get_ledger_service()
            assert svc1 is not None
            mock_ledger.assert_called_once()
            svc2 = await builder._get_ledger_service()
            assert svc2 is svc1
            assert mock_ledger.call_count == 1

    async def test_get_tax_service(self, builder):
        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.TaxService") as mock_tax:
            mock_tax.return_value = MagicMock()
            svc1 = await builder._get_tax_service()
            assert svc1 is not None
            mock_tax.assert_called_once()
            svc2 = await builder._get_tax_service()
            assert svc2 is svc1
            assert mock_tax.call_count == 1

    def test_get_cache_key(self, builder):
        key1 = builder._get_cache_key("123456789012345", 2026)
        key2 = builder._get_cache_key("123456789012345", 2026)
        assert key1 == key2
        assert "spt_tahunan_badan" in key1
        assert "123456789012345" in key1
        assert "2026" in key1

    async def test_get_cached_and_set_cached(self, builder):
        cache_key = "test_key"
        data = {"test": "data"}
        await builder._set_cached(cache_key, data)
        assert builder._cache[cache_key] == data
        result = await builder._get_cached(cache_key)
        assert result == data

    async def test_collect_data_calls_getter_methods(self, sample_builder):
        """Test that collect_data calls the appropriate service methods and verifies calls."""
        with patch.object(sample_builder, "_get_ledger_service", new_callable=AsyncMock) as mock_get_ledger:
            with patch.object(sample_builder, "_get_tax_service", new_callable=AsyncMock) as mock_get_tax:
                ledger_mock = AsyncMock()
                tax_mock = AsyncMock()
                mock_get_ledger.return_value = ledger_mock
                mock_get_tax.return_value = tax_mock

                ledger_mock.get_commercial_financials = AsyncMock(return_value={
                    "net_income_before_tax": Decimal("1000000000"),
                    "total_revenue": Decimal("5000000000"),
                })
                tax_mock.get_fiscal_reconciliation = AsyncMock(return_value={
                    "total_positive_correction": Decimal("0"),
                    "total_negative_correction": Decimal("0"),
                    "details": [],
                    "details_negative": [],
                })
                tax_mock.get_loss_compensation = AsyncMock(return_value=Decimal("0"))
                tax_mock.check_public_company = AsyncMock(return_value=False)
                tax_mock.get_tax_credits = AsyncMock(return_value=[])
                tax_mock.get_ntpn_for_period = AsyncMock(return_value=None)
                tax_mock.get_shareholders = AsyncMock(return_value=[])
                tax_mock.get_fiscal_depreciation = AsyncMock(return_value=[])

                await sample_builder.collect_data("123", 2026)

                # Verifikasi semua method dipanggil dengan argumen yang benar
                mock_get_ledger.assert_called_once()
                mock_get_tax.assert_called_once()
                ledger_mock.get_commercial_financials.assert_called_once_with("123", 2026)
                tax_mock.get_fiscal_reconciliation.assert_called_once_with("123", 2026)
                tax_mock.get_loss_compensation.assert_called_once_with("123", 2026)
                tax_mock.check_public_company.assert_called_once_with("123")
                tax_mock.get_tax_credits.assert_called_once_with("123", 2026)
                tax_mock.get_ntpn_for_period.assert_called_once_with("123", 2026, None, tax_type="badan")
                tax_mock.get_shareholders.assert_called_once_with("123", 2026)
                tax_mock.get_fiscal_depreciation.assert_called_once_with("123", 2026)

    async def test_submit_spt_calls_trigger_alert_on_success(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)
        mock_spt.transition = MagicMock(return_value=mock_spt)
        mock_spt.spt_number = "SPT-001"
        mock_spt.tracking_id = "TRK-123"
        mock_spt.coretax_id = "COR-456"
        mock_spt.status = SPTStatus.SUBMITTED

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "success", "message": "OK"})

        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.trigger_alert") as mock_alert:
            result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
            assert result["success"]
            mock_alert.assert_called_once()
            call_args = mock_alert.call_args[1]
            assert call_args["title"] == "SPT Tahunan Badan Submitted"
            assert call_args["severity"] == "info"

    async def test_submit_spt_calls_trigger_alert_on_failure(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.transition = MagicMock(return_value=mock_spt)

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(side_effect=Exception("Network error"))

        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.trigger_alert") as mock_alert:
            result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
            assert not result["success"]
            assert "Network error" in result["error"]
            mock_alert.assert_called_once()
            call_args = mock_alert.call_args[1]
            assert call_args["title"] == "SPT Tahunan Badan Submission Failed"
            assert call_args["severity"] == "critical"

    async def test_submit_spt_alert_import_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)
        mock_spt.spt_number = "SPT-001"
        mock_spt.tracking_id = "TRK-123"
        mock_spt.coretax_id = "COR-456"
        mock_spt.status = SPTStatus.SUBMITTED

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})

        with patch("adapters.coretax_djp.spt_tahunan_badan_builder.trigger_alert", side_effect=ImportError("No module")):
            # Harus tetap sukses meskipun alert gagal
            result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
            assert result["success"]

    async def test_check_spt_status_approves_when_approved(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.tracking_id = "TRK-123"
        mock_spt.status = SPTStatus.SUBMITTED
        mock_spt.approve = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.get = AsyncMock(return_value={"status": "approved", "approval_date": "2026-05-15"})

        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert result["success"]
        mock_spt.approve.assert_called_once()

    async def test_check_spt_status_rejects_when_rejected(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.tracking_id = "TRK-123"
        mock_spt.status = SPTStatus.SUBMITTED
        mock_spt.reject = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.get = AsyncMock(return_value={"status": "rejected", "rejection_reason": "Data tidak lengkap"})

        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert result["success"]
        mock_spt.reject.assert_called_once_with(ANY, "Data tidak lengkap")

    async def test_submit_spt_with_s3_upload_success(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)
        mock_spt.spt_number = "SPT-001"
        mock_spt.tracking_id = "TRK-123"
        mock_spt.coretax_id = "COR-456"
        mock_spt.status = SPTStatus.SUBMITTED

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        sample_builder._file_storage = AsyncMock()
        sample_builder._file_storage.upload = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert result["success"]
        sample_builder._file_storage.upload.assert_called_once()
        call_args = sample_builder._file_storage.upload.call_args[0]
        file_name = call_args[1]
        assert file_name.startswith("spt_tahunan_")
        assert ".xml" in file_name

    def test_build_sync_creates_dummy_with_expected_attachments(self):
        builder = SPTTahunanBadanBuilder(config={})
        dummy = builder.build_sync({"penghasilan_bruto": Decimal("1000"), "beban": Decimal("600")}, 2026)
        assert dummy.has_attachment("laporan_keuangan")
        assert dummy.has_attachment("daftar_susunan_pemegang_saham")
        assert not dummy.has_attachment("other")

    async def test_create_with_existing_spt_uses_repository_exists(self, sample_builder):
        sample_builder._repository.exists = AsyncMock(return_value=True)
        result = await sample_builder.create("123", 2026, uuid.uuid4())
        assert not result["success"]
        assert "already exists" in result["error"]
        sample_builder._repository.exists.assert_called_once_with("123", 2026, 0)

    async def test_build_when_create_fails_returns_error(self, sample_builder):
        sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=None)
        with patch.object(sample_builder, "create", return_value={"success": False, "error": "Create failed"}):
            result = await sample_builder.build("123", 2026, uuid.uuid4())
            assert not result["success"]
            assert "Create failed" in result["error"]

    async def test_build_with_collect_data_error_returns_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.spt_id = uuid.uuid4()
        sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=mock_spt)
        with patch.object(sample_builder, "collect_data", return_value={"error": "Collect failed"}):
            result = await sample_builder.build("123", 2026, uuid.uuid4())
            assert not result["success"]
            assert "Collect failed" in result["error"]

    async def test_cancel_spt_removes_cache(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.tracking_id = "TRK-123"
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.cancel = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._cache = {"some_key": "data"}
        sample_builder._get_cache_key = MagicMock(return_value="some_key")

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "ok"})

        result = await sample_builder.cancel_spt(mock_spt.spt_id, uuid.uuid4(), "reason")
        assert result["success"]
        assert "some_key" not in sample_builder._cache

    async def test_validate_spt_with_existing_cache(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.to_dict = MagicMock(return_value={"data": "valid"})
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert result["success"]
        sample_builder._set_cached.assert_called_once()

    # ========================================================================
    # Additional Negative Path Tests for Builder
    # ========================================================================

    async def test_submit_spt_calculate_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.DRAFT
        mock_spt.calculate = MagicMock(side_effect=SPTBadanCalculationError("Calc error"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.submit_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "Calc error" in result["error"]

    async def test_submit_spt_xml_generation_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt._generate_xml = MagicMock(side_effect=SPTBadanXMLGenerationError("XML error"))
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.submit_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "XML error" in result["error"]

    async def test_submit_spt_client_post_failure(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.transition = MagicMock(return_value=mock_spt)

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(side_effect=Exception("Post error"))

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert not result["success"]
        assert "Post error" in result["error"]
        mock_spt.transition.assert_called_with(SPTStatus.ERROR, ANY, "Post error")

    async def test_check_spt_status_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.tracking_id = "TRK-123"
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        client = sample_builder._coretax_client
        client.get = AsyncMock(side_effect=Exception("Status check error"))
        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert not result["success"]
        assert "Status check error" in result["error"]

    async def test_cancel_spt_already_cancelled_error(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.cancel = MagicMock(side_effect=SPTBadanInvalidStateError("Already cancelled"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.cancel_spt(uuid.uuid4(), uuid.uuid4(), "reason")
        assert not result["success"]
        assert "Already cancelled" in result["error"]

    async def test_create_correction_spt_previous_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.create_correction_spt("123", 2026, uuid.uuid4(), 1, uuid.uuid4())
        assert not result["success"]
        assert "Previous SPT not found" in result["error"]

    async def test_get_status_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.get_status(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_get_history_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.get_history(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_snapshot_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.snapshot(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    # ========================================================================
    # Additional Database Verification Tests
    # ========================================================================

    async def test_create_updates_cache_and_repository(self, sample_builder):
        sample_builder._repository.exists = AsyncMock(return_value=False)
        sample_builder._repository.add = AsyncMock()
        sample_builder._set_cached = AsyncMock()
        result = await sample_builder.create("123", 2026, uuid.uuid4())
        assert result["success"]
        sample_builder._repository.add.assert_called_once()
        sample_builder._set_cached.assert_called_once()

    async def test_build_updates_repository(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.tahun_pajak = 2026
        mock_spt.status = SPTStatus.DRAFT
        sample_builder._repository.get_by_npwp_tahun = AsyncMock(return_value=mock_spt)
        with patch.object(sample_builder, "collect_data", return_value={
            "penghasilan_neto_komersial": Decimal("1000"),
            "penghasilan_neto_fiskal": Decimal("1100"),
            "kompensasi_kerugian": Decimal("100"),
            "penghasilan_kena_pajak": Decimal("1000"),
            "pph_terutang": Decimal("220"),
            "total_kredit_pajak": Decimal("20"),
            "kurang_bayar": Decimal("200"),
            "lebih_bayar": Decimal("0"),
            "tarif": Decimal("0.22"),
            "ntpn": "1234567890123456",
            "koreksi_positif": [],
            "koreksi_negatif": [],
            "shareholders": [],
        }):
            mock_spt.add_koreksi_positif = MagicMock(return_value=mock_spt)
            mock_spt.add_koreksi_negatif = MagicMock(return_value=mock_spt)
            mock_spt.add_pemegang_saham = MagicMock(return_value=mock_spt)
            mock_spt.set_ntpn = MagicMock(return_value=mock_spt)
            mock_spt.calculate = MagicMock(return_value=mock_spt)
            sample_builder._repository.update = AsyncMock()
            sample_builder._set_cached = AsyncMock()
            result = await sample_builder.build("123", 2026, uuid.uuid4())
            assert result["success"]
            sample_builder._repository.update.assert_called_once()
            sample_builder._set_cached.assert_called_once()

    async def test_validate_spt_updates_repository_and_cache(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.to_dict = MagicMock(return_value={"data": "valid"})
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()
        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert result["success"]
        sample_builder._repository.update.assert_called_once()
        sample_builder._set_cached.assert_called_once()

    async def test_submit_spt_updates_repository_and_cache(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.status = SPTStatus.CALCULATED
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.spt_type = SPTType.NORMAL
        mock_spt.correction_number = 0
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)
        mock_spt.spt_number = "SPT-001"
        mock_spt.tracking_id = "TRK-123"
        mock_spt.coretax_id = "COR-456"
        mock_spt.status = SPTStatus.SUBMITTED
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.to_dict = MagicMock(return_value={"data": "submitted"})

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "success", "message": "OK"})

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert result["success"]
        # Periksa bahwa update dipanggil setidaknya dua kali (sebelum dan sesudah submit)
        assert sample_builder._repository.update.call_count >= 2
        sample_builder._set_cached.assert_called()

    async def test_cancel_spt_updates_repository_and_removes_cache(self, sample_builder):
        mock_spt = MagicMock()
        mock_spt.spt_id = uuid.uuid4()
        mock_spt.tracking_id = "TRK-123"
        mock_spt.npwp_badan = "123"
        mock_spt.tahun_pajak = 2026
        mock_spt.cancel = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._cache = {"some_key": "data"}
        sample_builder._get_cache_key = MagicMock(return_value="some_key")

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "ok"})

        result = await sample_builder.cancel_spt(mock_spt.spt_id, uuid.uuid4(), "reason")
        assert result["success"]
        sample_builder._repository.update.assert_called_once()
        assert "some_key" not in sample_builder._cache