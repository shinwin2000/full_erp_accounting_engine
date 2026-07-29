# test_void_processor.py
# =========================
# Comprehensive tests for void_processor.py.
# Covers VoidReason, VoidScope, VoidRecord, and VoidProcessor.

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.intent.immutable_record import ImmutableIntentRecord, IntentSource, IntentStatus
from domain.intent.intent_type import IntentType
from domain.intent.void_processor import (
    VoidProcessor,
    VoidReason,
    VoidRecord,
    VoidScope,
    get_void_processor,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def intent_type() -> IntentType:
    return IntentType.APPROVE_TRANSACTION


@pytest.fixture
def sample_intent(intent_type) -> ImmutableIntentRecord:
    return ImmutableIntentRecord(
        intent_id=uuid4(),
        intent_type=intent_type,
        data={"amount": 1000, "description": "Test"},
        created_by="alice",
        created_at=datetime.now(UTC) - timedelta(days=1),
        status=IntentStatus.DRAFT,
        signed_by="alice",
        signature="sig",
        source=IntentSource.USER,
        version=1,
    )


@pytest.fixture
def sample_intent_approved(intent_type) -> ImmutableIntentRecord:
    return ImmutableIntentRecord(
        intent_id=uuid4(),
        intent_type=intent_type,
        data={"amount": 5000, "description": "Approved test"},
        created_by="bob",
        created_at=datetime.now(UTC) - timedelta(days=2),
        status=IntentStatus.APPROVED,
        signed_by="bob",
        signature="sig2",
        source=IntentSource.API,
        version=2,
    )


@pytest.fixture
def sample_intent_executed(intent_type) -> ImmutableIntentRecord:
    return ImmutableIntentRecord(
        intent_id=uuid4(),
        intent_type=intent_type,
        data={"amount": 10000, "description": "Executed test"},
        created_by="carol",
        created_at=datetime.now(UTC) - timedelta(days=3),
        status=IntentStatus.EXECUTED,
        signed_by="carol",
        signature="sig3",
        source=IntentSource.SYSTEM,
        version=3,
    )


@pytest.fixture
def void_processor() -> VoidProcessor:
    """Reset singleton and return fresh processor with mocked dependencies."""
    VoidProcessor._instance = None
    processor = VoidProcessor()
    processor._record_service = MagicMock()
    processor._audit_writer = MagicMock()
    processor._void_records = {}
    return processor


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestVoidReason:
    def test_members_exist(self):
        assert hasattr(VoidReason, "USER_CANCELLED")
        assert hasattr(VoidReason, "DUPLICATE")
        assert hasattr(VoidReason, "ERROR")
        assert hasattr(VoidReason, "EXPIRED")
        assert hasattr(VoidReason, "SUPERSEDED")
        assert hasattr(VoidReason, "COMPLIANCE")
        assert hasattr(VoidReason, "FRAUD_SUSPECTED")

    def test_member_is_instance(self):
        assert isinstance(VoidReason.USER_CANCELLED, VoidReason)


class TestVoidScope:
    def test_members_exist(self):
        assert hasattr(VoidScope, "SINGLE")
        assert hasattr(VoidScope, "BATCH")
        assert hasattr(VoidScope, "CHAIN")

    def test_member_is_instance(self):
        assert isinstance(VoidScope.SINGLE, VoidScope)


# ----------------------------------------------------------------------
# VoidRecord
# ----------------------------------------------------------------------
class TestVoidRecord:
    @pytest.fixture
    def void_record(self) -> VoidRecord:
        return VoidRecord(
            void_id=uuid4(),
            intent_id=uuid4(),
            voided_by="alice",
            voided_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            reason=VoidReason.USER_CANCELLED,
            reason_description="User requested cancellation",
            scope=VoidScope.SINGLE,
            related_intents=[],
            version=1,
        )

    def test_construction_valid(self, void_record):
        assert isinstance(void_record.void_id, UUID)
        assert void_record.voided_by == "alice"
        assert void_record.reason == VoidReason.USER_CANCELLED
        assert void_record.reason_description == "User requested cancellation"
        assert void_record.scope == VoidScope.SINGLE
        assert void_record.related_intents == []
        assert void_record.version == 1
        assert void_record.cryptographic_hash != ""
        assert len(void_record._snapshots) == 1
        assert len(void_record._audit_trail) == 1

    def test_validation_errors(self):
        with pytest.raises(ValueError, match="void_id must be UUID"):
            VoidRecord(
                void_id="not-uuid",  # type: ignore
                intent_id=uuid4(),
                voided_by="u",
                voided_at=datetime.now(UTC),
                reason=VoidReason.USER_CANCELLED,
                reason_description="desc",
                scope=VoidScope.SINGLE,
            )
        with pytest.raises(ValueError, match="intent_id must be UUID"):
            VoidRecord(
                void_id=uuid4(),
                intent_id="bad",  # type: ignore
                voided_by="u",
                voided_at=datetime.now(UTC),
                reason=VoidReason.USER_CANCELLED,
                reason_description="desc",
                scope=VoidScope.SINGLE,
            )
        with pytest.raises(ValueError, match="voided_by cannot be empty"):
            VoidRecord(
                void_id=uuid4(),
                intent_id=uuid4(),
                voided_by="",
                voided_at=datetime.now(UTC),
                reason=VoidReason.USER_CANCELLED,
                reason_description="desc",
                scope=VoidScope.SINGLE,
            )
        with pytest.raises(ValueError, match="reason must be VoidReason"):
            VoidRecord(
                void_id=uuid4(),
                intent_id=uuid4(),
                voided_by="u",
                voided_at=datetime.now(UTC),
                reason="USER_CANCELLED",  # type: ignore
                reason_description="desc",
                scope=VoidScope.SINGLE,
            )
        with pytest.raises(ValueError, match="reason_description cannot be empty"):
            VoidRecord(
                void_id=uuid4(),
                intent_id=uuid4(),
                voided_by="u",
                voided_at=datetime.now(UTC),
                reason=VoidReason.USER_CANCELLED,
                reason_description="",
                scope=VoidScope.SINGLE,
            )
        with pytest.raises(ValueError, match="scope must be VoidScope"):
            VoidRecord(
                void_id=uuid4(),
                intent_id=uuid4(),
                voided_by="u",
                voided_at=datetime.now(UTC),
                reason=VoidReason.USER_CANCELLED,
                reason_description="desc",
                scope="SINGLE",  # type: ignore
            )
        with pytest.raises(ValueError, match="related_intents must contain UUIDs"):
            VoidRecord(
                void_id=uuid4(),
                intent_id=uuid4(),
                voided_by="u",
                voided_at=datetime.now(UTC),
                reason=VoidReason.USER_CANCELLED,
                reason_description="desc",
                scope=VoidScope.SINGLE,
                related_intents=["bad"],  # type: ignore
            )
        with pytest.raises(ValueError, match="version must be >= 1"):
            VoidRecord(
                void_id=uuid4(),
                intent_id=uuid4(),
                voided_by="u",
                voided_at=datetime.now(UTC),
                reason=VoidReason.USER_CANCELLED,
                reason_description="desc",
                scope=VoidScope.SINGLE,
                version=0,
            )

    def test_compute_hash(self, void_record):
        h1 = void_record.compute_hash()
        h2 = void_record.compute_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_validate_valid(self, void_record):
        result = void_record.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["void_id"] == str(void_record.void_id)

    def test_validate_hash_mismatch(self, void_record):
        object.__setattr__(void_record, "cryptographic_hash", "corrupted")
        result = void_record.validate()
        assert result["is_valid"] is False
        assert any("Hash mismatch" in e for e in result["errors"])

    def test_to_dict(self, void_record):
        d = void_record.to_dict()
        assert d["void_id"] == str(void_record.void_id)
        assert d["intent_id"] == str(void_record.intent_id)
        assert d["voided_by"] == "alice"
        assert d["reason"] == "USER_CANCELLED"
        assert d["reason_description"] == "User requested cancellation"
        assert d["scope"] == "SINGLE"
        assert d["related_intents"] == []
        assert d["cryptographic_hash"] == void_record.cryptographic_hash[:16] + "..."
        assert d["version"] == 1

    def test_from_dict(self, void_record):
        d = void_record.to_dict()
        # Restore full hash
        d["cryptographic_hash"] = void_record.cryptographic_hash
        d["voided_at"] = void_record.voided_at.isoformat()
        new_record = VoidRecord.from_dict(d)
        assert new_record.void_id == void_record.void_id
        assert new_record.intent_id == void_record.intent_id
        assert new_record.voided_by == void_record.voided_by
        assert new_record.reason == void_record.reason
        assert new_record.reason_description == void_record.reason_description
        assert new_record.scope == void_record.scope
        assert new_record.related_intents == void_record.related_intents
        assert new_record.version == void_record.version

    def test_clone(self, void_record):
        cloned = void_record.clone()
        assert cloned.void_id != void_record.void_id
        assert cloned.intent_id == void_record.intent_id
        assert cloned.voided_by == void_record.voided_by
        assert cloned.voided_at != void_record.voided_at
        assert cloned.reason == void_record.reason
        assert cloned.reason_description == void_record.reason_description
        assert cloned.scope == void_record.scope
        assert cloned.related_intents == void_record.related_intents
        assert cloned.version == 1

    def test_snapshot(self, void_record):
        snap = void_record.snapshot()
        assert snap["version"] == 1
        assert snap["void_id"] == str(void_record.void_id)
        assert snap["intent_id"] == str(void_record.intent_id)
        assert snap["reason"] == "USER_CANCELLED"
        assert "timestamp" in snap

    def test_version(self, void_record):
        assert void_record.version() == 1

    def test_audit_trail(self, void_record):
        trail = void_record.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "alice"

    def test_touch(self, void_record):
        touched = void_record.touch("toucher")
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"
        assert touched is void_record

    def test_immutable_methods_raise(self, void_record):
        with pytest.raises(AttributeError, match="is immutable"):
            void_record.update("u", data={})
        with pytest.raises(AttributeError, match="cannot be deleted"):
            void_record.delete("u")
        with pytest.raises(AttributeError, match="cannot be restored"):
            void_record.restore("u")
        # activate/deactivate/lock/unlock are no-ops
        assert void_record.activate("u") is void_record
        assert void_record.deactivate("u") is void_record
        assert void_record.lock("u", "r") is void_record
        assert void_record.unlock("u") is void_record


# ----------------------------------------------------------------------
# VoidProcessor
# ----------------------------------------------------------------------
class TestVoidProcessor:
    def test_singleton(self):
        p1 = get_void_processor()
        p2 = get_void_processor()
        assert p1 is p2

    def test_can_void_draft(self, void_processor, sample_intent):
        can, msg = void_processor.can_void(sample_intent)
        assert can is True
        assert msg == ""

    def test_can_void_approved(self, void_processor, sample_intent_approved):
        can, msg = void_processor.can_void(sample_intent_approved)
        assert can is True
        assert "Approved intent requires justification" in msg

    def test_can_void_executed(self, void_processor, sample_intent_executed):
        can, msg = void_processor.can_void(sample_intent_executed)
        assert can is False
        assert "Cannot void intent in EXECUTED status" in msg

    def test_can_void_cancelled(self, void_processor, sample_intent):
        # modify to CANCELLED
        cancelled = ImmutableIntentRecord(
            intent_id=sample_intent.intent_id,
            intent_type=sample_intent.intent_type,
            data=sample_intent.data,
            created_by=sample_intent.created_by,
            created_at=sample_intent.created_at,
            status=IntentStatus.CANCELLED,
            signed_by=sample_intent.signed_by,
            signature=sample_intent.signature,
        )
        can, msg = void_processor.can_void(cancelled)
        assert can is False
        assert "Cannot void intent in CANCELLED status" in msg

    def test_void_intent_success(self, void_processor, sample_intent):
        intent_id = sample_intent.intent_id
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None

        success, msg = void_processor.void_intent(
            intent_id=intent_id,
            reason=VoidReason.USER_CANCELLED,
            reason_description="User changed mind",
            voided_by="alice",
            scope=VoidScope.SINGLE,
        )
        assert success is True
        assert "successfully voided" in msg

        # Verify record_service.store was called with CANCELLED status
        store_call = void_processor._record_service.store.call_args[0][0]
        assert store_call.status == IntentStatus.CANCELLED
        assert store_call.intent_id == intent_id

        # Void record stored
        record = void_processor.get_void_record(intent_id)
        assert record is not None
        assert record.voided_by == "alice"
        assert record.reason == VoidReason.USER_CANCELLED
        assert record.reason_description == "User changed mind"
        assert record.scope == VoidScope.SINGLE

        # Audit written
        void_processor._audit_writer.write.assert_called_once()
        call_kwargs = void_processor._audit_writer.write.call_args[1]
        assert call_kwargs["action"].name == "CANCELLED"
        assert call_kwargs["changed_by"] == "alice"
        assert call_kwargs["severity"].name == "INFO"

    def test_void_intent_with_fraud_reason_uses_warning(self, void_processor, sample_intent):
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None

        success, _ = void_processor.void_intent(
            intent_id=sample_intent.intent_id,
            reason=VoidReason.FRAUD_SUSPECTED,
            reason_description="Suspicious activity",
            voided_by="auditor",
        )
        assert success is True
        call_kwargs = void_processor._audit_writer.write.call_args[1]
        assert call_kwargs["severity"].name == "WARNING"

    def test_void_intent_uses_current_user_if_not_provided(self, void_processor, sample_intent):
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None
        with patch("domain.intent.void_processor._get_current_user", return_value="system_user"):
            success, _ = void_processor.void_intent(
                intent_id=sample_intent.intent_id,
                reason=VoidReason.DUPLICATE,
                reason_description="Duplicate",
            )
        assert success is True
        record = void_processor.get_void_record(sample_intent.intent_id)
        assert record.voided_by == "system_user"

    def test_void_intent_not_found(self, void_processor):
        void_processor._record_service.get.return_value = None
        success, msg = void_processor.void_intent(
            intent_id=uuid4(),
            reason=VoidReason.ERROR,
            reason_description="Not found",
        )
        assert success is False
        assert "not found" in msg

    def test_void_intent_not_voidable(self, void_processor, sample_intent_executed):
        void_processor._record_service.get.return_value = sample_intent_executed
        success, msg = void_processor.void_intent(
            intent_id=sample_intent_executed.intent_id,
            reason=VoidReason.ERROR,
            reason_description="Should fail",
        )
        assert success is False
        assert "Cannot void intent in EXECUTED status" in msg

    def test_void_intent_with_chain_scope(self, void_processor, sample_intent):
        # Create chain: root intent -> child intent1, child intent2
        root = sample_intent
        child1 = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=root.intent_type,
            data={"amount": 2000},
            created_by="bob",
            created_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            signed_by="bob",
            signature="sig",
            parent_intent_id=root.intent_id,
        )
        child2 = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=root.intent_type,
            data={"amount": 3000},
            created_by="carol",
            created_at=datetime.now(UTC),
            status=IntentStatus.SUBMITTED,
            signed_by="carol",
            signature="sig",
            parent_intent_id=root.intent_id,
        )

        # Mock get for root and children
        def mock_get(iid):
            if iid == root.intent_id:
                return root
            elif iid == child1.intent_id:
                return child1
            elif iid == child2.intent_id:
                return child2
            return None

        void_processor._record_service.get.side_effect = mock_get
        void_processor._record_service.store.return_value = None

        success, msg = void_processor.void_intent(
            intent_id=root.intent_id,
            reason=VoidReason.SUPERSEDED,
            reason_description="Replaced",
            voided_by="alice",
            scope=VoidScope.CHAIN,
            related_intents=[child1.intent_id, child2.intent_id],
        )
        assert success is True
        # All three should be voided and have records
        assert void_processor.is_voided(root.intent_id) is True
        assert void_processor.is_voided(child1.intent_id) is True
        assert void_processor.is_voided(child2.intent_id) is True

    def test_void_batch(self, void_processor, sample_intent, sample_intent_approved):
        intent1 = sample_intent
        intent2 = sample_intent_approved
        void_processor._record_service.get.side_effect = lambda iid: (
            intent1 if iid == intent1.intent_id else
            intent2 if iid == intent2.intent_id else None
        )
        void_processor._record_service.store.return_value = None

        results = void_processor.void_batch(
            intent_ids=[intent1.intent_id, intent2.intent_id],
            reason=VoidReason.COMPLIANCE,
            reason_description="Compliance cleanup",
            voided_by="admin",
        )
        assert len(results) == 2
        assert results[intent1.intent_id][0] is True
        assert results[intent2.intent_id][0] is True
        # Both should be voided
        assert void_processor.is_voided(intent1.intent_id) is True
        assert void_processor.is_voided(intent2.intent_id) is True

    def test_void_batch_with_failure(self, void_processor, sample_intent, sample_intent_executed):
        intent1 = sample_intent
        intent2 = sample_intent_executed  # cannot void executed
        void_processor._record_service.get.side_effect = lambda iid: (
            intent1 if iid == intent1.intent_id else
            intent2 if iid == intent2.intent_id else None
        )
        void_processor._record_service.store.return_value = None

        results = void_processor.void_batch(
            intent_ids=[intent1.intent_id, intent2.intent_id],
            reason=VoidReason.ERROR,
            reason_description="Batch test",
            voided_by="admin",
        )
        assert results[intent1.intent_id][0] is True
        assert results[intent2.intent_id][0] is False

    def test_void_chain(self, void_processor, sample_intent):
        # Create chain: root -> child1 -> child2 (grandchild)
        root = sample_intent
        child1 = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=root.intent_type,
            data={"amount": 2000},
            created_by="bob",
            created_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            signed_by="bob",
            signature="sig",
            parent_intent_id=root.intent_id,
        )
        child2 = ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=root.intent_type,
            data={"amount": 3000},
            created_by="carol",
            created_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            signed_by="carol",
            signature="sig",
            parent_intent_id=child1.intent_id,
        )
        # Mock get_all to return all intents
        void_processor._record_service.get_all.return_value = [root, child1, child2]
        void_processor._record_service.get.side_effect = lambda iid: (
            root if iid == root.intent_id else
            child1 if iid == child1.intent_id else
            child2 if iid == child2.intent_id else None
        )
        void_processor._record_service.store.return_value = None

        results = void_processor.void_chain(
            root_intent_id=root.intent_id,
            reason=VoidReason.SUPERSEDED,
            reason_description="Chain void",
            voided_by="admin",
        )
        assert len(results) == 3
        assert all(success for success, _ in results.values())
        assert void_processor.is_voided(root.intent_id) is True
        assert void_processor.is_voided(child1.intent_id) is True
        assert void_processor.is_voided(child2.intent_id) is True

    def test_get_void_record(self, void_processor, sample_intent):
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None
        void_processor.void_intent(
            sample_intent.intent_id,
            VoidReason.USER_CANCELLED,
            "Test",
            "alice",
        )
        record = void_processor.get_void_record(sample_intent.intent_id)
        assert record is not None
        assert record.intent_id == sample_intent.intent_id
        # Non-existent
        assert void_processor.get_void_record(uuid4()) is None

    def test_is_voided(self, void_processor, sample_intent):
        assert void_processor.is_voided(sample_intent.intent_id) is False
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None
        void_processor.void_intent(
            sample_intent.intent_id,
            VoidReason.DUPLICATE,
            "Duplicate",
            "alice",
        )
        assert void_processor.is_voided(sample_intent.intent_id) is True

    def test_get_voided_intents(self, void_processor, sample_intent, sample_intent_approved):
        # Void two intents with different reasons
        void_processor._record_service.get.side_effect = lambda iid: (
            sample_intent if iid == sample_intent.intent_id else
            sample_intent_approved if iid == sample_intent_approved.intent_id else None
        )
        void_processor._record_service.store.return_value = None
        void_processor.void_intent(
            sample_intent.intent_id,
            VoidReason.USER_CANCELLED,
            "Cancelled",
            "alice",
        )
        void_processor.void_intent(
            sample_intent_approved.intent_id,
            VoidReason.COMPLIANCE,
            "Compliance",
            "bob",
        )
        # Get all
        records = void_processor.get_voided_intents()
        assert len(records) == 2
        # Filter by reason
        user_cancelled = void_processor.get_voided_intents(reason=VoidReason.USER_CANCELLED)
        assert len(user_cancelled) == 1
        assert user_cancelled[0].intent_id == sample_intent.intent_id
        # Filter by voided_by
        by_bob = void_processor.get_voided_intents(voided_by="bob")
        assert len(by_bob) == 1
        assert by_bob[0].intent_id == sample_intent_approved.intent_id
        # Limit
        limited = void_processor.get_voided_intents(limit=1)
        assert len(limited) == 1

    def test_save_void_record(self, void_processor):
        record = VoidRecord(
            void_id=uuid4(),
            intent_id=uuid4(),
            voided_by="alice",
            voided_at=datetime.now(UTC),
            reason=VoidReason.USER_CANCELLED,
            reason_description="Desc",
            scope=VoidScope.SINGLE,
        )
        void_processor.save_void_record(record)
        assert void_processor.get_void_record(record.intent_id) is record

    def test_get_all_void_records(self, void_processor, sample_intent):
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None
        void_processor.void_intent(
            sample_intent.intent_id,
            VoidReason.ERROR,
            "Error",
            "alice",
        )
        all_records = void_processor.get_all_void_records()
        assert len(all_records) == 1

    def test_delete_void_record(self, void_processor, sample_intent):
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None
        void_processor.void_intent(
            sample_intent.intent_id,
            VoidReason.ERROR,
            "Error",
            "alice",
        )
        assert void_processor.is_voided(sample_intent.intent_id) is True
        result = void_processor.delete_void_record(sample_intent.intent_id)
        assert result is True
        assert void_processor.is_voided(sample_intent.intent_id) is False
        # Delete again
        result = void_processor.delete_void_record(sample_intent.intent_id)
        assert result is False

    def test_count_void_records(self, void_processor, sample_intent):
        assert void_processor.count_void_records() == 0
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None
        void_processor.void_intent(
            sample_intent.intent_id,
            VoidReason.ERROR,
            "Error",
            "alice",
        )
        assert void_processor.count_void_records() == 1

    def test_get_statistics(self, void_processor):
        stats = void_processor.get_statistics()
        assert stats["total_voided_intents"] == 0

        # Create some void records manually
        now = datetime.now(UTC)
        record1 = VoidRecord(
            void_id=uuid4(),
            intent_id=uuid4(),
            voided_by="alice",
            voided_at=now - timedelta(days=1),
            reason=VoidReason.USER_CANCELLED,
            reason_description="Desc1",
            scope=VoidScope.SINGLE,
        )
        record2 = VoidRecord(
            void_id=uuid4(),
            intent_id=uuid4(),
            voided_by="bob",
            voided_at=now,
            reason=VoidReason.COMPLIANCE,
            reason_description="Desc2",
            scope=VoidScope.BATCH,
        )
        void_processor.save_void_record(record1)
        void_processor.save_void_record(record2)

        stats = void_processor.get_statistics()
        assert stats["total_voided_intents"] == 2
        assert stats["by_reason"] == {"USER_CANCELLED": 1, "COMPLIANCE": 1}
        assert stats["by_user"] == {"alice": 1, "bob": 1}
        assert stats["latest_void"] == now.isoformat()

    def test_reset(self, void_processor, sample_intent):
        void_processor._record_service.get.return_value = sample_intent
        void_processor._record_service.store.return_value = None
        void_processor.void_intent(
            sample_intent.intent_id,
            VoidReason.ERROR,
            "Error",
            "alice",
        )
        assert void_processor.count_void_records() == 1
        void_processor.reset()
        assert void_processor.count_void_records() == 0
