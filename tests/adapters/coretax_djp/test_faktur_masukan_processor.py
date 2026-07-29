#!/usr/bin/env python3
"""
tests/adapters/coretax_djp/test_faktur_masukan_processor.py
Test untuk adapters/coretax_djp/faktur_masukan_processor.py
Mencakup semua kelas dan metode secara exhaustive dengan mocking.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from adapters.coretax_djp.faktur_masukan_processor import (
    CORETAX_PM_CANCEL_ENDPOINT,
    CORETAX_PM_CREDIT_ENDPOINT,
    DEFAULT_PPN_RATE,
    EXPIRY_DAYS,
    FakturMasukan,
    FakturMasukanAlreadyExistsError,
    FakturMasukanError,
    FakturMasukanExpiredError,
    FakturMasukanInvalidStateError,
    FakturMasukanLockedError,
    FakturMasukanNotFoundError,
    FakturMasukanProcessor,
    FakturMasukanStatus,
    FakturMasukanValidationError,
    _FallbackTaxRepository,
    get_faktur_masukan_processor,
)

# ============================================================================
# FIXED DATETIME & FIXTURES
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 1)
EXPIRED_DATE = FIXED_DATE - timedelta(days=EXPIRY_DAYS + 1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() and date.today() globally for all tests."""
    with patch("adapters.coretax_djp.faktur_masukan_processor.datetime") as mock_dt:
        mock_dt.datetime.now.return_value = FIXED_NOW
        mock_dt.date.today.return_value = FIXED_DATE
        mock_dt.UTC = UTC
        with patch("adapters.coretax_djp.faktur_masukan_processor.datetime.now", return_value=FIXED_NOW):
            with patch("adapters.coretax_djp.faktur_masukan_processor.date.today", return_value=FIXED_DATE):
                yield


@pytest.fixture
def sample_faktur_data() -> dict:
    return {
        "faktur_number": "010.2026.05.00000001",
        "npwp_penjual": "123456789012345",
        "nama_penjual": "PT Supplier Maju",
        "tanggal_faktur": FIXED_DATE,
        "dpp": Decimal("100000000"),
        "ppn": Decimal("11000000"),
        "npwp_pembeli": "987654321098765",
        "alamat_penjual": "Jl. Supplier No. 1",
        "ppn_bm": Decimal("0"),
        "keterangan": "Test faktur",
        "xml_content": "<xml>test</xml>",
    }


@pytest.fixture
def sample_faktur(sample_faktur_data) -> FakturMasukan:
    return FakturMasukan(**sample_faktur_data)


@pytest.fixture
def sample_processor() -> FakturMasukanProcessor:
    with patch("adapters.coretax_djp.faktur_masukan_processor.FakturMasukanProcessor._init_file_storage"):
        processor = FakturMasukanProcessor(config={})
        processor._coretax_client = AsyncMock()
        processor._tax_service = AsyncMock()
        processor._file_storage = AsyncMock()
        processor._cache = {}
        return processor


# ============================================================================
# Tests for Enums
# ============================================================================

class TestFakturMasukanStatus:
    def test_members(self):
        assert FakturMasukanStatus.DRAFT.value == "draft"
        assert FakturMasukanStatus.PENDING.value == "pending"
        assert FakturMasukanStatus.VALIDATED.value == "validated"
        assert FakturMasukanStatus.MATCHED.value == "matched"
        assert FakturMasukanStatus.CREDITED.value == "credited"
        assert FakturMasukanStatus.APPROVED.value == "approved"
        assert FakturMasukanStatus.REJECTED.value == "rejected"
        assert FakturMasukanStatus.POSTED.value == "posted"
        assert FakturMasukanStatus.CANCELLED.value == "cancelled"
        assert FakturMasukanStatus.VOID.value == "void"
        assert FakturMasukanStatus.REVERSED.value == "reversed"
        assert FakturMasukanStatus.CLOSED.value == "closed"
        assert FakturMasukanStatus.ARCHIVED.value == "archived"
        assert FakturMasukanStatus.LOCKED.value == "locked"
        assert FakturMasukanStatus.ERROR.value == "error"
        assert FakturMasukanStatus.SYNCED.value == "synced"
        assert FakturMasukanStatus.EXPIRED.value == "expired"


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_exceptions_are_defined(self):
        for exc in [
            FakturMasukanError,
            FakturMasukanNotFoundError,
            FakturMasukanAlreadyExistsError,
            FakturMasukanInvalidStateError,
            FakturMasukanValidationError,
            FakturMasukanExpiredError,
            FakturMasukanLockedError,
        ]:
            assert issubclass(exc, Exception)


# ============================================================================
# Tests for FakturMasukan Entity
# ============================================================================

class TestFakturMasukan:
    def test_constructor(self, sample_faktur_data):
        faktur = FakturMasukan(**sample_faktur_data)
        assert faktur.faktur_id is not None
        assert faktur.faktur_number == sample_faktur_data["faktur_number"]
        assert faktur.npwp_penjual == sample_faktur_data["npwp_penjual"]
        assert faktur.nama_penjual == sample_faktur_data["nama_penjual"]
        assert faktur.dpp == sample_faktur_data["dpp"]
        assert faktur.ppn == sample_faktur_data["ppn"]
        assert faktur.total_amount == sample_faktur_data["dpp"] + sample_faktur_data["ppn"]
        assert faktur.status == FakturMasukanStatus.DRAFT
        assert faktur.version == 1
        assert faktur.hash != ""
        assert not faktur.is_locked
        assert faktur.is_active
        assert not faktur.is_expired

    def test_is_expired(self, sample_faktur):
        sample_faktur._tanggal_faktur = EXPIRED_DATE
        with patch("adapters.coretax_djp.faktur_masukan_processor.date") as mock_date:
            mock_date.today.return_value = EXPIRED_DATE + timedelta(days=1)
            assert sample_faktur.is_expired
            sample_faktur._status = FakturMasukanStatus.CANCELLED
            assert not sample_faktur.is_expired

    def test_create(self, sample_faktur):
        created_by = uuid.uuid4()
        result = sample_faktur.create(created_by)
        assert result.status == FakturMasukanStatus.DRAFT
        assert result.version == 2
        assert len(result._events) == 1
        assert result._events[0]["event_type"] == "faktur_masukan_created"

    def test_update(self, sample_faktur):
        updated_by = uuid.uuid4()
        data = {"dpp": Decimal("150000000"), "ppn": Decimal("16500000"), "keterangan": "Updated"}
        result = sample_faktur.update(data, updated_by)
        assert result.dpp == Decimal("150000000")
        assert result.ppn == Decimal("16500000")
        assert result.keterangan == "Updated"
        assert result.version == 2
        assert len(result._events) == 1
        assert result._events[0]["event_type"] == "faktur_masukan_updated"

    def test_update_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.update({}, uuid.uuid4())

    def test_update_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot modify"):
            sample_faktur.update({}, uuid.uuid4())

    def test_delete_soft(self, sample_faktur):
        deleted_by = uuid.uuid4()
        result = sample_faktur.delete(deleted_by, permanent=False)
        assert result.status == FakturMasukanStatus.ARCHIVED
        assert result.archived_at is not None
        assert result.version == 2
        assert result._events[0]["event_type"] == "faktur_masukan_deleted"

    def test_delete_permanent(self, sample_faktur):
        deleted_by = uuid.uuid4()
        result = sample_faktur.delete(deleted_by, permanent=True)
        assert result.status == FakturMasukanStatus.VOID
        assert result.version == 2

    def test_restore(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.ARCHIVED
        restored_by = uuid.uuid4()
        result = sample_faktur.restore(restored_by)
        assert result.status == FakturMasukanStatus.DRAFT
        assert result.archived_at is None
        assert result.version == 2

    def test_restore_invalid_status_raises(self, sample_faktur):
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot restore"):
            sample_faktur.restore(uuid.uuid4())

    def test_activate(self, sample_faktur):
        activated_by = uuid.uuid4()
        result = sample_faktur.activate(activated_by)
        assert result.status == FakturMasukanStatus.PENDING
        assert result.version == 2

    def test_activate_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot activate"):
            sample_faktur.activate(uuid.uuid4())

    def test_deactivate(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        deactivated_by = uuid.uuid4()
        result = sample_faktur.deactivate(deactivated_by)
        assert result.status == FakturMasukanStatus.DRAFT
        assert result.version == 2

    def test_deactivate_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot deactivate"):
            sample_faktur.deactivate(uuid.uuid4())

    def test_lock(self, sample_faktur):
        locked_by = uuid.uuid4()
        result = sample_faktur.lock(locked_by, "test")
        assert result.is_locked
        assert result.locked_by == locked_by
        assert result.locked_at is not None
        assert result.status == FakturMasukanStatus.LOCKED
        assert result.version == 2

    def test_lock_already_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="already locked"):
            sample_faktur.lock(uuid.uuid4(), "test")

    def test_unlock(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        sample_faktur._locked_by = uuid.uuid4()
        unlocked_by = uuid.uuid4()
        result = sample_faktur.unlock(unlocked_by)
        assert not result.is_locked
        assert result.locked_by is None
        assert result.locked_at is None
        assert result.status == FakturMasukanStatus.VALIDATED
        assert result.version == 2

    def test_unlock_not_locked_raises(self, sample_faktur):
        with pytest.raises(FakturMasukanLockedError, match="is not locked"):
            sample_faktur.unlock(uuid.uuid4())

    def test_validate(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        validator_id = uuid.uuid4()
        result = sample_faktur.validate(validator_id)
        assert result.status == FakturMasukanStatus.VALIDATED
        assert result.version == 2
        assert result._events[0]["event_type"] == "faktur_masukan_validated"

    def test_validate_expired_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        sample_faktur._tanggal_faktur = EXPIRED_DATE
        with patch("adapters.coretax_djp.faktur_masukan_processor.date") as mock_date:
            mock_date.today.return_value = EXPIRED_DATE + timedelta(days=1)
            with pytest.raises(FakturMasukanExpiredError, match="has expired"):
                sample_faktur.validate(uuid.uuid4())
            assert sample_faktur.status == FakturMasukanStatus.EXPIRED

    def test_validate_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.validate(uuid.uuid4())

    def test_validate_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot validate"):
            sample_faktur.validate(uuid.uuid4())

    def test_approve(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.VALIDATED
        approver_id = uuid.uuid4()
        result = sample_faktur.approve(approver_id, "approved")
        assert result.status == FakturMasukanStatus.APPROVED
        assert result.approved_at is not None
        assert result.version == 2

    def test_approve_expired_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.VALIDATED
        sample_faktur._tanggal_faktur = EXPIRED_DATE
        with patch("adapters.coretax_djp.faktur_masukan_processor.date") as mock_date:
            mock_date.today.return_value = EXPIRED_DATE + timedelta(days=1)
            with pytest.raises(FakturMasukanExpiredError, match="has expired"):
                sample_faktur.approve(uuid.uuid4())
            assert sample_faktur.status == FakturMasukanStatus.EXPIRED

    def test_approve_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.approve(uuid.uuid4())

    def test_approve_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot approve"):
            sample_faktur.approve(uuid.uuid4())

    def test_reject(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        rejector_id = uuid.uuid4()
        result = sample_faktur.reject(rejector_id, "Invalid data")
        assert result.status == FakturMasukanStatus.REJECTED
        assert result.rejection_reason == "Invalid data"
        assert result.version == 2

    def test_reject_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.reject(uuid.uuid4(), "reason")

    def test_reject_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot reject"):
            sample_faktur.reject(uuid.uuid4(), "reason")

    def test_cancel(self, sample_faktur):
        cancelled_by = uuid.uuid4()
        result = sample_faktur.cancel(cancelled_by, "test")
        assert result.status == FakturMasukanStatus.CANCELLED
        assert result.cancellation_reason == "test"
        assert result.version == 2

    def test_cancel_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.cancel(uuid.uuid4(), "reason")

    def test_cancel_closed_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.CLOSED
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot cancel"):
            sample_faktur.cancel(uuid.uuid4(), "reason")

    def test_cancel_credited_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.CREDITED
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot cancel"):
            sample_faktur.cancel(uuid.uuid4(), "reason")

    def test_void(self, sample_faktur):
        voided_by = uuid.uuid4()
        result = sample_faktur.void(voided_by, "void reason")
        assert result.status == FakturMasukanStatus.VOID
        assert result.cancellation_reason == "void reason"
        assert result.version == 2

    def test_void_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.void(uuid.uuid4(), "reason")

    def test_post(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        posted_by = uuid.uuid4()
        result = sample_faktur.post(posted_by)
        assert result.status == FakturMasukanStatus.POSTED
        assert result.posted_at is not None
        assert result.version == 2

    def test_post_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.post(uuid.uuid4())

    def test_post_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot post"):
            sample_faktur.post(uuid.uuid4())

    def test_unpost(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.POSTED
        unposted_by = uuid.uuid4()
        result = sample_faktur.unpost(unposted_by)
        assert result.status == FakturMasukanStatus.APPROVED
        assert result.posted_at is None
        assert result.version == 2

    def test_unpost_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.unpost(uuid.uuid4())

    def test_unpost_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot unpost"):
            sample_faktur.unpost(uuid.uuid4())

    def test_reverse(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.CREDITED
        reversed_by = uuid.uuid4()
        result = sample_faktur.reverse(reversed_by, "test")
        assert result.status == FakturMasukanStatus.REVERSED
        assert result.version == 2

    def test_reverse_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.reverse(uuid.uuid4(), "reason")

    def test_close(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.POSTED
        closed_by = uuid.uuid4()
        result = sample_faktur.close(closed_by)
        assert result.status == FakturMasukanStatus.CLOSED
        assert result.closed_at is not None
        assert result.version == 2

    def test_close_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.close(uuid.uuid4())

    def test_close_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot close"):
            sample_faktur.close(uuid.uuid4())

    def test_reopen(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.CLOSED
        reopened_by = uuid.uuid4()
        result = sample_faktur.reopen(reopened_by)
        assert result.status == FakturMasukanStatus.POSTED
        assert result.closed_at is None
        assert result.version == 2

    def test_reopen_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.reopen(uuid.uuid4())

    def test_reopen_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot reopen"):
            sample_faktur.reopen(uuid.uuid4())

    def test_archive(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.CLOSED
        archived_by = uuid.uuid4()
        result = sample_faktur.archive(archived_by)
        assert result.status == FakturMasukanStatus.ARCHIVED
        assert result.archived_at is not None
        assert result.version == 2

    def test_archive_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot archive"):
            sample_faktur.archive(uuid.uuid4())

    def test_unarchive(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.ARCHIVED
        unarchived_by = uuid.uuid4()
        result = sample_faktur.unarchive(unarchived_by)
        assert result.status == FakturMasukanStatus.CLOSED
        assert result.archived_at is None
        assert result.version == 2

    def test_unarchive_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot unarchive"):
            sample_faktur.unarchive(uuid.uuid4())

    def test_sync(self, sample_faktur):
        synced_by = uuid.uuid4()
        result = sample_faktur.sync(synced_by)
        assert result.status == FakturMasukanStatus.SYNCED
        assert result.synced_at is not None
        assert result.version == 2

    def test_download(self, sample_faktur):
        result = sample_faktur.download()
        assert result.synced_at is not None
        assert result.updated_at is not None

    def test_credit(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        period_id = uuid.uuid4()
        credited_by = uuid.uuid4()
        result = sample_faktur.credit(period_id, credited_by)
        assert result.status == FakturMasukanStatus.CREDITED
        assert result.period_id == period_id
        assert result.credit_amount == sample_faktur.ppn
        assert result.credited_at is not None
        assert result.version == 2

    def test_credit_with_amount(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        period_id = uuid.uuid4()
        credited_by = uuid.uuid4()
        result = sample_faktur.credit(period_id, credited_by, Decimal("5000000"))
        assert result.credit_amount == Decimal("5000000")

    def test_credit_amount_exceeds_ppn_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        with pytest.raises(FakturMasukanValidationError, match="Credit amount"):
            sample_faktur.credit(uuid.uuid4(), uuid.uuid4(), Decimal("999999999"))

    def test_credit_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.credit(uuid.uuid4(), uuid.uuid4())

    def test_credit_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot credit"):
            sample_faktur.credit(uuid.uuid4(), uuid.uuid4())

    def test_reverse_credit(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.CREDITED
        sample_faktur._period_id = uuid.uuid4()
        sample_faktur._credit_amount = Decimal("11000000")
        sample_faktur._credited_at = FIXED_NOW
        reversed_by = uuid.uuid4()
        result = sample_faktur.reverse_credit(reversed_by, "test")
        assert result.status == FakturMasukanStatus.APPROVED
        assert result.period_id is None
        assert result.credit_amount == Decimal(0)
        assert result.credited_at is None
        assert result.version == 2

    def test_reverse_credit_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.reverse_credit(uuid.uuid4(), "reason")

    def test_reverse_credit_invalid_status_raises(self, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        with pytest.raises(FakturMasukanInvalidStateError, match="Cannot reverse credit"):
            sample_faktur.reverse_credit(uuid.uuid4(), "reason")

    def test_calculate(self, sample_faktur):
        result = sample_faktur.calculate()
        assert result["dpp"] == sample_faktur.dpp
        assert result["ppn"] == sample_faktur.ppn
        assert result["total"] == sample_faktur.total_amount
        assert result["ppn_rate_percent"] == DEFAULT_PPN_RATE * 100

    def test_recalculate(self, sample_faktur):
        sample_faktur._ppn = Decimal("0")
        result = sample_faktur.recalculate()
        expected_ppn = (sample_faktur.dpp * DEFAULT_PPN_RATE).quantize(Decimal("0.01"))
        assert result.ppn == expected_ppn
        assert result.version == 2

    def test_match(self, sample_faktur):
        transaction_id = uuid.uuid4()
        matched_by = uuid.uuid4()
        result = sample_faktur.match(transaction_id, matched_by)
        assert result.matched_transaction_id == transaction_id
        assert result.status == FakturMasukanStatus.MATCHED
        assert result.version == 2

    def test_match_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = FIXED_NOW
        with pytest.raises(FakturMasukanLockedError, match="is locked"):
            sample_faktur.match(uuid.uuid4(), uuid.uuid4())

    def test_get_status(self, sample_faktur):
        status = sample_faktur.get_status()
        assert status["status"] == "draft"
        assert not status["is_locked"]
        assert status["is_active"]
        assert not status["is_expired"]
        assert not status["can_approve"]
        assert status["can_cancel"]
        assert not status["can_credit"]
        assert not status["can_post"]
        assert not status["can_reverse"]
        assert not status["can_close"]

    def test_get_history(self, sample_faktur):
        sample_faktur._history.append({"event": "test"})
        history = sample_faktur.get_history()
        assert len(history) == 1

    def test_snapshot(self, sample_faktur):
        snap = sample_faktur.snapshot()
        assert snap["faktur_number"] == sample_faktur.faktur_number
        assert snap["status"] == "draft"
        assert snap["dpp"] == float(sample_faktur.dpp)

    def test_clone(self, sample_faktur):
        cloned = sample_faktur.clone("010.2026.05.00000002")
        assert cloned.faktur_number == "010.2026.05.00000002"
        assert cloned.status == FakturMasukanStatus.DRAFT
        assert cloned.dpp == sample_faktur.dpp
        assert cloned.faktur_id != sample_faktur.faktur_id

    def test_clone_without_new_number(self, sample_faktur):
        cloned = sample_faktur.clone()
        assert cloned.faktur_number == sample_faktur.faktur_number + "_COPY"

    def test_to_dict(self, sample_faktur):
        d = sample_faktur.to_dict()
        assert d["faktur_number"] == sample_faktur.faktur_number
        assert d["status"] == "draft"
        assert not d["is_locked"]

    def test_from_dict(self, sample_faktur_data):
        d = sample_faktur_data.copy()
        d["faktur_id"] = str(uuid.uuid4())
        d["status"] = "pending"
        faktur = FakturMasukan.from_dict(d)
        assert faktur.faktur_number == d["faktur_number"]
        assert faktur.status == FakturMasukanStatus.PENDING
        assert faktur.dpp == d["dpp"]

    def test_audit_trail(self, sample_faktur):
        sample_faktur._history.append({"event": "test"})
        trail = sample_faktur.audit_trail()
        assert len(trail) == 1

    def test_can_transition(self, sample_faktur):
        assert sample_faktur.can_transition(FakturMasukanStatus.PENDING)
        assert not sample_faktur.can_transition(FakturMasukanStatus.APPROVED)
        sample_faktur._status = FakturMasukanStatus.PENDING
        assert sample_faktur.can_transition(FakturMasukanStatus.VALIDATED)

    def test_transition(self, sample_faktur):
        actor_id = uuid.uuid4()
        result = sample_faktur.transition(FakturMasukanStatus.PENDING, actor_id, "test")
        assert result.status == FakturMasukanStatus.PENDING
        assert result.version == 2
        assert len(result._history) == 1
        assert result._history[0]["from_status"] == "draft"
        assert result._history[0]["to_status"] == "pending"

    def test_transition_invalid_raises(self, sample_faktur):
        with pytest.raises(FakturMasukanInvalidStateError, match="Status transition invalid"):
            sample_faktur.transition(FakturMasukanStatus.APPROVED, uuid.uuid4())

    def test_register_event(self, sample_faktur):
        # register_event is a public wrapper around _register_event; we test both
        result = sample_faktur.register_event("test", {"data": "value"})
        events = result.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test"
        # Also verify the private method was called by checking the event structure
        assert events[0]["aggregate_id"] == str(sample_faktur.faktur_id)
        assert events[0]["aggregate_type"] == "FakturMasukan"
        assert "event_id" in events[0]

    def test_clear_events(self, sample_faktur):
        sample_faktur.register_event("test", {})
        result = sample_faktur.clear_events()
        assert len(result.get_events()) == 0

    def test_get_events(self, sample_faktur):
        sample_faktur.register_event("test", {})
        events = sample_faktur.get_events()
        assert len(events) == 1
        # Should return a copy
        events.append({"extra": "event"})
        assert len(sample_faktur.get_events()) == 1

    def test_private__calculate_hash(self, sample_faktur):
        h1 = sample_faktur._hash
        sample_faktur._dpp = Decimal("999")
        sample_faktur._calculate_hash()
        assert sample_faktur._hash != h1

    def test_private__check_expiry(self, sample_faktur):
        sample_faktur._tanggal_faktur = EXPIRED_DATE
        sample_faktur._status = FakturMasukanStatus.PENDING
        with patch("adapters.coretax_djp.faktur_masukan_processor.date") as mock_date:
            mock_date.today.return_value = EXPIRED_DATE + timedelta(days=1)
            assert sample_faktur._check_expiry()
            assert sample_faktur.status == FakturMasukanStatus.EXPIRED


# ============================================================================
# Tests for _FallbackTaxRepository
# ============================================================================

@pytest.mark.asyncio
class TestFallbackTaxRepository:
    async def test_get_faktur_masukan_by_number(self, sample_faktur):
        repo = _FallbackTaxRepository()
        repo._faktur_store[sample_faktur.faktur_id] = sample_faktur
        repo._faktur_by_number[sample_faktur.faktur_number] = sample_faktur.faktur_id
        result = await repo.get_faktur_masukan_by_number(sample_faktur.faktur_number)
        assert result is not None
        assert result["faktur_number"] == sample_faktur.faktur_number

    async def test_get_faktur_masukan_by_number_not_found(self):
        repo = _FallbackTaxRepository()
        result = await repo.get_faktur_masukan_by_number("NONEXISTENT")
        assert result is None

    async def test_get_faktur_masukan_by_id(self, sample_faktur):
        repo = _FallbackTaxRepository()
        repo._faktur_store[sample_faktur.faktur_id] = sample_faktur
        result = await repo.get_faktur_masukan_by_id(sample_faktur.faktur_id)
        assert result is not None
        assert result["faktur_id"] == str(sample_faktur.faktur_id)

    async def test_get_faktur_masukan_by_id_not_found(self):
        repo = _FallbackTaxRepository()
        result = await repo.get_faktur_masukan_by_id(uuid.uuid4())
        assert result is None

    async def test_save_faktur_masukan(self, sample_faktur_data):
        repo = _FallbackTaxRepository()
        faktur_id = await repo.save_faktur_masukan(**sample_faktur_data)
        assert faktur_id is not None
        assert faktur_id in repo._faktur_store
        assert sample_faktur_data["faktur_number"] in repo._faktur_by_number

    async def test_update_faktur_masukan_status(self, sample_faktur):
        repo = _FallbackTaxRepository()
        repo._faktur_store[sample_faktur.faktur_id] = sample_faktur
        await repo.update_faktur_masukan_status(sample_faktur.faktur_id, "pending")
        assert sample_faktur.status == FakturMasukanStatus.PENDING

    async def test_update_faktur_masukan_status_not_found(self):
        repo = _FallbackTaxRepository()
        # Should not raise, and no changes
        await repo.update_faktur_masukan_status(uuid.uuid4(), "pending")
        assert len(repo._faktur_store) == 0

    async def test_find_matching_purchase_transactions(self):
        repo = _FallbackTaxRepository()
        result = await repo.find_matching_purchase_transactions("123", FIXED_DATE, Decimal("1000"))
        assert result == []

    async def test_record_ppn_credit(self, sample_faktur):
        repo = _FallbackTaxRepository()
        repo._faktur_store[sample_faktur.faktur_id] = sample_faktur
        period_id = uuid.uuid4()
        credited_by = uuid.uuid4()
        await repo.record_ppn_credit(sample_faktur.faktur_id, period_id, Decimal("11000000"), credited_by)
        assert sample_faktur.status == FakturMasukanStatus.CREDITED

    async def test_record_ppn_credit_not_found(self):
        repo = _FallbackTaxRepository()
        await repo.record_ppn_credit(uuid.uuid4(), uuid.uuid4(), Decimal("1000"), uuid.uuid4())
        assert len(repo._faktur_store) == 0

    async def test_reverse_ppn_credit(self, sample_faktur):
        repo = _FallbackTaxRepository()
        sample_faktur._status = FakturMasukanStatus.CREDITED
        repo._faktur_store[sample_faktur.faktur_id] = sample_faktur
        await repo.reverse_ppn_credit(sample_faktur.faktur_id, uuid.uuid4(), "test")
        assert sample_faktur.status == FakturMasukanStatus.APPROVED

    async def test_reverse_ppn_credit_not_found(self):
        repo = _FallbackTaxRepository()
        await repo.reverse_ppn_credit(uuid.uuid4(), uuid.uuid4(), "test")
        assert len(repo._faktur_store) == 0

    async def test_get_unprocessed_periods(self):
        repo = _FallbackTaxRepository()
        result = await repo.get_unprocessed_periods("123")
        assert result == []


# ============================================================================
# Tests for FakturMasukanProcessor
# ============================================================================

class TestFakturMasukanProcessorInit:
    def test_load_config_with_config(self):
        config = {"custom": "value"}
        processor = FakturMasukanProcessor(config=config)
        result = processor._load_config()
        assert result == config

    def test_load_config_without_config(self):
        with patch("adapters.coretax_djp.faktur_masukan_processor.FakturMasukanProcessor._init_file_storage"):
            processor = FakturMasukanProcessor(config=None)
            result = processor._load_config()
            assert "coretax_djp" in result
            assert "faktur_masukan" in result["coretax_djp"]
            assert "download_enabled" in result["coretax_djp"]["faktur_masukan"]

    def test_init_file_storage_success(self):
        with patch("adapters.coretax_djp.faktur_masukan_processor.S3FileStorageAdapter") as mock_adapter:
            mock_adapter.return_value = MagicMock()
            processor = FakturMasukanProcessor(config={})
            assert processor._file_storage is not None
            # Verify that the adapter was called with the bucket name from config
            mock_adapter.assert_called_once_with(bucket_name="coretax-faktur-masukan")

    def test_init_file_storage_failure(self, caplog):
        with patch("adapters.coretax_djp.faktur_masukan_processor.S3FileStorageAdapter", side_effect=Exception("Import failed")):
            with caplog.at_level("WARNING"):
                processor = FakturMasukanProcessor(config={})
                assert processor._file_storage is None
                assert "File storage not available" in caplog.text


# ============================================================================
# Tests for FakturMasukanProcessor - Private Methods
# ============================================================================

class TestFakturMasukanProcessorPrivate:
    def test_parse_faktur_xml_valid(self, sample_processor):
        xml_content = """
        <Faktur xmlns="http://www.djp.go.id/efaktur">
            <KepalaFaktur>
                <NomorFaktur>010.2026.05.00000001</NomorFaktur>
                <TanggalFaktur>2026-01-01</TanggalFaktur>
            </KepalaFaktur>
            <Penjual>
                <NPWP>123456789012345</NPWP>
                <Nama>PT Supplier Maju</Nama>
                <Alamat>Jl. Supplier No. 1</Alamat>
            </Penjual>
            <Pembeli>
                <NPWP>987654321098765</NPWP>
            </Pembeli>
            <DetailTransaksi>
                <DPP>100000000</DPP>
                <PPN>11000000</PPN>
                <PPNBM>0</PPNBM>
                <Keterangan>Test</Keterangan>
            </DetailTransaksi>
        </Faktur>
        """
        parsed = sample_processor._parse_faktur_xml(xml_content)
        assert parsed["faktur_number"] == "010.2026.05.00000001"
        assert parsed["tanggal_faktur"] == date(2026, 1, 1)
        assert parsed["npwp_penjual"] == "123456789012345"
        assert parsed["nama_penjual"] == "PT Supplier Maju"
        assert parsed["alamat_penjual"] == "Jl. Supplier No. 1"
        assert parsed["npwp_pembeli"] == "987654321098765"
        assert parsed["dpp"] == Decimal("100000000")
        assert parsed["ppn"] == Decimal("11000000")
        assert parsed["ppn_bm"] == Decimal("0")
        assert parsed["keterangan"] == "Test"

    def test_parse_faktur_xml_missing_kepala(self, sample_processor):
        xml_content = "<Faktur><Penjual/></Faktur>"
        with pytest.raises(ValueError, match="missing KepalaFaktur"):
            sample_processor._parse_faktur_xml(xml_content)

    def test_parse_faktur_xml_invalid_xml(self, sample_processor):
        with pytest.raises(ValueError, match="Invalid XML format"):
            sample_processor._parse_faktur_xml("<invalid>")

    def test_check_expiry_true(self, sample_processor):
        faktur_data = {"tanggal_faktur": EXPIRED_DATE}
        with patch("adapters.coretax_djp.faktur_masukan_processor.date") as mock_date:
            mock_date.today.return_value = EXPIRED_DATE + timedelta(days=1)
            assert sample_processor._check_expiry(faktur_data) is True

    def test_check_expiry_false(self, sample_processor):
        faktur_data = {"tanggal_faktur": FIXED_DATE}
        assert sample_processor._check_expiry(faktur_data) is False

    def test_check_expiry_missing_date(self, sample_processor):
        faktur_data = {}
        assert sample_processor._check_expiry(faktur_data) is False

    def test_legacy_approve_expiry_check_not_expired(self, sample_processor):
        faktur_data = {"tanggal_faktur": FIXED_DATE}
        result = sample_processor.legacy_approve_expiry_check(faktur_data)
        assert result.status == "APPROVED"
        assert result.pengkreditan_allowed is True

    def test_legacy_approve_expiry_check_expired(self, sample_processor):
        faktur_data = {"tanggal_faktur": EXPIRED_DATE}
        with patch("adapters.coretax_djp.faktur_masukan_processor.date") as mock_date:
            mock_date.today.return_value = EXPIRED_DATE + timedelta(days=1)
            with pytest.raises(ValueError, match="melebihi batas waktu 3 bulan"):
                sample_processor.legacy_approve_expiry_check(faktur_data)

    def test_get_cache_key(self, sample_processor):
        key = sample_processor._get_cache_key("010.123.45.00000001")
        assert key == "faktur_masukan:010.123.45.00000001"

    async def test_get_cached(self, sample_processor):
        sample_processor._cache["faktur_masukan:123"] = {"data": "value"}
        result = await sample_processor._get_cached("123")
        assert result == {"data": "value"}

    async def test_get_cached_not_found(self, sample_processor):
        result = await sample_processor._get_cached("nonexistent")
        assert result is None

    async def test_set_cached(self, sample_processor):
        await sample_processor._set_cached("123", {"data": "value"})
        assert sample_processor._cache["faktur_masukan:123"] == {"data": "value"}


# ============================================================================
# Tests for FakturMasukanProcessor - Async Methods (continued)
# ============================================================================

@pytest.mark.asyncio
class TestFakturMasukanProcessorAsync:
    async def test_get_coretax_client(self, sample_processor):
        with patch("adapters.coretax_djp.faktur_masukan_processor.get_coretax_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client
            client = await sample_processor._get_coretax_client()
            assert client is mock_client
            # Second call should return cached
            client2 = await sample_processor._get_coretax_client()
            assert client2 is client
            mock_get.assert_called_once()

    async def test_get_tax_service(self, sample_processor):
        with patch("adapters.coretax_djp.faktur_masukan_processor.application.service_layer.service_tax.TaxService") as mock_tax:
            mock_repo = AsyncMock()
            with patch("adapters.coretax_djp.faktur_masukan_processor.SQLAlchemyTaxRepository", return_value=mock_repo):
                service = await sample_processor._get_tax_service()
                assert service is not None
                mock_tax.assert_called_once_with(mock_repo)

    async def test_get_tax_service_fallback(self, sample_processor):
        with patch("adapters.coretax_djp.faktur_masukan_processor.application.service_layer.service_tax.TaxService") as mock_tax:
            with patch("adapters.coretax_djp.faktur_masukan_processor.SQLAlchemyTaxRepository", side_effect=ImportError):
                service = await sample_processor._get_tax_service()
                assert service is not None
                # Should use fallback repository
                mock_tax.assert_called_once_with(ANY)
                assert isinstance(mock_tax.call_args[0][0], _FallbackTaxRepository)

    # ---- CRUD operations ----
    async def test_create_success(self, sample_processor, sample_faktur_data):
        created_by = uuid.uuid4()
        mock_service = sample_processor._tax_service
        mock_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())

        result = await sample_processor.create(sample_faktur_data, created_by)
        assert result["success"] is True
        assert "faktur_id" in result
        assert result["status"] == "draft"
        mock_service.save_faktur_masukan.assert_called_once()

    async def test_update_success(self, sample_processor, sample_faktur):
        faktur_id = sample_faktur.faktur_id
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.update(faktur_id, {"dpp": "150000000"}, uuid.uuid4())
        assert result["success"] is True
        assert result["status"] == "draft"
        # verify cache updated
        assert sample_processor._cache["faktur_masukan:" + sample_faktur.faktur_number] is not None

    async def test_update_not_found(self, sample_processor):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.update(uuid.uuid4(), {}, uuid.uuid4())
        assert result["success"] is False
        assert result["error"] == "Faktur not found"

    async def test_delete_success(self, sample_processor, sample_faktur):
        faktur_id = sample_faktur.faktur_id
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.delete(faktur_id, uuid.uuid4(), permanent=False)
        assert result["success"] is True
        assert result["status"] == "archived"

    async def test_restore_success(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.ARCHIVED
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.restore(sample_faktur.faktur_id, uuid.uuid4())
        assert result["success"] is True
        assert result["status"] == "draft"

    async def test_activate_success(self, sample_processor, sample_faktur):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.activate(sample_faktur.faktur_id, uuid.uuid4())
        assert result["success"] is True
        assert result["status"] == "pending"

    # ---- Validation and approval ----
    async def test_validate_faktur_success(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.validate_faktur(sample_faktur.faktur_id, uuid.uuid4())
        assert result["success"] is True
        assert result["valid"] is True
        assert result["status"] == "validated"

    async def test_validate_faktur_expired(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        sample_faktur._tanggal_faktur = EXPIRED_DATE
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        with patch("adapters.coretax_djp.faktur_masukan_processor.date") as mock_date:
            mock_date.today.return_value = EXPIRED_DATE + timedelta(days=1)
            result = await sample_processor.validate_faktur(sample_faktur.faktur_id, uuid.uuid4())
            assert result["success"] is False
            assert result["error"] is not None
            assert result["status"] == "expired"
            mock_service.update_faktur_masukan_status.assert_called_with(sample_faktur.faktur_id, "expired")

    async def test_approve_success(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.VALIDATED
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        with patch.object(sample_processor, 'credit_ppn_masukan', new_callable=AsyncMock) as mock_credit:
            result = await sample_processor.approve(sample_faktur.faktur_id, uuid.uuid4(), "ok")
            assert result["success"] is True
            assert result["status"] == "approved"
            # auto_credit disabled by default, so credit not called
            mock_credit.assert_not_called()

    async def test_approve_with_auto_credit(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.VALIDATED
        # Enable auto_credit in config
        sample_processor._config = {"coretax_djp": {"faktur_masukan": {"auto_credit": True}}}
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        with patch.object(sample_processor, 'credit_ppn_masukan', new_callable=AsyncMock) as mock_credit:
            mock_credit.return_value = {"success": True}
            result = await sample_processor.approve(sample_faktur.faktur_id, uuid.uuid4(), "ok")
            assert result["success"] is True
            assert result["status"] == "approved"
            mock_credit.assert_called_once_with(sample_faktur.faktur_id, None, ANY)

    async def test_reject_success(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.PENDING
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.reject(sample_faktur.faktur_id, uuid.uuid4(), "bad")
        assert result["success"] is True
        assert result["status"] == "rejected"
        assert result["rejection_reason"] == "bad"

    async def test_cancel_success(self, sample_processor, sample_faktur):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()
        client = sample_processor._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})

        result = await sample_processor.cancel(sample_faktur.faktur_id, uuid.uuid4(), "test")
        assert result["success"] is True
        assert result["status"] == "cancelled"
        client.post.assert_called_once_with(CORETAX_PM_CANCEL_ENDPOINT, ANY)

    # ---- Credit operations ----
    async def test_credit_ppn_masukan_success(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()
        mock_service.record_ppn_credit = AsyncMock()
        client = sample_processor._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})

        period_id = uuid.uuid4()
        result = await sample_processor.credit_ppn_masukan(sample_faktur.faktur_id, period_id, uuid.uuid4())
        assert result["success"] is True
        assert result["status"] == "credited"
        client.post.assert_called_once_with(CORETAX_PM_CREDIT_ENDPOINT, ANY)
        mock_service.record_ppn_credit.assert_called_once()

    async def test_credit_ppn_masukan_invalid_status(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.DRAFT
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())

        result = await sample_processor.credit_ppn_masukan(sample_faktur.faktur_id, uuid.uuid4(), uuid.uuid4())
        assert result["success"] is False
        assert "Faktur status must be APPROVED or POSTED" in result["error"]

    # ---- Download and sync ----
    async def test_download_faktur_masukan(self, sample_processor):
        client = sample_processor._coretax_client
        client.get = AsyncMock(return_value={"data": [{"nomor_faktur": "010.123.45.00000001"}]})
        with patch.object(sample_processor, '_download_detail_faktur', new_callable=AsyncMock) as mock_detail:
            mock_detail.return_value = {"faktur_number": "010.123.45.00000001", "data": "value"}
            result = await sample_processor.download_faktur_masukan("123", 5, 2026)
            assert len(result) == 1
            assert result[0]["faktur_number"] == "010.123.45.00000001"
            # Cache is used
            sample_processor._cache["faktur_masukan:010.123.45.00000001"] = {"cached": True}
            result2 = await sample_processor.download_faktur_masukan("123", 5, 2026)
            assert result2[0]["cached"] is True
            mock_detail.assert_called_once()

    async def test_download_faktur_masukan_retry(self, sample_processor):
        client = sample_processor._coretax_client
        client.get = AsyncMock(side_effect=Exception("Network error"))
        result = await sample_processor.download_faktur_masukan("123", 5, 2026)
        assert result == []
        assert client.get.call_count == 3  # MAX_RETRY_ATTEMPTS

    async def test_download_detail_faktur(self, sample_processor):
        client = sample_processor._coretax_client
        xml_b64 = base64.b64encode(b"<Faktur><KepalaFaktur><NomorFaktur>010.123.45.00000001</NomorFaktur><TanggalFaktur>2026-01-01</TanggalFaktur></KepalaFaktur><Penjual><NPWP>123</NPWP><Nama>N</Nama></Penjual><DetailTransaksi><DPP>1000</DPP><PPN>110</PPN></DetailTransaksi></Faktur>").decode()
        client.get = AsyncMock(return_value={"faktur_xml": xml_b64})
        storage = sample_processor._file_storage
        storage.upload = AsyncMock()

        result = await sample_processor._download_detail_faktur("123", "010.123.45.00000001")
        assert result is not None
        assert result["faktur_number"] == "010.123.45.00000001"
        assert result["stored_uri"] is not None
        storage.upload.assert_called_once()

    async def test_import_faktur_from_upload(self, sample_processor, sample_faktur_data):
        xml_content = """
        <Faktur>
            <KepalaFaktur>
                <NomorFaktur>010.2026.05.00000001</NomorFaktur>
                <TanggalFaktur>2026-01-01</TanggalFaktur>
            </KepalaFaktur>
            <Penjual><NPWP>123456789012345</NPWP><Nama>PT Supplier Maju</Nama></Penjual>
            <Pembeli><NPWP>987654321098765</NPWP></Pembeli>
            <DetailTransaksi><DPP>100000000</DPP><PPN>11000000</PPN></DetailTransaksi>
        </Faktur>
        """
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_number = AsyncMock(return_value=None)
        mock_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())
        storage = sample_processor._file_storage
        storage.upload = AsyncMock()

        result = await sample_processor.import_faktur_from_upload(xml_content, uuid.uuid4())
        assert result["success"] is True
        assert result["status"] == "pending"
        mock_service.save_faktur_masukan.assert_called_once()
        storage.upload.assert_called_once()

    async def test_import_faktur_from_upload_already_exists(self, sample_processor):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_number = AsyncMock(return_value={"faktur_number": "010.2026.05.00000001"})
        result = await sample_processor.import_faktur_from_upload("<xml/>", uuid.uuid4())
        assert result["success"] is False
        assert "Faktur already exists" in result["error"]

    async def test_sync_faktur_masukan_periodic(self, sample_processor):
        mock_service = sample_processor._tax_service
        mock_service.get_unprocessed_periods = AsyncMock(return_value=[{"month": 1, "year": 2026}])
        with patch.object(sample_processor, 'download_faktur_masukan', new_callable=AsyncMock) as mock_download:
            mock_download.return_value = [{"faktur_number": "010.123.45.00000001", "npwp_penjual": "123", "nama_penjual": "N", "tanggal_faktur": FIXED_DATE, "dpp": Decimal("1000"), "ppn": Decimal("110")}]
            mock_service.get_faktur_masukan_by_number = AsyncMock(return_value=None)
            mock_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())

            result = await sample_processor.sync_faktur_masukan_periodic("123")
            assert result["synced_count"] == 1
            assert "010.123.45.00000001" in result["faktur_numbers"]
            mock_service.save_faktur_masukan.assert_called_once()

    # ---- Other processor methods ----
    async def test_reverse_credit(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.CREDITED
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()
        mock_service.reverse_ppn_credit = AsyncMock()
        client = sample_processor._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})

        result = await sample_processor.reverse_credit(sample_faktur.faktur_id, uuid.uuid4(), "test")
        assert result["success"] is True
        assert result["status"] == "approved"
        client.post.assert_called_once_with(CORETAX_PM_CANCEL_ENDPOINT, ANY)

    async def test_post_and_unpost(self, sample_processor, sample_faktur):
        sample_faktur._status = FakturMasukanStatus.APPROVED
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.post(sample_faktur.faktur_id, uuid.uuid4())
        assert result["success"] is True
        assert result["status"] == "posted"

        result = await sample_processor.unpost(sample_faktur.faktur_id, uuid.uuid4())
        assert result["success"] is True
        assert result["status"] == "approved"

    async def test_get_history(self, sample_processor, sample_faktur):
        sample_faktur._history = [{"event": "test"}]
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())

        result = await sample_processor.get_history(sample_faktur.faktur_id)
        assert result["success"] is True
        assert len(result["history"]) == 1

    async def test_snapshot(self, sample_processor, sample_faktur):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())

        result = await sample_processor.snapshot(sample_faktur.faktur_id)
        assert result["faktur_id"] == str(sample_faktur.faktur_id)
        assert result["status"] == "draft"

    async def test_clone_faktur(self, sample_processor, sample_faktur):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())

        result = await sample_processor.clone_faktur(sample_faktur.faktur_id, "NEW", uuid.uuid4())
        assert result["success"] is True
        assert result["new_faktur_number"] == "NEW"

    async def test_can_transition(self, sample_processor, sample_faktur):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())

        result = await sample_processor.can_transition(sample_faktur.faktur_id, "pending")
        assert result["success"] is True
        assert result["can_transition"] is True

    async def test_transition(self, sample_processor, sample_faktur):
        mock_service = sample_processor._tax_service
        mock_service.get_faktur_masukan_by_id = AsyncMock(return_value=sample_faktur.to_dict())
        mock_service.update_faktur_masukan_status = AsyncMock()

        result = await sample_processor.transition(sample_faktur.faktur_id, "pending", uuid.uuid4())
        assert result["success"] is True
        assert result["to_status"] == "pending"

    # ---- Singleton ----
    async def test_get_faktur_masukan_processor(self):
        with patch("adapters.coretax_djp.faktur_masukan_processor._processor", None):
            with patch("adapters.coretax_djp.faktur_masukan_processor.FakturMasukanProcessor") as mock_cls:
                mock_cls.return_value = MagicMock()
                processor = await get_faktur_masukan_processor(config={"a": 1})
                mock_cls.assert_called_once_with(config={"a": 1})
                assert processor is not None
                # Second call returns cached
                processor2 = await get_faktur_masukan_processor()
                assert processor2 is processor
                mock_cls.assert_called_once()
