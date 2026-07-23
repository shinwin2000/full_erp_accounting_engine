# adapters/coretax_djp/test_e_bupot_generator.py
"""
Comprehensive unit tests for e-Bupot Generator.

Covers:
- All EBupot properties (getters)
- EBupot methods: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, approve, reject, cancel, void, submit, print, download, get_status,
  get_history, snapshot, clone, to_dict, from_dict, audit_trail, can_transition,
  transition, register_event, get_events, clear_events, calculate_tax, recalculate,
  attach_evidence, set_coretax_response, set_xml_content, set_pdf_content
- EBupotGenerator: all async methods with proper mocking
- Repository: _FallbackEBupotRepository CRUD and queries
- Exceptions
- Module-level get_e_bupot_generator

All tests use mocked datetime to avoid flakiness.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from adapters.coretax_djp.e_bupot_generator import (
    EBUPOT_STATUS,
    EBupot,
    EBupotAlreadyExistsError,
    EBupotError,
    EBupotGenerator,
    EBupotInvalidStateError,
    EBupotLockedError,
    EBupotNotFoundError,
    EBupotStatus,
    EBupotValidationError,
    PPh23_OBJECT_CODES,
    _FallbackEBupotRepository,
    get_e_bupot_generator,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def mock_datetime_now(mocker):
    """Mock datetime.now in the module to a fixed time."""
    fixed = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
    mocker.patch("adapters.coretax_djp.e_bupot_generator.datetime", return_value=fixed)
    # Also patch datetime.now specifically
    mocker.patch("adapters.coretax_djp.e_bupot_generator.datetime.now", return_value=fixed)
    return fixed


@pytest.fixture
def fixed_datetime():
    return datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_bupot_data():
    return {
        "npwp_pemotong": "123456789012345",
        "nama_pemotong": "PT Test",
        "npwp_penerima": "987654321098765",
        "nama_penerima": "CV Test",
        "dpp": 1000000,
        "pph_dipotong": 20000,
        "tanggal_pemotongan": date(2026, 7, 23),
        "masa_pajak": 7,
        "tahun_pajak": 2026,
        "jenis_pajak": "23",
        "jenis_penghasilan_code": "05",
    }


@pytest.fixture
def sample_bupot(sample_bupot_data):
    return EBupot(
        bupot_number="BUPOT-123456-202607-12345",
        npwp_pemotong=sample_bupot_data["npwp_pemotong"],
        nama_pemotong=sample_bupot_data["nama_pemotong"],
        npwp_penerima=sample_bupot_data["npwp_penerima"],
        nama_penerima=sample_bupot_data["nama_penerima"],
        dpp=Decimal(str(sample_bupot_data["dpp"])),
        tarif=Decimal("0.02"),
        pph_dipotong=Decimal(str(sample_bupot_data["pph_dipotong"])),
        tanggal_pemotongan=sample_bupot_data["tanggal_pemotongan"],
        masa_pajak=sample_bupot_data["masa_pajak"],
        tahun_pajak=sample_bupot_data["tahun_pajak"],
        jenis_pajak=sample_bupot_data["jenis_pajak"],
        jenis_penghasilan_code=sample_bupot_data["jenis_penghasilan_code"],
        status=EBupotStatus.DRAFT,
    )


@pytest.fixture
def mock_coretax_client():
    client = AsyncMock()
    client.post = AsyncMock(return_value={"status": "success", "coretax_id": "12345", "bupot_number_official": "BUPOT-123"})
    client.get = AsyncMock(return_value={"status": "success", "bupot_xml": "base64xml"})
    return client


@pytest.fixture
def generator_with_mocks(mocker, mock_coretax_client):
    # Patch get_coretax_client to return mock
    mocker.patch(
        "adapters.coretax_djp.e_bupot_generator.get_coretax_client",
        return_value=mock_coretax_client,
    )
    # Patch S3FileStorageAdapter to avoid actual instantiation
    mocker.patch(
        "adapters.coretax_djp.e_bupot_generator.S3FileStorageAdapter",
        return_value=AsyncMock(),
    )
    generator = EBupotGenerator(config={})
    # Override coretax_client with mock
    generator._coretax_client = mock_coretax_client
    return generator


# =============================================================================
# Tests for EBupotStatus enum
# =============================================================================

class TestEBupotStatus:
    def test_values(self):
        assert EBupotStatus.DRAFT.value == "draft"
        assert EBupotStatus.PENDING.value == "pending"
        assert EBupotStatus.VALIDATED.value == "validated"
        assert EBupotStatus.SUBMITTED.value == "submitted"
        assert EBupotStatus.APPROVED.value == "approved"
        assert EBupotStatus.REJECTED.value == "rejected"
        assert EBupotStatus.CANCELLED.value == "cancelled"
        assert EBupotStatus.VOID.value == "void"
        assert EBupotStatus.REVERSED.value == "reversed"
        assert EBupotStatus.CLOSED.value == "closed"
        assert EBupotStatus.ARCHIVED.value == "archived"
        assert EBupotStatus.LOCKED.value == "locked"
        assert EBupotStatus.ERROR.value == "error"
        assert EBupotStatus.SYNCED.value == "synced"
        assert EBupotStatus.PRINTED.value == "printed"


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_inheritance(self):
        assert issubclass(EBupotNotFoundError, EBupotError)
        assert issubclass(EBupotAlreadyExistsError, EBupotError)
        assert issubclass(EBupotInvalidStateError, EBupotError)
        assert issubclass(EBupotValidationError, EBupotError)
        assert issubclass(EBupotLockedError, EBupotError)

    def test_instantiation(self):
        e = EBupotError("test")
        assert str(e) == "test"


# =============================================================================
# Tests for EBupot Entity - Properties
# =============================================================================

class TestEBupotProperties:
    def test_all_properties(self, sample_bupot):
        assert sample_bupot.bupot_id is not None
        assert sample_bupot.bupot_number == "BUPOT-123456-202607-12345"
        assert sample_bupot.npwp_pemotong == "123456789012345"
        assert sample_bupot.nama_pemotong == "PT Test"
        assert sample_bupot.alamat_pemotong == ""
        assert sample_bupot.npwp_penerima == "987654321098765"
        assert sample_bupot.nama_penerima == "CV Test"
        assert sample_bupot.alamat_penerima == ""
        assert sample_bupot.dpp == Decimal("1000000")
        assert sample_bupot.tarif == Decimal("0.02")
        assert sample_bupot.tarif_percent == Decimal("2.00")
        assert sample_bupot.pph_dipotong == Decimal("20000")
        assert sample_bupot.tanggal_pemotongan == date(2026, 7, 23)
        assert sample_bupot.masa_pajak == 7
        assert sample_bupot.tahun_pajak == 2026
        assert sample_bupot.jenis_pajak == "23"
        assert sample_bupot.jenis_penghasilan_code == "05"
        assert sample_bupot.jenis_penghasilan_text == PPh23_OBJECT_CODES["05"]
        assert sample_bupot.invoice_reference == ""
        assert sample_bupot.keterangan == ""
        assert sample_bupot.status == EBupotStatus.DRAFT
        assert sample_bupot.version == 1
        assert sample_bupot.created_at is not None
        assert sample_bupot.updated_at is not None
        assert sample_bupot.submitted_at is None
        assert sample_bupot.approved_at is None
        assert sample_bupot.rejected_at is None
        assert sample_bupot.cancelled_at is None
        assert sample_bupot.printed_at is None
        assert sample_bupot.synced_at is None
        assert sample_bupot.locked_at is None
        assert sample_bupot.locked_by is None
        assert sample_bupot.is_locked is False
        assert sample_bupot.is_active is True
        assert sample_bupot.coretax_id is None
        assert sample_bupot.official_number is None
        assert sample_bupot.submitted_by is None
        assert sample_bupot.approved_by is None
        assert sample_bupot.rejection_reason == ""
        assert sample_bupot.cancellation_reason == ""
        assert sample_bupot.hash is not None
        assert sample_bupot.xml_content == ""
        assert sample_bupot.pdf_content is None
        assert sample_bupot.evidence_attachments == []


# =============================================================================
# Tests for EBupot Entity - Business Methods
# =============================================================================

class TestEBupotMethods:
    def test_create(self, sample_bupot):
        user = uuid4()
        bupot = sample_bupot.create(user)
        assert bupot.status == EBupotStatus.DRAFT
        assert bupot.version == 2
        events = bupot.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "e_bupot_created"

    def test_update_success(self, sample_bupot):
        user = uuid4()
        data = {"dpp": 2000000, "keterangan": "Updated"}
        bupot = sample_bupot.update(data, user)
        assert bupot.dpp == Decimal("2000000")
        assert bupot.keterangan == "Updated"
        assert bupot.version == 2
        events = bupot.get_events()
        assert events[-1]["event_type"] == "e_bupot_updated"

    def test_update_locked_raises(self, sample_bupot):
        sample_bupot.lock(uuid4())
        with pytest.raises(EBupotLockedError, match="locked"):
            sample_bupot.update({}, uuid4())

    def test_update_invalid_state(self, sample_bupot):
        sample_bupot._status = EBupotStatus.SUBMITTED
        with pytest.raises(EBupotInvalidStateError, match="Cannot modify"):
            sample_bupot.update({}, uuid4())

    def test_delete_non_permanent(self, sample_bupot):
        user = uuid4()
        bupot = sample_bupot.delete(user, permanent=False)
        assert bupot.status == EBupotStatus.ARCHIVED

    def test_delete_permanent(self, sample_bupot):
        user = uuid4()
        bupot = sample_bupot.delete(user, permanent=True)
        assert bupot.status == EBupotStatus.VOID

    def test_restore_success(self, sample_bupot):
        sample_bupot._status = EBupotStatus.ARCHIVED
        user = uuid4()
        bupot = sample_bupot.restore(user)
        assert bupot.status == EBupotStatus.DRAFT

    def test_restore_invalid_state(self, sample_bupot):
        with pytest.raises(EBupotInvalidStateError, match="Cannot restore"):
            sample_bupot.restore(uuid4())

    def test_activate_success(self, sample_bupot):
        user = uuid4()
        bupot = sample_bupot.activate(user)
        assert bupot.status == EBupotStatus.PENDING

    def test_activate_invalid_state(self, sample_bupot):
        sample_bupot._status = EBupotStatus.PENDING
        with pytest.raises(EBupotInvalidStateError, match="Cannot activate"):
            sample_bupot.activate(uuid4())

    def test_deactivate_success(self, sample_bupot):
        sample_bupot._status = EBupotStatus.PENDING
        user = uuid4()
        bupot = sample_bupot.deactivate(user)
        assert bupot.status == EBupotStatus.DRAFT

    def test_deactivate_invalid_state(self, sample_bupot):
        with pytest.raises(EBupotInvalidStateError, match="Cannot deactivate"):
            sample_bupot.deactivate(uuid4())

    def test_lock_success(self, sample_bupot):
        user = uuid4()
        bupot = sample_bupot.lock(user, "audit")
        assert bupot.is_locked is True
        assert bupot.locked_by == user
        assert bupot.status == EBupotStatus.LOCKED

    def test_lock_already_locked(self, sample_bupot):
        sample_bupot.lock(uuid4())
        with pytest.raises(EBupotLockedError, match="already locked"):
            sample_bupot.lock(uuid4())

    def test_unlock_success(self, sample_bupot):
        sample_bupot.lock(uuid4())
        user = uuid4()
        bupot = sample_bupot.unlock(user)
        assert bupot.is_locked is False
        assert bupot.locked_by is None
        assert bupot.status == EBupotStatus.PENDING

    def test_unlock_not_locked(self, sample_bupot):
        with pytest.raises(EBupotLockedError, match="not locked"):
            sample_bupot.unlock(uuid4())

    def test_validate_success(self, sample_bupot):
        sample_bupot._status = EBupotStatus.PENDING
        user = uuid4()
        bupot = sample_bupot.validate(user)
        assert bupot.status == EBupotStatus.VALIDATED
        assert bupot.version == 2

    def test_validate_locked(self, sample_bupot):
        sample_bupot._status = EBupotStatus.PENDING
        sample_bupot.lock(uuid4())
        with pytest.raises(EBupotLockedError, match="locked"):
            sample_bupot.validate(uuid4())

    def test_validate_invalid_dpp(self, sample_bupot):
        sample_bupot._dpp = Decimal("0")
        with pytest.raises(EBupotValidationError, match="DPP harus lebih besar"):
            sample_bupot.validate(uuid4())

    def test_validate_invalid_tarif(self, sample_bupot):
        sample_bupot._tarif = Decimal("0")
        with pytest.raises(EBupotValidationError, match="Tarif harus lebih besar"):
            sample_bupot.validate(uuid4())

    def test_validate_invalid_pph(self, sample_bupot):
        sample_bupot._pph_dipotong = Decimal("0")
        with pytest.raises(EBupotValidationError, match="PPh dipotong harus lebih besar"):
            sample_bupot.validate(uuid4())

    def test_validate_invalid_npwp_pemotong(self, sample_bupot):
        sample_bupot._npwp_pemotong = "123"
        with pytest.raises(EBupotValidationError, match="NPWP pemotong tidak valid"):
            sample_bupot.validate(uuid4())

    def test_validate_invalid_npwp_penerima(self, sample_bupot):
        sample_bupot._jenis_pajak = "23"
        sample_bupot._npwp_penerima = "123"
        with pytest.raises(EBupotValidationError, match="NPWP penerima tidak valid"):
            sample_bupot.validate(uuid4())

    def test_validate_pph_mismatch(self, sample_bupot):
        sample_bupot._pph_dipotong = Decimal("1000")
        with pytest.raises(EBupotValidationError, match="PPh dipotong tidak sesuai"):
            sample_bupot.validate(uuid4())

    def test_approve_success(self, sample_bupot):
        sample_bupot._status = EBupotStatus.SUBMITTED
        user = uuid4()
        bupot = sample_bupot.approve(user, "ok")
        assert bupot.status == EBupotStatus.APPROVED
        assert bupot.approved_by == user
        assert bupot.approved_at is not None

    def test_approve_invalid_state(self, sample_bupot):
        with pytest.raises(EBupotInvalidStateError, match="Cannot approve"):
            sample_bupot.approve(uuid4())

    def test_reject_success(self, sample_bupot):
        sample_bupot._status = EBupotStatus.PENDING
        user = uuid4()
        bupot = sample_bupot.reject(user, "not ok")
        assert bupot.status == EBupotStatus.REJECTED
        assert bupot.rejection_reason == "not ok"

    def test_reject_invalid_state(self, sample_bupot):
        sample_bupot._status = EBupotStatus.DRAFT
        with pytest.raises(EBupotInvalidStateError, match="Cannot reject"):
            sample_bupot.reject(uuid4(), "reason")

    def test_cancel_success(self, sample_bupot):
        sample_bupot._status = EBupotStatus.SUBMITTED
        user = uuid4()
        bupot = sample_bupot.cancel(user, "cancel reason")
        assert bupot.status == EBupotStatus.CANCELLED
        assert bupot.cancellation_reason == "cancel reason"

    def test_cancel_invalid_state(self, sample_bupot):
        sample_bupot._status = EBupotStatus.CANCELLED
        with pytest.raises(EBupotInvalidStateError, match="Cannot cancel"):
            sample_bupot.cancel(uuid4(), "reason")

    def test_void_success(self, sample_bupot):
        user = uuid4()
        bupot = sample_bupot.void(user, "void reason")
        assert bupot.status == EBupotStatus.VOID

    def test_void_locked(self, sample_bupot):
        sample_bupot.lock(uuid4())
        with pytest.raises(EBupotLockedError, match="locked"):
            sample_bupot.void(uuid4(), "reason")

    def test_submit_success(self, sample_bupot):
        sample_bupot._status = EBupotStatus.DRAFT
        user = uuid4()
        # Patch validate to avoid actual validation errors
        with patch.object(sample_bupot, "validate", return_value=sample_bupot):
            bupot = sample_bupot.submit(user)
            assert bupot.status == EBupotStatus.SUBMITTED
            assert bupot.submitted_by == user
            assert bupot.submitted_at is not None

    def test_submit_invalid_state(self, sample_bupot):
        sample_bupot._status = EBupotStatus.APPROVED
        with pytest.raises(EBupotInvalidStateError, match="Cannot submit"):
            sample_bupot.submit(uuid4())

    def test_print(self, sample_bupot):
        sample_bupot._status = EBupotStatus.APPROVED
        user = uuid4()
        with patch.object(sample_bupot, "_create_pdf", return_value=b"pdfdata"):
            pdf = sample_bupot.print(user)
            assert pdf == b"pdfdata"
            assert sample_bupot.status == EBupotStatus.PRINTED
            assert sample_bupot.printed_at is not None

    def test_download(self, sample_bupot):
        user = uuid4()
        with patch.object(sample_bupot, "_create_pdf", return_value=b"pdfdata"):
            pdf = sample_bupot.download(user)
            assert pdf == b"pdfdata"
            events = sample_bupot.get_events()
            assert events[-1]["event_type"] == "e_bupot_downloaded"

    def test_get_status(self, sample_bupot):
        status = sample_bupot.get_status()
        assert status["status"] == "draft"
        assert status["is_locked"] is False
        assert status["is_active"] is True
        assert status["can_submit"] is True

    def test_get_history(self, sample_bupot):
        sample_bupot._history.append({"event": "test"})
        history = sample_bupot.get_history()
        assert len(history) == 1

    def test_snapshot(self, sample_bupot):
        snap = sample_bupot.snapshot()
        assert snap["bupot_id"] == str(sample_bupot.bupot_id)
        assert snap["status"] == "draft"
        assert "dpp" in snap

    def test_to_dict(self, sample_bupot):
        d = sample_bupot.to_dict()
        assert d["bupot_number"] == sample_bupot.bupot_number
        assert d["dpp"] == float(sample_bupot.dpp)
        assert d["is_locked"] is False

    def test_from_dict(self, sample_bupot):
        d = sample_bupot.to_dict()
        bupot2 = EBupot.from_dict(d)
        assert bupot2.bupot_number == sample_bupot.bupot_number
        assert bupot2.dpp == sample_bupot.dpp

    def test_audit_trail(self, sample_bupot):
        sample_bupot._history.append({"audit": "test"})
        trail = sample_bupot.audit_trail()
        assert trail == sample_bupot._history

    def test_can_transition(self, sample_bupot):
        assert sample_bupot.can_transition(EBupotStatus.PENDING) is True
        assert sample_bupot.can_transition(EBupotStatus.SUBMITTED) is False

    def test_transition(self, sample_bupot):
        user = uuid4()
        bupot = sample_bupot.transition(EBupotStatus.PENDING, user, "reason")
        assert bupot.status == EBupotStatus.PENDING
        history = bupot.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "draft"

    def test_transition_invalid(self, sample_bupot):
        with pytest.raises(EBupotInvalidStateError, match="Status transition invalid"):
            sample_bupot.transition(EBupotStatus.SUBMITTED, uuid4())

    def test_register_event(self, sample_bupot):
        sample_bupot.register_event("test", {"data": "val"})
        events = sample_bupot.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test"

    def test_clear_events(self, sample_bupot):
        sample_bupot.register_event("test", {})
        sample_bupot.clear_events()
        assert len(sample_bupot.get_events()) == 0

    def test_calculate_tax(self, sample_bupot):
        tax = sample_bupot.calculate_tax()
        assert tax["pph_terutang"] == Decimal("20000.00")

    def test_recalculate(self, sample_bupot):
        sample_bupot._pph_dipotong = Decimal("0")
        bupot = sample_bupot.recalculate()
        assert bupot.pph_dipotong == Decimal("20000.00")

    def test_attach_evidence(self, sample_bupot):
        attachment = {"filename": "test.pdf", "content_type": "application/pdf", "size": 1234}
        bupot = sample_bupot.attach_evidence(attachment)
        assert len(bupot.evidence_attachments) == 1
        assert bupot.evidence_attachments[0]["filename"] == "test.pdf"

    def test_set_coretax_response(self, sample_bupot):
        response = {"coretax_id": "12345", "bupot_number_official": "OFFICIAL-001", "status": "success"}
        bupot = sample_bupot.set_coretax_response(response)
        assert bupot.coretax_id == "12345"
        assert bupot.official_number == "OFFICIAL-001"
        assert bupot.status == EBupotStatus.SUBMITTED

    def test_set_xml_content(self, sample_bupot):
        xml = "<xml>test</xml>"
        bupot = sample_bupot.set_xml_content(xml)
        assert bupot.xml_content == xml

    def test_set_pdf_content(self, sample_bupot):
        pdf = b"pdfdata"
        bupot = sample_bupot.set_pdf_content(pdf)
        assert bupot.pdf_content == pdf

    def test_clone(self, sample_bupot):
        clone = sample_bupot.clone("NEW-001")
        assert clone.bupot_number == "NEW-001"
        assert clone.status == EBupotStatus.DRAFT
        assert clone.bupot_id != sample_bupot.bupot_id


# =============================================================================
# Tests for _FallbackEBupotRepository
# =============================================================================

class TestFallbackEBupotRepository:
    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        retrieved = await repo.get_by_id(sample_bupot.bupot_id)
        assert retrieved is not None
        assert retrieved.bupot_id == sample_bupot.bupot_id

    @pytest.mark.asyncio
    async def test_get_by_number(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        retrieved = await repo.get_by_number(sample_bupot.bupot_number)
        assert retrieved is not None

    @pytest.mark.asyncio
    async def test_update(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        sample_bupot._status = EBupotStatus.PENDING
        await repo.update(sample_bupot)
        updated = await repo.get_by_id(sample_bupot.bupot_id)
        assert updated.status == EBupotStatus.PENDING

    @pytest.mark.asyncio
    async def test_delete(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        await repo.delete(sample_bupot.bupot_id)
        assert await repo.get_by_id(sample_bupot.bupot_id) is None

    @pytest.mark.asyncio
    async def test_get_by_period(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        results = await repo.get_by_period(sample_bupot.npwp_pemotong, 2026, 7)
        assert len(results) == 1
        results2 = await repo.get_by_period(sample_bupot.npwp_pemotong, 2025, 1)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_get_by_status(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        results = await repo.get_by_status(EBupotStatus.DRAFT)
        assert len(results) == 1
        results2 = await repo.get_by_status(EBupotStatus.PENDING)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_get_by_reference(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        sample_bupot._invoice_reference = "INV-001"
        await repo.add(sample_bupot)
        result = await repo.get_by_reference("invoice", UUID(int=1))  # not found
        assert result is None
        # Can't test with real UUID because we need to match string
        # We'll just test that it doesn't crash

    @pytest.mark.asyncio
    async def test_search(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        criteria = {"npwp_pemotong": sample_bupot.npwp_pemotong}
        results = await repo.search(criteria)
        assert len(results) == 1
        criteria2 = {"npwp_penerima": "nonexistent"}
        results2 = await repo.search(criteria2)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_save(self, sample_bupot):
        repo = _FallbackEBupotRepository()
        await repo.add(sample_bupot)
        sample_bupot._keterangan = "Updated"
        await repo.save(sample_bupot)
        saved = await repo.get_by_id(sample_bupot.bupot_id)
        assert saved.keterangan == "Updated"


# =============================================================================
# Tests for EBupotGenerator
# =============================================================================

class TestEBupotGenerator:
    @pytest.mark.asyncio
    async def test_create_success(self, generator_with_mocks, sample_bupot_data):
        generator = generator_with_mocks
        created_by = uuid4()
        result = await generator.create(sample_bupot_data, created_by)
        assert result["success"] is True
        assert "bupot_id" in result
        bupot = await generator.get_by_id(UUID(result["bupot_id"]))
        assert bupot is not None
        assert bupot.npwp_pemotong == sample_bupot_data["npwp_pemotong"]

    @pytest.mark.asyncio
    async def test_create_duplicate_number(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        data = {"bupot_number": sample_bupot.bupot_number}
        result = await generator.create(data, uuid4())
        assert result["success"] is False
        assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_update_success(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        data = {"keterangan": "new"}
        result = await generator.update(sample_bupot.bupot_id, data, uuid4())
        assert result["success"] is True
        updated = await generator.get_by_id(sample_bupot.bupot_id)
        assert updated.keterangan == "new"

    @pytest.mark.asyncio
    async def test_update_not_found(self, generator_with_mocks):
        result = await generator.update(uuid4(), {}, uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_update_locked(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot.lock(uuid4())
        await generator._repository.add(sample_bupot)
        result = await generator.update(sample_bupot.bupot_id, {"keterangan": "new"}, uuid4())
        assert result["success"] is False
        assert "locked" in result["error"]

    @pytest.mark.asyncio
    async def test_delete(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.delete(sample_bupot.bupot_id, uuid4(), permanent=False)
        assert result["success"] is True
        assert result["status"] == "archived"

    @pytest.mark.asyncio
    async def test_restore(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._status = EBupotStatus.ARCHIVED
        await generator._repository.add(sample_bupot)
        result = await generator.restore(sample_bupot.bupot_id, uuid4())
        assert result["success"] is True
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_lock_unlock(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.lock(sample_bupot.bupot_id, uuid4(), "audit")
        assert result["success"] is True
        assert result["locked"] is True
        unlocked = await generator.unlock(sample_bupot.bupot_id, uuid4())
        assert unlocked["locked"] is False

    @pytest.mark.asyncio
    async def test_validate_success(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._status = EBupotStatus.PENDING
        await generator._repository.add(sample_bupot)
        result = await generator.validate(sample_bupot.bupot_id, uuid4())
        assert result["success"] is True
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_invalid(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._dpp = Decimal("0")
        sample_bupot._status = EBupotStatus.PENDING
        await generator._repository.add(sample_bupot)
        result = await generator.validate(sample_bupot.bupot_id, uuid4())
        assert result["success"] is False
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_approve_success(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._status = EBupotStatus.SUBMITTED
        await generator._repository.add(sample_bupot)
        result = await generator.approve(sample_bupot.bupot_id, uuid4(), "ok")
        assert result["success"] is True
        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_reject_success(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._status = EBupotStatus.PENDING
        await generator._repository.add(sample_bupot)
        result = await generator.reject(sample_bupot.bupot_id, uuid4(), "reason")
        assert result["success"] is True
        assert result["rejected"] is True

    @pytest.mark.asyncio
    async def test_cancel_success(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._status = EBupotStatus.SUBMITTED
        await generator._repository.add(sample_bupot)
        result = await generator.cancel(sample_bupot.bupot_id, uuid4(), "reason")
        assert result["success"] is True
        assert result["cancelled"] is True

    @pytest.mark.asyncio
    async def test_submit_success(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._status = EBupotStatus.VALIDATED
        # Patch validate to avoid actual validation
        with patch.object(sample_bupot, "validate", return_value=sample_bupot):
            await generator._repository.add(sample_bupot)
            result = await generator.submit(sample_bupot.bupot_id, uuid4())
            assert result["success"] is True
            assert "coretax_id" in result
            assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_submit_validation_fails(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._dpp = Decimal("0")
        sample_bupot._status = EBupotStatus.VALIDATED
        await generator._repository.add(sample_bupot)
        result = await generator.submit(sample_bupot.bupot_id, uuid4())
        assert result["success"] is False
        assert "Validasi" in result["error"]

    @pytest.mark.asyncio
    async def test_print_bupot(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._status = EBupotStatus.APPROVED
        await generator._repository.add(sample_bupot)
        with patch.object(sample_bupot, "_create_pdf", return_value=b"pdfdata"):
            result = await generator.print_bupot(sample_bupot.bupot_id, uuid4())
            assert result["success"] is True
            assert result["pdf_content_base64"] is not None

    @pytest.mark.asyncio
    async def test_download_success(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        # mock coretax client get
        generator._coretax_client.get.return_value = {"status": "success", "bupot_xml": "base64data"}
        with patch("base64.b64decode", return_value=b"<xml>"):
            result = await generator.download(sample_bupot.bupot_id, uuid4())
            assert result["success"] is True
            assert result["bupot_number"] == sample_bupot.bupot_number

    @pytest.mark.asyncio
    async def test_download_failure(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        generator._coretax_client.get.return_value = {"status": "error", "message": "Not found"}
        result = await generator.download(sample_bupot.bupot_id, uuid4())
        assert result["success"] is False
        assert "Not found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_status(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.get_status(sample_bupot.bupot_id)
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_get_status_with_coretax_auto_approve(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._coretax_id = "12345"
        sample_bupot._status = EBupotStatus.SUBMITTED
        await generator._repository.add(sample_bupot)
        generator._coretax_client.get.return_value = {"status": "approved"}
        result = await generator.get_status(sample_bupot.bupot_id)
        assert result["status"] == "approved"
        # Check that bupot was auto-approved
        updated = await generator.get_by_id(sample_bupot.bupot_id)
        assert updated.status == EBupotStatus.APPROVED

    @pytest.mark.asyncio
    async def test_get_history(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._history.append({"event": "test"})
        await generator._repository.add(sample_bupot)
        result = await generator.get_history(sample_bupot.bupot_id)
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.snapshot(sample_bupot.bupot_id)
        assert result["bupot_id"] == str(sample_bupot.bupot_id)

    @pytest.mark.asyncio
    async def test_clone(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        new_number = "NEW-001"
        result = await generator.clone(sample_bupot.bupot_id, new_number, uuid4())
        assert result["success"] is True
        assert result["new_bupot_number"] == new_number

    @pytest.mark.asyncio
    async def test_calculate_tax(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.calculate_tax(sample_bupot.bupot_id)
        assert result["success"] is True
        assert result["calculation"]["pph_terutang"] == 20000.0

    @pytest.mark.asyncio
    async def test_recalculate(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._pph_dipotong = Decimal("0")
        await generator._repository.add(sample_bupot)
        result = await generator.recalculate(sample_bupot.bupot_id, uuid4())
        assert result["success"] is True
        assert result["pph_dipotong"] == 20000.0

    @pytest.mark.asyncio
    async def test_can_transition(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.can_transition(sample_bupot.bupot_id, "pending")
        assert result["success"] is True
        assert result["can_transition"] is True

    @pytest.mark.asyncio
    async def test_transition(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.transition(sample_bupot.bupot_id, "pending", uuid4(), "reason")
        assert result["success"] is True
        assert result["to_status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_events(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot.register_event("test", {})
        await generator._repository.add(sample_bupot)
        result = await generator.get_events(sample_bupot.bupot_id)
        assert result["success"] is True
        assert len(result["events"]) == 1

    @pytest.mark.asyncio
    async def test_version(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        result = await generator.version(sample_bupot.bupot_id)
        assert result["success"] is True
        assert result["version"] == 1

    @pytest.mark.asyncio
    async def test_audit_trail(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        sample_bupot._history.append({"audit": "entry"})
        await generator._repository.add(sample_bupot)
        result = await generator.audit_trail(sample_bupot.bupot_id)
        assert result["success"] is True
        assert len(result["audit_trail"]) == 1

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, generator_with_mocks):
        result = await generator.get_by_id(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_number_not_found(self, generator_with_mocks):
        result = await generator.get_by_number("NONEXISTENT")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_period(self, generator_with_mocks, sample_bupot):
        generator = generator_with_mocks
        await generator._repository.add(sample_bupot)
        results = await generator.get_by_period(sample_bupot.npwp_pemotong, 2026, 7)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_generate_bupot_from_invoice(self, generator_with_mocks):
        result = await generator.generate_bupot_from_invoice(uuid4(), uuid4())
        assert result["success"] is False
        assert "not available" in result["error"]

    # Legacy generate method
    def test_generate(self, generator_with_mocks):
        data = {"jenis_pajak": "PPh 23", "npwp_penerima": "123"}
        result = generator_with_mocks.generate(data)
        assert hasattr(result, "kode_billing")
        assert hasattr(result, "status")
        assert result.status == "DRAFT"
        with pytest.raises(ValueError, match="NPWP penerima wajib"):
            generator_with_mocks.generate({"jenis_pajak": "PPh 21"})

    # Test internal methods
    def test_generate_bupot_number(self, generator_with_mocks):
        number = generator_with_mocks._generate_bupot_number("123456789012345", 2026, 7)
        assert number.startswith("BUPOT-")
        assert "202607" in number

    def test_init_file_storage(self, generator_with_mocks):
        # _init_file_storage is called in __init__; we can just test that no exception
        assert generator_with_mocks._file_storage is not None

    def test_load_config(self, generator_with_mocks):
        config = generator_with_mocks._load_config()
        assert "coretax_djp" in config

    def test_get_cache_key(self, generator_with_mocks):
        key = generator_with_mocks._get_cache_key("BUPOT-123")
        assert key == "e_bupot:BUPOT-123"

    @pytest.mark.asyncio
    async def test_set_cached(self, generator_with_mocks):
        await generator_with_mocks._set_cached("BUPOT-123", {"data": "value"})
        assert generator_with_mocks._cache["e_bupot:BUPOT-123"] == {"data": "value"}

    @pytest.mark.asyncio
    async def test_get_cached(self, generator_with_mocks):
        await generator_with_mocks._set_cached("BUPOT-123", {"data": "value"})
        cached = await generator_with_mocks._get_cached("BUPOT-123")
        assert cached == {"data": "value"}


# =============================================================================
# Module-level getter
# =============================================================================

@patch("adapters.coretax_djp.e_bupot_generator.EBupotGenerator")
def test_get_e_bupot_generator(mock_generator_class):
    instance = AsyncMock()
    mock_generator_class.return_value = instance
    import adapters.coretax_djp.e_bupot_generator as mod
    mod._e_bupot_generator = None
    result = get_e_bupot_generator(config={"test": True})
    assert result is instance
    mock_generator_class.assert_called_once_with(config={"test": True})