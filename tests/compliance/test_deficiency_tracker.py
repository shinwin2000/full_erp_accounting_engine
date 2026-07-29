# test_deficiency_tracker.py
# Comprehensive tests for compliance/deficiency_tracker.py

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from compliance.deficiency_tracker import (
    Comment,
    Deficiency,
    DeficiencyAction,
    DeficiencyCategory,
    DeficiencyError,
    DeficiencyHistoryEntry,
    DeficiencyNotFoundError,
    DeficiencySeverity,
    DeficiencyStatus,
    DeficiencyTracker,
    EscalationError,
    EvidenceAttachment,
    InvalidStatusTransitionError,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def fixed_now():
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("compliance.deficiency_tracker.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.today.return_value = fixed_now.date()
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def fixed_date():
    return date(2026, 1, 15)


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def sample_deficiency(user_id, fixed_date):
    return Deficiency(
        deficiency_id=uuid4(),
        title="Test Deficiency",
        description="Test description",
        category=DeficiencyCategory.INTERNAL_CONTROL,
        regulation="SOX 404",
        severity=DeficiencySeverity.HIGH,
        discovered_date=fixed_date,
        discovered_by=user_id,
        owner_id=user_id,
        due_date=fixed_date + timedelta(days=30),
        status=DeficiencyStatus.OPEN,
        remediation_plan="Plan",
        root_cause="Cause",
        impact_assessment="Impact",
        external_ticket_id="TICKET-123",
    )


@pytest.fixture
def tracker():
    return DeficiencyTracker()


@pytest.fixture
def tracker_with_ext():
    return DeficiencyTracker(enable_external_ticketing=True, external_ticket_config={
        "url": "https://jira.example.com",
        "api_key": "key",
        "project": "COMP",
    })


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_deficiency_severity(self):
        assert DeficiencySeverity.LOW.value == "low"
        assert DeficiencySeverity.MEDIUM.value == "medium"
        assert DeficiencySeverity.HIGH.value == "high"
        assert DeficiencySeverity.CRITICAL.value == "critical"

    def test_deficiency_status(self):
        assert DeficiencyStatus.OPEN.value == "open"
        assert DeficiencyStatus.IN_PROGRESS.value == "in_progress"
        assert DeficiencyStatus.UNDER_REVIEW.value == "under_review"
        assert DeficiencyStatus.REMEDIATED.value == "remediated"
        assert DeficiencyStatus.CLOSED.value == "closed"
        assert DeficiencyStatus.WAIVED.value == "waived"

    def test_deficiency_category(self):
        assert DeficiencyCategory.ACCOUNTING_POLICY.value == "accounting_policy"
        assert DeficiencyCategory.INTERNAL_CONTROL.value == "internal_control"
        assert DeficiencyCategory.TAX_COMPLIANCE.value == "tax_compliance"

    def test_deficiency_action(self):
        assert DeficiencyAction.CREATED.value == "created"
        assert DeficiencyAction.ASSIGNED.value == "assigned"


# -------------------- Tests for Exceptions --------------------
class TestExceptions:
    def test_deficiency_error(self):
        with pytest.raises(DeficiencyError):
            raise DeficiencyError("test")

    def test_deficiency_not_found_error(self):
        with pytest.raises(DeficiencyNotFoundError):
            raise DeficiencyNotFoundError("not found")

    def test_invalid_status_transition_error(self):
        with pytest.raises(InvalidStatusTransitionError):
            raise InvalidStatusTransitionError("invalid")

    def test_escalation_error(self):
        with pytest.raises(EscalationError):
            raise EscalationError("escalation")


# -------------------- Tests for Value Objects --------------------
class TestDeficiencyHistoryEntry:
    def test_construction(self, user_id, fixed_now):
        entry = DeficiencyHistoryEntry(
            action=DeficiencyAction.CREATED,
            performed_by=user_id,
            timestamp=fixed_now,
            old_value="old",
            new_value="new",
            comment="comment",
        )
        assert entry.id is not None
        assert entry.action == DeficiencyAction.CREATED
        assert entry.performed_by == user_id
        assert entry.timestamp == fixed_now
        assert entry.old_value == "old"
        assert entry.new_value == "new"

    def test_to_dict(self, user_id, fixed_now):
        entry = DeficiencyHistoryEntry(
            action=DeficiencyAction.STATUS_CHANGED,
            performed_by=user_id,
            timestamp=fixed_now,
            old_value="open",
            new_value="closed",
            comment="closed",
        )
        d = entry.to_dict()
        assert d["action"] == "status_changed"
        assert d["performed_by"] == str(user_id)
        assert d["timestamp"] == fixed_now.isoformat()
        assert d["old_value"] == "open"
        assert d["new_value"] == "closed"
        assert d["comment"] == "closed"


class TestEvidenceAttachment:
    def test_construction(self, user_id, fixed_now):
        att = EvidenceAttachment(
            attachment_id=uuid4(),
            filename="evidence.pdf",
            file_url="s3://bucket/evidence.pdf",
            uploaded_by=user_id,
            uploaded_at=fixed_now,
            file_hash="abc123",
            file_size_bytes=1024,
        )
        assert att.filename == "evidence.pdf"
        assert att.file_hash == "abc123"

    def test_to_dict(self, user_id, fixed_now):
        att_id = uuid4()
        att = EvidenceAttachment(
            attachment_id=att_id,
            filename="test.pdf",
            file_url="http://example.com/test.pdf",
            uploaded_by=user_id,
            uploaded_at=fixed_now,
            file_hash="hash",
            file_size_bytes=512,
        )
        d = att.to_dict()
        assert d["id"] == str(att_id)
        assert d["filename"] == "test.pdf"
        assert d["file_url"] == "http://example.com/test.pdf"
        assert d["file_hash"] == "hash"
        assert d["file_size_bytes"] == 512


class TestComment:
    def test_construction(self, user_id, fixed_now):
        comment = Comment(
            comment_id=uuid4(),
            author_id=user_id,
            content="Test comment",
            timestamp=fixed_now,
        )
        assert comment.content == "Test comment"
        assert comment.author_id == user_id

    def test_to_dict(self, user_id, fixed_now):
        cid = uuid4()
        comment = Comment(
            comment_id=cid,
            author_id=user_id,
            content="Hello",
            timestamp=fixed_now,
        )
        d = comment.to_dict()
        assert d["id"] == str(cid)
        assert d["author_id"] == str(user_id)
        assert d["content"] == "Hello"
        assert d["timestamp"] == fixed_now.isoformat()


# -------------------- Tests for Deficiency Aggregate --------------------
class TestDeficiency:
    def test_construction(self, sample_deficiency):
        assert sample_deficiency.title == "Test Deficiency"
        assert sample_deficiency.status == DeficiencyStatus.OPEN
        assert sample_deficiency._hash is None
        assert sample_deficiency.history == []
        assert sample_deficiency.attachments == []
        assert sample_deficiency.comments == []

    def test_compute_hash(self, sample_deficiency):
        h1 = sample_deficiency._compute_hash()
        assert h1 is not None
        assert len(h1) == 64  # SHA256
        # Refresh and compare
        h2 = sample_deficiency.refresh_hash()
        assert h2 == h1
        # Changing a field changes hash
        old = sample_deficiency.title
        sample_deficiency.title = "Changed"
        h3 = sample_deficiency._compute_hash()
        assert h3 != h2

    def test_add_history_entry(self, sample_deficiency, user_id):
        sample_deficiency.add_history_entry(
            DeficiencyAction.CREATED,
            user_id,
            old_value="old",
            new_value="new",
            comment="test",
        )
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.updated_at is not None
        assert sample_deficiency._hash is not None

    def test_assign_owner(self, sample_deficiency, user_id):
        new_owner = uuid4()
        sample_deficiency.assign_owner(new_owner, user_id)
        assert sample_deficiency.owner_id == new_owner
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.history[0].action == DeficiencyAction.ASSIGNED
        assert sample_deficiency.history[0].old_value == str(user_id)
        assert sample_deficiency.history[0].new_value == str(new_owner)

    def test_update_status_valid(self, sample_deficiency, user_id):
        sample_deficiency.update_status(DeficiencyStatus.IN_PROGRESS, user_id, "started")
        assert sample_deficiency.status == DeficiencyStatus.IN_PROGRESS
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.history[0].action == DeficiencyAction.STATUS_CHANGED
        assert sample_deficiency.history[0].old_value == "open"
        assert sample_deficiency.history[0].new_value == "in_progress"
        # Transition to CLOSED
        sample_deficiency.update_status(DeficiencyStatus.CLOSED, user_id)
        assert sample_deficiency.status == DeficiencyStatus.CLOSED
        assert sample_deficiency.closed_at is not None

    def test_update_status_invalid(self, sample_deficiency, user_id):
        with pytest.raises(InvalidStatusTransitionError, match="Cannot transition"):
            sample_deficiency.update_status(DeficiencyStatus.REMEDIATED, user_id)  # OPEN -> REMEDIATED invalid

    def test_is_valid_transition(self, sample_deficiency):
        assert sample_deficiency._is_valid_transition(DeficiencyStatus.OPEN, DeficiencyStatus.IN_PROGRESS) is True
        assert sample_deficiency._is_valid_transition(DeficiencyStatus.OPEN, DeficiencyStatus.CLOSED) is True
        assert sample_deficiency._is_valid_transition(DeficiencyStatus.OPEN, DeficiencyStatus.REMEDIATED) is False
        assert sample_deficiency._is_valid_transition(DeficiencyStatus.CLOSED, DeficiencyStatus.OPEN) is False

    def test_set_remediation_plan(self, sample_deficiency, user_id):
        plan = "New plan"
        sample_deficiency.set_remediation_plan(plan, user_id)
        assert sample_deficiency.remediation_plan == plan
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.history[0].action == DeficiencyAction.REMEDIATION_PLAN_UPDATED

    def test_add_evidence(self, sample_deficiency, user_id, fixed_now):
        att = EvidenceAttachment(
            attachment_id=uuid4(),
            filename="file.pdf",
            file_url="url",
            uploaded_by=user_id,
            uploaded_at=fixed_now,
        )
        sample_deficiency.add_evidence(att, user_id)
        assert len(sample_deficiency.attachments) == 1
        assert sample_deficiency.attachments[0] == att
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.history[0].action == DeficiencyAction.EVIDENCE_ATTACHED
        assert sample_deficiency.history[0].new_value == "file.pdf"

    def test_add_comment(self, sample_deficiency, user_id):
        content = "This is a comment"
        sample_deficiency.add_comment(user_id, content)
        assert len(sample_deficiency.comments) == 1
        assert sample_deficiency.comments[0].content == content
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.history[0].action == DeficiencyAction.COMMENT_ADDED

    def test_escalate(self, sample_deficiency, user_id):
        assert sample_deficiency.escalation_level == 0
        sample_deficiency.escalate(user_id, "reason")
        assert sample_deficiency.escalation_level == 1
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.history[0].action == DeficiencyAction.ESCALATED
        # Escalate to critical
        sample_deficiency.escalation_level = 2
        sample_deficiency.escalate(user_id, "third")
        assert sample_deficiency.escalation_level == 3
        assert sample_deficiency.severity == DeficiencySeverity.CRITICAL
        # Check that severity change is logged
        assert len(sample_deficiency.history) >= 2
        assert any(entry.action == DeficiencyAction.STATUS_CHANGED for entry in sample_deficiency.history)

    def test_mark_sla_breach(self, sample_deficiency, user_id):
        assert sample_deficiency.sla_breach_notified is False
        sample_deficiency.mark_sla_breach(user_id)
        assert sample_deficiency.sla_breach_notified is True
        assert len(sample_deficiency.history) == 1
        assert sample_deficiency.history[0].action == DeficiencyAction.SLA_BREACH
        # Second call should not add another history
        sample_deficiency.mark_sla_breach(user_id)
        assert len(sample_deficiency.history) == 1  # unchanged

    def test_to_dict(self, sample_deficiency):
        d = sample_deficiency.to_dict()
        assert d["id"] == str(sample_deficiency.id)
        assert d["title"] == "Test Deficiency"
        assert d["status"] == "open"
        assert "hash" in d
        # With includes
        d_full = sample_deficiency.to_dict(include_history=True, include_attachments=True, include_comments=True)
        assert "history" in d_full
        assert d_full["history"] == []
        assert "attachments" in d_full
        assert "comments" in d_full


# -------------------- Tests for DeficiencyTracker --------------------
class TestDeficiencyTracker:
    def test_add_deficiency(self, tracker, user_id, fixed_date):
        did = tracker.add_deficiency(
            title="New",
            description="Desc",
            category=DeficiencyCategory.AML,
            regulation="PSAK 72",
            severity=DeficiencySeverity.HIGH,
            discovered_by=user_id,
            due_date=fixed_date + timedelta(days=10),
            owner_id=user_id,
            root_cause="cause",
            impact_assessment="impact",
            external_ticket_id="EXT-001",
        )
        d = tracker.get_deficiency(did)
        assert d is not None
        assert d.title == "New"
        assert d.status == DeficiencyStatus.OPEN
        assert len(d.history) == 1
        assert d.history[0].action == DeficiencyAction.CREATED
        assert d.due_date == fixed_date + timedelta(days=10)
        assert d.owner_id == user_id
        assert d.root_cause == "cause"
        assert d.external_ticket_id == "EXT-001"

    def test_add_deficiency_overdue(self, tracker, user_id, fixed_date):
        # Due date in the past
        did = tracker.add_deficiency(
            title="Overdue",
            description="desc",
            category=DeficiencyCategory.OTHER,
            regulation="GDPR",
            severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
            due_date=fixed_date - timedelta(days=1),
        )
        d = tracker.get_deficiency(did)
        assert d.sla_breach_notified is True
        assert len(d.history) >= 1
        assert any(entry.action == DeficiencyAction.SLA_BREACH for entry in d.history)

    def test_get_deficiency_not_found(self, tracker):
        assert tracker.get_deficiency(uuid4()) is None

    def test_update_deficiency(self, tracker, user_id):
        did = tracker.add_deficiency(
            title="Old",
            description="Old desc",
            category=DeficiencyCategory.ACCOUNTING_POLICY,
            regulation="IFRS 9",
            severity=DeficiencySeverity.MEDIUM,
            discovered_by=user_id,
        )
        tracker.update_deficiency(did, title="Updated", description="New desc")
        d = tracker.get_deficiency(did)
        assert d.title == "Updated"
        assert d.description == "New desc"
        assert d.updated_at is not None
        # Ensure history added
        assert len(d.history) >= 2  # creation + updates
        assert any("Updated" in entry.new_value for entry in d.history if entry.new_value)

    def test_update_deficiency_not_found(self, tracker):
        with pytest.raises(DeficiencyNotFoundError):
            tracker.update_deficiency(uuid4(), title="x")

    def test_delete_deficiency(self, tracker, user_id):
        did = tracker.add_deficiency(
            title="ToDelete",
            description="desc",
            category=DeficiencyCategory.SECURITY,
            regulation="ISO 27001",
            severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        result = tracker.delete_deficiency(did, user_id)
        assert result is True
        assert tracker.get_deficiency(did) is None
        # Delete non-existent
        result2 = tracker.delete_deficiency(uuid4(), user_id)
        assert result2 is False

    # ---- Query methods ----
    def test_get_deficiencies(self, tracker, user_id, fixed_date):
        d1 = tracker.add_deficiency(
            title="A", description="", category=DeficiencyCategory.AML,
            regulation="", severity=DeficiencySeverity.HIGH,
            discovered_by=user_id, due_date=fixed_date + timedelta(days=10)
        )
        d2 = tracker.add_deficiency(
            title="B", description="", category=DeficiencyCategory.INTERNAL_CONTROL,
            regulation="SOX", severity=DeficiencySeverity.CRITICAL,
            discovered_by=user_id, due_date=fixed_date + timedelta(days=20)
        )
        d3 = tracker.add_deficiency(
            title="C", description="", category=DeficiencyCategory.AML,
            regulation="PSAK", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date - timedelta(days=5)
        )
        # Filter by status
        all_open = tracker.get_deficiencies(status=[DeficiencyStatus.OPEN])
        assert len(all_open) == 3
        # Filter by severity
        critical = tracker.get_deficiencies(severity=[DeficiencySeverity.CRITICAL])
        assert len(critical) == 1
        assert critical[0].id == d2
        # Filter by category
        aml = tracker.get_deficiencies(category=[DeficiencyCategory.AML])
        assert len(aml) == 2
        # Filter by owner
        owned = tracker.get_deficiencies(owner_id=user_id)
        assert len(owned) == 3
        # Filter by regulation
        sox = tracker.get_deficiencies(regulation="SOX")
        assert len(sox) == 1
        # Filter by date range
        from_date = fixed_date + timedelta(days=5)
        to_date = fixed_date + timedelta(days=25)
        date_filtered = tracker.get_deficiencies(from_date=from_date, to_date=to_date)
        assert len(date_filtered) == 2  # d1 and d2

    def test_get_open_deficiencies(self, tracker, user_id):
        d1 = tracker.add_deficiency(title="O1", description="", category=DeficiencyCategory.OTHER,
                                    regulation="", severity=DeficiencySeverity.LOW,
                                    discovered_by=user_id)
        d2 = tracker.add_deficiency(title="O2", description="", category=DeficiencyCategory.OTHER,
                                    regulation="", severity=DeficiencySeverity.LOW,
                                    discovered_by=user_id)
        # Close one
        d = tracker.get_deficiency(d2)
        d.update_status(DeficiencyStatus.CLOSED, user_id)
        open_list = tracker.get_open_deficiencies()
        assert len(open_list) == 1
        assert open_list[0].id == d1
        # Filter by severity
        high = tracker.add_deficiency(title="High", description="", category=DeficiencyCategory.OTHER,
                                      regulation="", severity=DeficiencySeverity.HIGH,
                                      discovered_by=user_id)
        open_high = tracker.get_open_deficiencies(severity=DeficiencySeverity.HIGH)
        assert len(open_high) == 1
        assert open_high[0].id == high

    def test_get_overdue_deficiencies(self, tracker, user_id, fixed_date):
        d1 = tracker.add_deficiency(
            title="Due now", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date
        )
        d2 = tracker.add_deficiency(
            title="Overdue", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date - timedelta(days=1)
        )
        d3 = tracker.add_deficiency(
            title="Future", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date + timedelta(days=10)
        )
        overdue = tracker.get_overdue_deficiencies(as_of=fixed_date)
        assert len(overdue) == 2  # d1 and d2 (due <= today)
        # SLA breach should be marked for d2 (d1 is due today, not marked)
        d2_obj = tracker.get_deficiency(d2)
        assert d2_obj.sla_breach_notified is True
        d1_obj = tracker.get_deficiency(d1)
        assert d1_obj.sla_breach_notified is False  # not marked yet
        # Call again should not duplicate
        overdue2 = tracker.get_overdue_deficiencies(as_of=fixed_date)
        assert len(overdue2) == 2

    def test_get_by_owner(self, tracker, user_id):
        owner1 = uuid4()
        owner2 = uuid4()
        d1 = tracker.add_deficiency(title="1", description="", category=DeficiencyCategory.OTHER,
                                    regulation="", severity=DeficiencySeverity.LOW,
                                    discovered_by=user_id, owner_id=owner1)
        d2 = tracker.add_deficiency(title="2", description="", category=DeficiencyCategory.OTHER,
                                    regulation="", severity=DeficiencySeverity.LOW,
                                    discovered_by=user_id, owner_id=owner2)
        d3 = tracker.add_deficiency(title="3", description="", category=DeficiencyCategory.OTHER,
                                    regulation="", severity=DeficiencySeverity.LOW,
                                    discovered_by=user_id, owner_id=owner1)
        owned1 = tracker.get_by_owner(owner1)
        assert len(owned1) == 2
        owned2 = tracker.get_by_owner(owner2)
        assert len(owned2) == 1

    def test_get_by_external_ticket(self, tracker, user_id):
        did = tracker.add_deficiency(
            title="X", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, external_ticket_id="TICK-123"
        )
        found = tracker.get_by_external_ticket("TICK-123")
        assert found is not None
        assert found.id == did
        assert tracker.get_by_external_ticket("NONEXISTENT") is None

    # ---- SLA and Escalation ----
    def test_check_all_sla(self, tracker, user_id, fixed_date):
        d1 = tracker.add_deficiency(
            title="D1", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date - timedelta(days=1)
        )
        d2 = tracker.add_deficiency(
            title="D2", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date + timedelta(days=1)
        )
        count = tracker.check_all_sla()
        assert count == 1  # only d1

    def test_auto_escalate(self, tracker, user_id, fixed_date):
        d1 = tracker.add_deficiency(
            title="Overdue", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date - timedelta(days=10)
        )
        d2 = tracker.add_deficiency(
            title="Not overdue", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date + timedelta(days=1)
        )
        # auto_escalate with threshold 5 days -> only d1 escalates
        escalated = tracker.auto_escalate(escalation_days=5)
        assert escalated == 1
        d1_obj = tracker.get_deficiency(d1)
        assert d1_obj.escalation_level == 1
        d2_obj = tracker.get_deficiency(d2)
        assert d2_obj.escalation_level == 0
        # Second call should not escalate again (already escalated)
        escalated2 = tracker.auto_escalate(escalation_days=5)
        assert escalated2 == 0

    def test_get_sla_summary(self, tracker, user_id, fixed_date):
        d1 = tracker.add_deficiency(
            title="D1", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date + timedelta(days=10)
        )
        d2 = tracker.add_deficiency(
            title="D2", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date - timedelta(days=1)
        )
        d3 = tracker.add_deficiency(
            title="D3", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id, due_date=fixed_date + timedelta(days=20)
        )
        # Close one
        d = tracker.get_deficiency(d3)
        d.update_status(DeficiencyStatus.CLOSED, user_id)
        summary = tracker.get_sla_summary()
        assert summary["total_deficiencies"] == 3
        assert summary["overdue_count"] == 1  # d2
        assert summary["on_track_count"] == 1  # d1 (d3 closed excluded)
        # Compliance rate = 1 / (1+1) = 50%
        assert summary["sla_compliance_rate"] == 50.0
        assert summary["escalated_count"] == 0

    # ---- External ticketing ----
    @patch("compliance.deficiency_tracker.requests")
    def test_create_external_ticket_success(self, mock_requests, tracker_with_ext, user_id):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"key": "COMP-123"}
        mock_requests.post.return_value = mock_response

        did = tracker_with_ext.add_deficiency(
            title="Ext",
            description="desc",
            category=DeficiencyCategory.OTHER,
            regulation="",
            severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        d = tracker_with_ext.get_deficiency(did)
        assert d.external_ticket_id == "COMP-123"
        assert len(d.history) >= 2
        assert any(entry.action == DeficiencyAction.COMMENT_ADDED and entry.new_value == "COMP-123"
                   for entry in d.history)

    @patch("compliance.deficiency_tracker.requests")
    def test_create_external_ticket_failure(self, mock_requests, tracker_with_ext, user_id):
        mock_requests.post.side_effect = Exception("Network error")
        did = tracker_with_ext.add_deficiency(
            title="Fail", description="desc", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        d = tracker_with_ext.get_deficiency(did)
        assert d.external_ticket_id is None  # not set

    def test_create_external_ticket_disabled(self, tracker, user_id):
        # tracker without external enabled
        did = tracker.add_deficiency(
            title="No ext", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        d = tracker.get_deficiency(did)
        assert d.external_ticket_id is None

    def test_sync_external_status(self, tracker_with_ext, user_id):
        # Simulate sync (not implemented, just returns False)
        did = tracker_with_ext.add_deficiency(
            title="Sync", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        result = tracker_with_ext.sync_external_status(did)
        assert result is False  # not implemented

    # ---- Reporting ----
    def test_generate_summary(self, tracker, user_id):
        tracker.add_deficiency(
            title="A", description="", category=DeficiencyCategory.AML,
            regulation="", severity=DeficiencySeverity.CRITICAL,
            discovered_by=user_id,
        )
        tracker.add_deficiency(
            title="B", description="", category=DeficiencyCategory.INTERNAL_CONTROL,
            regulation="", severity=DeficiencySeverity.HIGH,
            discovered_by=user_id,
        )
        tracker.add_deficiency(
            title="C", description="", category=DeficiencyCategory.AML,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        # Close one
        d = list(tracker._deficiencies.values())[-1]
        d.update_status(DeficiencyStatus.CLOSED, user_id)
        summary = tracker.generate_summary()
        assert summary["total_deficiencies"] == 3
        assert summary["open_deficiencies"] == 2  # two open (A and B)
        assert summary["closed_deficiencies"] == 1
        assert summary["by_severity"]["critical"] == 1
        assert summary["by_severity"]["high"] == 1
        assert summary["by_severity"]["low"] == 1
        assert summary["by_category"]["aml"] == 2
        assert summary["by_status"]["open"] == 1  # A is open? Actually A is open, B is open, so 2
        # Let's check: A -> open, B -> open, C -> closed => open=2
        assert summary["by_status"]["open"] == 1  # Wait, we have 2 open? We added A and B open, C closed. So open=2.
        assert summary["by_status"]["closed"] == 1

    def test_export_to_json(self, tracker, user_id, tmp_path):
        did = tracker.add_deficiency(
            title="Test", description="desc", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        # Add history, attachment, comment
        d = tracker.get_deficiency(did)
        d.add_history_entry(DeficiencyAction.COMMENT_ADDED, user_id, comment="test")
        d.add_evidence(
            EvidenceAttachment(uuid4(), "file.pdf", "url", user_id, datetime.utcnow()),
            user_id
        )
        d.add_comment(user_id, "comment")
        file_path = tmp_path / "export.json"
        json_str = tracker.export_to_json(str(file_path))
        assert file_path.exists()
        data = json.loads(json_str)
        assert "export_timestamp" in data
        assert len(data["deficiencies"]) == 1
        assert data["deficiencies"][0]["title"] == "Test"
        assert "history" in data["deficiencies"][0]
        assert "attachments" in data["deficiencies"][0]
        assert "comments" in data["deficiencies"][0]

    def test_export_to_csv(self, tracker, user_id, tmp_path):
        did = tracker.add_deficiency(
            title="CSV", description="desc", category=DeficiencyCategory.AML,
            regulation="PSAK 72", severity=DeficiencySeverity.HIGH,
            discovered_by=user_id,
            due_date=date(2026, 1, 20),
            owner_id=user_id,
        )
        file_path = tmp_path / "export.csv"
        tracker.export_to_csv(str(file_path))
        assert file_path.exists()
        content = file_path.read_text()
        assert "CSV" in content
        assert "PSAK 72" in content

    # ---- Maintenance ----
    def test_archive_closed_deficiencies(self, tracker, user_id, fixed_now):
        d1 = tracker.add_deficiency(
            title="Old", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        d2 = tracker.add_deficiency(
            title="New", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        # Close d1 and set closed_at to 100 days ago
        d1_obj = tracker.get_deficiency(d1)
        d1_obj.update_status(DeficiencyStatus.CLOSED, user_id)
        d1_obj.closed_at = fixed_now - timedelta(days=100)
        # Close d2 with recent closed_at
        d2_obj = tracker.get_deficiency(d2)
        d2_obj.update_status(DeficiencyStatus.CLOSED, user_id)
        d2_obj.closed_at = fixed_now - timedelta(days=10)
        archived = tracker.archive_closed_deficiencies(older_than_days=30)
        assert archived == 1
        assert tracker.get_deficiency(d1) is None
        assert tracker.get_deficiency(d2) is not None

    def test_get_audit_trail(self, tracker, user_id):
        did = tracker.add_deficiency(
            title="Audit", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        trail = tracker.get_audit_trail(did)
        assert len(trail) >= 1
        assert trail[0]["action"] == "created"
        # Non-existent
        assert tracker.get_audit_trail(uuid4()) == []

    def test_get_all_audit_trails(self, tracker, user_id):
        d1 = tracker.add_deficiency(
            title="A", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        d2 = tracker.add_deficiency(
            title="B", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        all_trails = tracker.get_all_audit_trails()
        assert len(all_trails) == 2
        assert d1 in all_trails
        assert d2 in all_trails
        for trail in all_trails.values():
            assert len(trail) >= 1
            assert trail[0]["action"] == "created"

    # ---- Edge cases ----
    def test_add_deficiency_with_none_owner(self, tracker, user_id):
        did = tracker.add_deficiency(
            title="No owner", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
            owner_id=None,
        )
        d = tracker.get_deficiency(did)
        assert d.owner_id is None

    def test_update_deficiency_with_missing_field(self, tracker, user_id):
        did = tracker.add_deficiency(
            title="Orig", description="", category=DeficiencyCategory.OTHER,
            regulation="", severity=DeficiencySeverity.LOW,
            discovered_by=user_id,
        )
        tracker.update_deficiency(did, unknown_field="value")  # Should ignore
        d = tracker.get_deficiency(did)
        assert not hasattr(d, "unknown_field")
