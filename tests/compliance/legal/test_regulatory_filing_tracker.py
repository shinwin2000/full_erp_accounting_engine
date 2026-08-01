# tests/compliance/legal/test_regulatory_filing_tracker.py
# Comprehensive tests for compliance/legal/regulatory_filing_tracker.py

import json
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest

from compliance.legal.regulatory_filing_tracker import (
    FilingNotFoundError,
    FilingStatus,
    FilingTrackerError,
    FilingType,
    InvalidStatusTransitionError,
    RegulatoryFiling,
    RegulatoryFilingTracker,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_today():
    return date(2026, 7, 27)


@pytest.fixture(autouse=True)
def mock_today(fixed_today):
    with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
        mock_date.today.return_value = fixed_today
        yield mock_date


@pytest.fixture
def sample_filing():
    return RegulatoryFiling(
        filing_id=uuid4(),
        filing_type=FilingType.TAX_RETURN,
        regulatory_body="DJP",
        jurisdiction="ID",
        due_date=date(2026, 8, 10),
        title="SPT Masa PPN",
        description="Laporan PPN",
        status=FilingStatus.DRAFT,
    )


@pytest.fixture
def tracker():
    return RegulatoryFilingTracker()


@pytest.fixture
def tracker_with_filings(tracker):
    fid1 = tracker.create_filing(
        filing_type=FilingType.TAX_RETURN,
        regulatory_body="DJP",
        jurisdiction="ID",
        due_date=date(2026, 8, 10),
        title="SPT PPN",
    )
    tracker.create_filing(
        filing_type=FilingType.FINANCIAL_STATEMENT,
        regulatory_body="OJK",
        jurisdiction="ID",
        due_date=date(2026, 7, 20),
        title="LKPBU",
    )
    tracker.create_filing(
        filing_type=FilingType.AML_REPORT,
        regulatory_body="PPATK",
        jurisdiction="ID",
        due_date=date(2026, 8, 5),
        title="STR",
    )
    # Submit one
    tracker.submit_filing(fid1, submitted_by=uuid4(), reference_number="REF123")
    return tracker


# ============================================================================
# Tests for Enums
# ============================================================================

class TestFilingStatus:
    def test_members_exist(self):
        assert hasattr(FilingStatus, "DRAFT")
        assert hasattr(FilingStatus, "SUBMITTED")
        assert hasattr(FilingStatus, "ACKNOWLEDGED")
        assert hasattr(FilingStatus, "REJECTED")
        assert hasattr(FilingStatus, "COMPLETED")
        assert hasattr(FilingStatus, "EXPIRED")

    def test_member_is_instance(self):
        assert isinstance(FilingStatus.DRAFT, FilingStatus)


class TestFilingType:
    def test_members_exist(self):
        assert hasattr(FilingType, "TAX_RETURN")
        assert hasattr(FilingType, "FINANCIAL_STATEMENT")
        assert hasattr(FilingType, "ANNUAL_REPORT")
        assert hasattr(FilingType, "CAPITAL_ADJUSTMENT")
        assert hasattr(FilingType, "AUDIT_REPORT")
        assert hasattr(FilingType, "AML_REPORT")
        assert hasattr(FilingType, "OTHER")

    def test_member_is_instance(self):
        assert isinstance(FilingType.TAX_RETURN, FilingType)


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_filing_tracker_error(self):
        with pytest.raises(FilingTrackerError):
            raise FilingTrackerError("test")

    def test_filing_not_found_error(self):
        with pytest.raises(FilingNotFoundError):
            raise FilingNotFoundError("not found")

    def test_invalid_status_transition_error(self):
        with pytest.raises(InvalidStatusTransitionError):
            raise InvalidStatusTransitionError("invalid")


# ============================================================================
# Tests for RegulatoryFiling
# ============================================================================

class TestRegulatoryFiling:
    def test_construction(self, sample_filing):
        assert sample_filing.id is not None
        assert sample_filing.filing_type == FilingType.TAX_RETURN
        assert sample_filing.regulatory_body == "DJP"
        assert sample_filing.status == FilingStatus.DRAFT
        assert sample_filing.created_at is not None
        assert sample_filing.updated_at is not None
        assert sample_filing._hash != ""

    def test_compute_hash(self, sample_filing):
        h1 = sample_filing._compute_hash()
        h2 = sample_filing._compute_hash()
        assert h1 == h2
        # Change status
        sample_filing.status = FilingStatus.SUBMITTED
        h3 = sample_filing._compute_hash()
        assert h1 != h3

    def test_submit_from_draft(self, sample_filing):
        submitter = uuid4()
        sample_filing.submit(submitter, "REF-001")
        assert sample_filing.status == FilingStatus.SUBMITTED
        assert sample_filing.submitted_date == date.today()
        assert sample_filing.submitted_by == submitter
        assert sample_filing.reference_number == "REF-001"
        assert sample_filing.updated_at is not None
        assert sample_filing._hash != ""

    def test_submit_without_reference(self, sample_filing):
        submitter = uuid4()
        sample_filing.submit(submitter)
        assert sample_filing.reference_number is None

    def test_submit_from_invalid_status_raises(self, sample_filing):
        sample_filing.status = FilingStatus.SUBMITTED
        with pytest.raises(InvalidStatusTransitionError, match="Cannot submit"):
            sample_filing.submit(uuid4())

    def test_acknowledge_from_submitted(self, sample_filing):
        sample_filing.submit(uuid4(), "REF")
        sample_filing.acknowledge("ACK-001")
        assert sample_filing.status == FilingStatus.ACKNOWLEDGED
        assert sample_filing.acknowledged_date == date.today()
        assert sample_filing.reference_number == "ACK-001"

    def test_acknowledge_from_acknowledged(self, sample_filing):
        sample_filing.submit(uuid4(), "REF")
        sample_filing.acknowledge("ACK-001")
        # Call again should update reference
        sample_filing.acknowledge("ACK-002")
        assert sample_filing.reference_number == "ACK-002"

    def test_acknowledge_from_invalid_status_raises(self, sample_filing):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot acknowledge"):
            sample_filing.acknowledge("ACK")

    def test_reject_from_submitted(self, sample_filing):
        sample_filing.submit(uuid4(), "REF")
        sample_filing.reject("Invalid data")
        assert sample_filing.status == FilingStatus.REJECTED
        assert sample_filing.rejection_reason == "Invalid data"
        assert sample_filing.updated_at is not None
        assert sample_filing._hash != ""

    def test_reject_from_invalid_status_raises(self, sample_filing):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot reject"):
            sample_filing.reject("reason")

    def test_complete_from_acknowledged(self, sample_filing):
        sample_filing.submit(uuid4(), "REF")
        sample_filing.acknowledge("ACK")
        sample_filing.complete()
        assert sample_filing.status == FilingStatus.COMPLETED

    def test_complete_from_submitted(self, sample_filing):
        sample_filing.submit(uuid4(), "REF")
        sample_filing.complete()
        assert sample_filing.status == FilingStatus.COMPLETED

    def test_complete_from_invalid_status_raises(self, sample_filing):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot complete"):
            sample_filing.complete()

    def test_mark_overdue_when_draft_and_due_date_passed(self, sample_filing):
        sample_filing.due_date = date(2026, 7, 20)  # past
        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            sample_filing.mark_overdue()
            assert sample_filing.status == FilingStatus.EXPIRED

    def test_mark_overdue_when_not_draft_or_not_overdue(self, sample_filing):
        sample_filing.status = FilingStatus.SUBMITTED
        sample_filing.due_date = date(2026, 7, 20)
        sample_filing.mark_overdue()
        assert sample_filing.status == FilingStatus.SUBMITTED  # unchanged

        # Not overdue
        sample_filing.status = FilingStatus.DRAFT
        sample_filing.due_date = date(2026, 8, 20)
        sample_filing.mark_overdue()
        assert sample_filing.status == FilingStatus.DRAFT

    def test_add_attachment(self, sample_filing):
        sample_filing.add_attachment("s3://bucket/file1.pdf")
        assert sample_filing.attachments == ["s3://bucket/file1.pdf"]
        sample_filing.add_attachment("s3://bucket/file2.pdf")
        assert sample_filing.attachments == ["s3://bucket/file1.pdf", "s3://bucket/file2.pdf"]
        assert sample_filing.updated_at is not None
        assert sample_filing._hash != ""

    def test_is_overdue(self, sample_filing):
        # Not overdue because due_date is in future
        sample_filing.due_date = date(2026, 8, 10)
        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            assert sample_filing.is_overdue() is False

        # Overdue: due_date past and status DRAFT
        sample_filing.due_date = date(2026, 7, 20)
        sample_filing.status = FilingStatus.DRAFT
        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            assert sample_filing.is_overdue() is True

        # Overdue but status SUBMITTED -> still overdue (based on logic: DRAFT or SUBMITTED)
        sample_filing.status = FilingStatus.SUBMITTED
        assert sample_filing.is_overdue() is True

        # Status ACKNOWLEDGED -> not overdue
        sample_filing.status = FilingStatus.ACKNOWLEDGED
        assert sample_filing.is_overdue() is False

        # With custom reference date
        assert sample_filing.is_overdue(reference_date=date(2026, 8, 1)) is False

    def test_to_dict(self, sample_filing):
        d = sample_filing.to_dict()
        assert d["filing_id"] == str(sample_filing.id)
        assert d["filing_type"] == "tax_return"
        assert d["regulatory_body"] == "DJP"
        assert d["status"] == "draft"
        assert d["due_date"] == "2026-08-10"
        assert d["hash"] == sample_filing._hash
        assert d["attachments"] == []


# ============================================================================
# Tests for RegulatoryFilingTracker
# ============================================================================

class TestRegulatoryFilingTracker:
    def test_create_filing(self, tracker):
        filing_id = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
            description="Desc",
        )
        assert filing_id in tracker._filings
        filing = tracker._filings[filing_id]
        assert filing.filing_type == FilingType.TAX_RETURN
        assert filing.regulatory_body == "DJP"
        assert filing.status == FilingStatus.DRAFT

    def test_get_filing_found(self, tracker):
        filing_id = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
        )
        retrieved = tracker.get_filing(filing_id)
        assert retrieved is not None
        assert retrieved.id == filing_id

    def test_get_filing_not_found(self, tracker):
        assert tracker.get_filing(uuid4()) is None

    def test_submit_filing_success(self, tracker):
        filing_id = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
        )
        result = tracker.submit_filing(filing_id, uuid4(), "REF")
        assert result is True
        filing = tracker.get_filing(filing_id)
        assert filing.status == FilingStatus.SUBMITTED

    def test_submit_filing_not_found(self, tracker):
        result = tracker.submit_filing(uuid4(), uuid4())
        assert result is False

    def test_acknowledge_filing_success(self, tracker):
        filing_id = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
        )
        tracker.submit_filing(filing_id, uuid4(), "REF")
        result = tracker.acknowledge_filing(filing_id, "ACK")
        assert result is True
        filing = tracker.get_filing(filing_id)
        assert filing.status == FilingStatus.ACKNOWLEDGED

    def test_acknowledge_filing_not_found(self, tracker):
        result = tracker.acknowledge_filing(uuid4(), "ACK")
        assert result is False

    def test_reject_filing_success(self, tracker):
        filing_id = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
        )
        tracker.submit_filing(filing_id, uuid4(), "REF")
        result = tracker.reject_filing(filing_id, "Invalid")
        assert result is True
        filing = tracker.get_filing(filing_id)
        assert filing.status == FilingStatus.REJECTED
        assert filing.rejection_reason == "Invalid"

    def test_reject_filing_not_found(self, tracker):
        result = tracker.reject_filing(uuid4(), "reason")
        assert result is False

    def test_complete_filing_success(self, tracker):
        filing_id = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
        )
        tracker.submit_filing(filing_id, uuid4(), "REF")
        result = tracker.complete_filing(filing_id)
        assert result is True
        filing = tracker.get_filing(filing_id)
        assert filing.status == FilingStatus.COMPLETED

    def test_complete_filing_not_found(self, tracker):
        result = tracker.complete_filing(uuid4())
        assert result is False

    def test_add_attachment_success(self, tracker):
        filing_id = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
        )
        result = tracker.add_attachment(filing_id, "s3://bucket/file.pdf")
        assert result is True
        filing = tracker.get_filing(filing_id)
        assert filing.attachments == ["s3://bucket/file.pdf"]

    def test_add_attachment_not_found(self, tracker):
        result = tracker.add_attachment(uuid4(), "url")
        assert result is False

    def test_get_filings_by_status(self, tracker_with_filings):
        # One filing is submitted, others are draft
        submitted = tracker_with_filings.get_filings_by_status(FilingStatus.SUBMITTED)
        assert len(submitted) == 1
        draft = tracker_with_filings.get_filings_by_status(FilingStatus.DRAFT)
        assert len(draft) == 2

    def test_get_filings_by_regulatory_body(self, tracker_with_filings):
        djp = tracker_with_filings.get_filings_by_regulatory_body("DJP")
        assert len(djp) == 1
        ojk = tracker_with_filings.get_filings_by_regulatory_body("OJK")
        assert len(ojk) == 1
        ppatk = tracker_with_filings.get_filings_by_regulatory_body("PPATK")
        assert len(ppatk) == 1

    def test_get_filings_by_jurisdiction(self, tracker_with_filings):
        # All have jurisdiction "ID"
        id_filings = tracker_with_filings.get_filings_by_jurisdiction("ID")
        assert len(id_filings) == 3
        others = tracker_with_filings.get_filings_by_jurisdiction("US")
        assert len(others) == 0

    def test_get_overdue_filings(self, tracker):
        # Create overdue filing
        fid1 = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 7, 20),  # past
            title="Overdue",
        )
        # Create non-overdue
        tracker.create_filing(
            filing_type=FilingType.FINANCIAL_STATEMENT,
            regulatory_body="OJK",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),  # future
            title="Future",
        )
        # Create submitted but overdue
        fid3 = tracker.create_filing(
            filing_type=FilingType.AML_REPORT,
            regulatory_body="PPATK",
            jurisdiction="ID",
            due_date=date(2026, 7, 15),  # past
            title="Submitted Overdue",
        )
        tracker.submit_filing(fid3, uuid4(), "REF")

        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            overdue = tracker.get_overdue_filings()
            # fid1 and fid3 are overdue (fid1 draft, fid3 submitted)
            # fid2 is not overdue
            assert len(overdue) == 2
            ids = {f.id for f in overdue}
            assert fid1 in ids
            assert fid3 in ids
            # Check that fid1 was marked expired
            filing = tracker.get_filing(fid1)
            assert filing.status == FilingStatus.EXPIRED

    def test_get_upcoming_filings(self, tracker):
        # Create filings with different due dates
        fid1 = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 1),
            title="Upcoming 1",
        )
        fid2 = tracker.create_filing(
            filing_type=FilingType.FINANCIAL_STATEMENT,
            regulatory_body="OJK",
            jurisdiction="ID",
            due_date=date(2026, 8, 20),
            title="Upcoming 2",
        )
        tracker.create_filing(
            filing_type=FilingType.AML_REPORT,
            regulatory_body="PPATK",
            jurisdiction="ID",
            due_date=date(2026, 9, 15),
            title="Beyond",
        )
        # Submit one (should not be in upcoming because only DRAFT)
        tracker.submit_filing(fid2, uuid4(), "REF")

        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            upcoming = tracker.get_upcoming_filings(days_ahead=30)
            # Should include fid1 (due Aug 1) and fid2? fid2 is submitted, so not included
            # fid3 due Sep 15 > 30 days, not included
            assert len(upcoming) == 1
            assert upcoming[0].id == fid1

    def test_send_reminders(self, tracker):
        # Create an upcoming filing
        fid1 = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 1),
            title="Reminder Test",
        )
        # Create one not upcoming
        tracker.create_filing(
            filing_type=FilingType.FINANCIAL_STATEMENT,
            regulatory_body="OJK",
            jurisdiction="ID",
            due_date=date(2026, 9, 15),
            title="Far",
        )

        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)

            # Dry run
            reminders = tracker.send_reminders(days_ahead=7, dry_run=True)
            assert len(reminders) == 1  # fid1 due in 5 days
            assert reminders[0]["filing_id"] == str(fid1)
            assert reminders[0]["days_left"] == 5
            # Check that reminder_sent_at is not set
            filing = tracker.get_filing(fid1)
            assert filing.reminder_sent_at is None

            # Non-dry run
            reminders2 = tracker.send_reminders(days_ahead=7, dry_run=False)
            assert len(reminders2) == 1
            filing2 = tracker.get_filing(fid1)
            assert filing2.reminder_sent_at is not None
            assert filing2._hash != ""

    def test_generate_report(self, tracker_with_filings):
        report = tracker_with_filings.generate_report()
        assert report["total_filings"] == 3
        assert report["by_status"]["draft"] == 2
        assert report["by_status"]["submitted"] == 1
        assert report["by_status"]["acknowledged"] == 0
        assert report["by_jurisdiction"]["ID"] == 3
        assert report["overdue_count"] == 0
        assert report["upcoming_count"] >= 0

    def test_export_to_json(self, tracker_with_filings, tmp_path):
        file_path = tmp_path / "filings.json"
        tracker_with_filings.export_to_json(str(file_path))
        assert file_path.exists()
        data = json.loads(file_path.read_text())
        assert "report" in data
        assert "filings" in data
        assert len(data["filings"]) == 3
        assert data["report"]["total_filings"] == 3

    def test_overdue_filings_are_marked_expired_in_report(self, tracker):
        fid = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 7, 20),
            title="Overdue",
        )
        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            # get_overdue_filings marks expired
            tracker.get_overdue_filings()
            filing = tracker.get_filing(fid)
            assert filing.status == FilingStatus.EXPIRED

    def test_attachment_hash_update(self, tracker):
        fid = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 10),
            title="SPT",
        )
        filing = tracker.get_filing(fid)
        old_hash = filing._hash
        tracker.add_attachment(fid, "s3://file.pdf")
        new_hash = filing._hash
        assert old_hash != new_hash

    def test_reminder_does_not_send_for_non_draft(self, tracker):
        fid = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 8, 1),
            title="SPT",
        )
        tracker.submit_filing(fid, uuid4(), "REF")
        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            reminders = tracker.send_reminders(days_ahead=7, dry_run=False)
            # Should be empty because submitted filings are not in upcoming (only DRAFT)
            assert len(reminders) == 0

    def test_mark_overdue_on_get_overdue(self, tracker):
        fid = tracker.create_filing(
            filing_type=FilingType.TAX_RETURN,
            regulatory_body="DJP",
            jurisdiction="ID",
            due_date=date(2026, 7, 20),
            title="Overdue",
        )
        with patch("compliance.legal.regulatory_filing_tracker.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 27)
            tracker.get_overdue_filings()
            filing = tracker.get_filing(fid)
            assert filing.status == FilingStatus.EXPIRED
            # Calling again should not change
            tracker.get_overdue_filings()
            assert filing.status == FilingStatus.EXPIRED
