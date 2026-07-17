#!/usr/bin/env python3
"""
tests/unit/test_faktur_masukan_processor.py
Test untuk adapters/coretax_djp/faktur_masukan_processor.py
Mencakup semua kelas dan metode secara exhaustive dengan mocking.
"""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.coretax_djp.faktur_masukan_processor import (
    CORETAX_PM_CANCEL_ENDPOINT,
    CORETAX_PM_CREDIT_ENDPOINT,
    CORETAX_PM_DETAIL_ENDPOINT,
    CORETAX_PM_DOWNLOAD_ENDPOINT,
    CORETAX_PM_LIST_ENDPOINT,
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
    FakturMasukanRepositoryPort,
    FakturMasukanStatus,
    FakturMasukanValidationError,
    _FallbackTaxRepository,
    get_faktur_masukan_processor,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_faktur_data() -> dict:
    return {
        "faktur_number": "010.2026.05.00000001",
        "npwp_penjual": "123456789012345",
        "nama_penjual": "PT Supplier Maju",
        "tanggal_faktur": date(2026, 5, 1),
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
        sample_faktur._tanggal_faktur = date.today() - timedelta(days=EXPIRY_DAYS + 1)
        assert sample_faktur.is_expired
        sample_faktur._status = FakturMasukanStatus.CANCELLED
        assert not sample_faktur.is_expired  # cancelled not expired

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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
        with pytest.raises(FakturMasukanLockedError, match="already locked"):
            sample_faktur.lock(uuid.uuid4(), "test")

    def test_unlock(self, sample_faktur):
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._tanggal_faktur = date.today() - timedelta(days=EXPIRY_DAYS + 1)
        with pytest.raises(FakturMasukanExpiredError, match="has expired"):
            sample_faktur.validate(uuid.uuid4())
        assert sample_faktur.status == FakturMasukanStatus.EXPIRED

    def test_validate_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._tanggal_faktur = date.today() - timedelta(days=EXPIRY_DAYS + 1)
        with pytest.raises(FakturMasukanExpiredError, match="has expired"):
            sample_faktur.approve(uuid.uuid4())
        assert sample_faktur.status == FakturMasukanStatus.EXPIRED

    def test_approve_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._credited_at = datetime.now()
        reversed_by = uuid.uuid4()
        result = sample_faktur.reverse_credit(reversed_by, "test")
        assert result.status == FakturMasukanStatus.APPROVED
        assert result.period_id is None
        assert result.credit_amount == Decimal(0)
        assert result.credited_at is None
        assert result.version == 2

    def test_reverse_credit_locked_raises(self, sample_faktur):
        sample_faktur._locked_at = datetime.now()
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
        sample_faktur._locked_at = datetime.now()
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
        result = sample_faktur.register_event("test", {"data": "value"})
        events = result.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test"

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
        sample_faktur._tanggal_faktur = date.today() - timedelta(days=EXPIRY_DAYS + 1)
        sample_faktur._status = FakturMasukanStatus.PENDING
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
        # Should not raise
        await repo.update_faktur_masukan_status(uuid.uuid4(), "pending")

    async def test_find_matching_purchase_transactions(self):
        repo = _FallbackTaxRepository()
        result = await repo.find_matching_purchase_transactions("123", date.today(), Decimal("1000"))
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
        # Should not raise
        await repo.record_ppn_credit(uuid.uuid4(), uuid.uuid4(), Decimal("1000"), uuid.uuid4())

    async def test_reverse_ppn_credit(self, sample_faktur):
        repo = _FallbackTaxRepository()
        sample_faktur._status = FakturMasukanStatus.CREDITED
        repo._faktur_store[sample_faktur.faktur_id] = sample_faktur
        await repo.reverse_ppn_credit(sample_faktur.faktur_id, uuid.uuid4(), "test")
        assert sample_faktur.status == FakturMasukanStatus.APPROVED

    async def test_reverse_ppn_credit_not_found(self):
        repo = _FallbackTaxRepository()
        # Should not raise
        await repo.reverse_ppn_credit(uuid.uuid4(), uuid.uuid4(), "test")

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

    def test_init_file_storage_failure(self, caplog):
        with patch("adapters.coretax_djp.faktur_masukan_processor.S3FileStorageAdapter", side_effect=Exception("Import failed")):
            with caplog.at_level("WARNING"):
                processor = FakturMasukanProcessor(config={})
                assert processor._file_storage is None
                assert "File storage not available" in caplog.text


@pytest.mark.asyncio
class TestFakturMasukanProcessorAsync:
    async def test_get_coretax_client(self, sample_processor):
        with patch("adapters.coretax_djp.faktur_masukan_processor.get_coretax_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client
            client1 = await sample_processor._get_coretax_client()
            assert client1 is mock_client
            mock_get.assert_called_once()
            client2 = await sample_processor._get_coretax_client()
            assert client2 is client1
            assert mock_get.call_count == 1

    async def test_get_tax_service(self, sample_processor):
        with patch("adapters.coretax_djp.faktur_masukan_processor.TaxService") as mock_tax:
            mock_tax.return_value = AsyncMock()
            svc1 = await sample_processor._get_tax_service()
            assert svc1 is not None
            mock_tax.assert_called_once()
            svc2 = await sample_processor._get_tax_service()
            assert svc2 is svc1
            assert mock_tax.call_count == 1

    async def test_get_tax_service_fallback(self, sample_processor):
        with patch("adapters.coretax_djp.faktur_masukan_processor.TaxService", side_effect=ImportError):
            svc = await sample_processor._get_tax_service()
            assert svc is not None

    def test_get_cache_key(self, sample_processor):
        key = sample_processor._get_cache_key("FK-001")
        assert key == "faktur_masukan:FK-001"

    async def test_get_cached(self, sample_processor):
        sample_processor._cache["faktur_masukan:FK-001"] = {"data": "value"}
        result = await sample_processor._get_cached("FK-001")
        assert result == {"data": "value"}

    async def test_get_cached_missing(self, sample_processor):
        result = await sample_processor._get_cached("MISSING")
        assert result is None

    async def test_set_cached(self, sample_processor):
        await sample_processor._set_cached("FK-001", {"data": "value"})
        assert sample_processor._cache["faktur_masukan:FK-001"] == {"data": "value"}

    def test_parse_faktur_xml_valid(self, sample_processor):
        xml = """
        <Faktur>
            <KepalaFaktur>
                <NomorFaktur>010.2026.05.00000001</NomorFaktur>
                <TanggalFaktur>2026-05-01</TanggalFaktur>
            </KepalaFaktur>
            <Penjual>
                <NPWP>123456789012345</NPWP>
                <Nama>PT Supplier</Nama>
                <Alamat>Jl. Supplier</Alamat>
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
        result = sample_processor._parse_faktur_xml(xml)
        assert result["faktur_number"] == "010.2026.05.00000001"
        assert result["npwp_penjual"] == "123456789012345"
        assert result["nama_penjual"] == "PT Supplier"
        assert result["dpp"] == Decimal("100000000")
        assert result["ppn"] == Decimal("11000000")

    def test_parse_faktur_xml_invalid(self, sample_processor):
        with pytest.raises(ValueError, match="Invalid faktur XML"):
            sample_processor._parse_faktur_xml("<invalid></invalid>")

    def test_parse_faktur_xml_missing_kepala(self, sample_processor):
        with pytest.raises(ValueError, match="missing KepalaFaktur"):
            sample_processor._parse_faktur_xml("<Faktur></Faktur>")

    def test_parse_faktur_xml_parse_error(self, sample_processor):
        with pytest.raises(ValueError, match="Invalid XML format"):
            sample_processor._parse_faktur_xml("not xml")

    async def test_create(self, sample_processor, sample_faktur_data):
        tax_service = sample_processor._tax_service
        tax_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())
        result = await sample_processor.create(sample_faktur_data, uuid.uuid4())
        assert result["success"]
        assert "faktur_id" in result
        assert result["faktur_number"] == sample_faktur_data["faktur_number"]

    async def test_update_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        sample_processor._set_cached = AsyncMock()
        result = await sample_processor.update(faktur_id, {"keterangan": "Updated"}, uuid.uuid4())
        assert result["success"]
        assert result["faktur_id"] == str(faktur_id)

    async def test_update_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.update(uuid.uuid4(), {}, uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_delete_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.delete(faktur_id, uuid.uuid4(), permanent=False)
        assert result["success"]

    async def test_delete_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.delete(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_restore_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "archived"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.restore(faktur_id, uuid.uuid4())
        assert result["success"]

    async def test_restore_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.restore(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]

    async def test_validate_faktur_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "pending"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.validate_faktur(faktur_id, uuid.uuid4())
        assert result["success"]
        assert result["valid"]

    async def test_validate_faktur_expired(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={
            "faktur_id": str(faktur_id),
            "faktur_number": "FK-001",
            "status": "pending",
            "tanggal_faktur": (date.today() - timedelta(days=EXPIRY_DAYS + 1)).isoformat(),
        })
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.validate_faktur(faktur_id, uuid.uuid4())
        assert not result["success"]
        assert "expired" in result["error"]
        assert result["status"] == "expired"

    async def test_approve_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "validated"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        sample_processor._load_config = MagicMock(return_value={"coretax_djp": {"faktur_masukan": {"auto_credit": False}}})
        result = await sample_processor.approve(faktur_id, uuid.uuid4(), "Approved")
        assert result["success"]
        assert result["approved"]

    async def test_approve_with_auto_credit(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "validated"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        sample_processor._load_config = MagicMock(return_value={"coretax_djp": {"faktur_masukan": {"auto_credit": True}}})
        sample_processor.credit_ppn_masukan = AsyncMock(return_value={"success": True})
        result = await sample_processor.approve(faktur_id, uuid.uuid4(), "Approved")
        assert result["success"]
        sample_processor.credit_ppn_masukan.assert_called_once()

    async def test_approve_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.approve(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]

    async def test_reject_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "pending"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.reject(faktur_id, uuid.uuid4(), "Invalid")
        assert result["success"]
        assert result["rejection_reason"] == "Invalid"

    async def test_cancel_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "pending"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        client = sample_processor._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})
        result = await sample_processor.cancel(faktur_id, uuid.uuid4(), "test")
        assert result["success"]
        assert result["cancelled"]
        client.post.assert_called_once_with(CORETAX_PM_CANCEL_ENDPOINT, {"faktur_number": "FK-001", "npwp": "", "reason": "test"})

    async def test_cancel_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.cancel(uuid.uuid4(), uuid.uuid4(), "test")
        assert not result["success"]

    async def test_void_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "pending"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.void(faktur_id, uuid.uuid4(), "test")
        assert result["success"]
        assert result["voided"]

    async def test_post_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "approved"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.post(faktur_id, uuid.uuid4())
        assert result["success"]
        assert result["posted"]

    async def test_unpost_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "posted"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.unpost(faktur_id, uuid.uuid4())
        assert result["success"]
        assert not result["posted"]

    async def test_reverse_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "credited"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.reverse(faktur_id, uuid.uuid4(), "test")
        assert result["success"]
        assert result["reversed"]

    async def test_close_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "posted"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.close(faktur_id, uuid.uuid4())
        assert result["success"]
        assert result["closed"]

    async def test_reopen_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "closed"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.reopen(faktur_id, uuid.uuid4())
        assert result["success"]
        assert not result["closed"]

    async def test_archive_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "closed"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.archive(faktur_id, uuid.uuid4())
        assert result["success"]
        assert result["archived"]

    async def test_unarchive_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "archived"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.unarchive(faktur_id, uuid.uuid4())
        assert result["success"]
        assert not result["archived"]

    async def test_sync_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "npwp_pembeli": "123"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        client = sample_processor._coretax_client
        client.get = AsyncMock(return_value={"status": "success", "dpp": "150000000", "ppn": "16500000"})
        result = await sample_processor.sync(faktur_id, uuid.uuid4())
        assert result["success"]
        assert result["synced"]

    async def test_sync_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.sync(uuid.uuid4(), uuid.uuid4())
        assert not result["success"]

    async def test_sync_coretax_error(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "npwp_pembeli": "123"})
        client = sample_processor._coretax_client
        client.get = AsyncMock(return_value={"status": "error", "message": "Failed"})
        result = await sample_processor.sync(faktur_id, uuid.uuid4())
        assert not result["success"]
        assert "Failed" in result["error"]

    async def test_download_faktur_masukan_success(self, sample_processor):
        npwp = "123456789012345"
        tahun = 2026
        bulan = 5
        client = sample_processor._coretax_client
        client.get = AsyncMock(return_value={"data": [{"nomor_faktur": "FK-001"}]})
        sample_processor._download_detail_faktur = AsyncMock(return_value={"faktur_number": "FK-001", "dpp": 100000000})
        sample_processor._get_cached = AsyncMock(return_value=None)
        sample_processor._set_cached = AsyncMock()
        results = await sample_processor.download_faktur_masukan(npwp, bulan, tahun)
        assert len(results) == 1
        assert results[0]["faktur_number"] == "FK-001"

    async def test_download_faktur_masukan_with_cache(self, sample_processor):
        npwp = "123"
        tahun = 2026
        bulan = 5
        client = sample_processor._coretax_client
        client.get = AsyncMock(return_value={"data": [{"nomor_faktur": "FK-001"}]})
        sample_processor._get_cached = AsyncMock(return_value={"faktur_number": "FK-001", "cached": True})
        results = await sample_processor.download_faktur_masukan(npwp, bulan, tahun)
        assert len(results) == 1
        assert results[0]["cached"]

    async def test_download_faktur_masukan_auth_error(self, sample_processor):
        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        npwp = "123"
        tahun = 2026
        bulan = 5
        client = sample_processor._coretax_client
        client.get = AsyncMock(side_effect=CoretaxAuthError("Auth failed"))
        results = await sample_processor.download_faktur_masukan(npwp, bulan, tahun)
        assert results == []

    async def test_download_faktur_masukan_generic_error(self, sample_processor):
        npwp = "123"
        tahun = 2026
        bulan = 5
        client = sample_processor._coretax_client
        client.get = AsyncMock(side_effect=Exception("Network error"))
        results = await sample_processor.download_faktur_masukan(npwp, bulan, tahun)
        assert results == []

    async def test__download_detail_faktur_success(self, sample_processor):
        npwp = "123"
        faktur_number = "FK-001"
        client = sample_processor._coretax_client
        xml_content = "<Faktur><KepalaFaktur><NomorFaktur>FK-001</NomorFaktur></KepalaFaktur></Faktur>"
        xml_b64 = base64.b64encode(xml_content.encode()).decode()
        client.get = AsyncMock(return_value={"faktur_xml": xml_b64})
        result = await sample_processor._download_detail_faktur(npwp, faktur_number)
        assert result is not None
        assert result["faktur_number"] == "FK-001"
        assert "raw_xml" in result

    async def test__download_detail_faktur_no_xml(self, sample_processor):
        npwp = "123"
        faktur_number = "FK-001"
        client = sample_processor._coretax_client
        client.get = AsyncMock(return_value={})
        result = await sample_processor._download_detail_faktur(npwp, faktur_number)
        assert result is None

    async def test__download_detail_faktur_with_storage(self, sample_processor):
        npwp = "123"
        faktur_number = "FK-001"
        sample_processor._file_storage = AsyncMock()
        sample_processor._file_storage.upload = AsyncMock()
        client = sample_processor._coretax_client
        xml_content = "<Faktur><KepalaFaktur><NomorFaktur>FK-001</NomorFaktur></KepalaFaktur></Faktur>"
        xml_b64 = base64.b64encode(xml_content.encode()).decode()
        client.get = AsyncMock(return_value={"faktur_xml": xml_b64})
        result = await sample_processor._download_detail_faktur(npwp, faktur_number)
        assert result is not None
        assert "stored_uri" in result
        sample_processor._file_storage.upload.assert_called_once()

    async def test__download_detail_faktur_error(self, sample_processor):
        npwp = "123"
        faktur_number = "FK-001"
        client = sample_processor._coretax_client
        client.get = AsyncMock(side_effect=Exception("Error"))
        result = await sample_processor._download_detail_faktur(npwp, faktur_number)
        assert result is None

    async def test_import_faktur_from_upload_success(self, sample_processor):
        xml = """
        <Faktur>
            <KepalaFaktur>
                <NomorFaktur>010.2026.05.00000001</NomorFaktur>
                <TanggalFaktur>2026-05-01</TanggalFaktur>
            </KepalaFaktur>
            <Penjual>
                <NPWP>123456789012345</NPWP>
                <Nama>PT Supplier</Nama>
            </Penjual>
            <Pembeli>
                <NPWP>987654321098765</NPWP>
            </Pembeli>
            <DetailTransaksi>
                <DPP>100000000</DPP>
                <PPN>11000000</PPN>
            </DetailTransaksi>
        </Faktur>
        """
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_number = AsyncMock(return_value=None)
        tax_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())
        result = await sample_processor.import_faktur_from_upload(xml, uuid.uuid4())
        assert result["success"]
        assert result["faktur_number"] == "010.2026.05.00000001"

    async def test_import_faktur_from_upload_already_exists(self, sample_processor):
        xml = "<Faktur><KepalaFaktur><NomorFaktur>FK-001</NomorFaktur></KepalaFaktur></Faktur>"
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_number = AsyncMock(return_value={"faktur_number": "FK-001"})
        result = await sample_processor.import_faktur_from_upload(xml, uuid.uuid4())
        assert not result["success"]
        assert "already exists" in result["error"]

    async def test_import_faktur_from_upload_parse_error(self, sample_processor):
        result = await sample_processor.import_faktur_from_upload("invalid", uuid.uuid4())
        assert not result["success"]

    async def test_credit_ppn_masukan_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        period_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "npwp_pembeli": "123", "status": "approved"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        tax_service.record_ppn_credit = AsyncMock()
        client = sample_processor._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})
        result = await sample_processor.credit_ppn_masukan(faktur_id, period_id, uuid.uuid4())
        assert result["success"]
        assert result["status"] == "credited"
        client.post.assert_called_once_with(CORETAX_PM_CREDIT_ENDPOINT, {"faktur_number": "FK-001", "npwp": "123", "period_id": str(period_id), "amount": 0.0})

    async def test_credit_ppn_masukan_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.credit_ppn_masukan(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "not found" in result["error"]

    async def test_credit_ppn_masukan_invalid_status(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.credit_ppn_masukan(faktur_id, uuid.uuid4(), uuid.uuid4())
        assert not result["success"]
        assert "status must be APPROVED" in result["error"]

    async def test_credit_ppn_masukan_coretax_error(self, sample_processor):
        faktur_id = uuid.uuid4()
        period_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "npwp_pembeli": "123", "status": "approved"})
        client = sample_processor._coretax_client
        client.post = AsyncMock(return_value={"status": "error", "message": "Coretax error"})
        result = await sample_processor.credit_ppn_masukan(faktur_id, period_id, uuid.uuid4())
        assert not result["success"]
        assert "Coretax error" in result["error"]

    async def test_reverse_credit_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "npwp_pembeli": "123", "status": "credited"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        tax_service.reverse_ppn_credit = AsyncMock()
        client = sample_processor._coretax_client
        client.post = AsyncMock(return_value={"status": "success"})
        result = await sample_processor.reverse_credit(faktur_id, uuid.uuid4(), "test")
        assert result["success"]
        assert result["status"] == "approved"

    async def test_reverse_credit_not_found(self, sample_processor):
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value=None)
        result = await sample_processor.reverse_credit(uuid.uuid4(), uuid.uuid4(), "test")
        assert not result["success"]

    async def test_reverse_credit_invalid_status(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.reverse_credit(faktur_id, uuid.uuid4(), "test")
        assert not result["success"]
        assert "not in CREDITED status" in result["error"]

    async def test_match_faktur_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        transaction_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "validated"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.match_faktur(faktur_id, transaction_id, uuid.uuid4())
        assert result["success"]
        assert result["matched_transaction_id"] == str(transaction_id)

    async def test_calculate_faktur_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "dpp": 100000000, "ppn": 11000000})
        result = await sample_processor.calculate_faktur(faktur_id)
        assert result["success"]
        assert result["dpp"] == 100000000
        assert result["ppn"] == 11000000

    async def test_recalculate_faktur_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "dpp": 100000000, "ppn": 0})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.recalculate_faktur(faktur_id, uuid.uuid4())
        assert result["success"]
        expected_ppn = (Decimal("100000000") * DEFAULT_PPN_RATE).quantize(Decimal("0.01"))
        assert result["ppn"] == float(expected_ppn)

    async def test_get_status_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.get_status(faktur_id)
        assert result["success"]
        assert result["status"] == "draft"

    async def test_get_history_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.get_history(faktur_id)
        assert result["success"]
        assert "history" in result

    async def test_snapshot_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft", "dpp": 100000000})
        result = await sample_processor.snapshot(faktur_id)
        assert result["success"]
        assert result["faktur_number"] == "FK-001"

    async def test_clone_faktur_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        new_faktur_number = "FK-002"
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft", "dpp": 100000000, "ppn": 11000000})
        tax_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())
        result = await sample_processor.clone_faktur(faktur_id, new_faktur_number, uuid.uuid4())
        assert result["success"]
        assert result["new_faktur_number"] == new_faktur_number

    async def test_to_dict_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001"})
        result = await sample_processor.to_dict(faktur_id)
        assert result["success"]
        assert result["faktur_number"] == "FK-001"

    async def test_audit_trail_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.audit_trail(faktur_id)
        assert result["success"]
        assert "audit_trail" in result

    async def test_can_transition_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.can_transition(faktur_id, "pending")
        assert result["success"]
        assert result["can_transition"]

    async def test_transition_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.transition(faktur_id, "pending", uuid.uuid4(), "test")
        assert result["success"]
        assert result["to_status"] == "pending"

    async def test_transition_invalid_raises(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.transition(faktur_id, "approved", uuid.uuid4())
        assert not result["success"]
        assert "invalid" in result["error"].lower()

    async def test_register_event_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.register_event(faktur_id, "test", {"data": "value"})
        assert result["success"]
        assert len(result["events"]) == 1

    async def test_get_events_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.get_events(faktur_id)
        assert result["success"]
        assert "events" in result

    async def test_clear_events_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        result = await sample_processor.clear_events(faktur_id)
        assert result["success"]
        assert result["events_cleared"]

    async def test_version_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft", "version": 5})
        result = await sample_processor.version(faktur_id)
        assert result["success"]
        assert result["version"] == 5

    async def test_lock_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "pending"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.lock(faktur_id, uuid.uuid4(), "test")
        assert result["success"]
        assert result["locked"]

    async def test_unlock_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "locked"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.unlock(faktur_id, uuid.uuid4())
        assert result["success"]
        assert not result["locked"]

    async def test_activate_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "draft"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.activate(faktur_id, uuid.uuid4())
        assert result["success"]
        assert result["status"] == "pending"

    async def test_deactivate_success(self, sample_processor):
        faktur_id = uuid.uuid4()
        tax_service = sample_processor._tax_service
        tax_service.get_faktur_masukan_by_id = AsyncMock(return_value={"faktur_id": str(faktur_id), "faktur_number": "FK-001", "status": "pending"})
        tax_service.update_faktur_masukan_status = AsyncMock()
        result = await sample_processor.deactivate(faktur_id, uuid.uuid4())
        assert result["success"]
        assert result["status"] == "draft"

    async def test_sync_faktur_masukan_periodic_success(self, sample_processor):
        npwp = "123456789012345"
        tax_service = sample_processor._tax_service
        tax_service.get_unprocessed_periods = AsyncMock(return_value=[{"month": 5, "year": 2026}])
        sample_processor.download_faktur_masukan = AsyncMock(return_value=[{"faktur_number": "FK-001", "npwp_penjual": "123", "nama_penjual": "Supplier", "tanggal_faktur": date.today(), "dpp": 100000000, "ppn": 11000000}])
        tax_service.get_faktur_masukan_by_number = AsyncMock(return_value=None)
        tax_service.save_faktur_masukan = AsyncMock(return_value=uuid.uuid4())
        result = await sample_processor.sync_faktur_masukan_periodic(npwp)
        assert result["synced_count"] == 1
        assert "FK-001" in result["faktur_numbers"]

    async def test_sync_faktur_masukan_periodic_with_existing(self, sample_processor):
        npwp = "123"
        tax_service = sample_processor._tax_service
        tax_service.get_unprocessed_periods = AsyncMock(return_value=[{"month": 5, "year": 2026}])
        sample_processor.download_faktur_masukan = AsyncMock(return_value=[{"faktur_number": "FK-001"}])
        tax_service.get_faktur_masukan_by_number = AsyncMock(return_value={"faktur_number": "FK-001"})
        result = await sample_processor.sync_faktur_masukan_periodic(npwp)
        assert result["synced_count"] == 0

    def test__check_expiry(self, sample_processor):
        data = {"tanggal_faktur": date.today() - timedelta(days=EXPIRY_DAYS + 1)}
        assert sample_processor._check_expiry(data)
        data = {"tanggal_faktur": date.today()}
        assert not sample_processor._check_expiry(data)
        data = {}
        assert not sample_processor._check_expiry(data)

    def test_legacy_approve_expiry_check(self, sample_processor):
        data = {"tanggal_faktur": date.today()}
        result = sample_processor.legacy_approve_expiry_check(data)
        assert result.status == "APPROVED"
        assert result.pengkreditan_allowed
        data = {"tanggal_faktur": date.today() - timedelta(days=EXPIRY_DAYS + 1)}
        with pytest.raises(ValueError, match="batas waktu 3 bulan"):
            sample_processor.legacy_approve_expiry_check(data)


# ============================================================================
# Tests for Singleton get_faktur_masukan_processor
# ============================================================================

@pytest.mark.asyncio
async def test_get_faktur_masukan_processor_singleton():
    with patch("adapters.coretax_djp.faktur_masukan_processor.FakturMasukanProcessor") as MockProcessor:
        MockProcessor.return_value = MagicMock()
        proc1 = await get_faktur_masukan_processor()
        proc2 = await get_faktur_masukan_processor()
        assert proc1 is proc2
        assert MockProcessor.call_count == 1