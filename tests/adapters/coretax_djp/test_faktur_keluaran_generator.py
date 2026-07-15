#!/usr/bin/env python3
"""
tests/unit/test_faktur_keluaran_generator.py
Test untuk adapters/coretax_djp/faktur_keluaran_generator.py
Mencakup: FakturKeluaran, FakturKeluaranGenerator
"""

from __future__ import annotations

import base64
import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.coretax_djp.faktur_keluaran_generator import (
    CORETAX_FAKTUR_ENDPOINT,
    FakturError,
    FakturInvalidStateError,
    FakturKeluaran,
    FakturKeluaranGenerator,
    FakturLockedError,
    FakturStatus,
    FakturValidationError,
    PPN_RATE,
    get_faktur_generator,
)


class TestFakturKeluaran:
    def test_create_valid_faktur(self):
        """Test creation of valid FakturKeluaran."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        assert faktur.faktur_number == "010.2026.05.00000001"
        assert faktur.nsfp == "00000001"
        assert faktur.status == FakturStatus.DRAFT
        assert faktur.dpp == Decimal("100000000")
        assert faktur.ppn == Decimal("11000000")
        assert faktur.total_amount == Decimal("111000000")
        assert faktur.hash != ""

    def test_total_amount_calculation(self):
        """Test total_amount calculates correctly."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            ppn_bm=Decimal("5000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        assert faktur.total_amount == Decimal("116000000")

    def test_jenis_transaksi_text(self):
        """Test jenis_transaksi_text returns display name."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            jenis_transaksi="01",
        )
        assert faktur.jenis_transaksi_text == "Penyerahan BKP"

    def test_validate_validation_passes(self):
        """Test validate passes for valid faktur."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        # Should not raise
        faktur.validate(uuid.uuid4())

    def test_validate_raises_on_invalid_npwp(self):
        """Test validate raises on invalid NPWP."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123",  # invalid
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        with pytest.raises(FakturValidationError, match="NPWP penjual tidak valid"):
            faktur.validate(uuid.uuid4())

    def test_validate_raises_on_invalid_ppn(self):
        """Test validate raises when PPN doesn't match 11%."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("5000000"),  # wrong (should be 11,000,000)
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        with pytest.raises(FakturValidationError, match="PPN tidak sesuai"):
            faktur.validate(uuid.uuid4())

    def test_submit_transitions_to_submitted(self):
        """Test submit changes status to SUBMITTED."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        # First activate to PENDING
        faktur.activate(uuid.uuid4())
        submitted = faktur.submit(uuid.uuid4())
        assert submitted.status == FakturStatus.SUBMITTED
        assert submitted.submitted_at is not None

    def test_approve_transitions_to_approved(self):
        """Test approve changes status to APPROVED."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur.activate(uuid.uuid4())
        submitted = faktur.submit(uuid.uuid4())
        approved = submitted.approve(uuid.uuid4(), "Approved by admin")
        assert approved.status == FakturStatus.APPROVED
        assert approved.approved_at is not None

    def test_reject_sets_rejection_reason(self):
        """Test reject sets rejection reason."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur.activate(uuid.uuid4())
        rejected = faktur.reject(uuid.uuid4(), "Invalid data")
        assert rejected.status == FakturStatus.REJECTED
        assert rejected.rejection_reason == "Invalid data"

    def test_cancel_cancels_faktur(self):
        """Test cancel changes status to CANCELLED."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        cancelled = faktur.cancel(uuid.uuid4(), "Duplicate")
        assert cancelled.status == FakturStatus.CANCELLED
        assert cancelled.cancellation_reason == "Duplicate"

    def test_lock_locks_faktur(self):
        """Test lock changes status to LOCKED."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        locked = faktur.lock(uuid.uuid4(), "Review")
        assert locked.is_locked is True
        assert locked.status == FakturStatus.LOCKED
        assert locked.locked_at is not None

    def test_unlock_unlocks_faktur(self):
        """Test unlock changes status back to PENDING."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        locked = faktur.lock(uuid.uuid4(), "Review")
        unlocked = locked.unlock(uuid.uuid4())
        assert unlocked.is_locked is False
        assert unlocked.status == FakturStatus.PENDING

    def test_update_allowed_in_draft(self):
        """Test update works in DRAFT status."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        updated = faktur.update({"keterangan": "Updated"}, uuid.uuid4())
        assert updated.keterangan == "Updated"
        assert updated.version == 2

    def test_update_not_allowed_when_locked(self):
        """Test update raises when locked."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        locked = faktur.lock(uuid.uuid4(), "Review")
        with pytest.raises(FakturLockedError):
            locked.update({"keterangan": "Should fail"}, uuid.uuid4())

    def test_can_transition_valid_transitions(self):
        """Test can_transition checks valid status transitions."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.DRAFT,
        )
        assert faktur.can_transition(FakturStatus.PENDING) is True
        assert faktur.can_transition(FakturStatus.APPROVED) is False
        assert faktur.can_transition(FakturStatus.CANCELLED) is True

    def test_transition_changes_status(self):
        """Test transition changes status and records history."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        transitioned = faktur.transition(FakturStatus.PENDING, uuid.uuid4(), "Activate")
        assert transitioned.status == FakturStatus.PENDING
        history = transitioned.get_history()
        assert len(history) == 1
        assert history[0]["from_status"] == "draft"
        assert history[0]["to_status"] == "pending"

    def test_recalculate_updates_ppn(self):
        """Test recalculate updates PPN based on DPP."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("0"),  # wrong
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        recalculated = faktur.recalculate()
        expected_ppn = (Decimal("100000000") * PPN_RATE).quantize(Decimal("0.01"))
        assert recalculated.ppn == expected_ppn

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        d = faktur.to_dict()
        assert d["faktur_number"] == "010.2026.05.00000001"
        assert d["dpp"] == 100000000.0
        assert d["ppn"] == 11000000.0
        assert d["status"] == "draft"
        assert "hash" in d

    def test_from_dict_reconstructs(self):
        """Test from_dict reconstructs object."""
        original = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        d = original.to_dict()
        reconstructed = FakturKeluaran.from_dict(d)
        assert reconstructed.faktur_number == original.faktur_number
        assert reconstructed.dpp == original.dpp
        assert reconstructed.ppn == original.ppn

    def test_clone_creates_draft_copy(self):
        """Test clone creates new draft copy."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        cloned = faktur.clone("010.2026.05.00000002")
        assert cloned.faktur_number == "010.2026.05.00000002"
        assert cloned.status == FakturStatus.DRAFT
        assert cloned.dpp == faktur.dpp
        assert cloned.id != faktur.id

    def test_get_events_returns_events(self):
        """Test get_events returns registered events."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur.register_event("test_event", {"data": "test"})
        events = faktur.get_events()
        assert len(events) >= 1
        assert events[-1]["event_type"] == "test_event"

    def test_clear_events_clears(self):
        """Test clear_events clears event list."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur.register_event("test", {})
        faktur.clear_events()
        assert len(faktur.get_events()) == 0

    def test_snapshot_returns_summary(self):
        """Test snapshot returns summary dict."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        snap = faktur.snapshot()
        assert snap["faktur_number"] == "010.2026.05.00000001"
        assert snap["status"] == "draft"
        assert snap["dpp"] == 100000000.0
        assert "hash" in snap


class TestFakturKeluaranGenerator:
    @pytest.mark.asyncio
    async def test_create_faktur(self):
        """Test create creates new faktur."""
        generator = FakturKeluaranGenerator()
        result = await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        assert result["success"] is True
        assert "faktur_id" in result
        assert "faktur_number" in result

    @pytest.mark.asyncio
    async def test_get_by_id(self):
        """Test get_by_id returns faktur."""
        generator = FakturKeluaranGenerator()
        result = await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        faktur_id = uuid.UUID(result["faktur_id"])
        retrieved = await generator.get_by_id(faktur_id)
        assert retrieved is not None
        assert retrieved.faktur_id == faktur_id

    @pytest.mark.asyncio
    async def test_get_by_number(self):
        """Test get_by_number returns faktur."""
        generator = FakturKeluaranGenerator()
        result = await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        retrieved = await generator.get_by_number(result["faktur_number"])
        assert retrieved is not None
        assert retrieved.faktur_number == result["faktur_number"]

    @pytest.mark.asyncio
    async def test_get_by_period(self):
        """Test get_by_period returns fakturs for period."""
        generator = FakturKeluaranGenerator()
        await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        results = await generator.get_by_period(2026, 5)
        assert len(results) >= 1
        assert results[0].tahun == 2026
        assert results[0].bulan == 5

    @pytest.mark.asyncio
    async def test_submit_faktur_calls_coretax(self):
        """Test submit_faktur calls Coretax API."""
        generator = FakturKeluaranGenerator()
        # Mock Coretax client
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "status": "success",
            "approval_code": "TEST-123",
            "faktur_id": "CORETAX-123",
        }
        generator._coretax_client = mock_client

        result = await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        faktur_id = uuid.UUID(result["faktur_id"])

        submit_result = await generator.submit_faktur(faktur_id, uuid.uuid4())
        assert submit_result["success"] is True
        assert submit_result["approval_code"] == "TEST-123"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_faktur_status(self):
        """Test check_faktur_status returns status."""
        generator = FakturKeluaranGenerator()
        mock_client = AsyncMock()
        mock_client.get.return_value = {
            "status_kode": "APPROVED",
            "status_desc": "Disetujui",
            "tanggal_approval": date.today().isoformat(),
        }
        generator._coretax_client = mock_client

        result = await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        faktur = await generator.get_by_id(uuid.UUID(result["faktur_id"]))
        # Set coretax_id manually to simulate submitted state
        faktur._coretax_id = "CORETAX-123"
        await generator._repository.save(faktur)

        status = await generator.check_faktur_status(faktur.faktur_id)
        assert status["success"] is True
        mock_client.get.assert_called()

    @pytest.mark.asyncio
    async def test_cancel_faktur(self):
        """Test cancel_faktur cancels faktur."""
        generator = FakturKeluaranGenerator()
        result = await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        faktur_id = uuid.UUID(result["faktur_id"])
        cancel_result = await generator.cancel_faktur(faktur_id, uuid.uuid4(), "Test cancellation")
        assert cancel_result["success"] is True
        assert cancel_result["cancelled"] is True

        # Verify status changed
        faktur = await generator.get_by_id(faktur_id)
        assert faktur.status == FakturStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_print_faktur_returns_pdf(self):
        """Test print_faktur returns PDF content."""
        generator = FakturKeluaranGenerator()
        result = await generator.create(
            {
                "nsfp": "00000001",
                "npwp_penjual": "123456789012345",
                "nama_penjual": "PT Maju Jaya",
                "npwp_pembeli": "987654321098765",
                "nama_pembeli": "PT Sejahtera",
                "dpp": 100000000,
                "tanggal_faktur": date.today(),
                "tahun": 2026,
                "bulan": 5,
            },
            uuid.uuid4(),
        )
        faktur_id = uuid.UUID(result["faktur_id"])
        # Activate and approve first
        faktur = await generator.get_by_id(faktur_id)
        faktur.activate(uuid.uuid4())
        submitted = faktur.submit(uuid.uuid4())
        approved = submitted.approve(uuid.uuid4(), "Approved")
        await generator._repository.save(approved)

        print_result = await generator.print_faktur(faktur_id, uuid.uuid4())
        assert print_result["success"] is True
        assert "pdf_content_base64" in print_result
        # Decode to verify it's valid base64
        base64.b64decode(print_result["pdf_content_base64"])

    def test_generate_example_returns_dummy(self):
        """Test generate_example returns dummy faktur."""
        generator = FakturKeluaranGenerator()
        dummy = generator.generate_example()
        assert dummy.kode_faktur == "010"
        assert dummy.status == "SUBMITTED"
        assert dummy.is_valid is True
        assert dummy.ppn == Decimal("11000000")

    def test_generate_returns_dummy(self):
        """Test generate returns dummy faktur."""
        generator = FakturKeluaranGenerator()
        dummy = generator.generate(
            {
                "dpp": 100000000,
                "ppn": 11000000,
                "penjual_npwp": "123456789012345",
                "pembeli_npwp": "987654321098765",
                "nsfp": "00000001",
                "tahun": 2026,
                "bulan": 5,
            }
        )
        assert dummy.kode_faktur == "01"
        assert dummy.is_valid is True

    def test_submit_dummy(self):
        """Test submit method on dummy faktur."""
        generator = FakturKeluaranGenerator()
        dummy = generator.generate_example()
        result = generator.submit(dummy)
        assert result.status_code == 201
        assert result.approval_code is not None

    async def test_get_faktur_generator_singleton(self):
        """Test get_faktur_generator returns singleton."""
        gen1 = await get_faktur_generator()
        gen2 = await get_faktur_generator()
        # They should be the same instance (singleton)
        assert gen1 is gen2


class TestFakturKeluaranAdditional:
    """Additional tests for FakturKeluaran entity to cover missing methods."""

    def test_create_method(self):
        """Test create method sets status to DRAFT and increments version."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        created_by = uuid.uuid4()
        result = faktur.create(created_by)
        assert result.status == FakturStatus.DRAFT
        assert result.version == 2  # initial version 1, then increment
        assert len(result._events) == 1
        assert result._events[0]["event_type"] == "faktur_keluaran_created"
        assert result._events[0]["data"]["created_by"] == str(created_by)

    def test_update_method(self):
        """Test update modifies fields and increments version."""
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        updated_by = uuid.uuid4()
        data = {
            "dpp": Decimal("150000000"),
            "ppn": Decimal("16500000"),
            "keterangan": "Updated description",
            "alamat_penjual": "Jl. Baru",
            "status_pembayaran": "2",
        }
        result = faktur.update(data, updated_by)
        assert result.dpp == Decimal("150000000")
        assert result.ppn == Decimal("16500000")
        assert result.keterangan == "Updated description"
        assert result.alamat_penjual == "Jl. Baru"
        assert result.status_pembayaran == "2"
        assert result.version == 2
        assert len(result._events) == 1
        assert result._events[0]["event_type"] == "faktur_keluaran_updated"

    def test_update_in_locked_state_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._locked_at = datetime.now()
        with pytest.raises(FakturLockedError, match="is locked"):
            faktur.update({}, uuid.uuid4())

    def test_delete_soft(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        deleted_by = uuid.uuid4()
        result = faktur.delete(deleted_by, permanent=False)
        assert result.status == FakturStatus.ARCHIVED
        assert result.version == 2
        assert result._events[0]["event_type"] == "faktur_keluaran_deleted"

    def test_delete_permanent(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        deleted_by = uuid.uuid4()
        result = faktur.delete(deleted_by, permanent=True)
        assert result.status == FakturStatus.VOID

    def test_delete_locked_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._locked_at = datetime.now()
        with pytest.raises(FakturLockedError, match="is locked"):
            faktur.delete(uuid.uuid4())

    def test_restore(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._status = FakturStatus.ARCHIVED
        restored_by = uuid.uuid4()
        result = faktur.restore(restored_by)
        assert result.status == FakturStatus.DRAFT
        assert result.version == 2
        assert result._events[0]["event_type"] == "faktur_keluaran_restored"

    def test_restore_invalid_state_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        with pytest.raises(FakturInvalidStateError, match="Cannot restore"):
            faktur.restore(uuid.uuid4())

    def test_activate(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        activated_by = uuid.uuid4()
        result = faktur.activate(activated_by)
        assert result.status == FakturStatus.PENDING
        assert result.version == 2

    def test_activate_invalid_state_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.PENDING,
        )
        with pytest.raises(FakturInvalidStateError, match="Cannot activate"):
            faktur.activate(uuid.uuid4())

    def test_deactivate(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.PENDING,
        )
        deactivated_by = uuid.uuid4()
        result = faktur.deactivate(deactivated_by)
        assert result.status == FakturStatus.DRAFT
        assert result.version == 2

    def test_deactivate_invalid_state_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        with pytest.raises(FakturInvalidStateError, match="Cannot deactivate"):
            faktur.deactivate(uuid.uuid4())

    def test_lock(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        locked_by = uuid.uuid4()
        result = faktur.lock(locked_by, "review")
        assert result.is_locked is True
        assert result.locked_by == locked_by
        assert result.locked_at is not None
        assert result.status == FakturStatus.LOCKED
        assert result.version == 2

    def test_lock_already_locked_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._locked_at = datetime.now()
        with pytest.raises(FakturLockedError, match="already locked"):
            faktur.lock(uuid.uuid4(), "test")

    def test_unlock(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._locked_at = datetime.now()
        faktur._locked_by = uuid.uuid4()
        unlocked_by = uuid.uuid4()
        result = faktur.unlock(unlocked_by)
        assert result.is_locked is False
        assert result.locked_by is None
        assert result.locked_at is None
        assert result.status == FakturStatus.PENDING
        assert result.version == 2

    def test_unlock_not_locked_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        with pytest.raises(FakturLockedError, match="is not locked"):
            faktur.unlock(uuid.uuid4())

    def test_void(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        voided_by = uuid.uuid4()
        result = faktur.void(voided_by, "test")
        assert result.status == FakturStatus.VOID
        assert result.cancellation_reason == "test"
        assert result.version == 2

    def test_void_locked_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._locked_at = datetime.now()
        with pytest.raises(FakturLockedError, match="is locked"):
            faktur.void(uuid.uuid4(), "reason")

    def test_download(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        # Ensure pdf_content exists
        faktur._pdf_content = b"pdf content"
        downloaded_by = uuid.uuid4()
        result = faktur.download(downloaded_by)
        assert result == b"pdf content"
        assert faktur.version == 2
        assert faktur._events[-1]["event_type"] == "faktur_keluaran_downloaded"

    def test_get_status(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.APPROVED,
        )
        faktur._approval_code = "APP-001"
        faktur._coretax_id = "COR-123"
        status = faktur.get_status()
        assert status["status"] == "approved"
        assert status["is_locked"] is False
        assert status["is_active"] is True
        assert status["can_submit"] is False
        assert status["can_cancel"] is True
        assert status["can_print"] is True
        assert status["approval_code"] == "APP-001"
        assert status["coretax_id"] == "COR-123"

    def test_get_history(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._history.append({"event": "test"})
        history = faktur.get_history()
        assert len(history) == 1

    def test_snapshot(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        snap = faktur.snapshot()
        assert snap["faktur_number"] == "010.2026.05.00000001"
        assert snap["status"] == "draft"
        assert snap["dpp"] == 100000000.0
        assert "hash" in snap

    def test_clone(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        cloned = faktur.clone("010.2026.05.00000002")
        assert cloned.faktur_number == "010.2026.05.00000002"
        assert cloned.status == FakturStatus.DRAFT
        assert cloned.dpp == faktur.dpp
        assert cloned.id != faktur.id

    def test_audit_trail(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._history.append({"event": "test"})
        trail = faktur.audit_trail()
        assert len(trail) == 1

    def test_calculate_tax(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("0"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        tax = faktur.calculate_tax()
        expected_ppn = (Decimal("100000000") * Decimal("0.11")).quantize(Decimal("0.01"))
        assert tax["dpp"] == Decimal("100000000")
        assert tax["ppn_terutang"] == expected_ppn
        assert tax["total"] == Decimal("100000000") + expected_ppn

    def test_recalculate(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("0"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        result = faktur.recalculate()
        expected_ppn = (Decimal("100000000") * Decimal("0.11")).quantize(Decimal("0.01"))
        assert result.ppn == expected_ppn
        assert result.version == 2

    def test_sign_without_private_key_does_nothing(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        # Ensure XML content is generated
        faktur._create_xml_faktur()
        result = faktur.sign(private_key=None)
        assert result is faktur  # returns self
        assert faktur.signature is None  # no signature

    def test_sign_with_private_key(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._create_xml_faktur()
        result = faktur.sign(private_key)
        assert result.signature is not None
        assert isinstance(result.signature, str)
        assert len(result.signature) > 0

    def test_sign_failure_raises(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        # Simulate failure during signing by passing a key that is not compatible
        # Actually we can patch the sign method to raise
        with patch("cryptography.hazmat.primitives.asymmetric.rsa.RSAPrivateKey.sign", side_effect=Exception("Signing error")):
            faktur._create_xml_faktur()
            with pytest.raises(FakturSigningError, match="Failed to sign"):
                faktur.sign(private_key)

    def test_generate_qr_code(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        result = faktur.generate_qr_code()
        assert result.qr_code is not None
        assert result.qr_code.startswith("QR:")
        assert len(result.qr_code) >= 100

    def test_check_approval_status_approved(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        status_data = {"status": "approved", "approval_code": "APP-001", "coretax_id": "COR-123"}
        result = faktur.check_approval_status(status_data)
        assert result.status == FakturStatus.APPROVED
        assert result.approval_code == "APP-001"
        assert result.coretax_id == "COR-123"

    def test_check_approval_status_not_approved(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.PENDING,
        )
        status_data = {"status": "pending", "approval_code": None}
        result = faktur.check_approval_status(status_data)
        assert result.status == FakturStatus.PENDING  # unchanged

    def test_resend_from_rejected(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.REJECTED,
        )
        faktur._rejection_reason = "Invalid"
        result = faktur.resend()
        assert result.status == FakturStatus.PENDING
        assert result.rejection_reason == ""

    def test_resend_from_error(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.ERROR,
        )
        result = faktur.resend()
        assert result.status == FakturStatus.PENDING

    def test_resend_invalid_state_raises(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.APPROVED,
        )
        with pytest.raises(FakturInvalidStateError, match="Cannot resend"):
            faktur.resend()

    def test_set_coretax_response_success(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        response = {
            "status": "success",
            "approval_code": "APP-001",
            "faktur_id": "COR-123",
            "qr_code": "QR:abcd",
        }
        result = faktur.set_coretax_response(response)
        assert result.approval_code == "APP-001"
        assert result.coretax_id == "COR-123"
        assert result.qr_code == "QR:abcd"
        assert result.status == FakturStatus.APPROVED
        assert result.approved_at is not None
        assert result.version == 2

    def test_set_coretax_response_not_success(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            status=FakturStatus.PENDING,
        )
        response = {"status": "pending", "approval_code": "APP-001"}
        result = faktur.set_coretax_response(response)
        assert result.status == FakturStatus.PENDING  # unchanged

    def test_set_xml_content(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        xml_content = "<xml/>"
        result = faktur.set_xml_content(xml_content)
        assert result.xml_content == xml_content

    def test_set_pdf_content(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        pdf_content = b"pdf data"
        result = faktur.set_pdf_content(pdf_content)
        assert result.pdf_content == pdf_content

    def test_private__create_xml_faktur(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
            jenis_transaksi="01",
            status_pembayaran="1",
            alamat_penjual="Jl. A",
            alamat_pembeli="Jl. B",
            keterangan="Test",
            referensi="REF001",
        )
        xml = faktur._create_xml_faktur()
        assert "Faktur" in xml
        assert "KodeDokumen" in xml
        assert "01" in xml  # jenis transaksi
        assert "NomorFaktur" in xml
        assert "010.2026.05.00000001" in xml
        assert "TanggalFaktur" in xml
        assert date.today().strftime("%Y-%m-%d") in xml
        assert "NPWP" in xml
        assert "123456789012345" in xml
        assert "PT Maju Jaya" in xml
        assert "Jl. A" in xml
        assert "Jl. B" in xml
        assert "100000000.00" in xml
        assert "11000000.00" in xml
        assert "DPP" in xml
        assert "PPN" in xml
        assert "Keterangan" in xml
        assert "Test" in xml
        assert "Referensi" in xml
        assert "REF001" in xml

    def test_private__create_xml_faktur_failure(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        with patch("xml.etree.ElementTree.tostring", side_effect=Exception("XML error")):
            with pytest.raises(FakturXMLGenerationError, match="Failed to create XML"):
                faktur._create_xml_faktur()

    def test_private__generate_qr_code(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        faktur._generate_qr_code()
        assert faktur.qr_code is not None
        assert faktur.qr_code.startswith("QR:")

    def test_private__create_pdf(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        pdf = faktur._create_pdf()
        assert pdf is not None
        # PDF should start with %PDF
        assert pdf.startswith(b'%PDF') or pdf.startswith(b'%PDF-')  # reportlab or fallback?

    def test_private__calculate_hash(self):
        faktur = FakturKeluaran(
            faktur_number="010.2026.05.00000001",
            nsfp="00000001",
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            dpp=Decimal("100000000"),
            ppn=Decimal("11000000"),
            tanggal_faktur=date.today(),
            tahun=2026,
            bulan=5,
        )
        h1 = faktur._hash
        faktur._dpp = Decimal("150000000")
        faktur._calculate_hash()
        assert faktur._hash != h1


class TestFakturKeluaranGeneratorAdditional:
    """Additional tests for FakturKeluaranGenerator to cover missing methods."""

    def test_load_config_with_config(self):
        config = {"custom": "value"}
        generator = FakturKeluaranGenerator(config=config)
        result = generator._load_config()
        assert result == config

    def test_load_config_without_config(self):
        with patch("adapters.coretax_djp.faktur_keluaran_generator.FakturKeluaranGenerator._load_signing_key"):
            generator = FakturKeluaranGenerator(config=None)
            result = generator._load_config()
            assert "coretax_djp" in result
            assert "faktur_keluaran" in result["coretax_djp"]
            assert "private_key_path" in result["coretax_djp"]["faktur_keluaran"]

    def test_load_signing_key_with_hsm(self):
        with patch("adapters.coretax_djp.faktur_keluaran_generator.HSMSigner") as mock_hsm:
            mock_hsm.return_value = MagicMock()
            config = {"coretax_djp": {"faktur_keluaran": {"use_hsm": True}}}
            generator = FakturKeluaranGenerator(config=config)
            assert generator._hsm_signer is not None
            generator._hsm_signer = MagicMock()

    def test_load_signing_key_hsm_fallback(self):
        with patch("adapters.coretax_djp.faktur_keluaran_generator.HSMSigner", side_effect=Exception("HSM error")):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.side_effect = [MagicMock(), MagicMock()]
                generator = FakturKeluaranGenerator(config={})
                assert generator._private_key is not None
                assert generator._certificate is not None

    def test_load_signing_key_file_error(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch("logging.Logger.warning") as mock_warning:
                generator = FakturKeluaranGenerator(config={})
                assert generator._private_key is None
                mock_warning.assert_called()

    async def test_get_coretax_client_caches(self):
        with patch("adapters.coretax_djp.faktur_keluaran_generator.get_coretax_client") as mock_get:
            mock_client = AsyncMock()
            mock_get.return_value = mock_client
            generator = FakturKeluaranGenerator()
            client1 = await generator._get_coretax_client()
            assert client1 is mock_client
            mock_get.assert_called_once()
            client2 = await generator._get_coretax_client()
            assert client2 is client1
            assert mock_get.call_count == 1

    def test_get_cache_key(self):
        generator = FakturKeluaranGenerator()
        key = generator._get_cache_key("FK-001")
        assert key == "faktur_keluaran:FK-001"

    async def test_get_cached(self):
        generator = FakturKeluaranGenerator()
        generator._cache["test_key"] = {"data": "value"}
        result = await generator._get_cached("test_key")
        assert result == {"data": "value"}

    async def test_get_cached_missing(self):
        generator = FakturKeluaranGenerator()
        result = await generator._get_cached("missing")
        assert result is None

    async def test_set_cached(self):
        generator = FakturKeluaranGenerator()
        await generator._set_cached("test_key", {"data": "value"})
        assert generator._cache["test_key"] == {"data": "value"}

    def test_generate_faktur_id(self):
        generator = FakturKeluaranGenerator()
        faktur_id = generator._generate_faktur_id("01", 2026, 5, "00000001")
        assert faktur_id == "01.2026.05.00000001"

    def test_generate_long_qr_code(self):
        generator = FakturKeluaranGenerator()
        qr = generator._generate_long_qr_code("test_base")
        assert qr.startswith("QR:")
        assert len(qr) >= 100

    def test_generate_returns_dummy(self):
        generator = FakturKeluaranGenerator()
        data = {
            "dpp": 100000000,
            "ppn": 11000000,
            "penjual_npwp": "123456789012345",
            "pembeli_npwp": "987654321098765",
            "nsfp": "00000001",
            "tahun": 2026,
            "bulan": 5,
        }
        dummy = generator.generate(data)
        assert dummy.kode_faktur == "01"
        assert dummy.is_valid is True
        assert dummy.ppn == Decimal("11000000")
        assert dummy.dpp == Decimal("100000000")

    def test_generate_with_warning(self, caplog):
        generator = FakturKeluaranGenerator()
        data = {
            "dpp": 100000000,
            "ppn": 5000000,  # wrong ppn
            "penjual_npwp": "123456789012345",
            "pembeli_npwp": "987654321098765",
            "nsfp": "00000001",
            "tahun": 2026,
            "bulan": 5,
        }
        with caplog.at_level("WARNING"):
            dummy = generator.generate(data)
            assert "PPN tidak sesuai tarif 11%" in caplog.text

    def test_submit_dummy_invalid(self):
        generator = FakturKeluaranGenerator()
        dummy = generator.generate({})  # invalid because missing keys
        result = generator.submit(dummy)
        assert result.status_code == 400

    def test_submit_dummy_valid(self):
        generator = FakturKeluaranGenerator()
        dummy = generator.generate_example()
        result = generator.submit(dummy)
        assert result.status_code == 201
        assert result.approval_code is not None

    def test_generate_example(self):
        generator = FakturKeluaranGenerator()
        dummy = generator.generate_example()
        assert dummy.kode_faktur == "010"
        assert dummy.status == "SUBMITTED"
        assert dummy.is_valid is True

    async def test_get_faktur_generator_singleton(self):
        with patch("adapters.coretax_djp.faktur_keluaran_generator.FakturKeluaranGenerator") as MockGen:
            MockGen.return_value = MagicMock()
            gen1 = await get_faktur_generator()
            gen2 = await get_faktur_generator()
            assert gen1 is gen2
            assert MockGen.call_count == 1       