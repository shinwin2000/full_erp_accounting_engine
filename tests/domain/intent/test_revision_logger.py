# test_revision_logger.py
# =========================
# Comprehensive tests for revision_logger.py.
# Covers RevisionChangeType, RevisionChange, IntentRevision, and RevisionLogger.

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.intent.immutable_record import IntentStatus
from domain.intent.revision_logger import (
    IntentRevision,
    RevisionChange,
    RevisionChangeType,
    RevisionLogger,
    get_revision_logger,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_change() -> RevisionChange:
    return RevisionChange(
        field_name="amount",
        change_type=RevisionChangeType.UPDATE,
        old_value=100,
        new_value=200,
    )


@pytest.fixture
def sample_revision(sample_change) -> IntentRevision:
    return IntentRevision(
        revision_id=uuid4(),
        intent_id=uuid4(),
        revision_number=1,
        changed_by="alice",
        changed_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        changes=[sample_change],
        snapshot={"amount": 200, "description": "test"},
        reason="Updated amount",
        previous_hash=None,
        version=1,
    )


@pytest.fixture
def revision_logger() -> RevisionLogger:
    """Reset singleton and return fresh logger with mocked audit writer."""
    RevisionLogger._instance = None
    logger = RevisionLogger()
    logger._audit_writer = MagicMock()
    return logger


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestRevisionChangeType:
    def test_members_exist(self):
        assert hasattr(RevisionChangeType, "CREATE")
        assert hasattr(RevisionChangeType, "UPDATE")
        assert hasattr(RevisionChangeType, "DELETE")
        assert hasattr(RevisionChangeType, "STATUS_CHANGE")

    def test_member_is_instance(self):
        assert isinstance(RevisionChangeType.CREATE, RevisionChangeType)


# ----------------------------------------------------------------------
# RevisionChange
# ----------------------------------------------------------------------
class TestRevisionChange:
    def test_construction_valid(self, sample_change):
        assert sample_change.field_name == "amount"
        assert sample_change.change_type == RevisionChangeType.UPDATE
        assert sample_change.old_value == 100
        assert sample_change.new_value == 200

    def test_construction_empty_field_raises(self):
        with pytest.raises(ValueError, match="field_name cannot be empty"):
            RevisionChange(
                field_name="",
                change_type=RevisionChangeType.CREATE,
                old_value=None,
                new_value=None,
            )

    def test_construction_invalid_change_type_raises(self):
        with pytest.raises(ValueError, match="change_type must be RevisionChangeType"):
            RevisionChange(
                field_name="test",
                change_type="CREATE",  # type: ignore
                old_value=None,
                new_value=None,
            )

    def test_to_dict(self, sample_change):
        d = sample_change.to_dict()
        assert d["field_name"] == "amount"
        assert d["change_type"] == "UPDATE"
        assert d["old_value"] == "100"
        assert d["new_value"] == "200"

    def test_to_dict_with_none_values(self):
        change = RevisionChange(
            field_name="status",
            change_type=RevisionChangeType.DELETE,
            old_value="active",
            new_value=None,
        )
        d = change.to_dict()
        assert d["old_value"] == "active"
        assert d["new_value"] is None


# ----------------------------------------------------------------------
# IntentRevision
# ----------------------------------------------------------------------
class TestIntentRevision:
    def test_construction_valid(self, sample_revision, sample_change):
        assert isinstance(sample_revision.revision_id, UUID)
        assert sample_revision.revision_number == 1
        assert sample_revision.changed_by == "alice"
        assert sample_revision.changed_at == datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
        assert len(sample_revision.changes) == 1
        assert sample_revision.changes[0] is sample_change
        assert sample_revision.snapshot == {"amount": 200, "description": "test"}
        assert sample_revision.reason == "Updated amount"
        assert sample_revision.previous_hash is None
        assert sample_revision.version == 1
        assert sample_revision.cryptographic_hash != ""
        assert len(sample_revision._snapshots) == 1
        assert len(sample_revision._audit_trail) == 1

    def test_validation_errors(self):
        with pytest.raises(ValueError, match="revision_id must be UUID"):
            IntentRevision(
                revision_id="not-uuid",  # type: ignore
                intent_id=uuid4(),
                revision_number=1,
                changed_by="u",
                changed_at=datetime.now(UTC),
                changes=[],
                snapshot={},
            )
        with pytest.raises(ValueError, match="revision_number must be >= 1"):
            IntentRevision(
                revision_id=uuid4(),
                intent_id=uuid4(),
                revision_number=0,
                changed_by="u",
                changed_at=datetime.now(UTC),
                changes=[],
                snapshot={},
            )
        with pytest.raises(ValueError, match="changed_by cannot be empty"):
            IntentRevision(
                revision_id=uuid4(),
                intent_id=uuid4(),
                revision_number=1,
                changed_by="",
                changed_at=datetime.now(UTC),
                changes=[],
                snapshot={},
            )
        with pytest.raises(ValueError, match="changes must be list"):
            IntentRevision(
                revision_id=uuid4(),
                intent_id=uuid4(),
                revision_number=1,
                changed_by="u",
                changed_at=datetime.now(UTC),
                changes="not-list",  # type: ignore
                snapshot={},
            )
        with pytest.raises(ValueError, match="snapshot must be dict"):
            IntentRevision(
                revision_id=uuid4(),
                intent_id=uuid4(),
                revision_number=1,
                changed_by="u",
                changed_at=datetime.now(UTC),
                changes=[],
                snapshot="not-dict",  # type: ignore
            )

    def test_compute_hash(self, sample_revision):
        h1 = sample_revision.compute_hash()
        h2 = sample_revision.compute_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_validate_valid(self, sample_revision):
        result = sample_revision.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["revision_id"] == str(sample_revision.revision_id)

    def test_validate_hash_mismatch(self, sample_revision):
        object.__setattr__(sample_revision, "cryptographic_hash", "corrupted")
        result = sample_revision.validate()
        assert result["is_valid"] is False
        assert any("Hash mismatch" in e for e in result["errors"])

    def test_to_dict(self, sample_revision, sample_change):
        d = sample_revision.to_dict()
        assert d["revision_id"] == str(sample_revision.revision_id)
        assert d["intent_id"] == str(sample_revision.intent_id)
        assert d["revision_number"] == 1
        assert d["changed_by"] == "alice"
        assert d["changes"] == [sample_change.to_dict()]
        assert d["reason"] == "Updated amount"
        assert d["previous_hash"] is None
        assert d["cryptographic_hash"] == sample_revision.cryptographic_hash[:16] + "..."
        assert d["version"] == 1

    def test_from_dict(self, sample_revision, sample_change):
        d = sample_revision.to_dict()
        # Restore full hash and previous_hash (which is None)
        d["cryptographic_hash"] = sample_revision.cryptographic_hash
        d["previous_hash"] = sample_revision.previous_hash
        d["changed_at"] = sample_revision.changed_at.isoformat()
        # Need to reconstruct changes
        d["changes"] = [
            {
                "field_name": "amount",
                "change_type": "UPDATE",
                "old_value": 100,
                "new_value": 200,
            }
        ]
        new_revision = IntentRevision.from_dict(d)
        assert new_revision.revision_id == sample_revision.revision_id
        assert new_revision.intent_id == sample_revision.intent_id
        assert new_revision.revision_number == sample_revision.revision_number
        assert new_revision.changed_by == sample_revision.changed_by
        assert new_revision.changes[0].field_name == "amount"
        assert new_revision.changes[0].change_type == RevisionChangeType.UPDATE
        assert new_revision.changes[0].old_value == 100
        assert new_revision.changes[0].new_value == 200
        assert new_revision.reason == sample_revision.reason
        assert new_revision.version == sample_revision.version
        # snapshot is not stored in dict, so it's empty by from_dict
        assert new_revision.snapshot == {}

    def test_clone(self, sample_revision):
        cloned = sample_revision.clone()
        assert cloned.revision_id != sample_revision.revision_id
        assert cloned.intent_id == sample_revision.intent_id
        assert cloned.revision_number == sample_revision.revision_number + 1
        assert cloned.changed_by == sample_revision.changed_by
        assert cloned.changed_at != sample_revision.changed_at
        assert len(cloned.changes) == len(sample_revision.changes)
        assert cloned.snapshot == sample_revision.snapshot
        assert cloned.reason.startswith("Clone of revision")
        assert cloned.previous_hash == sample_revision.cryptographic_hash
        assert cloned.version == 1

    def test_snapshot(self, sample_revision):
        snap = sample_revision.snapshot()
        assert snap["version"] == 1
        assert snap["revision_id"] == str(sample_revision.revision_id)
        assert snap["intent_id"] == str(sample_revision.intent_id)
        assert snap["revision_number"] == 1
        assert "timestamp" in snap

    def test_get_version(self, sample_revision):
        assert sample_revision.get_version() == 1

    def test_audit_trail(self, sample_revision):
        trail = sample_revision.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "alice"

    def test_touch(self, sample_revision):
        touched = sample_revision.touch("toucher")
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"
        assert touched is sample_revision

    def test_immutable_methods_raise(self, sample_revision):
        with pytest.raises(AttributeError, match="is immutable"):
            sample_revision.update("u", data={})
        with pytest.raises(AttributeError, match="cannot be deleted"):
            sample_revision.delete("u")
        with pytest.raises(AttributeError, match="cannot be restored"):
            sample_revision.restore("u")
        # activate/deactivate/lock/unlock are no-ops
        assert sample_revision.activate("u") is sample_revision
        assert sample_revision.deactivate("u") is sample_revision
        assert sample_revision.lock("u", "r") is sample_revision
        assert sample_revision.unlock("u") is sample_revision


# ----------------------------------------------------------------------
# RevisionLogger
# ----------------------------------------------------------------------
class TestRevisionLogger:
    def test_singleton(self):
        l1 = get_revision_logger()
        l2 = get_revision_logger()
        assert l1 is l2

    def test_log_revision_new(self, revision_logger):
        intent_id = uuid4()
        old_data = {"amount": 100, "description": "old"}
        new_data = {"amount": 200, "description": "old", "extra": "new"}
        revision = revision_logger.log_revision(
            intent_id=intent_id,
            changed_by="bob",
            old_data=old_data,
            new_data=new_data,
            reason="Updated amount"
        )
        assert revision is not None
        assert revision.intent_id == intent_id
        assert revision.revision_number == 1
        assert revision.changed_by == "bob"
        assert len(revision.changes) == 2  # amount updated, extra created
        # Check changes
        changes = {c.field_name: c for c in revision.changes}
        assert "amount" in changes
        assert changes["amount"].change_type == RevisionChangeType.UPDATE
        assert changes["amount"].old_value == 100
        assert changes["amount"].new_value == 200
        assert "extra" in changes
        assert changes["extra"].change_type == RevisionChangeType.CREATE
        assert changes["extra"].old_value is None
        assert changes["extra"].new_value == "new"
        # Snapshot should be new_data
        assert revision.snapshot == new_data
        # Audit written
        revision_logger._audit_writer.write.assert_called_once()

    def test_log_revision_no_changes(self, revision_logger):
        intent_id = uuid4()
        old_data = {"amount": 100}
        new_data = {"amount": 100}
        result = revision_logger.log_revision(
            intent_id=intent_id,
            changed_by="bob",
            old_data=old_data,
            new_data=new_data,
        )
        assert result is None
        # No revision stored
        assert revision_logger.get_revisions(intent_id) == []
        # Audit should not be called? Actually the method checks changes and returns None before audit.
        # So audit_writer.write is not called.
        revision_logger._audit_writer.write.assert_not_called()

    def test_log_revision_skips_underscore_fields(self, revision_logger):
        old_data = {"amount": 100, "_internal": "secret"}
        new_data = {"amount": 200, "_internal": "secret_updated"}
        revision = revision_logger.log_revision(
            intent_id=uuid4(),
            changed_by="bob",
            old_data=old_data,
            new_data=new_data,
        )
        assert revision is not None
        # Only amount change should be present
        assert len(revision.changes) == 1
        assert revision.changes[0].field_name == "amount"
        assert revision.changes[0].change_type == RevisionChangeType.UPDATE

    def test_log_revision_creates_chain_with_previous_hash(self, revision_logger):
        intent_id = uuid4()
        # First revision
        rev1 = revision_logger.log_revision(
            intent_id, "alice", {"a": 1}, {"a": 2}, "first"
        )
        # Second revision
        rev2 = revision_logger.log_revision(
            intent_id, "bob", {"a": 2}, {"a": 3}, "second"
        )
        assert rev1 is not None
        assert rev2 is not None
        assert rev1.revision_number == 1
        assert rev2.revision_number == 2
        assert rev2.previous_hash == rev1.cryptographic_hash

    def test_log_status_change(self, revision_logger):
        intent_id = uuid4()
        old_status = IntentStatus.DRAFT
        new_status = IntentStatus.SUBMITTED
        revision = revision_logger.log_status_change(
            intent_id=intent_id,
            changed_by="alice",
            old_status=old_status,
            new_status=new_status,
            reason="Submit for approval"
        )
        assert revision is not None
        assert revision.revision_number == 1
        assert len(revision.changes) == 1
        change = revision.changes[0]
        assert change.field_name == "status"
        assert change.change_type == RevisionChangeType.STATUS_CHANGE
        assert change.old_value == "DRAFT"
        assert change.new_value == "SUBMITTED"
        assert revision.snapshot["status"] == "SUBMITTED"
        # Audit written with severity WARNING if new_status is REJECTED
        # For SUBMITTED, it should be INFO
        revision_logger._audit_writer.write.assert_called_once()
        call_kwargs = revision_logger._audit_writer.write.call_args[1]
        assert call_kwargs["severity"].name == "INFO"

    def test_log_status_change_rejected_uses_warning(self, revision_logger):
        intent_id = uuid4()
        revision = revision_logger.log_status_change(
            intent_id=intent_id,
            changed_by="alice",
            old_status=IntentStatus.SUBMITTED,
            new_status=IntentStatus.REJECTED,
            reason="Not approved"
        )
        assert revision is not None
        call_kwargs = revision_logger._audit_writer.write.call_args[1]
        assert call_kwargs["severity"].name == "WARNING"

    def test_get_revisions(self, revision_logger):
        intent_id = uuid4()
        # Log multiple revisions
        for i in range(5):
            revision_logger.log_revision(
                intent_id,
                "u",
                {"a": i},
                {"a": i + 1},
                f"rev{i}"
            )
        revs = revision_logger.get_revisions(intent_id, limit=3)
        # Should return latest 3 in descending order (newest first)
        assert len(revs) == 3
        assert revs[0].revision_number == 5
        assert revs[1].revision_number == 4
        assert revs[2].revision_number == 3
        # Without limit, default 50
        revs_all = revision_logger.get_revisions(intent_id)
        assert len(revs_all) == 5

    def test_get_revision_by_number(self, revision_logger):
        intent_id = uuid4()
        rev1 = revision_logger.log_revision(intent_id, "u", {"a": 1}, {"a": 2}, "first")
        rev2 = revision_logger.log_revision(intent_id, "u", {"a": 2}, {"a": 3}, "second")
        found = revision_logger.get_revision(intent_id, 2)
        assert found is not None
        assert found.revision_number == 2
        assert found.previous_hash == rev1.cryptographic_hash
        # Not found
        assert revision_logger.get_revision(intent_id, 99) is None

    def test_get_latest_revision(self, revision_logger):
        intent_id = uuid4()
        assert revision_logger.get_latest_revision(intent_id) is None
        rev1 = revision_logger.log_revision(intent_id, "u", {"a": 1}, {"a": 2}, "first")
        latest = revision_logger.get_latest_revision(intent_id)
        assert latest is rev1
        rev2 = revision_logger.log_revision(intent_id, "u", {"a": 2}, {"a": 3}, "second")
        latest = revision_logger.get_latest_revision(intent_id)
        assert latest is rev2

    def test_get_revision_diff(self, revision_logger):
        intent_id = uuid4()
        revision_logger.log_revision(intent_id, "u", {"a": 1, "b": 2}, {"a": 2, "b": 2}, "first")
        revision_logger.log_revision(intent_id, "u", {"a": 2, "b": 2}, {"a": 3, "b": 3}, "second")
        diff = revision_logger.get_revision_diff(intent_id, 1, 2)
        assert len(diff) == 2  # a updated, b created? Actually b changed from 2 to 3, so both a and b changed
        # From rev1 snapshot: a=2, b=2; to rev2 snapshot: a=3, b=3
        # So both changed: a: 2->3, b: 2->3
        assert any(c.field_name == "a" and c.old_value == 2 and c.new_value == 3 for c in diff)
        assert any(c.field_name == "b" and c.old_value == 2 and c.new_value == 3 for c in diff)
        # Invalid revision numbers
        assert revision_logger.get_revision_diff(intent_id, 1, 99) == []

    def test_rollback_to_revision(self, revision_logger):
        intent_id = uuid4()
        # Create revisions
        rev1 = revision_logger.log_revision(intent_id, "u", {"a": 1}, {"a": 2}, "first")
        rev2 = revision_logger.log_revision(intent_id, "u", {"a": 2}, {"a": 3}, "second")
        rev3 = revision_logger.log_revision(intent_id, "u", {"a": 3}, {"a": 4}, "third")
        # Rollback to revision 2
        rollback = revision_logger.rollback_to_revision(
            intent_id, 2, "admin", "Rollback to rev2"
        )
        assert rollback is not None
        # The rollback creates a new revision (rev4) that reverts snapshot from rev3 to rev2
        assert rollback.revision_number == 4
        assert rollback.snapshot == rev2.snapshot  # should be {"a": 3}
        # Changes should reflect the diff between rev3 and rev2
        # rev3 has a=4, rev2 has a=3, so change: a: 4->3
        assert len(rollback.changes) == 1
        assert rollback.changes[0].field_name == "a"
        assert rollback.changes[0].old_value == 4
        assert rollback.changes[0].new_value == 3
        # Rollback to non-existent revision
        assert revision_logger.rollback_to_revision(intent_id, 99, "admin") is None

    def test_save_revision(self, revision_logger, sample_revision):
        # Simulate saving a revision directly (not via log)
        revision_logger.save_revision(sample_revision)
        revs = revision_logger.get_revisions(sample_revision.intent_id)
        assert len(revs) == 1
        assert revs[0] is sample_revision
        # Ensure current_revision_numbers is updated? Actually save_revision doesn't update the counter,
        # so we should not rely on that. But get_revisions works.

    def test_get_all_revisions(self, revision_logger):
        # Create revisions for multiple intents
        intent1 = uuid4()
        intent2 = uuid4()
        revision_logger.log_revision(intent1, "u", {"a": 1}, {"a": 2}, "r1")
        revision_logger.log_revision(intent1, "u", {"a": 2}, {"a": 3}, "r2")
        revision_logger.log_revision(intent2, "u", {"b": 1}, {"b": 2}, "r3")
        all_revs = revision_logger.get_all_revisions()
        assert len(all_revs) == 3

    def test_delete_revisions_for_intent(self, revision_logger):
        intent_id = uuid4()
        revision_logger.log_revision(intent_id, "u", {"a": 1}, {"a": 2}, "r1")
        assert len(revision_logger.get_revisions(intent_id)) == 1
        result = revision_logger.delete_revisions_for_intent(intent_id)
        assert result is True
        assert revision_logger.get_revisions(intent_id) == []
        # Delete again returns False
        result = revision_logger.delete_revisions_for_intent(intent_id)
        assert result is False

    def test_get_statistics(self, revision_logger):
        stats = revision_logger.get_statistics()
        assert stats["total_intents_with_revisions"] == 0
        assert stats["total_revisions"] == 0
        assert stats["average_revisions_per_intent"] == 0
        assert stats["max_revisions_per_intent"] == 0

        # Add revisions for intents
        intent1 = uuid4()
        intent2 = uuid4()
        for i in range(3):
            revision_logger.log_revision(intent1, "u", {"a": i}, {"a": i+1}, f"r{i}")
        for i in range(5):
            revision_logger.log_revision(intent2, "u", {"b": i}, {"b": i+1}, f"r{i}")
        stats = revision_logger.get_statistics()
        assert stats["total_intents_with_revisions"] == 2
        assert stats["total_revisions"] == 8
        assert stats["average_revisions_per_intent"] == 4.0
        assert stats["max_revisions_per_intent"] == 5

    def test_reset(self, revision_logger):
        intent_id = uuid4()
        revision_logger.log_revision(intent_id, "u", {"a": 1}, {"a": 2}, "r1")
        assert len(revision_logger.get_revisions(intent_id)) == 1
        revision_logger.reset()
        assert revision_logger.get_revisions(intent_id) == []
        assert revision_logger.get_statistics()["total_revisions"] == 0

    def test_max_revisions_limit(self, revision_logger):
        # Set a small limit for testing
        revision_logger._max_revisions_per_intent = 3
        intent_id = uuid4()
        for i in range(5):
            revision_logger.log_revision(intent_id, "u", {"a": i}, {"a": i+1}, f"r{i}")
        revs = revision_logger.get_revisions(intent_id)
        # Only last 3 revisions should be kept
        assert len(revs) == 3
        assert revs[0].revision_number == 5
        assert revs[1].revision_number == 4
        assert revs[2].revision_number == 3
