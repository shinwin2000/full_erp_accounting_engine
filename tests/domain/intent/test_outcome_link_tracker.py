# test_outcome_link_tracker.py
# =============================
# Comprehensive tests for outcome_link_tracker.py.
# Covers LinkStatus, LinkType, IntentOutcomeLink, and OutcomeLinkTracker.

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.intent.outcome_link_tracker import (
    IntentOutcomeLink,
    LinkStatus,
    LinkType,
    OutcomeLinkTracker,
    get_outcome_link_tracker,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def link_data() -> dict:
    return {
        "link_id": uuid4(),
        "intent_id": uuid4(),
        "outcome_id": uuid4(),
        "outcome_type": "journal_entry",
        "link_type": LinkType.ONE_TO_ONE,
        "status": LinkStatus.MAPPED,
        "created_at": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        "created_by": "alice",
        "metadata": {"key": "value"},
        "version": 1,
    }


@pytest.fixture
def link(link_data) -> IntentOutcomeLink:
    return IntentOutcomeLink(**link_data)


@pytest.fixture
def tracker() -> OutcomeLinkTracker:
    """Reset singleton and return fresh tracker with mocked dependencies."""
    OutcomeLinkTracker._instance = None
    tracker = OutcomeLinkTracker()
    tracker._audit_writer = MagicMock()
    tracker._record_service = MagicMock()
    return tracker


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestLinkStatus:
    def test_members_exist(self):
        assert hasattr(LinkStatus, "PENDING")
        assert hasattr(LinkStatus, "MAPPED")
        assert hasattr(LinkStatus, "EXECUTED")
        assert hasattr(LinkStatus, "FAILED")
        assert hasattr(LinkStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(LinkStatus.PENDING, LinkStatus)


class TestLinkType:
    def test_members_exist(self):
        assert hasattr(LinkType, "ONE_TO_ONE")
        assert hasattr(LinkType, "ONE_TO_MANY")
        assert hasattr(LinkType, "MANY_TO_ONE")
        assert hasattr(LinkType, "MANY_TO_MANY")

    def test_member_is_instance(self):
        assert isinstance(LinkType.ONE_TO_ONE, LinkType)


# ----------------------------------------------------------------------
# IntentOutcomeLink
# ----------------------------------------------------------------------
class TestIntentOutcomeLink:
    def test_construction_valid(self, link):
        assert isinstance(link.link_id, UUID)
        assert link.intent_id is not None
        assert link.outcome_id is not None
        assert link.outcome_type == "journal_entry"
        assert link.link_type == LinkType.ONE_TO_ONE
        assert link.status == LinkStatus.MAPPED
        assert link.created_by == "alice"
        assert link.metadata == {"key": "value"}
        assert link.version == 1
        assert link.cryptographic_hash != ""
        assert len(link._snapshots) == 1
        assert len(link._audit_trail) == 1

    def test_construction_invalid_fields(self):
        # Invalid link_id type
        with pytest.raises(ValueError, match="link_id must be UUID"):
            IntentOutcomeLink(
                link_id="not-uuid",  # type: ignore
                intent_id=uuid4(),
                outcome_id=uuid4(),
                outcome_type="type",
                link_type=LinkType.ONE_TO_ONE,
                status=LinkStatus.PENDING,
                created_at=datetime.now(UTC),
                created_by="u",
            )
        # Invalid intent_id type
        with pytest.raises(ValueError, match="intent_id must be UUID"):
            IntentOutcomeLink(
                link_id=uuid4(),
                intent_id="bad",  # type: ignore
                outcome_id=uuid4(),
                outcome_type="type",
                link_type=LinkType.ONE_TO_ONE,
                status=LinkStatus.PENDING,
                created_at=datetime.now(UTC),
                created_by="u",
            )
        # Invalid outcome_type empty
        with pytest.raises(ValueError, match="outcome_type must be a non-empty string"):
            IntentOutcomeLink(
                link_id=uuid4(),
                intent_id=uuid4(),
                outcome_id=uuid4(),
                outcome_type="",
                link_type=LinkType.ONE_TO_ONE,
                status=LinkStatus.PENDING,
                created_at=datetime.now(UTC),
                created_by="u",
            )
        # Invalid status type
        with pytest.raises(ValueError, match="status must be LinkStatus"):
            IntentOutcomeLink(
                link_id=uuid4(),
                intent_id=uuid4(),
                outcome_id=uuid4(),
                outcome_type="type",
                link_type=LinkType.ONE_TO_ONE,
                status="PENDING",  # type: ignore
                created_at=datetime.now(UTC),
                created_by="u",
            )
        # Invalid version < 1
        with pytest.raises(ValueError, match="version must be >= 1"):
            IntentOutcomeLink(
                link_id=uuid4(),
                intent_id=uuid4(),
                outcome_id=uuid4(),
                outcome_type="type",
                link_type=LinkType.ONE_TO_ONE,
                status=LinkStatus.PENDING,
                created_at=datetime.now(UTC),
                created_by="u",
                version=0,
            )

    def test_compute_hash(self, link):
        h1 = link.compute_hash()
        h2 = link.compute_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_validate_valid(self, link):
        result = link.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["link_id"] == str(link.link_id)

    def test_validate_hash_mismatch(self, link):
        object.__setattr__(link, "cryptographic_hash", "corrupted")
        result = link.validate()
        assert result["is_valid"] is False
        assert any("Hash mismatch" in e for e in result["errors"])

    def test_to_dict(self, link):
        d = link.to_dict()
        assert d["link_id"] == str(link.link_id)
        assert d["intent_id"] == str(link.intent_id)
        assert d["outcome_id"] == str(link.outcome_id)
        assert d["outcome_type"] == "journal_entry"
        assert d["link_type"] == "ONE_TO_ONE"
        assert d["status"] == "MAPPED"
        assert d["created_by"] == "alice"
        assert d["metadata"] == {"key": "value"}
        assert d["version"] == 1
        assert d["cryptographic_hash"] == link.cryptographic_hash[:16] + "..."

    def test_from_dict(self, link):
        d = link.to_dict()
        # Restore full hash and created_at string
        d["cryptographic_hash"] = link.cryptographic_hash
        d["created_at"] = link.created_at.isoformat()
        new_link = IntentOutcomeLink.from_dict(d)
        assert new_link.link_id == link.link_id
        assert new_link.intent_id == link.intent_id
        assert new_link.outcome_id == link.outcome_id
        assert new_link.outcome_type == link.outcome_type
        assert new_link.link_type == link.link_type
        assert new_link.status == link.status
        assert new_link.created_by == link.created_by
        assert new_link.metadata == link.metadata
        assert new_link.version == link.version

    def test_clone(self, link):
        cloned = link.clone()
        assert cloned.link_id != link.link_id
        assert cloned.intent_id == link.intent_id
        assert cloned.outcome_id == link.outcome_id
        assert cloned.outcome_type == link.outcome_type
        assert cloned.link_type == link.link_type
        assert cloned.status == LinkStatus.PENDING  # reset
        assert cloned.created_at != link.created_at  # new timestamp
        assert cloned.created_by == link.created_by
        assert cloned.metadata == link.metadata
        assert cloned.version == 1

    def test_snapshot(self, link):
        snap = link.snapshot()
        assert snap["version"] == 1
        assert snap["link_id"] == str(link.link_id)
        assert snap["intent_id"] == str(link.intent_id)
        assert snap["outcome_id"] == str(link.outcome_id)
        assert snap["status"] == "MAPPED"
        assert "timestamp" in snap

    def test_get_version(self, link):
        assert link.get_version() == 1

    def test_audit_trail(self, link):
        trail = link.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "alice"

    def test_touch(self, link):
        touched = link.touch("toucher")
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"
        assert touched is link  # returns self

    def test_update(self, link):
        new_metadata = {"new": "value"}
        updated = link.update("bob", status=LinkStatus.EXECUTED, metadata=new_metadata)
        assert updated.status == LinkStatus.EXECUTED
        assert updated.metadata == {"key": "value", "new": "value"}
        assert updated.version == 2
        trail = updated.audit_trail(limit=1)
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["performed_by"] == "bob"
        assert trail[0]["details"]["changes"]["status"] == LinkStatus.EXECUTED

    def test_delete(self, link):
        deleted = link.delete("bob", "no longer needed")
        assert deleted.status == LinkStatus.CANCELLED
        assert deleted.version == 2
        trail = deleted.audit_trail(limit=1)
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["performed_by"] == "bob"
        assert trail[0]["details"]["reason"] == "no longer needed"

    def test_restore_not_cancelled(self, link):
        with pytest.raises(ValueError, match="Only cancelled links can be restored"):
            link.restore("restorer")

    def test_restore_cancelled(self, link):
        cancelled = link.delete("bob")
        restored = cancelled.restore("restorer")
        assert restored.status == LinkStatus.MAPPED
        assert restored.version == 3
        trail = restored.audit_trail(limit=1)
        assert trail[0]["action"] == "RESTORE"

    def test_activate_pending(self, link):
        # Set status to PENDING first
        pending = link.update("bob", status=LinkStatus.PENDING)
        activated = pending.activate("charlie")
        assert activated.status == LinkStatus.MAPPED
        assert activated.version == 3  # update (2) + activate (3)
        trail = activated.audit_trail(limit=1)
        assert trail[0]["action"] == "ACTIVATE"

    def test_activate_not_pending(self, link):
        # Already MAPPED, activate should return self
        result = link.activate("charlie")
        assert result is link  # no change
        # No new audit? Actually activate method checks if pending, else returns self.
        # It doesn't add audit, so trail length remains 1.
        assert len(link.audit_trail()) == 1

    def test_deactivate_mapped(self, link):
        deactivated = link.deactivate("charlie", "needs review")
        assert deactivated.status == LinkStatus.PENDING
        assert deactivated.version == 2
        trail = deactivated.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "needs review"

    def test_deactivate_not_mapped(self, link):
        # Set to EXECUTED first
        executed = link.update("bob", status=LinkStatus.EXECUTED)
        result = executed.deactivate("charlie")
        assert result.status == LinkStatus.EXECUTED  # unchanged
        # Should not add audit because returns self
        assert len(result.audit_trail()) == 2  # create + update

    def test_lock_unlock_noop(self, link):
        locked = link.lock("locker", "reason")
        assert locked is link
        unlocked = link.unlock("unlocker")
        assert unlocked is link


# ----------------------------------------------------------------------
# OutcomeLinkTracker
# ----------------------------------------------------------------------
class TestOutcomeLinkTracker:
    def test_singleton(self):
        t1 = get_outcome_link_tracker()
        t2 = get_outcome_link_tracker()
        assert t1 is t2

    def test_create_link(self, tracker):
        intent_id = uuid4()
        outcome_id = uuid4()
        link = tracker.create_link(
            intent_id=intent_id,
            outcome_id=outcome_id,
            outcome_type="journal",
            created_by="alice",
            link_type=LinkType.ONE_TO_ONE,
            metadata={"source": "test"},
        )
        assert isinstance(link, IntentOutcomeLink)
        assert link.intent_id == intent_id
        assert link.outcome_id == outcome_id
        assert link.outcome_type == "journal"
        assert link.status == LinkStatus.MAPPED
        assert link.created_by == "alice"
        assert link.metadata == {"source": "test"}
        # Check indexes
        assert tracker._intent_to_outcomes[intent_id] == [outcome_id]
        assert tracker._outcome_to_intents[outcome_id] == [intent_id]
        # Audit called
        tracker._audit_writer.write_linked_to_outcome.assert_called_once_with(
            intent_id, "alice", outcome_id
        )

    def test_create_multi_link(self, tracker):
        intent_id = uuid4()
        outcome_ids = [uuid4(), uuid4()]
        links = tracker.create_multi_link(
            intent_id=intent_id,
            outcome_ids=outcome_ids,
            outcome_type="invoice",
            created_by="bob",
            metadata={"batch": "001"},
        )
        assert len(links) == 2
        for link in links:
            assert link.intent_id == intent_id
            assert link.outcome_type == "invoice"
            assert link.link_type == LinkType.ONE_TO_MANY
            assert link.metadata == {"batch": "001"}
        # Both stored
        stored_ids = [l.outcome_id for l in tracker.get_all_links()]
        assert set(stored_ids) == set(outcome_ids)
        # Indexes
        assert tracker._intent_to_outcomes[intent_id] == outcome_ids

    def test_update_link_status(self, tracker):
        link = tracker.create_link(
            intent_id=uuid4(),
            outcome_id=uuid4(),
            outcome_type="type",
            created_by="u",
        )
        link_id = link.link_id
        updated = tracker.update_link_status(link_id, LinkStatus.EXECUTED, "updater")
        assert updated is not None
        assert updated.status == LinkStatus.EXECUTED
        assert updated.version == 2
        # Should be updated in store
        stored = tracker.get_link(link_id)
        assert stored.status == LinkStatus.EXECUTED
        tracker._audit_writer.write.assert_called_once()

    def test_update_link_status_not_found(self, tracker):
        result = tracker.update_link_status(uuid4(), LinkStatus.EXECUTED, "u")
        assert result is None

    def test_get_outcomes_for_intent(self, tracker):
        intent_id = uuid4()
        outcome1 = uuid4()
        outcome2 = uuid4()
        tracker.create_link(intent_id, outcome1, "type", "u")
        tracker.create_link(intent_id, outcome2, "type", "u")
        # One more with different outcome_type
        outcome3 = uuid4()
        tracker.create_link(intent_id, outcome3, "other", "u")
        results = tracker.get_outcomes_for_intent(intent_id)
        assert len(results) == 3
        # Filter by type
        results = tracker.get_outcomes_for_intent(intent_id, outcome_type="type")
        assert len(results) == 2
        # Should exclude cancelled links
        link = tracker.get_all_links()[0]
        tracker.update_link_status(link.link_id, LinkStatus.CANCELLED, "admin")
        results = tracker.get_outcomes_for_intent(intent_id)
        assert len(results) == 2  # only two left (the cancelled one excluded)

    def test_get_intents_for_outcome(self, tracker):
        outcome_id = uuid4()
        intent1 = uuid4()
        intent2 = uuid4()
        tracker.create_link(intent1, outcome_id, "type", "u")
        tracker.create_link(intent2, outcome_id, "type", "u")
        results = tracker.get_intents_for_outcome(outcome_id)
        assert len(results) == 2
        # Exclude cancelled
        link = tracker.get_all_links()[0]
        tracker.update_link_status(link.link_id, LinkStatus.CANCELLED, "admin")
        results = tracker.get_intents_for_outcome(outcome_id)
        assert len(results) == 1

    def test_get_link(self, tracker):
        link = tracker.create_link(uuid4(), uuid4(), "type", "u")
        retrieved = tracker.get_link(link.link_id)
        assert retrieved is link

    def test_get_traceability_chain(self, tracker):
        # Create chain: intent A -> outcome X -> intent B -> outcome Y
        intent_a = uuid4()
        outcome_x = uuid4()
        intent_b = uuid4()
        outcome_y = uuid4()
        tracker.create_link(intent_a, outcome_x, "type", "u")
        tracker.create_link(intent_b, outcome_x, "type", "u")  # many-to-one
        tracker.create_link(intent_b, outcome_y, "type", "u")

        # Start from intent_a
        chain = tracker.get_traceability_chain(intent_a, "intent", max_depth=5)
        # Should find: intent_a -> outcome_x -> intent_b -> outcome_y
        # Actually we have intent_a -> outcome_x, then outcome_x -> intent_b, then intent_b -> outcome_y
        assert len(chain) >= 3
        # First hop: from intent to outcome
        assert chain[0]["from_type"] == "intent"
        assert chain[0]["from_id"] == str(intent_a)
        assert chain[0]["to_type"] == "outcome"
        assert chain[0]["to_id"] == str(outcome_x)
        # Second hop: from outcome to intent
        found = False
        for entry in chain:
            if entry["from_type"] == "outcome" and entry["to_type"] == "intent":
                if entry["from_id"] == str(outcome_x) and entry["to_id"] == str(intent_b):
                    found = True
                    break
        assert found
        # Third hop: intent_b -> outcome_y
        found2 = False
        for entry in chain:
            if entry["from_type"] == "intent" and entry["to_type"] == "outcome":
                if entry["from_id"] == str(intent_b) and entry["to_id"] == str(outcome_y):
                    found2 = True
                    break
        assert found2

        # Start from outcome_y, should go backward: outcome_y -> intent_b -> outcome_x -> intent_a
        chain2 = tracker.get_traceability_chain(outcome_y, "outcome", max_depth=5)
        assert len(chain2) >= 2
        # First hop: outcome -> intent
        assert chain2[0]["from_type"] == "outcome"
        assert chain2[0]["from_id"] == str(outcome_y)
        assert chain2[0]["to_type"] == "intent"
        assert chain2[0]["to_id"] == str(intent_b)

    def test_save(self, tracker):
        link = IntentOutcomeLink(
            link_id=uuid4(),
            intent_id=uuid4(),
            outcome_id=uuid4(),
            outcome_type="type",
            link_type=LinkType.ONE_TO_ONE,
            status=LinkStatus.PENDING,
            created_at=datetime.now(UTC),
            created_by="u",
        )
        tracker.save(link)
        assert tracker.get_link(link.link_id) is link
        assert tracker._intent_to_outcomes[link.intent_id] == [link.outcome_id]
        assert tracker._outcome_to_intents[link.outcome_id] == [link.intent_id]

    def test_get_all_links(self, tracker):
        for _ in range(3):
            tracker.create_link(uuid4(), uuid4(), "type", "u")
        all_links = tracker.get_all_links()
        assert len(all_links) == 3

    def test_delete_link(self, tracker):
        link = tracker.create_link(uuid4(), uuid4(), "type", "u")
        link_id = link.link_id
        # Delete
        result = tracker.delete_link(link_id)
        assert result is True
        assert tracker.get_link(link_id) is None
        # Indexes cleaned
        assert link.intent_id not in tracker._intent_to_outcomes or link.outcome_id not in tracker._intent_to_outcomes.get(link.intent_id, [])
        # Try deleting non-existent
        result = tracker.delete_link(uuid4())
        assert result is False

    def test_count_links(self, tracker):
        assert tracker.count_links() == 0
        tracker.create_link(uuid4(), uuid4(), "type", "u")
        assert tracker.count_links() == 1

    def test_search_links_by_intent(self, tracker):
        intent_id = uuid4()
        tracker.create_link(intent_id, uuid4(), "type", "u")
        tracker.create_link(intent_id, uuid4(), "type", "u")
        tracker.create_link(uuid4(), uuid4(), "type", "u")
        results = tracker.search_links_by_intent(intent_id)
        assert len(results) == 2

    def test_search_links_by_outcome(self, tracker):
        outcome_id = uuid4()
        tracker.create_link(uuid4(), outcome_id, "type", "u")
        tracker.create_link(uuid4(), outcome_id, "type", "u")
        tracker.create_link(uuid4(), uuid4(), "type", "u")
        results = tracker.search_links_by_outcome(outcome_id)
        assert len(results) == 2

    def test_get_statistics(self, tracker):
        stats = tracker.get_statistics()
        assert stats["total_links"] == 0
        assert stats["by_status"] == {}
        assert stats["by_link_type"] == {}
        assert stats["total_intents_with_outcomes"] == 0
        assert stats["total_outcomes_with_intents"] == 0

        tracker.create_link(uuid4(), uuid4(), "type", "u")
        tracker.create_link(uuid4(), uuid4(), "other", "u", link_type=LinkType.ONE_TO_MANY)
        stats = tracker.get_statistics()
        assert stats["total_links"] == 2
        assert stats["by_status"] == {"MAPPED": 2}
        assert stats["by_link_type"] == {"ONE_TO_ONE": 1, "ONE_TO_MANY": 1}
        assert stats["total_intents_with_outcomes"] == 2
        assert stats["total_outcomes_with_intents"] == 2

    def test_reset(self, tracker):
        tracker.create_link(uuid4(), uuid4(), "type", "u")
        assert tracker.count_links() == 1
        tracker.reset()
        assert tracker.count_links() == 0
        assert tracker._intent_to_outcomes == {}
        assert tracker._outcome_to_intents == {}