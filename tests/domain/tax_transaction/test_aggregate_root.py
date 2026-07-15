#!/usr/bin/env python3
"""
tests/unit/test_aggregate_root.py
Test untuk domain/tax_transaction/aggregate_root.py
Mencakup: FakturPajak, SPTSubmission, Bupot, EMeterai
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from domain.shared_value_objects.money_vo import Money
from domain.tax_transaction.aggregate_root import (
    Bupot,
    EMeterai,
    FakturPajak,
    FakturStatus,
    SPTStatus,
    SPTSubmission,
)


class TestFakturPajak:
    def test_create_valid_faktur(self):
        """Test creation of valid FakturPajak."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        assert faktur.status == FakturStatus.DRAFT
        assert faktur.version == 1
        assert faktur.dpp.amount == Decimal("100000000")
        assert faktur.ppn.amount == Decimal("11000000")

    def test_validate_rejects_future_date(self):
        """Test validation rejects future faktur date."""
        with pytest.raises(ValueError, match="cannot be in the future"):
            FakturPajak(
                id=uuid.uuid4(),
                faktur_number="010.2026.05.00000001",
                nsfp_used="00000001",
                is_keluaran=True,
                npwp_penjual="123456789012345",
                nama_penjual="PT Maju Jaya",
                alamat_penjual="Jakarta",
                npwp_pembeli="987654321098765",
                nama_pembeli="PT Sejahtera",
                alamat_pembeli="Bandung",
                faktur_date=date.today() + timedelta(days=1),
                dpp=Money(Decimal("100000000"), "IDR"),
                ppn=Money(Decimal("11000000"), "IDR"),
            )

    def test_validate_rejects_non_idr_currency(self):
        """Test validation rejects non-IDR currency."""
        with pytest.raises(ValueError, match="must be in IDR"):
            FakturPajak(
                id=uuid.uuid4(),
                faktur_number="010.2026.05.00000001",
                nsfp_used="00000001",
                is_keluaran=True,
                npwp_penjual="123456789012345",
                nama_penjual="PT Maju Jaya",
                alamat_penjual="Jakarta",
                npwp_pembeli="987654321098765",
                nama_pembeli="PT Sejahtera",
                alamat_pembeli="Bandung",
                faktur_date=date.today(),
                dpp=Money(Decimal("100000000"), "USD"),
                ppn=Money(Decimal("11000000"), "IDR"),
            )

    def test_submit_transitions_to_submitted(self):
        """Test submit changes status to SUBMITTED."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        submitted = faktur.submit(uuid.uuid4())
        assert submitted.status == FakturStatus.SUBMITTED
        assert submitted.version == 2

    def test_submit_non_draft_raises(self):
        """Test submit from non-DRAFT status raises."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
            status=FakturStatus.SUBMITTED,
        )
        with pytest.raises(ValueError, match="Cannot submit"):
            faktur.submit(uuid.uuid4())

    def test_approve_changes_status(self):
        """Test approve changes status to APPROVED."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        submitted = faktur.submit(uuid.uuid4())
        approved = submitted.approve(str(uuid.uuid4()), "faktur", "approver")
        assert approved.status == FakturStatus.APPROVED
        assert approved.approval_code is not None

    def test_reject_sets_rejection_reason(self):
        """Test reject sets rejection reason."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        submitted = faktur.submit(uuid.uuid4())
        rejected = submitted.reject("rejector", "faktur", "rejector", "Invalid NPWP")
        assert rejected.status == FakturStatus.REJECTED
        assert rejected.rejection_reason == "Invalid NPWP"

    def test_cancel_cancels_faktur(self):
        """Test cancel changes status to CANCELLED."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        cancelled = faktur.cancel("canceller", "faktur", "canceller", "Duplicate")
        assert cancelled.status == FakturStatus.CANCELLED
        assert cancelled.cancellation_reason == "Duplicate"

    def test_cancel_non_cancellable_status_raises(self):
        """Test cancel from non-cancellable status raises."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
            status=FakturStatus.APPROVED,
        )
        with pytest.raises(ValueError, match="Cannot cancel"):
            faktur.cancel("canceller", "faktur", "canceller", "Test")

    def test_update_allowed_in_draft(self):
        """Test update works in DRAFT status."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        updated = faktur.update("updater", keterangan="Updated description")
        assert updated.keterangan == "Updated description"
        assert updated.version == 2

    def test_update_not_allowed_in_approved(self):
        """Test update from APPROVED status raises."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
            status=FakturStatus.APPROVED,
        )
        with pytest.raises(ValueError, match="Cannot update"):
            faktur.update("updater", keterangan="Should fail")

    def test_delete_marks_cancelled(self):
        """Test delete changes status to CANCELLED."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        deleted = faktur.delete("deleter", "Test")
        assert deleted.status == FakturStatus.CANCELLED

    def test_restore_recovers_cancelled(self):
        """Test restore recovers cancelled faktur."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        cancelled = faktur.cancel("canceller", "faktur", "canceller", "Test")
        restored = cancelled.restore("restorer")
        assert restored.status == FakturStatus.DRAFT

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        d = faktur.to_dict()
        assert d["faktur_number"] == "010.2026.05.00000001"
        assert d["npwp_penjual"] == "123456789012345"
        assert d["npwp_pembeli"] == "987654321098765"
        assert "dpp" in d
        assert "ppn" in d
        assert d["status"] == "draft"

    def test_from_dict_reconstructs(self):
        """Test from_dict reconstructs object."""
        original = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        d = original.to_dict()
        reconstructed = FakturPajak.from_dict(d)
        assert reconstructed.faktur_number == original.faktur_number
        assert reconstructed.npwp_penjual == original.npwp_penjual
        assert reconstructed.dpp.amount == original.dpp.amount

    def test_clone_creates_draft_copy(self):
        """Test clone creates new draft copy."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        cloned = faktur.clone()
        assert cloned.id != faktur.id
        assert cloned.faktur_number == f"{faktur.faktur_number}_COPY"
        assert cloned.status == FakturStatus.DRAFT
        assert cloned.version == 1

    def test_validate_returns_errors(self):
        """Test validate returns errors for invalid state."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123",  # invalid NPWP
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        result = faktur.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_add_child(self):
        """Test add_child adds line to faktur."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        child = {"id": "line1", "description": "Test line"}
        updated = faktur.add_child(child, "creator")
        assert len(updated.lines) == 1
        assert updated.lines[0]["id"] == "line1"

    def test_get_events_returns_events(self):
        """Test get_events returns registered events."""
        faktur = FakturPajak(
            id=uuid.uuid4(),
            faktur_number="010.2026.05.00000001",
            nsfp_used="00000001",
            is_keluaran=True,
            npwp_penjual="123456789012345",
            nama_penjual="PT Maju Jaya",
            alamat_penjual="Jakarta",
            npwp_pembeli="987654321098765",
            nama_pembeli="PT Sejahtera",
            alamat_pembeli="Bandung",
            faktur_date=date.today(),
            dpp=Money(Decimal("100000000"), "IDR"),
            ppn=Money(Decimal("11000000"), "IDR"),
        )
        faktur.register_event({"type": "test_event"})
        events = faktur.get_events()
        assert len(events) == 1
        assert events[0]["type"] == "test_event"


class TestSPTSubmission:
    def test_create_valid_spt(self):
        """Test creation of valid SPTSubmission."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        assert spt.spt_number == "SPT-2026-001"
        assert spt.status == SPTStatus.DRAFT
        assert spt.tahun == 2026
        assert spt.bulan == 5

    def test_validate_invalid_tahun(self):
        """Test validation rejects invalid tax year."""
        with pytest.raises(ValueError, match="Invalid tax year"):
            SPTSubmission(
                id=uuid.uuid4(),
                spt_number="SPT-2026-001",
                spt_type="PPN",
                npwp="123456789012345",
                tahun=1999,  # invalid
            )

    def test_submit_transitions_to_submitted(self):
        """Test submit changes status to SUBMITTED."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        submitted = spt.submit(uuid.uuid4())
        assert submitted.status == SPTStatus.SUBMITTED
        assert submitted.submitted_at is not None

    def test_approve_sets_approval_date(self):
        """Test approve sets approval date and tracking ID."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        submitted = spt.submit(uuid.uuid4())
        approved = submitted.approve(date.today(), "TRACK-123")
        assert approved.status == SPTStatus.APPROVED
        assert approved.coretax_tracking_id == "TRACK-123"
        assert approved.approval_date == date.today()

    def test_reject_sets_rejection_reason(self):
        """Test reject sets rejection reason."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        submitted = spt.submit(uuid.uuid4())
        rejected = submitted.reject("Data tidak lengkap")
        assert rejected.status == SPTStatus.REJECTED
        assert rejected.rejection_reason == "Data tidak lengkap"

    def test_update_changes_fields(self):
        """Test update modifies fields."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        updated = spt.update("admin", spt_type="PPH")
        assert updated.spt_type == "PPH"
        assert updated.version == 2

    def test_delete_marks_void(self):
        """Test delete changes status to VOID."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        deleted = spt.delete("admin", "Test")
        assert deleted.status == SPTStatus.VOID

    def test_restore_recovers_voided(self):
        """Test restore recovers voided SPT."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        deleted = spt.delete("admin", "Test")
        restored = deleted.restore("admin")
        assert restored.status == SPTStatus.DRAFT

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        spt = SPTSubmission(
            id=uuid.uuid4(),
            spt_number="SPT-2026-001",
            spt_type="PPN",
            npwp="123456789012345",
            tahun=2026,
            bulan=5,
        )
        d = spt.to_dict()
        assert d["spt_number"] == "SPT-2026-001"
        assert d["spt_type"] == "PPN"
        assert d["npwp"] == "123456789012345"
        assert d["tahun"] == 2026
        assert d["bulan"] == 5


class TestBupot:
    def test_create_valid_bupot(self):
        """Test creation of valid Bupot."""
        bupot = Bupot(
            id=uuid.uuid4(),
            bupot_number="BUPOT-2026-001",
            npwp_pemotong="123456789012345",
            npwp_penerima="987654321098765",
            nama_penerima="PT Penerima",
            jenis_pajak="PPh 23",
            masa_pajak=5,
            tahun_pajak=2026,
            dasar_pemotongan=Decimal("100000000"),
            tarif=Decimal("0.02"),
            pph_dipotong=Decimal("2000000"),
        )
        assert bupot.bupot_number == "BUPOT-2026-001"
        assert bupot.status == "draft"
        assert bupot.tarif == Decimal("0.02")
        assert bupot.pph_dipotong == Decimal("2000000")

    def test_validate_tarif_range(self):
        """Test validation rejects tarif out of range."""
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 1"):
            Bupot(
                id=uuid.uuid4(),
                bupot_number="BUPOT-2026-001",
                npwp_pemotong="123456789012345",
                npwp_penerima="987654321098765",
                nama_penerima="PT Penerima",
                jenis_pajak="PPh 23",
                masa_pajak=5,
                tahun_pajak=2026,
                dasar_pemotongan=Decimal("100000000"),
                tarif=Decimal("1.5"),  # > 1
                pph_dipotong=Decimal("2000000"),
            )

    def test_submit_transitions_to_submitted(self):
        """Test submit changes status to submitted."""
        bupot = Bupot(
            id=uuid.uuid4(),
            bupot_number="BUPOT-2026-001",
            npwp_pemotong="123456789012345",
            npwp_penerima="987654321098765",
            nama_penerima="PT Penerima",
            jenis_pajak="PPh 23",
            masa_pajak=5,
            tahun_pajak=2026,
            dasar_pemotongan=Decimal("100000000"),
            tarif=Decimal("0.02"),
            pph_dipotong=Decimal("2000000"),
        )
        submitted = bupot.submit(uuid.uuid4())
        assert submitted.status == "submitted"
        assert submitted.version == 2

    def test_approve_sets_coretax_id(self):
        """Test approve sets coretax_id."""
        bupot = Bupot(
            id=uuid.uuid4(),
            bupot_number="BUPOT-2026-001",
            npwp_pemotong="123456789012345",
            npwp_penerima="987654321098765",
            nama_penerima="PT Penerima",
            jenis_pajak="PPh 23",
            masa_pajak=5,
            tahun_pajak=2026,
            dasar_pemotongan=Decimal("100000000"),
            tarif=Decimal("0.02"),
            pph_dipotong=Decimal("2000000"),
        )
        submitted = bupot.submit(uuid.uuid4())
        approved = submitted.approve("CORETAX-123")
        assert approved.status == "approved"
        assert approved.coretax_id == "CORETAX-123"

    def test_cancel_cancels_bupot(self):
        """Test cancel changes status to cancelled."""
        bupot = Bupot(
            id=uuid.uuid4(),
            bupot_number="BUPOT-2026-001",
            npwp_pemotong="123456789012345",
            npwp_penerima="987654321098765",
            nama_penerima="PT Penerima",
            jenis_pajak="PPh 23",
            masa_pajak=5,
            tahun_pajak=2026,
            dasar_pemotongan=Decimal("100000000"),
            tarif=Decimal("0.02"),
            pph_dipotong=Decimal("2000000"),
        )
        cancelled = bupot.cancel("admin", "Duplicate")
        assert cancelled.status == "cancelled"

    def test_update_changes_fields(self):
        """Test update modifies fields."""
        bupot = Bupot(
            id=uuid.uuid4(),
            bupot_number="BUPOT-2026-001",
            npwp_pemotong="123456789012345",
            npwp_penerima="987654321098765",
            nama_penerima="PT Penerima",
            jenis_pajak="PPh 23",
            masa_pajak=5,
            tahun_pajak=2026,
            dasar_pemotongan=Decimal("100000000"),
            tarif=Decimal("0.02"),
            pph_dipotong=Decimal("2000000"),
        )
        updated = bupot.update("admin", tarif=Decimal("0.03"))
        assert updated.tarif == Decimal("0.03")
        assert updated.version == 2

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        bupot = Bupot(
            id=uuid.uuid4(),
            bupot_number="BUPOT-2026-001",
            npwp_pemotong="123456789012345",
            npwp_penerima="987654321098765",
            nama_penerima="PT Penerima",
            jenis_pajak="PPh 23",
            masa_pajak=5,
            tahun_pajak=2026,
            dasar_pemotongan=Decimal("100000000"),
            tarif=Decimal("0.02"),
            pph_dipotong=Decimal("2000000"),
        )
        d = bupot.to_dict()
        assert d["bupot_number"] == "BUPOT-2026-001"
        assert d["npwp_pemotong"] == "123456789012345"
        assert d["dasar_pemotongan"] == "100000000"
        assert d["tarif"] == "0.02"


class TestEMeterai:
    def test_create_valid_emeterai(self):
        """Test creation of valid EMeterai."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="MTR-001",
            npwp="123456789012345",
            nominal=Money(Decimal("10000"), "IDR"),
        )
        assert meterai.meterai_code == "MTR-001"
        assert meterai.status == "available"
        assert meterai.nominal.amount == Decimal("10000")

    def test_value_property(self):
        """Test value property returns nominal."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="MTR-001",
            npwp="123456789012345",
            nominal=Money(Decimal("10000"), "IDR"),
        )
        assert meterai.value == meterai.nominal

    def test_use_changes_status_to_used(self):
        """Test use changes status to used and sets fields."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="MTR-001",
            npwp="123456789012345",
            nominal=Money(Decimal("10000"), "IDR"),
        )
        used = meterai.use("DOC-001", uuid.uuid4())
        assert used.status == "used"
        assert used.used_on_document == "DOC-001"
        assert used.used_at is not None

    def test_use_unavailable_raises(self):
        """Test use on unavailable meterai raises."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="MTR-001",
            npwp="123456789012345",
            nominal=Money(Decimal("10000"), "IDR"),
            status="used",
        )
        with pytest.raises(ValueError, match="not available"):
            meterai.use("DOC-001", uuid.uuid4())

    def test_expire_changes_status_to_expired(self):
        """Test expire changes status to expired."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="MTR-001",
            npwp="123456789012345",
            nominal=Money(Decimal("10000"), "IDR"),
        )
        expired = meterai.expire()
        assert expired.status == "expired"

    def test_validate_returns_errors(self):
        """Test validate returns errors for invalid state."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="",  # invalid
            npwp="123456789012345",
            nominal=Money(Decimal("-1000"), "IDR"),  # negative
        )
        result = meterai.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="MTR-001",
            npwp="123456789012345",
            nominal=Money(Decimal("10000"), "IDR"),
        )
        d = meterai.to_dict()
        assert d["meterai_code"] == "MTR-001"
        assert d["npwp"] == "123456789012345"
        assert d["value"]["amount"] == "10000"
        assert d["status"] == "available"

    def test_clone_creates_new_copy(self):
        """Test clone creates new available copy."""
        meterai = EMeterai(
            id=uuid.uuid4(),
            meterai_code="MTR-001",
            npwp="123456789012345",
            nominal=Money(Decimal("10000"), "IDR"),
        )
        cloned = meterai.clone()
        assert cloned.id != meterai.id
        assert cloned.meterai_code == "MTR-001_COPY"
        assert cloned.status == "available"