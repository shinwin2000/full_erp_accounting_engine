# test_immutable_record.py
# =========================
# Comprehensive tests for immutable_record.py.
# Covers ImmutableIntentRecord and ImmutableIntentRecordService.

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    ImmutableIntentRecordService,
    IntentSource,
    IntentStatus,
    get_immutable_intent_record_service,
)
from domain.intent.intent_type import IntentType


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def intent_type() -> IntentType:
    """Return a sample IntentType."""
    return IntentType.APPROVE_TRANSACTION


@pytest.fixture
def sample_data() -> dict:
    return {"amount": 1000, "description": "Test"}


@pytest.fixture
def immutable_record(intent_type, sample_data) -> ImmutableIntentRecord:
    """Create a valid ImmutableIntentRecord."""
    return ImmutableIntentRecord(
        intent_id=uuid4(),
        intent_type=intent_type,
        data=sample_data,
        created_by="creator",
        created_at=datetime.now(UTC),
        status=IntentStatus.DRAFT,
        signed_by="signer",
        signature="signature_123",
        parent_intent_id=None,
        source=IntentSource.USER,
        source_id="src_001",
        version=1,
        previous_hash=None,
    )


@pytest.fixture
def record_service() -> ImmutableIntentRecordService:
    """Reset singleton and return fresh service."""
    ImmutableIntentRecordService._instance = None
    return ImmutableIntentRecordService()


# ----------------------------------------------------------------------
# Tests for Enums
# ----------------------------------------------------------------------
class TestIntentStatus:
    def test_members_exist(self):
        assert hasattr(IntentStatus, "DRAFT")
        assert hasattr(IntentStatus, "SUBMITTED")
        assert hasattr(IntentStatus, "APPROVED")
        assert hasattr(IntentStatus, "REJECTED")
        assert hasattr(IntentStatus, "EXECUTED")
        assert hasattr(IntentStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(IntentStatus.DRAFT, IntentStatus)


class TestIntentSource:
    def test_members_exist(self):
        assert hasattr(IntentSource, "USER")
        assert hasattr(IntentSource, "API")
        assert hasattr(IntentSource, "SYSTEM")
        assert hasattr(IntentSource, "IMPORT")
        assert hasattr(IntentSource, "WEBHOOK")

    def test_member_is_instance(self):
        assert isinstance(IntentSource.USER, IntentSource)


# ----------------------------------------------------------------------
# Tests for ImmutableIntentRecord
# ----------------------------------------------------------------------
class TestImmutableIntentRecord:
    def test_construction_valid(self, immutable_record):
        assert isinstance(immutable_record.intent_id, UUID)
        assert immutable_record.status == IntentStatus.DRAFT
        assert immutable_record.version == 1
        assert immutable_record.cryptographic_hash != ""
        assert len(immutable_record._snapshots) == 1
        assert len(immutable_record._audit_trail) == 1

    def test_construction_with_invalid_fields(self):
        # invalid created_by
        with pytest.raises(ValueError, match="created_by must be non-empty string"):
            ImmutableIntentRecord(
                intent_id=uuid4(),
                intent_type=IntentType.APPROVE_TRANSACTION,
                data={},
                created_by="",
                created_at=datetime.now(UTC),
                status=IntentStatus.DRAFT,
                signed_by="signer",
                signature="sig",
            )
        # invalid signature
        with pytest.raises(ValueError, match="signature must be non-empty string"):
            ImmutableIntentRecord(
                intent_id=uuid4(),
                intent_type=IntentType.APPROVE_TRANSACTION,
                data={},
                created_by="u",
                created_at=datetime.now(UTC),
                status=IntentStatus.DRAFT,
                signed_by="s",
                signature="",
            )
        # invalid version
        with pytest.raises(ValueError, match="version must be >= 1"):
            ImmutableIntentRecord(
                intent_id=uuid4(),
                intent_type=IntentType.APPROVE_TRANSACTION,
                data={},
                created_by="u",
                created_at=datetime.now(UTC),
                status=IntentStatus.DRAFT,
                signed_by="s",
                signature="sig",
                version=0,
            )
        # invalid source type
        with pytest.raises(TypeError, match="source must be IntentSource"):
            ImmutableIntentRecord(
                intent_id=uuid4(),
                intent_type=IntentType.APPROVE_TRANSACTION,
                data={},
                created_by="u",
                created_at=datetime.now(UTC),
                status=IntentStatus.DRAFT,
                signed_by="s",
                signature="sig",
                source="USER",  # type: ignore
            )

    def test_compute_hash(self, immutable_record):
        h1 = immutable_record.compute_hash()
        h2 = immutable_record.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA3-256

    def test_compute_hash_includes_snapshot_data(self, immutable_record):
        # changing data should change hash
        h1 = immutable_record.compute_hash()
        # We cannot modify frozen dataclass directly, but we can create a new one
        new_record = ImmutableIntentRecord(
            intent_id=immutable_record.intent_id,
            intent_type=immutable_record.intent_type,
            data={"different": "data"},
            created_by=immutable_record.created_by,
            created_at=immutable_record.created_at,
            status=immutable_record.status,
            signed_by=immutable_record.signed_by,
            signature=immutable_record.signature,
        )
        assert new_record.compute_hash() != h1

    def test_validate_valid(self, immutable_record):
        result = immutable_record.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["intent_id"] == str(immutable_record.intent_id)

    def test_validate_hash_mismatch(self, immutable_record):
        # Manually corrupt hash
        object.__setattr__(immutable_record, "cryptographic_hash", "corrupted")
        result = immutable_record.validate()
        assert result["is_valid"] is False
        assert any("Hash mismatch" in e for e in result["errors"])

    def test_to_dict(self, immutable_record):
        d = immutable_record.to_dict()
        assert d["intent_id"] == str(immutable_record.intent_id)
        assert d["intent_type"] == immutable_record.intent_type.name
        assert d["data"] == immutable_record.data
        assert d["created_by"] == immutable_record.created_by
        assert d["status"] == immutable_record.status.name
        assert d["signed_by"] == immutable_record.signed_by
        assert d["signature"] == immutable_record.signature[:16] + "..."  # truncated
        assert d["version"] == immutable_record.version

    def test_from_dict(self, immutable_record):
        d = immutable_record.to_dict()
        # Reconstruct with full signature (to_dict truncates, so we need original)
        d["signature"] = immutable_record.signature  # full signature
        d["created_at"] = immutable_record.created_at.isoformat()
        d["source"] = immutable_record.source.name
        new_record = ImmutableIntentRecord.from_dict(d)
        assert new_record.intent_id == immutable_record.intent_id
        assert new_record.intent_type == immutable_record.intent_type
        assert new_record.data == immutable_record.data
        assert new_record.created_by == immutable_record.created_by
        assert new_record.status == immutable_record.status
        assert new_record.signed_by == immutable_record.signed_by
        assert new_record.signature == immutable_record.signature
        assert new_record.source == immutable_record.source
        assert new_record.version == immutable_record.version

    def test_from_dict_with_intent_type_from_string(self, immutable_record):
        # Mock IntentType.from_string
        with patch("domain.intent.immutable_record.IntentType.from_string") as mock_from_string:
            mock_from_string.return_value = immutable_record.intent_type
            d = immutable_record.to_dict()
            d["signature"] = immutable_record.signature
            d["created_at"] = immutable_record.created_at.isoformat()
            ImmutableIntentRecord.from_dict(d)
            mock_from_string.assert_called_with(d["intent_type"])

    def test_clone(self, immutable_record):
        cloned = immutable_record.clone()
        assert cloned.intent_id != immutable_record.intent_id
        assert cloned.intent_type == immutable_record.intent_type
        assert cloned.data == immutable_record.data
        assert cloned.created_by == immutable_record.created_by
        assert cloned.status == IntentStatus.DRAFT
        assert cloned.parent_intent_id == immutable_record.intent_id
        assert cloned.version == 1

    def test_snapshot(self, immutable_record):
        snap = immutable_record.snapshot()
        assert snap["version"] == immutable_record.version
        assert snap["intent_id"] == str(immutable_record.intent_id)
        assert snap["status"] == immutable_record.status.name
        assert "timestamp" in snap

    def test_get_version(self, immutable_record):
        assert immutable_record.get_version() == 1

    def test_audit_trail(self, immutable_record):
        trail = immutable_record.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == immutable_record.created_by

    def test_touch(self, immutable_record):
        touched = immutable_record.touch("toucher")
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"
        assert touched is immutable_record  # returns self

    def test_is_approved(self, immutable_record):
        assert immutable_record.is_approved() is False
        approved = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=immutable_record.intent_type,
            data={},
            created_by="u",
            created_at=datetime.now(UTC),
            status=IntentStatus.APPROVED,
            signed_by="s",
            signature="sig",
        )
        assert approved.is_approved() is True

    def test_is_executable(self, immutable_record):
        assert immutable_record.is_executable() is False
        approved = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=immutable_record.intent_type,
            data={},
            created_by="u",
            created_at=datetime.now(UTC),
            status=IntentStatus.APPROVED,
            signed_by="s",
            signature="sig",
        )
        assert approved.is_executable() is True

    def test_create_amendment(self, immutable_record):
        new_data = {"extra": "value"}
        amendment = immutable_record.create_amendment(
            new_data=new_data,
            created_by="amender",
            signed_by="signer2",
            signature="sig2",
            reason="correct amount"
        )
        assert amendment.intent_id != immutable_record.intent_id
        assert amendment.intent_type == immutable_record.intent_type
        assert amendment.data["amount"] == immutable_record.data["amount"]  # original preserved
        assert amendment.data["extra"] == "value"
        assert amendment.data["amendment_reason"] == "correct amount"
        assert amendment.data["original_intent_id"] == str(immutable_record.intent_id)
        assert amendment.created_by == "amender"
        assert amendment.signed_by == "signer2"
        assert amendment.signature == "sig2"
        assert amendment.parent_intent_id == immutable_record.intent_id
        assert amendment.version == immutable_record.version + 1
        assert amendment.previous_hash == immutable_record.cryptographic_hash

    # Entity base methods (most are no-op or raise)
    def test_create_entity_method(self, immutable_record):
        result = immutable_record.create("creator")
        assert result is immutable_record
        trail = immutable_record.audit_trail(limit=1)
        # The first audit is from construction, new one is appended
        assert trail[0]["action"] == "TOUCH"  # because we just touched? Actually create method adds audit
        # We'll check that another audit entry was added
        assert len(immutable_record._audit_trail) >= 2

    def test_update_raises(self, immutable_record):
        with pytest.raises(AttributeError, match="ImmutableIntentRecord cannot be updated"):
            immutable_record.update("updater", data={})

    def test_delete_raises(self, immutable_record):
        with pytest.raises(AttributeError, match="Cannot delete. Cancel instead."):
            immutable_record.delete("deleter")

    def test_restore_raises(self, immutable_record):
        with pytest.raises(AttributeError, match="cannot be restored"):
            immutable_record.restore("restorer")

    def test_activate_noop(self, immutable_record):
        result = immutable_record.activate("activator")
        assert result is immutable_record
        # Should add audit trail
        trail = immutable_record.audit_trail(limit=1)
        # The last action should be ACTIVATE
        # But since we called activate after construction, it's the last
        assert trail[0]["action"] == "ACTIVATE"  # because we appended

    def test_deactivate_noop(self, immutable_record):
        result = immutable_record.deactivate("deactivator", "reason")
        assert result is immutable_record
        trail = immutable_record.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"

    def test_lock_noop(self, immutable_record):
        result = immutable_record.lock("locker", "reason")
        assert result is immutable_record
        trail = immutable_record.audit_trail(limit=1)
        assert trail[0]["action"] == "LOCK"

    def test_unlock_noop(self, immutable_record):
        result = immutable_record.unlock("unlocker")
        assert result is immutable_record
        trail = immutable_record.audit_trail(limit=1)
        assert trail[0]["action"] == "UNLOCK"


# ----------------------------------------------------------------------
# Tests for ImmutableIntentRecordService
# ----------------------------------------------------------------------
class TestImmutableIntentRecordService:
    def test_singleton(self):
        s1 = get_immutable_intent_record_service()
        s2 = get_immutable_intent_record_service()
        assert s1 is s2

    def test_store_and_get(self, record_service, immutable_record):
        record_service.store(immutable_record)
        retrieved = record_service.get(immutable_record.intent_id)
        assert retrieved is immutable_record

    def test_store_duplicate_raises(self, record_service, immutable_record):
        record_service.store(immutable_record)
        with pytest.raises(ValueError, match="already exists"):
            record_service.store(immutable_record)

    def test_get_not_found_returns_none(self, record_service):
        assert record_service.get(uuid4()) is None

    def test_get_chain_single(self, record_service, immutable_record):
        record_service.store(immutable_record)
        chain = record_service.get_chain(immutable_record.intent_id)
        assert len(chain) == 1
        assert chain[0] is immutable_record

    def test_get_chain_multiple(self, record_service, immutable_record):
        # Create parent-child chain
        parent = immutable_record
        record_service.store(parent)
        child = parent.create_amendment(
            new_data={"extra": "child"},
            created_by="child",
            signed_by="s",
            signature="sig",
            reason="child"
        )
        record_service.store(child)
        chain = record_service.get_chain(child.intent_id)
        assert len(chain) == 2
        assert chain[0] is parent
        assert chain[1] is child

    def test_get_by_status(self, record_service, immutable_record):
        record_service.store(immutable_record)
        # Create another with different status
        approved = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=immutable_record.intent_type,
            data={},
            created_by="u",
            created_at=datetime.now(UTC),
            status=IntentStatus.APPROVED,
            signed_by="s",
            signature="sig",
        )
        record_service.store(approved)
        drafts = record_service.get_by_status(IntentStatus.DRAFT)
        assert len(drafts) == 1
        assert drafts[0] is immutable_record
        approved_list = record_service.get_by_status(IntentStatus.APPROVED)
        assert len(approved_list) == 1
        assert approved_list[0] is approved

    def test_get_all(self, record_service, immutable_record):
        record_service.store(immutable_record)
        approved = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=immutable_record.intent_type,
            data={},
            created_by="u",
            created_at=datetime.now(UTC),
            status=IntentStatus.APPROVED,
            signed_by="s",
            signature="sig",
        )
        record_service.store(approved)
        all_records = record_service.get_all()
        assert len(all_records) == 2

    def test_count(self, record_service, immutable_record):
        assert record_service.count() == 0
        record_service.store(immutable_record)
        assert record_service.count() == 1

    def test_list(self, record_service, immutable_record):
        # Create 5 records with different timestamps
        now = datetime.now(UTC)
        for i in range(5):
            rec = ImmutableIntentRecord(
                intent_id=uuid4(),
                intent_type=immutable_record.intent_type,
                data={"index": i},
                created_by="u",
                created_at=now + timedelta(seconds=i),
                status=IntentStatus.DRAFT,
                signed_by="s",
                signature="sig",
            )
            record_service.store(rec)
        # list default limit 100 offset 0 -> all sorted reverse
        records = record_service.list(limit=3, offset=1)
        assert len(records) == 3
        # sorted by created_at descending, so index 4,3,2 then offset 1 gives 3,2,1
        assert records[0].data["index"] == 3
        assert records[1].data["index"] == 2
        assert records[2].data["index"] == 1

    def test_paginate(self, record_service, immutable_record):
        now = datetime.now(UTC)
        for i in range(25):
            rec = ImmutableIntentRecord(
                intent_id=uuid4(),
                intent_type=immutable_record.intent_type,
                data={"index": i},
                created_by="u",
                created_at=now + timedelta(seconds=i),
                status=IntentStatus.DRAFT,
                signed_by="s",
                signature="sig",
            )
            record_service.store(rec)
        page1, total = record_service.paginate(page=1, per_page=10)
        assert len(page1) == 10
        assert total == 25
        page2, _ = record_service.paginate(page=2, per_page=10)
        assert len(page2) == 10
        page3, _ = record_service.paginate(page=3, per_page=10)
        assert len(page3) == 5

    def test_exists(self, record_service, immutable_record):
        assert record_service.exists(immutable_record.intent_id) is False
        record_service.store(immutable_record)
        assert record_service.exists(immutable_record.intent_id) is True

    def test_search(self, record_service, immutable_record):
        rec1 = immutable_record
        rec2 = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=rec1.intent_type,
            data={"description": "purchase order"},
            created_by="bob",
            created_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            signed_by="s",
            signature="sig",
        )
        record_service.store(rec1)
        record_service.store(rec2)
        # Search by created_by
        results = record_service.search("creator")
        assert len(results) == 1
        assert results[0] is rec1
        # Search by data field
        results = record_service.search("purchase")
        assert len(results) == 1
        assert results[0] is rec2
        # Search with specific fields
        results = record_service.search("bob", fields=["created_by"])
        assert len(results) == 1

    def test_save_and_update(self, record_service, immutable_record):
        record_service.save(immutable_record)
        assert record_service.get(immutable_record.intent_id) is immutable_record
        record_service.update(immutable_record)  # no-op effectively

    def test_delete(self, record_service, immutable_record):
        record_service.store(immutable_record)
        assert record_service.exists(immutable_record.intent_id) is True
        record_service.delete(immutable_record.intent_id)
        assert record_service.exists(immutable_record.intent_id) is False

    def test_lock_and_unlock(self, record_service, immutable_record):
        record_service.store(immutable_record)
        # lock returns the same record (no-op)
        locked = record_service.lock(immutable_record.intent_id, "locker", "audit")
        assert locked is immutable_record
        unlocked = record_service.unlock(immutable_record.intent_id, "unlocker")
        assert unlocked is immutable_record

    def test_lock_not_found(self, record_service):
        with pytest.raises(ValueError, match="not found"):
            record_service.lock(uuid4(), "locker", "reason")

    def test_get_statistics(self, record_service, immutable_record):
        assert record_service.get_statistics() == {"total_records": 0, "by_status": {}}
        record_service.store(immutable_record)
        approved = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=immutable_record.intent_type,
            data={},
            created_by="u",
            created_at=datetime.now(UTC),
            status=IntentStatus.APPROVED,
            signed_by="s",
            signature="sig",
        )
        record_service.store(approved)
        stats = record_service.get_statistics()
        assert stats["total_records"] == 2
        assert stats["by_status"] == {"DRAFT": 1, "APPROVED": 1}

    def test_reset(self, record_service, immutable_record):
        record_service.store(immutable_record)
        assert record_service.count() == 1
        record_service.reset()
        assert record_service.count() == 0
