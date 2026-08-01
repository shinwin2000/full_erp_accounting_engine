# tests/compliance/ethics/test_whistleblower_case_tracker.py
"""
Comprehensive tests for compliance/ethics/whistleblower_case_tracker.py.

Covers:
- Enums: WhistleblowerCaseStatus, WhistleblowerCategory, WhistleblowerProtectionStatus
- EvidenceAttachment: construction, to_dict
- InvestigationNote: construction, to_dict
- WhistleblowerCase: all methods (assign_investigator, update_status, add_investigation_note,
  add_evidence, resolve, escalate, protect_reporter, report_retaliation, is_anonymous, to_dict)
- WhistleblowerCaseTracker: report_case, get_case, assign_case, update_case_status,
  add_investigation_note, add_evidence, resolve_case, escalate_case, protect_reporter,
  report_retaliation, get_cases_by_status, get_open_cases, get_cases_by_category,
  get_assigned_cases, generate_summary, to_json
- Edge cases: anonymous reporting, non-existent cases, status transitions, protection handling
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from uuid import uuid4

import pytest

from compliance.ethics.whistleblower_case_tracker import (
    EvidenceAttachment,
    InvestigationNote,
    WhistleblowerCase,
    WhistleblowerCaseStatus,
    WhistleblowerCaseTracker,
    WhistleblowerCategory,
    WhistleblowerProtectionStatus,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_datetime():
    """Fixed datetime for reproducible tests."""
    return datetime(2025, 1, 15, 12, 0, 0)


@pytest.fixture
def tracker():
    """Fresh WhistleblowerCaseTracker instance."""
    return WhistleblowerCaseTracker()


@pytest.fixture
def sample_case(tracker):
    """A sample case with known data."""
    case_id = tracker.report_case(
        report_text="Test report",
        category=WhistleblowerCategory.FRAUD,
        reported_by=uuid4(),
        reporter_contact="test@example.com",
    )
    return tracker.get_case(case_id)


@pytest.fixture
def anonymous_case(tracker):
    """An anonymous case."""
    case_id = tracker.report_case(
        report_text="Anonymous report",
        category=WhistleblowerCategory.CORRUPTION,
        reported_by=None,
    )
    return tracker.get_case(case_id)


# ============================================================================
# Tests for Enums
# ============================================================================

class TestWhistleblowerCaseStatus:
    def test_members(self):
        assert WhistleblowerCaseStatus.OPEN.value == "open"
        assert WhistleblowerCaseStatus.UNDER_INVESTIGATION.value == "under_investigation"
        assert WhistleblowerCaseStatus.CLOSED.value == "closed"
        assert WhistleblowerCaseStatus.DISMISSED.value == "dismissed"
        assert WhistleblowerCaseStatus.ESCALATED.value == "escalated"
        assert WhistleblowerCaseStatus.REFERRED_TO_AUTHORITY.value == "referred_to_authority"


class TestWhistleblowerCategory:
    def test_members(self):
        assert WhistleblowerCategory.FRAUD.value == "fraud"
        assert WhistleblowerCategory.CORRUPTION.value == "corruption"
        assert WhistleblowerCategory.HARASSMENT.value == "harassment"
        assert WhistleblowerCategory.SAFETY.value == "safety"
        assert WhistleblowerCategory.FINANCIAL_MISSTATEMENT.value == "financial_misstatement"
        assert WhistleblowerCategory.CONFLICT_OF_INTEREST.value == "conflict_of_interest"
        assert WhistleblowerCategory.DATA_PRIVACY.value == "data_privacy"
        assert WhistleblowerCategory.OTHER.value == "other"


class TestWhistleblowerProtectionStatus:
    def test_members(self):
        assert WhistleblowerProtectionStatus.NOT_APPLICABLE.value == "not_applicable"
        assert WhistleblowerProtectionStatus.PROTECTED.value == "protected"
        assert WhistleblowerProtectionStatus.RETALIATION_DETECTED.value == "retaliation_detected"
        assert WhistleblowerProtectionStatus.PROTECTION_ENFORCED.value == "protection_enforced"


# ============================================================================
# Tests for EvidenceAttachment
# ============================================================================

class TestEvidenceAttachment:
    def test_construction(self):
        attachment_id = uuid4()
        uploaded_by = uuid4()
        attachment = EvidenceAttachment(
            attachment_id=attachment_id,
            filename="doc.pdf",
            url="s3://bucket/doc.pdf",
            uploaded_by=uploaded_by,
        )
        assert attachment.id == attachment_id
        assert attachment.filename == "doc.pdf"
        assert attachment.url == "s3://bucket/doc.pdf"
        assert attachment.uploaded_by == uploaded_by
        assert attachment.uploaded_at is not None

    def test_to_dict(self):
        attachment = EvidenceAttachment(
            attachment_id=uuid4(),
            filename="evidence.txt",
            url="http://example.com/file",
            uploaded_by=uuid4(),
        )
        d = attachment.to_dict()
        assert d["id"] == str(attachment.id)
        assert d["filename"] == "evidence.txt"
        assert d["url"] == "http://example.com/file"
        assert d["uploaded_by"] == str(attachment.uploaded_by)
        assert "uploaded_at" in d


# ============================================================================
# Tests for InvestigationNote
# ============================================================================

class TestInvestigationNote:
    def test_construction(self):
        note = InvestigationNote(note="Findings", author="investigator", is_confidential=True)
        assert note.note == "Findings"
        assert note.author == "investigator"
        assert note.is_confidential is True
        assert note.id is not None
        assert note.created_at is not None

    def test_to_dict(self):
        note = InvestigationNote(note="Secret", author="admin", is_confidential=False)
        d = note.to_dict()
        assert d["note"] == "Secret"
        assert d["author"] == "admin"
        assert d["is_confidential"] is False
        assert "id" in d
        assert "created_at" in d


# ============================================================================
# Tests for WhistleblowerCase
# ============================================================================

class TestWhistleblowerCase:
    def test_construction(self):
        case_id = uuid4()
        reported_by = uuid4()
        case = WhistleblowerCase(
            case_id=case_id,
            report_text="Fraud reported",
            category=WhistleblowerCategory.FRAUD,
            reported_by=reported_by,
            reporter_contact="contact@example.com",
        )
        assert case.id == case_id
        assert case.report_text == "Fraud reported"
        assert case.category == WhistleblowerCategory.FRAUD
        assert case.reported_by == reported_by
        assert case.reporter_contact == "contact@example.com"
        assert case.status == WhistleblowerCaseStatus.OPEN
        assert case.protection_status == WhistleblowerProtectionStatus.NOT_APPLICABLE
        assert case.assigned_to is None
        assert case.investigation_notes == []
        assert case.evidence == []
        assert case._hash != ""

    def test_compute_hash(self, sample_case):
        h1 = sample_case._compute_hash()
        # Change something
        sample_case.status = WhistleblowerCaseStatus.UNDER_INVESTIGATION
        h2 = sample_case._compute_hash()
        assert h1 != h2

    def test_assign_investigator(self, sample_case):
        investigator_id = uuid4()
        sample_case.assign_investigator(investigator_id)
        assert sample_case.assigned_to == investigator_id
        assert sample_case.assigned_at is not None
        # Hash should update
        assert sample_case._hash != ""

    def test_update_status(self, sample_case):
        updated_by = uuid4()
        sample_case.update_status(
            WhistleblowerCaseStatus.UNDER_INVESTIGATION, updated_by, "Starting investigation"
        )
        assert sample_case.status == WhistleblowerCaseStatus.UNDER_INVESTIGATION
        # Should have added an investigation note
        assert len(sample_case.investigation_notes) == 1
        note = sample_case.investigation_notes[0]
        assert "Status changed" in note.note
        assert note.author == "system"

    def test_add_investigation_note(self, sample_case):
        sample_case.add_investigation_note("Interviewed witnesses", "investigator", True)
        assert len(sample_case.investigation_notes) == 1
        note = sample_case.investigation_notes[0]
        assert note.note == "Interviewed witnesses"
        assert note.author == "investigator"
        assert note.is_confidential is True

    def test_add_evidence(self, sample_case):
        attachment = EvidenceAttachment(
            attachment_id=uuid4(),
            filename="doc.pdf",
            url="s3://bucket/doc.pdf",
            uploaded_by=uuid4(),
        )
        sample_case.add_evidence(attachment)
        assert len(sample_case.evidence) == 1
        assert sample_case.evidence[0] == attachment

    def test_resolve(self, sample_case):
        resolved_by = uuid4()
        sample_case.resolve(resolved_by, "Resolved")
        assert sample_case.status == WhistleblowerCaseStatus.CLOSED
        assert sample_case.resolved_by == resolved_by
        assert sample_case.resolution_notes == "Resolved"
        assert sample_case.resolved_date is not None

    def test_escalate(self, sample_case):
        sample_case.escalate("Serious issue", "Compliance Committee")
        assert sample_case.status == WhistleblowerCaseStatus.ESCALATED
        assert sample_case.escalation_reason == "Serious issue"
        assert sample_case.escalated_to == "Compliance Committee"

    def test_protect_reporter(self, sample_case):
        sample_case.protect_reporter()
        assert sample_case.protection_status == WhistleblowerProtectionStatus.PROTECTED

    def test_report_retaliation(self, sample_case):
        sample_case.report_retaliation("Manager threatened whistleblower")
        assert sample_case.protection_status == WhistleblowerProtectionStatus.RETALIATION_DETECTED
        assert len(sample_case.investigation_notes) == 1
        assert "Retaliation reported" in sample_case.investigation_notes[0].note

    def test_is_anonymous(self, anonymous_case, sample_case):
        assert anonymous_case.is_anonymous() is True
        assert sample_case.is_anonymous() is False

    def test_to_dict(self, sample_case):
        sample_case.add_investigation_note("Note", "author")
        attachment = EvidenceAttachment(
            attachment_id=uuid4(), filename="file", url="url", uploaded_by=uuid4()
        )
        sample_case.add_evidence(attachment)
        d = sample_case.to_dict()
        assert d["case_id"] == str(sample_case.id)
        assert "report_text" in d
        assert d["category"] == sample_case.category.value
        assert d["status"] == sample_case.status.value
        assert "investigation_notes" in d
        assert "evidence" in d
        assert "hash" in d
        # Sensitive fields not included by default
        assert "reported_by" not in d

    def test_to_dict_with_sensitive(self, sample_case):
        d = sample_case.to_dict(include_sensitive=True)
        assert d["reported_by"] == str(sample_case.reported_by)
        assert d["reporter_contact"] == sample_case.reporter_contact

    def test_to_dict_anonymous_sensitive(self, anonymous_case):
        # Even with include_sensitive, anonymous case should not expose reporter info
        d = anonymous_case.to_dict(include_sensitive=True)
        assert "reported_by" not in d
        assert "reporter_contact" not in d


# ============================================================================
# Tests for WhistleblowerCaseTracker
# ============================================================================

class TestWhistleblowerCaseTracker:
    def test_initialization(self, tracker):
        assert tracker._cases == {}
        assert tracker._anonymous_counter == 0

    def test_report_case_identified(self, tracker):
        reporter_id = uuid4()
        case_id = tracker.report_case(
            report_text="Test",
            category=WhistleblowerCategory.FRAUD,
            reported_by=reporter_id,
            reporter_contact="test@example.com",
        )
        case = tracker.get_case(case_id)
        assert case is not None
        assert case.report_text == "Test"
        assert case.reported_by == reporter_id
        assert case.reporter_contact == "test@example.com"
        assert case.is_anonymous() is False

    def test_report_case_anonymous(self, tracker):
        case_id = tracker.report_case(
            report_text="Anonymous",
            category=WhistleblowerCategory.CORRUPTION,
            reported_by=None,
        )
        case = tracker.get_case(case_id)
        assert case is not None
        assert case.reported_by is None
        assert case.reporter_contact is None
        assert case.is_anonymous() is True

    def test_get_case_not_found(self, tracker):
        assert tracker.get_case(uuid4()) is None

    def test_assign_case(self, tracker, sample_case):
        investigator_id = uuid4()
        result = tracker.assign_case(sample_case.id, investigator_id)
        assert result is True
        case = tracker.get_case(sample_case.id)
        assert case.assigned_to == investigator_id

        # Non-existent case
        result2 = tracker.assign_case(uuid4(), investigator_id)
        assert result2 is False

    def test_update_case_status(self, tracker, sample_case):
        updated_by = uuid4()
        result = tracker.update_case_status(
            sample_case.id,
            WhistleblowerCaseStatus.UNDER_INVESTIGATION,
            updated_by,
            "Note",
        )
        assert result is True
        case = tracker.get_case(sample_case.id)
        assert case.status == WhistleblowerCaseStatus.UNDER_INVESTIGATION
        # Note added
        assert any("Note" in n.note for n in case.investigation_notes)

        # Non-existent
        result2 = tracker.update_case_status(uuid4(), WhistleblowerCaseStatus.CLOSED, updated_by)
        assert result2 is False

    def test_add_investigation_note(self, tracker, sample_case):
        result = tracker.add_investigation_note(
            sample_case.id, "New note", "investigator", is_confidential=False
        )
        assert result is True
        case = tracker.get_case(sample_case.id)
        assert len(case.investigation_notes) == 1
        note = case.investigation_notes[0]
        assert note.note == "New note"
        assert note.author == "investigator"
        assert note.is_confidential is False

        # Non-existent
        result2 = tracker.add_investigation_note(uuid4(), "Note", "author")
        assert result2 is False

    def test_add_evidence(self, tracker, sample_case):
        uploaded_by = uuid4()
        evidence_id = tracker.add_evidence(
            sample_case.id, "file.pdf", "s3://bucket/file.pdf", uploaded_by
        )
        assert evidence_id is not None
        case = tracker.get_case(sample_case.id)
        assert len(case.evidence) == 1
        assert case.evidence[0].id == evidence_id
        assert case.evidence[0].filename == "file.pdf"

        # Non-existent
        evidence_id2 = tracker.add_evidence(uuid4(), "file", "url")
        assert evidence_id2 is None

    def test_resolve_case(self, tracker, sample_case):
        resolved_by = uuid4()
        result = tracker.resolve_case(sample_case.id, resolved_by, "Resolved")
        assert result is True
        case = tracker.get_case(sample_case.id)
        assert case.status == WhistleblowerCaseStatus.CLOSED
        assert case.resolved_by == resolved_by

        # Non-existent
        result2 = tracker.resolve_case(uuid4(), resolved_by, "None")
        assert result2 is False

    def test_escalate_case(self, tracker, sample_case):
        result = tracker.escalate_case(sample_case.id, "Reason", "Committee")
        assert result is True
        case = tracker.get_case(sample_case.id)
        assert case.status == WhistleblowerCaseStatus.ESCALATED
        assert case.escalation_reason == "Reason"
        assert case.escalated_to == "Committee"

        # Non-existent
        result2 = tracker.escalate_case(uuid4(), "Reason", "Committee")
        assert result2 is False

    def test_protect_reporter(self, tracker, sample_case):
        result = tracker.protect_reporter(sample_case.id)
        assert result is True
        case = tracker.get_case(sample_case.id)
        assert case.protection_status == WhistleblowerProtectionStatus.PROTECTED

        # Non-existent
        result2 = tracker.protect_reporter(uuid4())
        assert result2 is False

    def test_report_retaliation(self, tracker, sample_case):
        result = tracker.report_retaliation(sample_case.id, "Retaliation description")
        assert result is True
        case = tracker.get_case(sample_case.id)
        assert case.protection_status == WhistleblowerProtectionStatus.RETALIATION_DETECTED

        # Non-existent
        result2 = tracker.report_retaliation(uuid4(), "desc")
        assert result2 is False

    def test_get_cases_by_status(self, tracker):
        # Create cases with different statuses
        case1 = tracker.report_case("Case1", WhistleblowerCategory.FRAUD, uuid4())
        case2 = tracker.report_case("Case2", WhistleblowerCategory.FRAUD, uuid4())
        tracker.update_case_status(
            case2, WhistleblowerCaseStatus.UNDER_INVESTIGATION, uuid4(), "Start"
        )
        case3 = tracker.report_case("Case3", WhistleblowerCategory.FRAUD, uuid4())
        tracker.update_case_status(case3, WhistleblowerCaseStatus.CLOSED, uuid4(), "Close")

        open_cases = tracker.get_cases_by_status(WhistleblowerCaseStatus.OPEN)
        assert len(open_cases) == 1  # only case1
        assert open_cases[0].id == case1

        under_inv = tracker.get_cases_by_status(WhistleblowerCaseStatus.UNDER_INVESTIGATION)
        assert len(under_inv) == 1
        assert under_inv[0].id == case2

        closed = tracker.get_cases_by_status(WhistleblowerCaseStatus.CLOSED)
        assert len(closed) == 1
        assert closed[0].id == case3

        # Non-existent status returns empty list
        dismissed = tracker.get_cases_by_status(WhistleblowerCaseStatus.DISMISSED)
        assert dismissed == []

    def test_get_open_cases(self, tracker):
        case1 = tracker.report_case("Case1", WhistleblowerCategory.FRAUD, uuid4())
        case2 = tracker.report_case("Case2", WhistleblowerCategory.FRAUD, uuid4())
        tracker.update_case_status(
            case2, WhistleblowerCaseStatus.UNDER_INVESTIGATION, uuid4(), "Start"
        )
        case3 = tracker.report_case("Case3", WhistleblowerCategory.FRAUD, uuid4())
        tracker.update_case_status(case3, WhistleblowerCaseStatus.CLOSED, uuid4(), "Close")
        case4 = tracker.report_case("Case4", WhistleblowerCategory.FRAUD, uuid4())
        tracker.update_case_status(case4, WhistleblowerCaseStatus.DISMISSED, uuid4(), "Dismiss")

        open_cases = tracker.get_open_cases()
        assert len(open_cases) == 2  # case1 (OPEN) and case2 (UNDER_INVESTIGATION)
        open_ids = {c.id for c in open_cases}
        assert case1 in open_ids
        assert case2 in open_ids

    def test_get_cases_by_category(self, tracker):
        c1 = tracker.report_case("Fraud", WhistleblowerCategory.FRAUD, uuid4())
        c2 = tracker.report_case("Corruption", WhistleblowerCategory.CORRUPTION, uuid4())
        c3 = tracker.report_case("Another Fraud", WhistleblowerCategory.FRAUD, uuid4())

        fraud_cases = tracker.get_cases_by_category(WhistleblowerCategory.FRAUD)
        assert len(fraud_cases) == 2
        fraud_ids = {c.id for c in fraud_cases}
        assert c1 in fraud_ids
        assert c3 in fraud_ids

        corruption = tracker.get_cases_by_category(WhistleblowerCategory.CORRUPTION)
        assert len(corruption) == 1
        assert corruption[0].id == c2

        harassment = tracker.get_cases_by_category(WhistleblowerCategory.HARASSMENT)
        assert harassment == []

    def test_get_assigned_cases(self, tracker):
        inv1 = uuid4()
        inv2 = uuid4()

        c1 = tracker.report_case("Case1", WhistleblowerCategory.FRAUD, uuid4())
        tracker.assign_case(c1, inv1)

        c2 = tracker.report_case("Case2", WhistleblowerCategory.FRAUD, uuid4())
        tracker.assign_case(c2, inv1)

        c3 = tracker.report_case("Case3", WhistleblowerCategory.FRAUD, uuid4())
        tracker.assign_case(c3, inv2)

        assigned_to_inv1 = tracker.get_assigned_cases(inv1)
        assert len(assigned_to_inv1) == 2
        assigned_ids = {c.id for c in assigned_to_inv1}
        assert c1 in assigned_ids
        assert c2 in assigned_ids

        assigned_to_inv2 = tracker.get_assigned_cases(inv2)
        assert len(assigned_to_inv2) == 1
        assert assigned_to_inv2[0].id == c3

        # Non-existent investigator
        no_cases = tracker.get_assigned_cases(uuid4())
        assert no_cases == []

    def test_generate_summary(self, tracker):
        # Add cases with different characteristics
        reporter = uuid4()
        tracker.report_case("Case1", WhistleblowerCategory.FRAUD, reporter)
        c2 = tracker.report_case("Case2", WhistleblowerCategory.FRAUD, None)  # anonymous
        tracker.report_case("Case3", WhistleblowerCategory.CORRUPTION, reporter)
        c4 = tracker.report_case("Case4", WhistleblowerCategory.HARASSMENT, reporter)
        tracker.update_case_status(c4, WhistleblowerCaseStatus.UNDER_INVESTIGATION, uuid4(), "Start")
        c5 = tracker.report_case("Case5", WhistleblowerCategory.CORRUPTION, reporter)
        tracker.update_case_status(c5, WhistleblowerCaseStatus.CLOSED, uuid4(), "Close")

        # Protect one reporter
        tracker.protect_reporter(c2)

        summary = tracker.generate_summary()
        assert summary["total_cases"] == 5
        assert summary["open_cases"] == 4  # c1,c2,c3 open, c4 under_investigation, c5 closed => 4
        assert summary["anonymous_reports"] == 1  # c2
        assert summary["protected_reporters"] == 1  # c2
        assert summary["by_category"]["fraud"] == 2
        assert summary["by_category"]["corruption"] == 2
        assert summary["by_category"]["harassment"] == 1
        assert summary["by_status"]["open"] == 3  # c1,c2,c3
        assert summary["by_status"]["under_investigation"] == 1
        assert summary["by_status"]["closed"] == 1

    def test_to_json(self, tracker):
        # Add some cases
        reporter = uuid4()
        tracker.report_case("Case1", WhistleblowerCategory.FRAUD, reporter)
        tracker.report_case("Case2", WhistleblowerCategory.FRAUD, None)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name

        try:
            tracker.to_json(file_path, include_sensitive=False)
            with open(file_path) as f:
                data = json.load(f)
            assert "summary" in data
            assert "cases" in data
            assert len(data["cases"]) == 2
            # Sensitive fields should not be present
            for case in data["cases"]:
                assert "reported_by" not in case
                assert "reporter_contact" not in case

            # Now with sensitive
            tracker.to_json(file_path, include_sensitive=True)
            with open(file_path) as f:
                data2 = json.load(f)
            for case in data2["cases"]:
                # Only the non-anonymous case has sensitive fields
                if "reported_by" in case:
                    assert case["reported_by"] == str(reporter)
        finally:
            import os
            os.unlink(file_path)


# ============================================================================
# Integration tests for status transitions and protection
# ============================================================================

class TestIntegration:
    def test_full_lifecycle(self, tracker):
        # Report
        case_id = tracker.report_case(
            "Suspicious activity", WhistleblowerCategory.FRAUD, uuid4(), "contact@example.com"
        )
        case = tracker.get_case(case_id)

        # Assign investigator
        inv_id = uuid4()
        tracker.assign_case(case_id, inv_id)
        assert case.assigned_to == inv_id

        # Add note and evidence
        tracker.add_investigation_note(case_id, "Initial review", "investigator")
        tracker.add_evidence(case_id, "doc.pdf", "s3://bucket/doc.pdf", inv_id)
        assert len(case.investigation_notes) == 1
        assert len(case.evidence) == 1

        # Update status
        tracker.update_case_status(case_id, WhistleblowerCaseStatus.UNDER_INVESTIGATION, inv_id)
        assert case.status == WhistleblowerCaseStatus.UNDER_INVESTIGATION

        # Protect reporter
        tracker.protect_reporter(case_id)
        assert case.protection_status == WhistleblowerProtectionStatus.PROTECTED

        # Report retaliation
        tracker.report_retaliation(case_id, "Threats received")
        assert case.protection_status == WhistleblowerProtectionStatus.RETALIATION_DETECTED
        assert any("Threats received" in n.note for n in case.investigation_notes)

        # Resolve
        tracker.resolve_case(case_id, inv_id, "Issue resolved")
        assert case.status == WhistleblowerCaseStatus.CLOSED
        assert case.resolved_by == inv_id
        assert case.resolution_notes == "Issue resolved"

        # Summary
        summary = tracker.generate_summary()
        assert summary["total_cases"] == 1
        assert summary["open_cases"] == 0
        assert summary["protected_reporters"] == 0  # since protection status changed to retaliation
