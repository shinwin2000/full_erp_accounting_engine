# adapters/coretax_djp/test_e_bupot_generator.py
"""
Comprehensive unit tests for e-Bupot Generator.

Covers:
- EBupotStatus enum
- All exception classes
- EBupot entity: properties, status transitions, validation, approval, submission,
  locking, XML generation, PDF generation, serialization
- _FallbackEBupotRepository: CRUD operations, period queries
- EBupotGenerator: create, update, delete, restore, lock/unlock, validate, approve, reject,
  cancel, void, submit, print, download, get_status, get_history, snapshot, clone,
  calculate_tax, recalculate, audit_trail, can_transition, transition, get_events, version
- Module-level function: get_e_bupot_generator
- Coretax API client mocked, file storage mocked
"""

from datetime import UTC, date, datetime
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
# Helpers
# =============================================================================

def create_bupot(
    number="BUPOT-123456-202501-12345",
    npwp_pemotong="123456789012345",
    nama_pemotong="PT Test",
    npwp_penerima="987654321098765",
    nama_penerima="CV Test",
    dpp=Decimal("1000000"),
    tarif=Decimal("0.02"),
    pph_dipotong=Decimal("20000"),
    tanggal_pemotongan=date.today(),
    masa_pajak=1,
    tahun_pajak=2025,
    jenis_pajak="23",
    jenis_penghasilan_code="05",
    status=EBupotStatus.DRAFT,
):
    return EBupot(
        bupot_number=number,
        npwp_pemotong=npwp_pemotong,
        nama_pemotong=nama_pemotong,
        npwp_penerima=npwp_penerima,
        nama_penerima=nama_penerima,
        dpp=dpp,
        tarif=tarif,
        pph_dipotong=pph_dipotong,
        tanggal_pemotongan=tanggal_pemotongan,
        masa_pajak=masa_pajak,
        tahun_pajak=tahun_pajak,
        jenis_pajak=jenis_pajak,
        jenis_penghasilan_code=jenis_penghasilan_code,
        status=status,
        bupot_id=uuid4(),
        version=1,
    )


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
# Tests for EBupot Entity
# =============================================================================

class TestEBupotEntity:
    def test_initialization(self):
        bupot = create_bupot()
        assert bupot.bupot_number == "BUPOT-123456-202501-12345"
        assert bupot.npwp_pemotong == "123456789012345"
        assert bupot.nama_pemotong == "PT Test"
        assert bupot.dpp == Decimal("1000000")
        assert bupot.tarif == Decimal("0.02")
        assert bupot.pph_dipotong == Decimal("20000")
        assert bupot.status == EBupotStatus.DRAFT
        assert bupot.bupot_id is not None
        assert bupot.version == 1
        assert bupot.jenis_penghasilan_text == PPh23_OBJECT_CODES["05"]
        assert bupot.tarif_percent == Decimal("2.00")
        assert bupot.is_active is True
        assert bupot.is_locked is False

    def test_create(self):
        bupot = create_bupot()
        created_by = uuid4()
        bupot.create(created_by)
        assert bupot.status == EBupotStatus.DRAFT
        assert bupot.version == 2
        events = bupot.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "e_bupot_created"

    def test_update(self):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        updated_by = uuid4()
        bupot.update({"dpp": Decimal("2000000"), "keterangan": "Updated"}, updated_by)
        assert bupot.dpp == Decimal("2000000")
        assert bupot.keterangan == "Updated"
        assert bupot.version == 2
        events = bupot.get_events()
        assert events[-1]["event_type"] == "e_bupot_updated"

    def test_update_locked_raises(self):
        bupot = create_bupot()
        bupot.lock(uuid4())
        with pytest.raises(EBupotLockedError, match="locked"):
            bupot.update({}, uuid4())

    def test_update_invalid_state(self):
        bupot = create_bupot(status=EBupotStatus.SUBMITTED)
        with pytest.raises(EBupotInvalidStateError, match="Cannot modify"):
            bupot.update({}, uuid4())

    def test_delete(self):
        bupot = create_bupot()
        deleted_by = uuid4()
        bupot.delete(deleted_by, permanent=False)
        assert bupot.status == EBupotStatus.ARCHIVED
        bupot.delete(deleted_by, permanent=True)
        assert bupot.status == EBupotStatus.VOID

    def test_restore(self):
        bupot = create_bupot(status=EBupotStatus.ARCHIVED)
        bupot.restore(uuid4())
        assert bupot.status == EBupotStatus.DRAFT

    def test_restore_invalid_state(self):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        with pytest.raises(EBupotInvalidStateError, match="Cannot restore"):
            bupot.restore(uuid4())

    def test_activate_deactivate(self):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        bupot.activate(uuid4())
        assert bupot.status == EBupotStatus.PENDING
        bupot.deactivate(uuid4())
        assert bupot.status == EBupotStatus.DRAFT

    def test_lock_unlock(self):
        bupot = create_bupot()
        locked_by = uuid4()
        bupot.lock(locked_by, "audit")
        assert bupot.is_locked
        assert bupot.locked_by == locked_by
        bupot.unlock(uuid4())
        assert not bupot.is_locked
        assert bupot.status == EBupotStatus.PENDING

    def test_validate_success(self):
        bupot = create_bupot(status=EBupotStatus.PENDING)
        bupot.validate(uuid4())
        assert bupot.status == EBupotStatus.VALIDATED

    def test_validate_invalid_dpp(self):
        bupot = create_bupot(dpp=Decimal("0"))
        with pytest.raises(EBupotValidationError, match="DPP harus lebih besar"):
            bupot.validate(uuid4())

    def test_validate_invalid_tarif(self):
        bupot = create_bupot(tarif=Decimal("0"))
        with pytest.raises(EBupotValidationError, match="Tarif harus lebih besar"):
            bupot.validate(uuid4())

    def test_validate_invalid_pph(self):
        bupot = create_bupot(pph_dipotong=Decimal("0"))
        with pytest.raises(EBupotValidationError, match="PPh dipotong harus lebih besar"):
            bupot.validate(uuid4())

    def test_validate_invalid_npwp_pemotong(self):
        bupot = create_bupot(npwp_pemotong="123")
        with pytest.raises(EBupotValidationError, match="NPWP pemotong tidak valid"):
            bupot.validate(uuid4())

    def test_validate_pph_mismatch(self):
        bupot = create_bupot(pph_dipotong=Decimal("1000"))
        with pytest.raises(EBupotValidationError, match="PPh dipotong tidak sesuai"):
            bupot.validate(uuid4())

    def test_validate_locked(self):
        bupot = create_bupot(status=EBupotStatus.PENDING)
        bupot.lock(uuid4())
        with pytest.raises(EBupotLockedError, match="locked"):
            bupot.validate(uuid4())

    def test_approve(self):
        bupot = create_bupot(status=EBupotStatus.SUBMITTED)
        bupot.approve(uuid4(), "ok")
        assert bupot.status == EBupotStatus.APPROVED
        assert bupot.approved_at is not None

    def test_approve_invalid_state(self):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        with pytest.raises(EBupotInvalidStateError, match="Cannot approve"):
            bupot.approve(uuid4())

    def test_reject(self):
        bupot = create_bupot(status=EBupotStatus.PENDING)
        bupot.reject(uuid4(), "not ok")
        assert bupot.status == EBupotStatus.REJECTED
        assert bupot.rejection_reason == "not ok"

    def test_submit(self):
        bupot = create_bupot(status=EBupotStatus.PENDING)
        bupot.validate(uuid4())  # needed for submit
        bupot.submit(uuid4())
        assert bupot.status == EBupotStatus.SUBMITTED
        assert bupot.submitted_at is not None

    def test_submit_invalid_state(self):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        with pytest.raises(EBupotInvalidStateError, match="Cannot submit"):
            bupot.submit(uuid4())

    def test_cancel(self):
        bupot = create_bupot(status=EBupotStatus.SUBMITTED)
        bupot.cancel(uuid4(), "cancel")
        assert bupot.status == EBupotStatus.CANCELLED
        assert bupot.cancellation_reason == "cancel"

    def test_void(self):
        bupot = create_bupot()
        bupot.void(uuid4(), "void")
        assert bupot.status == EBupotStatus.VOID

    def test_print(self):
        bupot = create_bupot(status=EBupotStatus.APPROVED)
        with patch.object(bupot, "_create_pdf", return_value=b"pdfdata"):
            pdf = bupot.print(uuid4())
            assert pdf == b"pdfdata"
            assert bupot.status == EBupotStatus.PRINTED

    def test_download(self):
        bupot = create_bupot()
        with patch.object(bupot, "_create_pdf", return_value=b"pdfdata"):
            pdf = bupot.download(uuid4())
            assert pdf == b"pdfdata"
            events = bupot.get_events()
            assert events[-1]["event_type"] == "e_bupot_downloaded"

    def test_get_status(self):
        bupot = create_bupot(status=EBupotStatus.PENDING)
        status = bupot.get_status()
        assert status["status"] == "pending"
        assert status["can_submit"] is True

    def test_get_history(self):
        bupot = create_bupot()
        bupot._history.append({"event": "test"})
        history = bupot.get_history()
        assert len(history) == 1

    def test_snapshot(self):
        bupot = create_bupot()
        snap = bupot.snapshot()
        assert snap["bupot_id"] == str(bupot.bupot_id)
        assert snap["status"] == "draft"

    def test_to_dict_from_dict(self):
        bupot = create_bupot()
        d = bupot.to_dict()
        assert d["bupot_number"] == bupot.bupot_number
        bupot2 = EBupot.from_dict(d)
        assert bupot2.bupot_number == bupot.bupot_number
        assert bupot2.dpp == bupot.dpp

    def test_audit_trail(self):
        bupot = create_bupot()
        bupot._history.append({"audit": "test"})
        trail = bupot.audit_trail()
        assert trail == bupot._history

    def test_can_transition(self):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        assert bupot.can_transition(EBupotStatus.PENDING) is True
        assert bupot.can_transition(EBupotStatus.SUBMITTED) is False

    def test_transition(self):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        bupot.transition(EBupotStatus.PENDING, uuid4(), "reason")
        assert bupot.status == EBupotStatus.PENDING
        history = bupot.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "draft"

    def test_register_event_and_clear(self):
        bupot = create_bupot()
        bupot.register_event("test", {"data": "val"})
        events = bupot.get_events()
        assert len(events) == 1
        bupot.clear_events()
        assert len(bupot.get_events()) == 0

    def test_calculate_tax(self):
        bupot = create_bupot(dpp=Decimal("1000000"), tarif=Decimal("0.02"))
        tax = bupot.calculate_tax()
        assert tax["pph_terutang"] == Decimal("20000.00")

    def test_recalculate(self):
        bupot = create_bupot(dpp=Decimal("1000000"), tarif=Decimal("0.02"), pph_dipotong=Decimal("0"))
        bupot.recalculate()
        assert bupot.pph_dipotong == Decimal("20000.00")

    def test_attach_evidence(self):
        bupot = create_bupot()
        bupot.attach_evidence({"filename": "test.pdf"})
        assert len(bupot.evidence_attachments) == 1
        assert bupot.evidence_attachments[0]["filename"] == "test.pdf"

    def test_set_coretax_response(self):
        bupot = create_bupot()
        bupot.set_coretax_response({"coretax_id": "123", "status": "success"})
        assert bupot.coretax_id == "123"
        assert bupot.status == EBupotStatus.SUBMITTED

    def test_clone(self):
        bupot = create_bupot()
        clone = bupot.clone()
        assert clone.bupot_number != bupot.bupot_number
        assert clone.status == EBupotStatus.DRAFT

    def test_xml_generation(self):
        bupot = create_bupot()
        xml = bupot._create_xml()
        assert "<EBupot" in xml
        assert bupot.bupot_number in xml

    def test_pdf_generation(self):
        bupot = create_bupot()
        with patch("adapters.coretax_djp.e_bupot_generator.REPORTLAB_AVAILABLE", False):
            pdf = bupot._create_pdf()
            assert isinstance(pdf, bytes)
            assert len(pdf) > 0


# =============================================================================
# Tests for _FallbackEBupotRepository
# =============================================================================

class TestFallbackEBupotRepository:
    @pytest.mark.asyncio
    async def test_crud(self):
        repo = _FallbackEBupotRepository()
        bupot = create_bupot()
        await repo.add(bupot)
        retrieved = await repo.get_by_id(bupot.bupot_id)
        assert retrieved is not None
        assert retrieved.bupot_id == bupot.bupot_id

        retrieved_by_num = await repo.get_by_number(bupot.bupot_number)
        assert retrieved_by_num is not None

        bupot._status = EBupotStatus.PENDING
        await repo.update(bupot)
        updated = await repo.get_by_id(bupot.bupot_id)
        assert updated.status == EBupotStatus.PENDING

        period_results = await repo.get_by_period(bupot.npwp_pemotong, 2025, 1)
        assert len(period_results) == 1

        status_results = await repo.get_by_status(EBupotStatus.PENDING)
        assert len(status_results) == 1

        by_ref = await repo.get_by_reference("invoice", uuid4())
        assert by_ref is None

        search = await repo.search({"npwp_pemotong": bupot.npwp_pemotong})
        assert len(search) == 1

        await repo.delete(bupot.bupot_id)
        assert await repo.get_by_id(bupot.bupot_id) is None


# =============================================================================
# Tests for EBupotGenerator
# =============================================================================

@pytest.fixture
def generator():
    return EBupotGenerator(config={})


@pytest.fixture
def mock_coretax_client():
    client = AsyncMock()
    client.post = AsyncMock(return_value={"status": "success", "coretax_id": "123", "bupot_number": "BUPOT-123"})
    client.get = AsyncMock()
    return client


class TestEBupotGenerator:
    @pytest.mark.asyncio
    async def test_create_success(self, generator):
        created_by = uuid4()
        data = {
            "npwp_pemotong": "123456789012345",
            "nama_pemotong": "PT Test",
            "npwp_penerima": "987654321098765",
            "nama_penerima": "CV Test",
            "dpp": "1000000",
            "pph_dipotong": "20000",
            "tanggal_pemotongan": date.today(),
            "masa_pajak": 1,
            "tahun_pajak": 2025,
        }
        result = await generator.create(data, created_by)
        assert result["success"] is True
        assert "bupot_id" in result
        bupot = await generator.get_by_id(UUID(result["bupot_id"]))
        assert bupot is not None
        assert bupot.npwp_pemotong == "123456789012345"

    @pytest.mark.asyncio
    async def test_create_duplicate_number(self, generator):
        # Simulate existing bupot
        bupot = create_bupot()
        await generator._repository.add(bupot)
        data = {"bupot_number": bupot.bupot_number}
        result = await generator.create(data, uuid4())
        assert result["success"] is False
        assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_update_success(self, generator):
        bupot = create_bupot(status=EBupotStatus.DRAFT)
        await generator._repository.add(bupot)
        data = {"keterangan": "new"}
        result = await generator.update(bupot.bupot_id, data, uuid4())
        assert result["success"] is True
        updated = await generator.get_by_id(bupot.bupot_id)
        assert updated.keterangan == "new"

    @pytest.mark.asyncio
    async def test_update_not_found(self, generator):
        result = await generator.update(uuid4(), {}, uuid4())
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_delete(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.delete(bupot.bupot_id, uuid4(), permanent=False)
        assert result["success"] is True
        assert result["status"] == "archived"

    @pytest.mark.asyncio
    async def test_restore(self, generator):
        bupot = create_bupot(status=EBupotStatus.ARCHIVED)
        await generator._repository.add(bupot)
        result = await generator.restore(bupot.bupot_id, uuid4())
        assert result["success"] is True
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_lock_unlock(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.lock(bupot.bupot_id, uuid4(), "audit")
        assert result["success"] is True
        assert result["locked"] is True
        unlocked = await generator.unlock(bupot.bupot_id, uuid4())
        assert unlocked["locked"] is False

    @pytest.mark.asyncio
    async def test_validate(self, generator):
        bupot = create_bupot(status=EBupotStatus.PENDING)
        await generator._repository.add(bupot)
        result = await generator.validate(bupot.bupot_id, uuid4())
        assert result["success"] is True
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_invalid(self, generator):
        bupot = create_bupot(status=EBupotStatus.PENDING, dpp=Decimal("0"))
        await generator._repository.add(bupot)
        result = await generator.validate(bupot.bupot_id, uuid4())
        assert result["success"] is False
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_approve(self, generator):
        bupot = create_bupot(status=EBupotStatus.SUBMITTED)
        await generator._repository.add(bupot)
        result = await generator.approve(bupot.bupot_id, uuid4(), "ok")
        assert result["success"] is True
        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_reject(self, generator):
        bupot = create_bupot(status=EBupotStatus.PENDING)
        await generator._repository.add(bupot)
        result = await generator.reject(bupot.bupot_id, uuid4(), "reason")
        assert result["success"] is True
        assert result["rejected"] is True

    @pytest.mark.asyncio
    async def test_cancel(self, generator):
        bupot = create_bupot(status=EBupotStatus.SUBMITTED)
        await generator._repository.add(bupot)
        result = await generator.cancel(bupot.bupot_id, uuid4(), "reason")
        assert result["success"] is True
        assert result["cancelled"] is True

    @pytest.mark.asyncio
    async def test_submit_success(self, generator, mock_coretax_client):
        generator._coretax_client = mock_coretax_client
        bupot = create_bupot(status=EBupotStatus.VALIDATED)
        await generator._repository.add(bupot)
        result = await generator.submit(bupot.bupot_id, uuid4())
        assert result["success"] is True
        assert "coretax_id" in result
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_submit_validation_fails(self, generator):
        bupot = create_bupot(status=EBupotStatus.VALIDATED, dpp=Decimal("0"))
        await generator._repository.add(bupot)
        result = await generator.submit(bupot.bupot_id, uuid4())
        assert result["success"] is False
        assert "Validasi" in result["error"]

    @pytest.mark.asyncio
    async def test_print_bupot(self, generator):
        bupot = create_bupot(status=EBupotStatus.APPROVED)
        await generator._repository.add(bupot)
        with patch.object(bupot, "_create_pdf", return_value=b"pdfdata"):
            result = await generator.print_bupot(bupot.bupot_id, uuid4())
            assert result["success"] is True
            assert result["pdf_content_base64"] is not None

    @pytest.mark.asyncio
    async def test_download_bupot(self, generator, mock_coretax_client):
        generator._coretax_client = mock_coretax_client
        bupot = create_bupot()
        await generator._repository.add(bupot)
        mock_coretax_client.get.return_value = {"status": "success", "bupot_xml": "base64data"}
        with patch("base64.b64decode", return_value=b"<xml>"):
            result = await generator.download(bupot.bupot_id, uuid4())
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_status(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.get_status(bupot.bupot_id)
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_get_history(self, generator):
        bupot = create_bupot()
        bupot._history.append({"event": "test"})
        await generator._repository.add(bupot)
        result = await generator.get_history(bupot.bupot_id)
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.snapshot(bupot.bupot_id)
        assert result["bupot_id"] == str(bupot.bupot_id)

    @pytest.mark.asyncio
    async def test_clone(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.clone(bupot.bupot_id, "NEW-001", uuid4())
        assert result["success"] is True
        assert result["new_bupot_number"] == "NEW-001"

    @pytest.mark.asyncio
    async def test_calculate_tax(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.calculate_tax(bupot.bupot_id)
        assert result["success"] is True
        assert result["calculation"]["pph_terutang"] == 20000.0

    @pytest.mark.asyncio
    async def test_recalculate(self, generator):
        bupot = create_bupot(dpp=Decimal("1000000"), tarif=Decimal("0.02"), pph_dipotong=Decimal("0"))
        await generator._repository.add(bupot)
        result = await generator.recalculate(bupot.bupot_id, uuid4())
        assert result["success"] is True
        assert result["pph_dipotong"] == 20000.0

    @pytest.mark.asyncio
    async def test_can_transition(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.can_transition(bupot.bupot_id, "pending")
        assert result["success"] is True
        assert result["can_transition"] is True

    @pytest.mark.asyncio
    async def test_transition(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.transition(bupot.bupot_id, "pending", uuid4(), "reason")
        assert result["success"] is True
        assert result["to_status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_events(self, generator):
        bupot = create_bupot()
        bupot.register_event("test", {})
        await generator._repository.add(bupot)
        result = await generator.get_events(bupot.bupot_id)
        assert result["success"] is True
        assert len(result["events"]) == 1

    @pytest.mark.asyncio
    async def test_version(self, generator):
        bupot = create_bupot()
        await generator._repository.add(bupot)
        result = await generator.version(bupot.bupot_id)
        assert result["success"] is True
        assert result["version"] == 1

    # Legacy method tests
    def test_generate(self, generator):
        data = {"jenis_pajak": "PPh 23", "npwp_penerima": "123"}
        result = generator.generate(data)
        assert hasattr(result, "kode_billing")
        assert hasattr(result, "status")
        assert result.status == "DRAFT"
        # PPh 21 without npwp penerima raises
        with pytest.raises(ValueError, match="NPWP penerima wajib"):
            generator.generate({"jenis_pajak": "PPh 21"})


# =============================================================================
# Tests for Module-level function
# =============================================================================

@patch("adapters.coretax_djp.e_bupot_generator.EBupotGenerator")
async def test_get_e_bupot_generator(mock_generator_class):
    instance = AsyncMock()
    mock_generator_class.return_value = instance
    import adapters.coretax_djp.e_bupot_generator as mod
    mod._e_bupot_generator = None
    result = await get_e_bupot_generator(config={"test": True})
    assert result is instance
    mock_generator_class.assert_called_once_with(config={"test": True})