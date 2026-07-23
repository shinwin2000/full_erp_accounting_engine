#!/usr/bin/env python3
"""
tests/adapters/coretax_djp/test_spt_masa_ppn_builder.py
Test untuk adapters/coretax_djp/spt_masa_ppn_builder.py
Mencakup semua kelas dan metode secara exhaustive dengan mocking.

Perbaikan pada revisi ini:
- Semua test async diberi marker @pytest.mark.asyncio secara eksplisit di
  level fungsi (sebelumnya hanya mengandalkan marker di level class, yang
  tidak terdeteksi oleh sebagian tool analisis statis).
- Mock entity SPTMasaPPN dibuat dengan spec=SPTMasaPPN supaya typo/attribute
  yang tidak ada di kelas asli langsung ketahuan (mock quality).
- Interaksi penting (payload ke Coretax, cache key, argumen ke repository)
  diverifikasi dengan assert_called_with/assert_called_once, bukan cuma
  memeriksa return value.
- Ditambahkan test negative-path yang sebelumnya tidak ada: approve/reject
  saat locked, build() saat collect_data gagal, validate_spt/cancel_spt saat
  locked/invalid state, submit_spt saat exception generik (bukan hanya
  CoretaxAuthError), check_spt_status saat exception, serta beberapa kasus
  "not found" pada repository dan builder yang belum diuji.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from adapters.coretax_djp.spt_masa_ppn_builder import (
    CORETAX_SPT_PPN_ENDPOINT,
    FORM_CODE,
    PaymentReference,
    SPTAlreadyExistsError,
    SPTCalculationError,
    SPTError,
    SPTInvalidStateError,
    SPTLockedError,
    SPTMasaPPN,
    SPTMasaPpn,
    SPTMasaPPNBuilder,
    SPTNotFoundError,
    SPTStatus,
    SPTType,
    SPTValidationError,
    SPTXMLGenerationError,
    SubmissionResult,
    _FallbackSPTRepository,
    get_spt_ppn_builder,
)

# ============================================================================
# Fixtures - datetime mocking untuk menghindari flaky tests
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0)
FIXED_TODAY = date(2026, 1, 1)
UUID_ZERO = uuid.UUID(int=0)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() dan date.today() untuk menghindari flaky tests."""
    with patch("adapters.coretax_djp.spt_masa_ppn_builder.datetime") as mock_dt, \
         patch("adapters.coretax_djp.spt_masa_ppn_builder.date") as mock_date:
        mock_dt.now.return_value = FIXED_NOW
        mock_date.today.return_value = FIXED_TODAY
        yield


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_spt_data() -> dict:
    return {
        "npwp": "123456789012345",
        "tahun": 2026,
        "bulan": 5,
        "spt_type": SPTType.NORMAL,
        "correction_number": 0,
        "total_penyerahan_dpp": Decimal("100000000"),
        "total_ppn_keluaran": Decimal("11000000"),
        "total_ppn_masukan": Decimal("5000000"),
        "total_retur_keluaran": Decimal("0"),
        "total_retur_masukan": Decimal("0"),
        "kompensasi": Decimal("0"),
        "ppn_kurang_bayar": Decimal("6000000"),
        "ppn_lebih_bayar": Decimal("0"),
        "total_bayar": Decimal("6000000"),
        "ntpn": "1234567890123456",
        "status_restitusi": None,
    }


@pytest.fixture
def sample_spt(sample_spt_data) -> SPTMasaPPN:
    return SPTMasaPPN(**sample_spt_data)


@pytest.fixture
def sample_builder() -> SPTMasaPPNBuilder:
    with patch("adapters.coretax_djp.spt_masa_ppn_builder.SPTMasaPPNBuilder._init_file_storage"):
        builder = SPTMasaPPNBuilder(config={})
        builder._repository = AsyncMock(spec=_FallbackSPTRepository)
        builder._tax_service = AsyncMock()
        builder._coretax_client = AsyncMock()
        builder._file_storage = AsyncMock()
        return builder


def make_mock_spt(**overrides) -> MagicMock:
    """Buat MagicMock ber-spec SPTMasaPPN supaya attribute yang tidak ada
    di kelas asli langsung memicu AttributeError (mock quality)."""
    mock_spt = MagicMock(spec=SPTMasaPPN)
    for key, value in overrides.items():
        setattr(mock_spt, key, value)
    return mock_spt


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


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_exceptions_are_defined(self):
        for exc in [SPTError, SPTNotFoundError, SPTAlreadyExistsError,
                    SPTInvalidStateError, SPTValidationError, SPTLockedError,
                    SPTXMLGenerationError, SPTCalculationError]:
            assert issubclass(exc, Exception)

    def test_exceptions_are_distinct_subclasses_of_spt_error(self):
        # Negative path: pastikan tiap exception spesifik BUKAN alias satu
        # sama lain, supaya except-block yang menangkap salah satunya tidak
        # diam-diam menangkap yang lain.
        specific = [SPTNotFoundError, SPTAlreadyExistsError, SPTInvalidStateError,
                    SPTValidationError, SPTLockedError, SPTXMLGenerationError,
                    SPTCalculationError]
        assert len(set(specific)) == len(specific)
        for exc in specific:
            assert exc is not SPTError
            assert issubclass(exc, SPTError)


# ============================================================================
# Tests for SPTMasaPPN Entity
# ============================================================================

class TestSPTMasaPPN:
    def test_constructor(self, sample_spt_data):
        spt = SPTMasaPPN(**sample_spt_data)
        assert spt.spt_id is not None
        assert spt.npwp == sample_spt_data["npwp"]
        assert spt.tahun == sample_spt_data["tahun"]
        assert spt.bulan == sample_spt_data["bulan"]
        assert spt.masa_pajak == "2026-05"
        assert spt.spt_type == SPTType.NORMAL
        assert spt.status == SPTStatus.DRAFT
        assert spt.version == 1
        assert spt.hash != ""
        assert not spt.is_locked
        assert spt.is_active
        assert spt.detail_pk == []
        assert spt.detail_pm == []
        assert spt.detail_retur == []
        assert spt.pk_count == 0
        assert spt.pm_count == 0
        assert spt.retur_count == 0
        assert spt.ntpn_masked == "12345678...3456"

    def test_status_kb_lb(self):
        spt = SPTMasaPPN(npwp="123", tahun=2026, bulan=1, ppn_kurang_bayar=Decimal("100"))
        assert spt.status_kb_lb == "KB"
        assert spt.status_kb_lb_desc == "Kurang Bayar"

        spt = SPTMasaPPN(npwp="123", tahun=2026, bulan=1, ppn_lebih_bayar=Decimal("100"))
        assert spt.status_kb_lb == "LB"
        assert spt.status_kb_lb_desc == "Lebih Bayar"

        spt = SPTMasaPPN(npwp="123", tahun=2026, bulan=1)
        assert spt.status_kb_lb == "Nihil"
        assert spt.status_kb_lb_desc == "Nihil"

    def test_properties(self, sample_spt):
        assert sample_spt.pk_count == 0
        assert sample_spt.pm_count == 0
        assert sample_spt.retur_count == 0
        assert sample_spt.created_at == FIXED_NOW
        assert sample_spt.updated_at == FIXED_NOW
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
        assert sample_spt._events[0]["event_type"] == "spt_ppn_created"

    def test_update(self, sample_spt):
        updated_by = uuid.uuid4()
        data = {"total_ppn_keluaran": Decimal("15000000"), "ntpn": "9876543210987654"}
        result = sample_spt.update(data, updated_by)
        assert result.total_ppn_keluaran == Decimal("15000000")
        assert result.ntpn == "9876543210987654"
        assert result.version == 2
        assert len(result._events) == 1
        assert result._events[0]["event_type"] == "spt_ppn_updated"

    def test_update_locked_raises(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.update({}, uuid.uuid4())

    def test_update_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.SUBMITTED
        with pytest.raises(SPTInvalidStateError, match="Cannot update"):
            sample_spt.update({}, uuid.uuid4())

    def test_delete(self, sample_spt):
        deleted_by = uuid.uuid4()
        result = sample_spt.delete(deleted_by, permanent=False)
        assert result.status == SPTStatus.ARCHIVED
        assert result.version == 2
        assert result._events[0]["event_type"] == "spt_ppn_deleted"

        # permanent delete
        result = sample_spt.delete(deleted_by, permanent=True)
        assert result.status == SPTStatus.VOID
        assert result.cancelled_at == FIXED_NOW

    def test_delete_locked_raises(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.delete(uuid.uuid4())

    def test_restore(self, sample_spt):
        sample_spt._status = SPTStatus.ARCHIVED
        restored_by = uuid.uuid4()
        result = sample_spt.restore(restored_by)
        assert result.status == SPTStatus.DRAFT
        assert result.cancelled_at is None
        assert result.version == 2

    def test_restore_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTInvalidStateError, match="Cannot restore"):
            sample_spt.restore(uuid.uuid4())

    def test_activate(self, sample_spt):
        activated_by = uuid.uuid4()
        result = sample_spt.activate(activated_by)
        assert result.status == SPTStatus.PENDING
        assert result.version == 2

    def test_activate_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        with pytest.raises(SPTInvalidStateError, match="Cannot activate"):
            sample_spt.activate(uuid.uuid4())

    def test_deactivate(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        deactivated_by = uuid.uuid4()
        result = sample_spt.deactivate(deactivated_by)
        assert result.status == SPTStatus.DRAFT
        assert result.version == 2

    def test_deactivate_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTInvalidStateError, match="Cannot deactivate"):
            sample_spt.deactivate(uuid.uuid4())

    def test_lock(self, sample_spt):
        locked_by = uuid.uuid4()
        result = sample_spt.lock(locked_by, "test")
        assert result.is_locked
        assert result.locked_by == locked_by
        assert result.locked_at == FIXED_NOW
        assert result.status == SPTStatus.LOCKED
        assert result.version == 2

    def test_lock_already_locked_raises(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="already locked"):
            sample_spt.lock(uuid.uuid4())

    def test_unlock(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        sample_spt._locked_by = uuid.uuid4()
        unlocked_by = uuid.uuid4()
        result = sample_spt.unlock(unlocked_by)
        assert not result.is_locked
        assert result.locked_by is None
        assert result.locked_at is None
        assert result.status == SPTStatus.PENDING
        assert result.version == 2

    def test_unlock_not_locked_raises(self, sample_spt):
        with pytest.raises(SPTLockedError, match="is not locked"):
            sample_spt.unlock(uuid.uuid4())

    def test_validate_valid(self, sample_spt):
        sample_spt._detail_pk = [{"dpp": 100000000, "ppn": 11000000}]
        sample_spt._detail_pm = [{"ppn": 5000000}]
        sample_spt._ppn_kurang_bayar = Decimal("6000000")
        sample_spt._ppn_lebih_bayar = Decimal("0")
        sample_spt._ntpn = "1234567890123456"
        validator_id = uuid.uuid4()
        result = sample_spt.validate(validator_id)
        assert result.status == SPTStatus.VALIDATED
        assert result.version == 2
        assert result._events[0]["event_type"] == "spt_ppn_validated"

    def test_validate_invalid_ntpn(self, sample_spt):
        sample_spt._ppn_kurang_bayar = Decimal("100")
        sample_spt._ntpn = "invalid"
        with pytest.raises(SPTValidationError, match="Format NTPN tidak valid"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_missing_ntpn(self, sample_spt):
        sample_spt._ppn_kurang_bayar = Decimal("100")
        sample_spt._ntpn = None
        with pytest.raises(SPTValidationError, match="tidak ada NTPN"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_invalid_kurang_bayar(self, sample_spt):
        sample_spt._total_ppn_keluaran = Decimal("100")
        sample_spt._total_ppn_masukan = Decimal("0")
        sample_spt._ppn_kurang_bayar = Decimal("200")  # mismatch
        with pytest.raises(SPTValidationError, match="PPN Kurang Bayar tidak sesuai"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_negative_ppn_keluaran_raises(self, sample_spt):
        sample_spt._total_ppn_keluaran = Decimal("-100")
        with pytest.raises(SPTValidationError, match="tidak boleh negatif"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_pk_missing_but_ppn_keluaran_present_raises(self, sample_spt):
        sample_spt._detail_pk = []
        sample_spt._total_ppn_keluaran = Decimal("11000000")
        sample_spt._ppn_kurang_bayar = Decimal("11000000")
        sample_spt._ntpn = "1234567890123456"
        with pytest.raises(SPTValidationError, match="tidak ada faktur keluaran"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_invalid_bulan_raises(self, sample_spt):
        sample_spt._bulan = 13
        sample_spt._ppn_kurang_bayar = Decimal("0")
        sample_spt._ppn_lebih_bayar = Decimal("0")
        with pytest.raises(SPTValidationError, match="Bulan pajak tidak valid"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_locked_raises(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.validate(uuid.uuid4())

    def test_validate_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.SUBMITTED
        with pytest.raises(SPTInvalidStateError, match="Cannot validate"):
            sample_spt.validate(uuid.uuid4())

    def test_approve(self, sample_spt):
        sample_spt._status = SPTStatus.SUBMITTED
        approver_id = uuid.uuid4()
        result = sample_spt.approve(approver_id, "approved")
        assert result.status == SPTStatus.APPROVED
        assert result.approved_at == FIXED_NOW
        assert result.version == 2

    def test_approve_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTInvalidStateError, match="Cannot approve"):
            sample_spt.approve(uuid.uuid4())

    def test_approve_locked_raises(self, sample_spt):
        sample_spt._status = SPTStatus.SUBMITTED
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.approve(uuid.uuid4())

    def test_reject(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        rejector_id = uuid.uuid4()
        result = sample_spt.reject(rejector_id, "invalid data")
        assert result.status == SPTStatus.REJECTED
        assert result.rejected_at == FIXED_NOW
        assert result.rejection_reason == "invalid data"
        assert result.version == 2

    def test_reject_invalid_status_raises(self, sample_spt):
        with pytest.raises(SPTInvalidStateError, match="Cannot reject"):
            sample_spt.reject(uuid.uuid4(), "reason")

    def test_reject_locked_raises(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.reject(uuid.uuid4(), "reason")

    def test_calculate(self, sample_spt):
        sample_spt._total_ppn_keluaran = Decimal("11000000")
        sample_spt._total_ppn_masukan = Decimal("5000000")
        sample_spt._kompensasi = Decimal("0")
        calculator_id = uuid.uuid4()
        result = sample_spt.calculate(calculator_id)
        assert result.ppn_kurang_bayar == Decimal("6000000")
        assert result.ppn_lebih_bayar == Decimal("0")
        assert result.total_bayar == Decimal("6000000")
        assert result.status == SPTStatus.CALCULATED
        assert result.version == 2

    def test_calculate_with_kompensasi(self, sample_spt):
        sample_spt._total_ppn_keluaran = Decimal("11000000")
        sample_spt._total_ppn_masukan = Decimal("5000000")
        sample_spt._kompensasi = Decimal("1000000")
        calculator_id = uuid.uuid4()
        result = sample_spt.calculate(calculator_id)
        assert result.ppn_kurang_bayar == Decimal("5000000")
        assert result.ppn_lebih_bayar == Decimal("0")

    def test_calculate_lebih_bayar(self, sample_spt):
        sample_spt._total_ppn_keluaran = Decimal("11000000")
        sample_spt._total_ppn_masukan = Decimal("15000000")
        calculator_id = uuid.uuid4()
        result = sample_spt.calculate(calculator_id)
        assert result.ppn_kurang_bayar == Decimal("0")
        assert result.ppn_lebih_bayar == Decimal("4000000")

    def test_calculate_locked_raises(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.calculate(uuid.uuid4())

    def test_submit(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        sample_spt._detail_pk = [{"dpp": 100000000, "ppn": 11000000}]
        sample_spt._detail_pm = [{"ppn": 5000000}]
        sample_spt._ppn_kurang_bayar = Decimal("6000000")
        sample_spt._ppn_lebih_bayar = Decimal("0")
        sample_spt._ntpn = "1234567890123456"
        submitted_by = uuid.uuid4()
        with patch.object(sample_spt, "_generate_xml", return_value="<xml/>") as mock_generate_xml:
            result = sample_spt.submit(submitted_by)
        mock_generate_xml.assert_called_once_with()
        assert result.status == SPTStatus.SUBMITTED
        assert result.submitted_at == FIXED_NOW
        assert result.version == 2
        assert result._events[0]["event_type"] == "spt_ppn_submitted"

    def test_submit_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.DRAFT
        with pytest.raises(SPTInvalidStateError, match="Cannot submit"):
            sample_spt.submit(uuid.uuid4())

    def test_submit_locked_raises(self, sample_spt):
        sample_spt._status = SPTStatus.PENDING
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.submit(uuid.uuid4())

    def test_submit_propagates_validation_error(self, sample_spt):
        # Negative path: submit() memanggil validate() secara internal, jika
        # data tidak valid maka SPTValidationError harus tetap menyebar
        # keluar dari submit(), bukan tertelan diam-diam.
        sample_spt._status = SPTStatus.PENDING
        sample_spt._ppn_kurang_bayar = Decimal("100")
        sample_spt._ntpn = None
        with pytest.raises(SPTValidationError, match="tidak ada NTPN"):
            sample_spt.submit(uuid.uuid4())
        # status tidak boleh berubah jadi SUBMITTED karena validasi gagal
        assert sample_spt.status == SPTStatus.PENDING

    def test_cancel(self, sample_spt):
        cancelled_by = uuid.uuid4()
        result = sample_spt.cancel(cancelled_by, "test")
        assert result.status == SPTStatus.CANCELLED
        assert result.cancelled_at == FIXED_NOW
        assert result.cancellation_reason == "test"
        assert result.version == 2

    def test_cancel_invalid_status_raises(self, sample_spt):
        sample_spt._status = SPTStatus.CANCELLED
        with pytest.raises(SPTInvalidStateError, match="Cannot cancel"):
            sample_spt.cancel(uuid.uuid4(), "reason")

    def test_cancel_locked_raises(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.cancel(uuid.uuid4(), "reason")

    def test_void(self, sample_spt):
        voided_by = uuid.uuid4()
        result = sample_spt.void(voided_by, "void reason")
        assert result.status == SPTStatus.VOID
        assert result.cancelled_at == FIXED_NOW
        assert result.cancellation_reason == "void reason"
        assert result.version == 2

    def test_void_locked_raises(self, sample_spt):
        sample_spt._locked_at = FIXED_NOW
        with pytest.raises(SPTLockedError, match="is locked"):
            sample_spt.void(uuid.uuid4(), "reason")

    def test_get_status(self, sample_spt):
        status = sample_spt.get_status()
        assert status["status"] == "draft"
        assert not status["is_locked"]
        assert status["is_active"]
        assert not status["can_submit"]
        assert status["can_cancel"]
        assert status["masa_pajak"] == "2026-05"

    def test_get_history(self, sample_spt):
        sample_spt._history.append({"event": "test"})
        history = sample_spt.get_history()
        assert len(history) == 1

    def test_get_history_empty_by_default(self, sample_spt):
        assert sample_spt.get_history() == []

    def test_snapshot(self, sample_spt):
        snap = sample_spt.snapshot()
        assert snap["npwp"] == "123456789012345"
        assert snap["tahun"] == 2026
        assert snap["bulan"] == 5
        assert snap["masa_pajak"] == "2026-05"

    def test_to_dict(self, sample_spt):
        d = sample_spt.to_dict()
        assert d["npwp"] == "123456789012345"
        assert d["spt_type"] == "normal"
        assert d["detail_pk"] == []
        assert not d["is_locked"]

    def test_from_dict(self, sample_spt):
        d = sample_spt.to_dict()
        reconstructed = SPTMasaPPN.from_dict(d)
        assert reconstructed.spt_id == sample_spt.spt_id
        assert reconstructed.npwp == sample_spt.npwp
        assert reconstructed.tahun == sample_spt.tahun
        assert reconstructed.bulan == sample_spt.bulan
        assert reconstructed.status == sample_spt.status

    def test_from_dict_missing_optional_fields_uses_defaults(self):
        # Negative/edge path: hanya field wajib yang diisi, sisanya harus
        # jatuh ke default tanpa melempar KeyError.
        minimal = {"npwp": "999", "tahun": 2026, "bulan": 1}
        spt = SPTMasaPPN.from_dict(minimal)
        assert spt.npwp == "999"
        assert spt.spt_type == SPTType.NORMAL
        assert spt.status == SPTStatus.DRAFT
        assert spt.total_ppn_keluaran == Decimal("0")
        assert spt.ntpn is None

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
        with pytest.raises(SPTInvalidStateError, match="Cannot transition"):
            sample_spt.transition(SPTStatus.SUBMITTED, uuid.uuid4())

    def test_transition_invalid_does_not_mutate_state(self, sample_spt):
        # Negative path: transisi yang gagal tidak boleh meninggalkan efek
        # samping (history/version tetap sama).
        version_before = sample_spt.version
        history_len_before = len(sample_spt._history)
        with pytest.raises(SPTInvalidStateError):
            sample_spt.transition(SPTStatus.SUBMITTED, uuid.uuid4())
        assert sample_spt.status == SPTStatus.DRAFT
        assert sample_spt.version == version_before
        assert len(sample_spt._history) == history_len_before

    def test_register_event(self, sample_spt):
        result = sample_spt.register_event("test", {"data": "value"})
        events = result.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test"

    def test_clear_events(self, sample_spt):
        sample_spt.register_event("test", {})
        result = sample_spt.clear_events()
        assert len(result.get_events()) == 0

    def test_collect_pk_data(self, sample_spt):
        faktur_list = [
            {"faktur_id": "1", "faktur_number": "FK-001", "dpp": Decimal("100000"), "ppn": Decimal("11000"), "npwp_pembeli": "123", "nama_pembeli": "PT A", "tanggal_faktur": date(2026, 5, 1)},
            {"faktur_id": "2", "faktur_number": "FK-002", "dpp": Decimal("200000"), "ppn": Decimal("22000"), "npwp_pembeli": "456", "nama_pembeli": "PT B", "retur": Decimal("5000")},
        ]
        result = sample_spt.collect_pk_data(faktur_list)
        assert result.pk_count == 2
        assert result.total_penyerahan_dpp == Decimal("300000")
        assert result.total_ppn_keluaran == Decimal("33000")
        assert result.total_retur_keluaran == Decimal("5000")
        assert len(result.detail_pk) == 2

    def test_collect_pk_data_empty_list_resets_totals(self, sample_spt):
        # Negative/edge path: memanggil ulang dengan list kosong harus
        # mereset total, bukan mempertahankan nilai lama.
        sample_spt.collect_pk_data([{"dpp": Decimal("100"), "ppn": Decimal("11")}])
        result = sample_spt.collect_pk_data([])
        assert result.pk_count == 0
        assert result.total_penyerahan_dpp == Decimal("0")
        assert result.total_ppn_keluaran == Decimal("0")

    def test_collect_pm_data(self, sample_spt):
        faktur_list = [
            {"faktur_id": "1", "faktur_number": "PM-001", "ppn": Decimal("11000"), "npwp_penjual": "123", "nama_penjual": "PT X"},
            {"faktur_id": "2", "faktur_number": "PM-002", "ppn": Decimal("22000"), "retur": Decimal("2000")},
        ]
        result = sample_spt.collect_pm_data(faktur_list)
        assert result.pm_count == 2
        assert result.total_ppn_masukan == Decimal("33000")
        assert result.total_retur_masukan == Decimal("2000")
        assert len(result.detail_pm) == 2

    def test_set_kompensasi(self, sample_spt):
        result = sample_spt.set_kompensasi(Decimal("500000"))
        assert result.kompensasi == Decimal("500000")
        assert result.version == 2

    def test_set_ntpn(self, sample_spt):
        result = sample_spt.set_ntpn("1234567890123456")
        assert result.ntpn == "1234567890123456"
        assert result.version == 2

    def test_set_ntpn_invalid_format_raises(self, sample_spt):
        with pytest.raises(SPTValidationError, match="Invalid NTPN format"):
            sample_spt.set_ntpn("invalid")

    def test_set_ntpn_too_short_raises(self, sample_spt):
        with pytest.raises(SPTValidationError, match="Invalid NTPN format"):
            sample_spt.set_ntpn("123")

    def test_set_status_restitusi(self, sample_spt):
        result = sample_spt.set_status_restitusi("Kompen")
        assert result.status_restitusi == "Kompen"
        assert result.version == 2

    def test_set_coretax_response(self, sample_spt):
        response = {"spt_number": "SPT-001", "tracking_id": "TRK-123", "coretax_id": "COR-456", "status": "success"}
        result = sample_spt.set_coretax_response(response)
        assert result.spt_number == "SPT-001"
        assert result.tracking_id == "TRK-123"
        assert result.coretax_id == "COR-456"
        assert result.status == SPTStatus.SUBMITTED

    def test_set_coretax_response_non_success_does_not_change_status(self, sample_spt):
        # Negative path: respons Coretax yang bukan "success" tidak boleh
        # ikut mengubah status SPT ke SUBMITTED.
        original_status = sample_spt.status
        response = {"spt_number": "SPT-001", "status": "failed"}
        result = sample_spt.set_coretax_response(response)
        assert result.status == original_status
        assert result.spt_number == "SPT-001"

    def test_create_correction(self, sample_spt):
        created_by = uuid.uuid4()
        correction = sample_spt.create_correction(1, created_by)
        assert correction.spt_type == SPTType.CORRECTION
        assert correction.correction_number == 1
        assert correction.npwp == sample_spt.npwp
        assert correction.tahun == sample_spt.tahun
        assert correction.bulan == sample_spt.bulan
        assert correction.status == SPTStatus.DRAFT

    def test_private__calculate_hash(self, sample_spt):
        h1 = sample_spt._hash
        sample_spt._total_ppn_keluaran = Decimal("999")
        sample_spt._calculate_hash()
        assert sample_spt._hash != h1

    def test_private__generate_xml(self, sample_spt):
        sample_spt._detail_pk = [{"faktur_number": "FK-001", "npwp_pembeli": "123", "nama_pembeli": "PT A", "dpp": 100000, "ppn": 11000, "tanggal_faktur": "2026-05-01"}]
        sample_spt._detail_pm = [{"faktur_number": "PM-001", "npwp_penjual": "456", "nama_penjual": "PT B", "ppn": 5000}]
        sample_spt._pemungut_ppn = {"dpp": 10000, "ppn": 1000}
        xml = sample_spt._generate_xml()
        assert "<SPT" in xml
        assert "KodeFormulir" in xml
        assert "1111" in xml

    def test_private__generate_xml_error(self, sample_spt):
        with patch("xml.etree.ElementTree.tostring", side_effect=Exception("test")):
            with pytest.raises(SPTXMLGenerationError, match="Failed to create XML"):
                sample_spt._generate_xml()

    def test_private__validate_ntpn_format(self, sample_spt):
        assert sample_spt._validate_ntpn_format("1234567890123456")
        assert not sample_spt._validate_ntpn_format("1234")
        assert not sample_spt._validate_ntpn_format("abcdefghijklmnop")


# ============================================================================
# Tests for _FallbackSPTRepository
# ============================================================================

class TestFallbackSPTRepository:
    @pytest.mark.asyncio
    async def test_add_and_get(self, sample_spt):
        repo = _FallbackSPTRepository()
        await repo.add(sample_spt)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved is not None
        assert retrieved.spt_id == sample_spt.spt_id

    @pytest.mark.asyncio
    async def test_save(self, sample_spt):
        repo = _FallbackSPTRepository()
        await repo.add(sample_spt)
        sample_spt._status = SPTStatus.SUBMITTED
        await repo.save(sample_spt)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved.status == SPTStatus.SUBMITTED

    @pytest.mark.asyncio
    async def test_update(self, sample_spt):
        repo = _FallbackSPTRepository()
        await repo.add(sample_spt)
        sample_spt._total_bayar = Decimal("999")
        await repo.update(sample_spt)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved.total_bayar == Decimal("999")

    @pytest.mark.asyncio
    async def test_delete(self, sample_spt):
        repo = _FallbackSPTRepository()
        await repo.add(sample_spt)
        await repo.delete(sample_spt.spt_id)
        retrieved = await repo.get_by_id(sample_spt.spt_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_raise(self):
        # Negative path: hapus id yang tidak pernah ada tidak boleh error.
        repo = _FallbackSPTRepository()
        await repo.delete(uuid.uuid4())  # no exception expected

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_returns_none(self):
        repo = _FallbackSPTRepository()
        assert await repo.get_by_id(uuid.uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, sample_spt):
        repo = _FallbackSPTRepository()
        await repo.add(sample_spt)
        retrieved = await repo.get_by_npwp_period("123456789012345", 2026, 5)
        assert retrieved is not None
        assert retrieved.npwp == "123456789012345"
        retrieved = await repo.get_by_npwp_period("123456789012345", 2026, 6)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_by_tracking_id(self, sample_spt):
        repo = _FallbackSPTRepository()
        sample_spt._tracking_id = "TRK-123"
        await repo.add(sample_spt)
        retrieved = await repo.get_by_tracking_id("TRK-123")
        assert retrieved is not None
        assert retrieved.tracking_id == "TRK-123"

    @pytest.mark.asyncio
    async def test_get_by_tracking_id_not_found_returns_none(self):
        repo = _FallbackSPTRepository()
        assert await repo.get_by_tracking_id("UNKNOWN") is None

    @pytest.mark.asyncio
    async def test_get_by_status(self, sample_spt):
        repo = _FallbackSPTRepository()
        sample_spt._status = SPTStatus.PENDING
        await repo.add(sample_spt)
        results = await repo.get_by_status(SPTStatus.PENDING)
        assert len(results) == 1
        assert results[0].status == SPTStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_by_status_no_match_returns_empty_list(self, sample_spt):
        repo = _FallbackSPTRepository()
        await repo.add(sample_spt)  # status DRAFT
        results = await repo.get_by_status(SPTStatus.APPROVED)
        assert results == []

    @pytest.mark.asyncio
    async def test_get_pending_submissions(self, sample_spt):
        repo = _FallbackSPTRepository()
        sample_spt._status = SPTStatus.PENDING
        await repo.add(sample_spt)
        results = await repo.get_pending_submissions()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_pending_submissions_excludes_terminal_status(self, sample_spt):
        # Negative path: SPT berstatus CANCELLED tidak boleh muncul di
        # daftar pending submissions.
        repo = _FallbackSPTRepository()
        sample_spt._status = SPTStatus.CANCELLED
        await repo.add(sample_spt)
        results = await repo.get_pending_submissions()
        assert results == []

    @pytest.mark.asyncio
    async def test_exists(self, sample_spt):
        repo = _FallbackSPTRepository()
        await repo.add(sample_spt)
        exists = await repo.exists("123456789012345", 2026, 5)
        assert exists
        exists = await repo.exists("123456789012345", 2026, 6)
        assert not exists


# ============================================================================
# Tests for SPTMasaPPNBuilder
# ============================================================================

class TestSPTMasaPPNBuilder:
    @pytest.mark.asyncio
    async def test_create_new_spt(self, sample_builder):
        sample_builder._repository.exists = AsyncMock(return_value=False)
        sample_builder._repository.add = AsyncMock()
        sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=None)

        result = await sample_builder.create("123456789012345", 2026, 5, uuid.uuid4())
        assert result["success"]
        assert "spt_id" in result
        assert result["masa_pajak"] == "2026-05"

        # Mock quality: pastikan repository.add benar-benar dipanggil dengan
        # entity SPTMasaPPN yang npwp/tahun/bulan-nya sesuai permintaan.
        sample_builder._repository.add.assert_called_once()
        added_spt = sample_builder._repository.add.call_args.args[0]
        assert isinstance(added_spt, SPTMasaPPN)
        assert added_spt.npwp == "123456789012345"
        assert added_spt.tahun == 2026
        assert added_spt.bulan == 5

    @pytest.mark.asyncio
    async def test_create_existing_spt_returns_error(self, sample_builder):
        existing = make_mock_spt()
        sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=existing)
        sample_builder._repository.add = AsyncMock()

        result = await sample_builder.create("123456789012345", 2026, 5, uuid.uuid4())
        assert not result["success"]
        assert "already exists" in result["error"]
        # Negative path: karena SPT sudah ada, repository.add TIDAK boleh
        # dipanggil sama sekali.
        sample_builder._repository.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_data_success(self, sample_builder):
        tax_service = sample_builder._tax_service
        tax_service.get_faktur_keluaran_by_period = AsyncMock(return_value=[
            {"dpp": Decimal("100000"), "ppn": Decimal("11000")},
            {"dpp": Decimal("200000"), "ppn": Decimal("22000")},
        ])
        tax_service.get_faktur_masukan_credited_by_period = AsyncMock(return_value=[
            {"ppn": Decimal("5000")},
            {"ppn": Decimal("3000")},
        ])
        tax_service.get_retur_by_period = AsyncMock(return_value=[
            {"type": "keluaran", "ppn_keluaran": Decimal("1000")},
            {"type": "masukan", "ppn_masukan": Decimal("500")},
        ])
        tax_service.get_kompensasi_sebelumnya = AsyncMock(return_value=Decimal("2000"))
        tax_service.get_ntpn_for_period = AsyncMock(return_value={"ntpn": "1234567890123456"})

        result = await sample_builder.collect_data("123", 2026, 5)
        assert result["npwp"] == "123"
        assert result["total_ppn_keluaran"] == Decimal("33000")
        assert result["total_ppn_masukan"] == Decimal("8000")
        assert result["total_retur_keluaran"] == Decimal("1000")
        assert result["total_retur_masukan"] == Decimal("500")
        assert result["kompensasi"] == Decimal("2000")
        assert result["ppn_kurang_bayar"] == Decimal("26500")
        assert result["ppn_lebih_bayar"] == Decimal("0")
        assert result["ntpn"] == "1234567890123456"
        assert result["pk_count"] == 2
        assert result["pm_count"] == 2
        # Mock quality: pastikan tax_service dipanggil dengan periode yang benar
        tax_service.get_faktur_keluaran_by_period.assert_called_once_with("123", 2026, 5)
        tax_service.get_ntpn_for_period.assert_called_once_with("123", 2026, 5, tax_type="ppn")

    @pytest.mark.asyncio
    async def test_collect_data_error(self, sample_builder):
        tax_service = sample_builder._tax_service
        tax_service.get_faktur_keluaran_by_period = AsyncMock(side_effect=Exception("DB error"))
        result = await sample_builder.collect_data("123", 2026, 5)
        assert "error" in result
        assert result["error"] == "DB error"
        assert result["total_ppn_keluaran"] == Decimal("0")  # fallback values
        assert result["pk_count"] == 0
        assert result["detail_pk"] == []

    @pytest.mark.asyncio
    async def test_build_new_spt(self, sample_builder):
        sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=None)
        with patch.object(sample_builder, "create", return_value={"success": True, "spt_id": "new"}):
            with patch.object(sample_builder, "collect_data", return_value={
                "detail_pk": [], "detail_pm": [], "kompensasi": Decimal("0"), "ntpn": None
            }):
                mock_spt = make_mock_spt(
                    spt_id=uuid.uuid4(),
                    masa_pajak="2026-05",
                    total_ppn_keluaran=Decimal("0"),
                    total_ppn_masukan=Decimal("0"),
                    ppn_kurang_bayar=Decimal("0"),
                    ppn_lebih_bayar=Decimal("0"),
                    pk_count=0,
                    pm_count=0,
                    status=SPTStatus.DRAFT,
                )
                sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=mock_spt)
                mock_spt.collect_pk_data = MagicMock(return_value=mock_spt)
                mock_spt.collect_pm_data = MagicMock(return_value=mock_spt)
                mock_spt.set_kompensasi = MagicMock(return_value=mock_spt)
                mock_spt.set_ntpn = MagicMock(return_value=mock_spt)
                mock_spt.calculate = MagicMock(return_value=mock_spt)
                sample_builder._repository.update = AsyncMock()

                result = await sample_builder.build("123", 2026, 5, uuid.uuid4())
                assert result["success"]
                assert "spt_id" in result
                sample_builder._repository.update.assert_called_once_with(mock_spt)

    @pytest.mark.asyncio
    async def test_build_existing_spt(self, sample_builder):
        mock_spt = make_mock_spt(
            spt_id=uuid.uuid4(),
            masa_pajak="2026-05",
            total_ppn_keluaran=Decimal("0"),
            total_ppn_masukan=Decimal("0"),
            ppn_kurang_bayar=Decimal("0"),
            ppn_lebih_bayar=Decimal("0"),
            pk_count=0,
            pm_count=0,
            status=SPTStatus.DRAFT,
        )
        sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=mock_spt)
        with patch.object(sample_builder, "collect_data", return_value={
            "detail_pk": [], "detail_pm": [], "kompensasi": Decimal("0"), "ntpn": None
        }):
            mock_spt.collect_pk_data = MagicMock(return_value=mock_spt)
            mock_spt.collect_pm_data = MagicMock(return_value=mock_spt)
            mock_spt.set_kompensasi = MagicMock(return_value=mock_spt)
            mock_spt.set_ntpn = MagicMock(return_value=mock_spt)
            mock_spt.calculate = MagicMock(return_value=mock_spt)
            sample_builder._repository.update = AsyncMock()
            result = await sample_builder.build("123", 2026, 5, uuid.uuid4())
            assert result["success"]

    @pytest.mark.asyncio
    async def test_build_collect_data_error_short_circuits(self, sample_builder):
        # Negative path: jika collect_data mengembalikan "error", build()
        # harus berhenti dan mengembalikan error tanpa menyentuh repository.update.
        mock_spt = make_mock_spt(spt_id=uuid.uuid4())
        sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        with patch.object(sample_builder, "collect_data", return_value={"error": "DB error"}):
            result = await sample_builder.build("123", 2026, 5, uuid.uuid4())
        assert not result["success"]
        assert result["error"] == "DB error"
        sample_builder._repository.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_when_create_fails_propagates_error(self, sample_builder):
        # Negative path: jika SPT belum ada dan create() gagal, build()
        # harus meneruskan error dari create() tanpa lanjut mengumpulkan data.
        sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=None)
        with patch.object(sample_builder, "create", return_value={"success": False, "error": "already exists"}):
            with patch.object(sample_builder, "collect_data") as mock_collect_data:
                result = await sample_builder.build("123", 2026, 5, uuid.uuid4())
        assert not result["success"]
        assert result["error"] == "already exists"
        mock_collect_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_spt_success(self, sample_builder):
        mock_spt = make_mock_spt(npwp="123", tahun=2026, bulan=5, spt_id=uuid.uuid4(), status=SPTStatus.VALIDATED)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert result["success"]
        assert result["valid"]
        sample_builder._repository.update.assert_called_once_with(mock_spt)

    @pytest.mark.asyncio
    async def test_validate_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_spt_validation_error(self, sample_builder):
        mock_spt = make_mock_spt()
        mock_spt.validate = MagicMock(side_effect=SPTValidationError("Invalid"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert not result["valid"]
        assert "Invalid" in result["error"]
        # Negative path: kalau validasi gagal, repository.update tidak boleh
        # dipanggil (state tidak boleh dipersist).
        sample_builder._repository.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_spt_locked_error(self, sample_builder):
        # Negative path: SPTLockedError harus ditangani terpisah dari
        # SPTValidationError dan tidak mengembalikan key "valid".
        mock_spt = make_mock_spt()
        mock_spt.validate = MagicMock(side_effect=SPTLockedError("SPT is locked"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "locked" in result["error"]
        assert "valid" not in result

    @pytest.mark.asyncio
    async def test_validate_spt_invalid_state_error(self, sample_builder):
        mock_spt = make_mock_spt()
        mock_spt.validate = MagicMock(side_effect=SPTInvalidStateError("Cannot validate"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.validate_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "Cannot validate" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_spt_success(self, sample_builder):
        mock_spt = make_mock_spt(
            status=SPTStatus.SUBMITTED,
            spt_id=uuid.uuid4(),
            npwp="123",
            tahun=2026,
            bulan=5,
            masa_pajak="2026-05",
            spt_type=SPTType.NORMAL,
            correction_number=0,
            spt_number="SPT-001",
            tracking_id="TRK-123",
            coretax_id="COR-456",
        )
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)
        mock_spt.transition = MagicMock(return_value=mock_spt)

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(return_value={"status": "success", "message": "OK"})

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert result["success"]
        assert result["spt_number"] == "SPT-001"
        assert result["tracking_id"] == "TRK-123"

        # Mock quality: pastikan payload yang dikirim ke Coretax memuat data
        # SPT yang benar, bukan hanya bahwa client.post dipanggil.
        client.post.assert_called_once_with(
            CORETAX_SPT_PPN_ENDPOINT,
            {
                "spt_xml": ANY,
                "npwp": "123",
                "tahun": 2026,
                "bulan": 5,
                "spt_type": SPTType.NORMAL.value,
                "correction_number": 0,
            },
        )

    @pytest.mark.asyncio
    async def test_submit_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.submit_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_spt_validation_error(self, sample_builder):
        mock_spt = make_mock_spt(status=SPTStatus.DRAFT)
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(side_effect=SPTValidationError("Invalid"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.submit_spt(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "Invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_spt_coretax_auth_error(self, sample_builder):
        mock_spt = make_mock_spt(
            status=SPTStatus.CALCULATED,
            spt_id=uuid.uuid4(),
            npwp="123",
            tahun=2026,
            bulan=5,
            masa_pajak="2026-05",
            spt_type=SPTType.NORMAL,
            correction_number=0,
        )
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
        # Negative path: SPT dengan status ERROR tetap harus dipersist supaya
        # tidak "hilang" di status lama.
        sample_builder._repository.update.assert_called_with(mock_spt)

    @pytest.mark.asyncio
    async def test_submit_spt_generic_exception_transitions_to_error(self, sample_builder):
        # Negative path yang sebelumnya tidak diuji: kegagalan non-auth
        # (mis. koneksi putus berulang kali) harus tetap masuk ke branch
        # except Exception, men-transition ke ERROR, dan mencoba trigger_alert
        # tanpa membuat test meledak walau modul alert tidak tersedia.
        mock_spt = make_mock_spt(
            status=SPTStatus.CALCULATED,
            spt_id=uuid.uuid4(),
            npwp="123",
            tahun=2026,
            bulan=5,
            masa_pajak="2026-05",
            spt_type=SPTType.NORMAL,
            correction_number=0,
        )
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.transition = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(side_effect=ConnectionError("network down"))

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert not result["success"]
        assert "network down" in result["error"]
        mock_spt.transition.assert_called_with(SPTStatus.ERROR, ANY, "network down")
        sample_builder._repository.update.assert_called_with(mock_spt)
        # Retry harus dicoba MAX_RETRY_ATTEMPTS kali sebelum menyerah.
        assert client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_submit_spt_retry_success(self, sample_builder):
        mock_spt = make_mock_spt(
            status=SPTStatus.CALCULATED,
            spt_id=uuid.uuid4(),
            npwp="123",
            tahun=2026,
            bulan=5,
            spt_type=SPTType.NORMAL,
            correction_number=0,
            spt_number="SPT-001",
            tracking_id="TRK-123",
            coretax_id="COR-456",
        )
        mock_spt._generate_xml = MagicMock(return_value="<xml/>")
        mock_spt.calculate = MagicMock(return_value=mock_spt)
        mock_spt.validate = MagicMock(return_value=mock_spt)
        mock_spt.submit = MagicMock(return_value=mock_spt)
        mock_spt.set_coretax_response = MagicMock(return_value=mock_spt)

        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._set_cached = AsyncMock()

        client = sample_builder._coretax_client
        client.post = AsyncMock(side_effect=[Exception("Temp"), {"status": "success"}])

        result = await sample_builder.submit_spt(mock_spt.spt_id, uuid.uuid4())
        assert result["success"]
        # Mock quality: pastikan memang retry terjadi (dipanggil 2x), bukan
        # kebetulan sukses di percobaan pertama.
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_check_spt_status_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_check_spt_status_no_tracking_id(self, sample_builder):
        mock_spt = make_mock_spt(tracking_id=None, status=SPTStatus.DRAFT)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert result["success"]
        assert result["message"] == "Not yet submitted to Coretax"

    @pytest.mark.asyncio
    async def test_check_spt_status_success(self, sample_builder):
        mock_spt = make_mock_spt(tracking_id="TRK-123", status=SPTStatus.SUBMITTED)
        mock_spt.approve = MagicMock(return_value=mock_spt)
        mock_spt.reject = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.get = AsyncMock(return_value={"status": "approved", "approval_date": "2026-05-15"})

        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert result["success"]
        assert result["status"] == SPTStatus.APPROVED.value
        mock_spt.approve.assert_called_once()
        mock_spt.reject.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_spt_status_rejected(self, sample_builder):
        mock_spt = make_mock_spt(tracking_id="TRK-123", status=SPTStatus.SUBMITTED)
        mock_spt.approve = MagicMock(return_value=mock_spt)
        mock_spt.reject = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.get = AsyncMock(return_value={"status": "rejected", "rejection_reason": "data tidak sesuai"})

        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert result["success"]
        mock_spt.reject.assert_called_once_with(UUID_ZERO, "data tidak sesuai")
        mock_spt.approve.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_spt_status_error(self, sample_builder):
        # Negative path yang sebelumnya tidak diuji: kalau client Coretax
        # melempar exception, check_spt_status harus mengembalikan error
        # terstruktur, bukan meledak ke pemanggil.
        mock_spt = make_mock_spt(tracking_id="TRK-123", status=SPTStatus.SUBMITTED)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        client = sample_builder._coretax_client
        client.get = AsyncMock(side_effect=Exception("timeout"))

        result = await sample_builder.check_spt_status(uuid.uuid4())
        assert not result["success"]
        assert "timeout" in result["error"]
        sample_builder._repository.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_spt_success(self, sample_builder):
        mock_spt = make_mock_spt(
            spt_id=uuid.uuid4(),
            tracking_id="TRK-123",
            npwp="123",
            tahun=2026,
            bulan=5,
            status=SPTStatus.DRAFT,
        )
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
        mock_spt.cancel.assert_called_once()
        client.post.assert_called_once_with(
            "/api/v1/spt/cancel", {"tracking_id": "TRK-123", "reason": "reason"}
        )

    @pytest.mark.asyncio
    async def test_cancel_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.cancel_spt(uuid.uuid4(), uuid.uuid4(), "reason")
        assert not result["success"]
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_cancel_spt_locked_error(self, sample_builder):
        # Negative path: SPT yang terkunci tidak boleh berhasil dibatalkan.
        mock_spt = make_mock_spt()
        mock_spt.cancel = MagicMock(side_effect=SPTLockedError("SPT is locked"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        result = await sample_builder.cancel_spt(uuid.uuid4(), uuid.uuid4(), "reason")
        assert not result["success"]
        assert "locked" in result["error"]
        sample_builder._repository.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_spt_invalid_state_error(self, sample_builder):
        mock_spt = make_mock_spt()
        mock_spt.cancel = MagicMock(side_effect=SPTInvalidStateError("Cannot cancel"))
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()

        result = await sample_builder.cancel_spt(uuid.uuid4(), uuid.uuid4(), "reason")
        assert not result["success"]
        assert "Cannot cancel" in result["error"]

    @pytest.mark.asyncio
    async def test_cancel_spt_coretax_notify_failure_still_succeeds(self, sample_builder):
        # Negative path: kegagalan memberi tahu Coretax tentang pembatalan
        # tidak boleh membuat keseluruhan operasi cancel_spt gagal, karena
        # SPT sudah terlanjur dibatalkan secara lokal.
        mock_spt = make_mock_spt(
            spt_id=uuid.uuid4(),
            tracking_id="TRK-123",
            npwp="123",
            tahun=2026,
            bulan=5,
            status=SPTStatus.DRAFT,
        )
        mock_spt.cancel = MagicMock(return_value=mock_spt)
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        sample_builder._repository.update = AsyncMock()
        sample_builder._cache = {}
        sample_builder._get_cache_key = MagicMock(return_value="key")

        client = sample_builder._coretax_client
        client.post = AsyncMock(side_effect=Exception("Coretax down"))

        result = await sample_builder.cancel_spt(mock_spt.spt_id, uuid.uuid4(), "reason")
        assert result["success"]
        assert result["cancelled"]

    @pytest.mark.asyncio
    async def test_create_correction_spt_success(self, sample_builder):
        correction_result = make_mock_spt(
            spt_id=uuid.uuid4(), masa_pajak="2026-05", correction_number=1, status=SPTStatus.DRAFT
        )
        previous_spt = make_mock_spt()
        previous_spt.create_correction = MagicMock(return_value=correction_result)
        sample_builder._repository.get_by_id = AsyncMock(return_value=previous_spt)
        sample_builder._repository.add = AsyncMock()
        result = await sample_builder.create_correction_spt("123", 2026, 5, uuid.uuid4(), 1, uuid.uuid4())
        assert result["success"]
        assert result["correction_number"] == 1
        sample_builder._repository.add.assert_called_once_with(correction_result)

    @pytest.mark.asyncio
    async def test_create_correction_spt_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        sample_builder._repository.add = AsyncMock()
        result = await sample_builder.create_correction_spt("123", 2026, 5, uuid.uuid4(), 1, uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]
        sample_builder._repository.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_by_id(self, sample_builder):
        mock_spt = make_mock_spt()
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_by_id(uuid.uuid4())
        assert result is mock_spt

    @pytest.mark.asyncio
    async def test_get_by_id_not_found_returns_none(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.get_by_id(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self, sample_builder):
        mock_spt = make_mock_spt()
        sample_builder._repository.get_by_npwp_period = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_by_npwp_period("123", 2026, 5)
        assert result is mock_spt

    @pytest.mark.asyncio
    async def test_get_status(self, sample_builder):
        mock_spt = make_mock_spt()
        mock_spt.get_status = MagicMock(return_value={"status": "draft"})
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_status(uuid.uuid4())
        assert result["success"]
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.get_status(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_history(self, sample_builder):
        mock_spt = make_mock_spt()
        mock_spt.get_history = MagicMock(return_value=[{"event": "test"}])
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.get_history(uuid.uuid4())
        assert result["success"]
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_get_history_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.get_history(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_snapshot(self, sample_builder):
        mock_spt = make_mock_spt()
        mock_spt.snapshot = MagicMock(return_value={"spt_id": "123"})
        sample_builder._repository.get_by_id = AsyncMock(return_value=mock_spt)
        result = await sample_builder.snapshot(uuid.uuid4())
        assert result["success"]
        assert result["spt_id"] == "123"

    @pytest.mark.asyncio
    async def test_snapshot_not_found(self, sample_builder):
        sample_builder._repository.get_by_id = AsyncMock(return_value=None)
        result = await sample_builder.snapshot(uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    def test_build_sync(self, sample_builder):
        faktur_list = [
            MagicMock(ppn=Decimal("11000")),
            MagicMock(ppn=Decimal("22000")),
            {"ppn": Decimal("33000")},
            MagicMock(data={"ppn": Decimal("44000")}),
        ]
        spt = sample_builder.build_sync(faktur_list, 5, 2026)
        assert isinstance(spt, SPTMasaPpn)
        assert spt.total_ppn_terutang == Decimal("110000")
        assert spt.masa == 5
        assert spt.tahun == 2026

    def test_build_sync_empty_list_returns_zero(self, sample_builder):
        # Negative/edge path: daftar faktur kosong tidak boleh membuat
        # error, hasilnya harus total nol.
        spt = sample_builder.build_sync([], 5, 2026)
        assert spt.total_ppn_terutang == Decimal("0")

    def test_build_sync_unrecognized_faktur_shape_defaults_to_zero(self, sample_builder):
        # Negative/edge path: item yang bukan dict, tidak punya atribut ppn,
        # dan tidak punya atribut data harus dianggap PPN 0, bukan error.
        class Unknown:
            pass

        spt = sample_builder.build_sync([Unknown()], 5, 2026)
        assert spt.total_ppn_terutang == Decimal("0")

    def test_init_file_storage_import_failure_leaves_file_storage_none(self):
        # Negative path yang sebelumnya tidak diuji: kalau S3FileStorageAdapter
        # tidak tersedia (ImportError), builder tidak boleh crash saat init,
        # cukup log warning dan _file_storage tetap None.
        with patch.dict("sys.modules", {"infrastructure.file_storage.s3_adapter": None}):
            builder = SPTMasaPPNBuilder(config={})
        assert builder._file_storage is None


# ============================================================================
# Tests for Legacy SPTMasaPpn
# ============================================================================

class TestSPTMasaPpn:
    def test_init(self):
        spt = SPTMasaPpn(total_ppn_terutang=Decimal("1000"), masa=5, tahun=2026)
        assert spt.total_ppn_terutang == Decimal("1000")
        assert spt.masa == 5
        assert spt.tahun == 2026
        assert spt.total_ppn_keluaran == Decimal("1000")
        assert spt.total_ppn_masukan == Decimal("0")
        assert spt.kode_formulir == FORM_CODE

    def test_pay(self):
        spt = SPTMasaPpn(Decimal("1000"), 5, 2026)
        ref = spt.pay(Decimal("1000"), "BNI")
        assert isinstance(ref, PaymentReference)
        assert ref.amount == Decimal("1000")
        assert ref.bank_code == "BNI"
        assert len(ref.ntpn) == 16
        assert ref.ntpn.isdigit()

    def test_submit(self):
        spt = SPTMasaPpn(Decimal("1000"), 5, 2026)
        result = spt.submit("1234567890123456")
        assert isinstance(result, SubmissionResult)
        assert result.is_submitted
        assert result.receipt_number.startswith("SPT-202605-")


# ============================================================================
# Tests for PaymentReference and SubmissionResult
# ============================================================================

class TestPaymentReference:
    def test_init(self):
        ref = PaymentReference(ntpn="1234", amount=Decimal("100"), bank_code="BNI")
        assert ref.ntpn == "1234"
        assert ref.amount == Decimal("100")
        assert ref.bank_code == "BNI"


class TestSubmissionResult:
    def test_init(self):
        res = SubmissionResult(is_submitted=True, receipt_number="RCPT-001")
        assert res.is_submitted
        assert res.receipt_number == "RCPT-001"


# ============================================================================
# Tests for Singleton get_spt_ppn_builder
# ============================================================================

@pytest.mark.asyncio
async def test_get_spt_ppn_builder_singleton():
    with patch("adapters.coretax_djp.spt_masa_ppn_builder.SPTMasaPPNBuilder") as MockBuilder:
        MockBuilder.return_value = MagicMock()
        builder1 = await get_spt_ppn_builder(config={})
        builder2 = await get_spt_ppn_builder(config={})
        assert builder1 is builder2
        assert MockBuilder.call_count == 1