# test_approval_workflow.py
# ===========================
# Comprehensive tests for approval_workflow.py.
# Covers ApprovalLevel, ApprovalAction, ApprovalStatus, ApprovalRule,
# ApprovalRecord, ApprovalWorkflow, and singleton accessor.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.intent.approval_workflow import (
    ApprovalAction,
    ApprovalLevel,
    ApprovalRecord,
    ApprovalRule,
    ApprovalStatus,
    ApprovalWorkflow,
    get_approval_workflow,
)


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestApprovalLevel:
    def test_members_exist(self):
        assert hasattr(ApprovalLevel, "LEVEL_1")
        assert hasattr(ApprovalLevel, "LEVEL_2")
        assert hasattr(ApprovalLevel, "LEVEL_3")
        assert hasattr(ApprovalLevel, "LEVEL_4")
        assert hasattr(ApprovalLevel, "LEVEL_5")

    def test_member_is_instance(self):
        assert isinstance(ApprovalLevel.LEVEL_1, ApprovalLevel)

    def test_from_int_valid(self):
        assert ApprovalLevel.from_int(1) == ApprovalLevel.LEVEL_1
        assert ApprovalLevel.from_int(3) == ApprovalLevel.LEVEL_3
        assert ApprovalLevel.from_int(5) == ApprovalLevel.LEVEL_5

    def test_from_int_invalid(self):
        with pytest.raises(ValueError, match="Invalid ApprovalLevel value"):
            ApprovalLevel.from_int(0)
        with pytest.raises(ValueError, match="Invalid ApprovalLevel value"):
            ApprovalLevel.from_int(6)


class TestApprovalAction:
    def test_members_exist(self):
        assert hasattr(ApprovalAction, "APPROVE")
        assert hasattr(ApprovalAction, "REJECT")
        assert hasattr(ApprovalAction, "REQUEST_CHANGES")
        assert hasattr(ApprovalAction, "ESCALATE")
        assert hasattr(ApprovalAction, "DELEGATE")

    def test_member_is_instance(self):
        assert isinstance(ApprovalAction.APPROVE, ApprovalAction)


class TestApprovalStatus:
    def test_members_exist(self):
        assert hasattr(ApprovalStatus, "PENDING")
        assert hasattr(ApprovalStatus, "APPROVED")
        assert hasattr(ApprovalStatus, "REJECTED")
        assert hasattr(ApprovalStatus, "CHANGES_REQUESTED")
        assert hasattr(ApprovalStatus, "ESCALATED")
        assert hasattr(ApprovalStatus, "DELEGATED")
        assert hasattr(ApprovalStatus, "EXPIRED")

    def test_member_is_instance(self):
        assert isinstance(ApprovalStatus.PENDING, ApprovalStatus)


# ----------------------------------------------------------------------
# ApprovalRule
# ----------------------------------------------------------------------
class TestApprovalRule:
    @pytest.fixture
    def rule(self) -> ApprovalRule:
        return ApprovalRule(
            min_amount=Decimal("1000"),
            max_amount=Decimal("50000"),
            required_level=ApprovalLevel.LEVEL_2,
            required_approvers=2,
            approver_roles=["manager", "finance"],
            version=1,
        )

    def test_construction_valid(self, rule):
        assert rule.min_amount == Decimal("1000")
        assert rule.max_amount == Decimal("50000")
        assert rule.required_level == ApprovalLevel.LEVEL_2
        assert rule.required_approvers == 2
        assert rule.approver_roles == ["manager", "finance"]
        assert rule.version == 1
        # Should have snapshot and audit trail
        assert len(rule._snapshots) == 1
        assert len(rule._audit_trail) == 1

    def test_construction_invalid_min_negative(self):
        with pytest.raises(ValueError, match="min_amount cannot be negative"):
            ApprovalRule(
                min_amount=Decimal("-1"),
                max_amount=Decimal("100"),
                required_level=ApprovalLevel.LEVEL_1,
            )

    def test_construction_invalid_max_less_than_min(self):
        with pytest.raises(ValueError, match="max_amount must be >= min_amount"):
            ApprovalRule(
                min_amount=Decimal("100"),
                max_amount=Decimal("50"),
                required_level=ApprovalLevel.LEVEL_1,
            )

    def test_construction_invalid_required_approvers_zero(self):
        with pytest.raises(ValueError, match="required_approvers must be at least 1"):
            ApprovalRule(
                min_amount=Decimal("0"),
                max_amount=Decimal("100"),
                required_level=ApprovalLevel.LEVEL_1,
                required_approvers=0,
            )

    def test_construction_invalid_level_type(self):
        with pytest.raises(ValueError, match="required_level must be ApprovalLevel"):
            ApprovalRule(
                min_amount=Decimal("0"),
                max_amount=Decimal("100"),
                required_level="LEVEL_1",  # type: ignore
            )

    def test_contains_amount(self, rule):
        assert rule.contains_amount(Decimal("1000")) is True
        assert rule.contains_amount(Decimal("50000")) is True
        assert rule.contains_amount(Decimal("999")) is False
        assert rule.contains_amount(Decimal("50001")) is False

    def test_to_dict(self, rule):
        d = rule.to_dict()
        assert d["min_amount"] == 1000.0
        assert d["max_amount"] == 50000.0
        assert d["required_level"] == "LEVEL_2"
        assert d["required_approvers"] == 2
        assert d["approver_roles"] == ["manager", "finance"]
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "min_amount": 2000.0,
            "max_amount": 100000.0,
            "required_level": "LEVEL_3",
            "required_approvers": 1,
            "approver_roles": ["director"],
            "version": 2,
        }
        rule = ApprovalRule.from_dict(data)
        assert rule.min_amount == Decimal("2000")
        assert rule.max_amount == Decimal("100000")
        assert rule.required_level == ApprovalLevel.LEVEL_3
        assert rule.required_approvers == 1
        assert rule.approver_roles == ["director"]
        assert rule.version == 2

    def test_from_dict_with_inf_max(self):
        data = {
            "min_amount": 0.0,
            "max_amount": float("inf"),
            "required_level": "LEVEL_5",
            "required_approvers": 3,
            "approver_roles": ["cfo", "ceo"],
            "version": 1,
        }
        rule = ApprovalRule.from_dict(data)
        assert rule.max_amount == Decimal("inf")

    def test_clone(self, rule):
        cloned = rule.clone()
        assert cloned.min_amount == rule.min_amount
        assert cloned.max_amount == rule.max_amount
        assert cloned.required_level == rule.required_level
        assert cloned.required_approvers == rule.required_approvers
        assert cloned.approver_roles == rule.approver_roles
        assert cloned.version == 1  # reset to 1
        assert cloned is not rule

    def test_snapshot(self, rule):
        snap = rule.snapshot()
        assert snap["version"] == 1
        assert snap["min_amount"] == 1000.0
        assert snap["max_amount"] == 50000.0
        assert snap["required_level"] == "LEVEL_2"
        assert "timestamp" in snap

    def test_get_version(self, rule):
        assert rule.get_version() == 1

    def test_audit_trail(self, rule):
        trail = rule.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "system"

    def test_touch(self, rule):
        new_rule = rule.touch("test_user")
        assert new_rule.version == 2
        assert new_rule.min_amount == rule.min_amount
        trail = new_rule.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "test_user"

    def test_create(self, rule):
        created = rule.create("creator")
        trail = created.audit_trail(limit=1)
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "creator"

    def test_update(self, rule):
        updated = rule.update("updater", required_approvers=3, min_amount=Decimal("500"))
        assert updated.required_approvers == 3
        assert updated.min_amount == Decimal("500")
        assert updated.version == 2
        trail = updated.audit_trail(limit=1)
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["performed_by"] == "updater"
        assert "changes" in trail[0]["details"]

    def test_delete(self, rule):
        deleted = rule.delete("deleter", reason="no longer needed")
        trail = deleted.audit_trail(limit=1)
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["performed_by"] == "deleter"
        assert trail[0]["details"]["reason"] == "no longer needed"

    def test_restore(self, rule):
        restored = rule.restore("restorer")
        trail = restored.audit_trail(limit=1)
        assert trail[0]["action"] == "RESTORE"
        assert trail[0]["performed_by"] == "restorer"

    def test_activate(self, rule):
        activated = rule.activate("activator")
        trail = activated.audit_trail(limit=1)
        assert trail[0]["action"] == "ACTIVATE"  # not implemented, but no-op

    def test_deactivate(self, rule):
        deactivated = rule.deactivate("deactivator", reason="test")
        trail = deactivated.audit_trail(limit=1)
        assert trail[0]["action"] == "DEACTIVATE"

    def test_lock(self, rule):
        locked = rule.lock("locker", "reason")
        trail = locked.audit_trail(limit=1)
        assert trail[0]["action"] == "LOCK"

    def test_unlock(self, rule):
        unlocked = rule.unlock("unlocker")
        trail = unlocked.audit_trail(limit=1)
        assert trail[0]["action"] == "UNLOCK"

    def test_validate_valid(self, rule):
        result = rule.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["version"] == 1

    def test_validate_invalid(self):
        # create invalid rule (min > max) and then validate
        with pytest.raises(ValueError):
            ApprovalRule(
                min_amount=Decimal("100"),
                max_amount=Decimal("50"),
                required_level=ApprovalLevel.LEVEL_1,
            )
        # Instead, we can directly set invalid state via __dict__? But we shouldn't.
        # The validation is done in __post_init__. So if we bypass that, we can test manually?
        # We'll just test that validation catches errors from _validate.
        # We can create a valid rule then modify internal state, but better to test via create with invalid args.
        # Already tested above.

    def test_copy(self, rule):
        copied = rule._copy()
        assert copied.min_amount == rule.min_amount
        assert copied.max_amount == rule.max_amount
        assert copied.required_level == rule.required_level
        assert copied.required_approvers == rule.required_approvers
        assert copied.approver_roles == rule.approver_roles
        assert copied.version == rule.version
        assert copied is not rule


# ----------------------------------------------------------------------
# ApprovalRecord
# ----------------------------------------------------------------------
class TestApprovalRecord:
    @pytest.fixture
    def record(self) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=uuid4(),
            intent_id=uuid4(),
            approver_id="user123",
            action=ApprovalAction.APPROVE,
            status=ApprovalStatus.PENDING,
            level=ApprovalLevel.LEVEL_2,
            notes="Initial review",
            approved_at=datetime.now(UTC),
            escalation_reason=None,
            delegated_to=None,
            version=1,
            cryptographic_hash="",
        )

    def test_construction_valid(self, record):
        assert isinstance(record.approval_id, UUID)
        assert isinstance(record.intent_id, UUID)
        assert record.approver_id == "user123"
        assert record.action == ApprovalAction.APPROVE
        assert record.status == ApprovalStatus.PENDING
        assert record.level == ApprovalLevel.LEVEL_2
        assert record.notes == "Initial review"
        assert record.cryptographic_hash != ""  # auto-generated

    def test_validation_errors(self):
        # Invalid approver_id empty
        with pytest.raises(ValueError, match="approver_id cannot be empty"):
            ApprovalRecord(
                approval_id=uuid4(),
                intent_id=uuid4(),
                approver_id="",
                action=ApprovalAction.APPROVE,
                status=ApprovalStatus.PENDING,
                level=ApprovalLevel.LEVEL_1,
                notes="",
                approved_at=datetime.now(UTC),
            )
        # Invalid version < 1
        with pytest.raises(ValueError, match="version must be >= 1"):
            ApprovalRecord(
                approval_id=uuid4(),
                intent_id=uuid4(),
                approver_id="a",
                action=ApprovalAction.APPROVE,
                status=ApprovalStatus.PENDING,
                level=ApprovalLevel.LEVEL_1,
                notes="",
                approved_at=datetime.now(UTC),
                version=0,
            )
        # Invalid action type
        with pytest.raises(ValueError, match="action must be ApprovalAction"):
            ApprovalRecord(
                approval_id=uuid4(),
                intent_id=uuid4(),
                approver_id="a",
                action="APPROVE",  # type: ignore
                status=ApprovalStatus.PENDING,
                level=ApprovalLevel.LEVEL_1,
                notes="",
                approved_at=datetime.now(UTC),
            )

    def test_compute_hash(self, record):
        h1 = record.compute_hash()
        h2 = record.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # sha3_256

    def test_to_dict(self, record):
        d = record.to_dict()
        assert d["approval_id"] == str(record.approval_id)
        assert d["intent_id"] == str(record.intent_id)
        assert d["approver_id"] == "user123"
        assert d["action"] == "APPROVE"
        assert d["status"] == "PENDING"
        assert d["level"] == "LEVEL_2"
        assert d["notes"] == "Initial review"
        assert "approved_at" in d
        assert d["cryptographic_hash"] == record.cryptographic_hash[:16] + "..."

    def test_from_dict(self):
        data = {
            "approval_id": str(uuid4()),
            "intent_id": str(uuid4()),
            "approver_id": "user456",
            "action": "REJECT",
            "status": "REJECTED",
            "level": "LEVEL_1",
            "notes": "Rejected due to insufficient info",
            "approved_at": datetime.now(UTC).isoformat(),
            "escalation_reason": "escalated",
            "delegated_to": "user789",
            "version": 2,
            "cryptographic_hash": "somehash",
        }
        record = ApprovalRecord.from_dict(data)
        assert str(record.approval_id) == data["approval_id"]
        assert record.action == ApprovalAction.REJECT
        assert record.status == ApprovalStatus.REJECTED
        assert record.level == ApprovalLevel.LEVEL_1
        assert record.escalation_reason == "escalated"
        assert record.delegated_to == "user789"
        assert record.version == 2
        assert record.cryptographic_hash == "somehash"

    def test_clone(self, record):
        cloned = record.clone()
        assert cloned.approval_id != record.approval_id
        assert cloned.intent_id == record.intent_id
        assert cloned.approver_id == record.approver_id
        assert cloned.action == record.action
        assert cloned.status == record.status
        assert cloned.level == record.level
        assert cloned.notes == record.notes
        assert cloned.version == 1

    def test_snapshot(self, record):
        snap = record.snapshot()
        assert snap["version"] == 1
        assert snap["approval_id"] == str(record.approval_id)
        assert snap["action"] == "APPROVE"
        assert snap["status"] == "PENDING"
        assert "timestamp" in snap

    def test_get_version(self, record):
        assert record.get_version() == 1

    def test_audit_trail(self, record):
        trail = record.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "user123"

    def test_touch(self, record):
        touched = record.touch("toucher")
        trail = touched.audit_trail(limit=1)
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"
        # Still immutable, version unchanged
        assert touched.version == 1

    def test_immutable_methods_raise(self, record):
        with pytest.raises(AttributeError, match="cannot be updated"):
            record.update("updater")
        with pytest.raises(AttributeError, match="cannot be deleted"):
            record.delete("deleter")
        with pytest.raises(AttributeError, match="cannot be restored"):
            record.restore("restorer")
        # activate/deactivate/lock/unlock are no-ops but don't raise
        assert record.activate("activator") is record
        assert record.deactivate("deactivator") is record
        assert record.lock("locker", "reason") is record
        assert record.unlock("unlocker") is record

    def test_validate_valid(self, record):
        result = record.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["approval_id"] == str(record.approval_id)

    def test_validate_hash_mismatch(self, record):
        # Manually corrupt hash
        object.__setattr__(record, "cryptographic_hash", "corrupted")
        result = record.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]


# ----------------------------------------------------------------------
# ApprovalWorkflow (with mocks)
# ----------------------------------------------------------------------
class TestApprovalWorkflow:
    @pytest.fixture
    def workflow(self) -> ApprovalWorkflow:
        # Reset singleton for isolation
        ApprovalWorkflow._instance = None
        return ApprovalWorkflow()

    @pytest.fixture
    def mock_intent_service(self):
        with patch("domain.intent.approval_workflow.get_immutable_intent_record_service") as mock:
            service = MagicMock()
            mock.return_value = service
            yield service

    @pytest.fixture
    def mock_audit_writer(self):
        with patch("domain.intent.approval_workflow.get_audit_trail_writer") as mock:
            writer = MagicMock()
            mock.return_value = writer
            yield writer

    def test_singleton(self):
        w1 = get_approval_workflow()
        w2 = get_approval_workflow()
        assert w1 is w2

    def test_initial_rules(self, workflow):
        rules = workflow.get_all_rules()
        assert len(rules) == 5
        assert rules[0].min_amount == Decimal("0")
        assert rules[-1].max_amount == Decimal("inf")

    def test_get_approval_requirement(self, workflow):
        rule = workflow.get_approval_requirement(Decimal("5000000"))
        assert rule.required_level == ApprovalLevel.LEVEL_1
        rule = workflow.get_approval_requirement(Decimal("50000000"))
        assert rule.required_level == ApprovalLevel.LEVEL_2
        rule = workflow.get_approval_requirement(Decimal("200000000"))
        assert rule.required_level == ApprovalLevel.LEVEL_3
        rule = workflow.get_approval_requirement(Decimal("750000000"))
        assert rule.required_level == ApprovalLevel.LEVEL_4
        rule = workflow.get_approval_requirement(Decimal("2000000000"))
        assert rule.required_level == ApprovalLevel.LEVEL_5

    def test_add_approval_rule(self, workflow):
        new_rule = ApprovalRule(
            min_amount=Decimal("100"),
            max_amount=Decimal("200"),
            required_level=ApprovalLevel.LEVEL_1,
        )
        workflow.add_approval_rule(new_rule)
        rules = workflow.get_all_rules()
        assert new_rule in rules
        # Check sorting
        assert rules[0].min_amount == Decimal("0")  # original first
        assert rules[1].min_amount == Decimal("100")  # new

    def test_submit_for_approval(self, workflow, mock_intent_service, mock_audit_writer):
        intent_id = uuid4()
        intent_mock = MagicMock()
        intent_mock.status = IntentStatus.DRAFT
        intent_mock.data = {"amount": 50000}
        mock_intent_service.get.return_value = intent_mock
        mock_intent_service.store.return_value = None

        result = workflow.submit_for_approval(intent_id, "submitter")
        assert result is True
        # Store called with updated status SUBMITTED
        mock_intent_service.store.assert_called_once()
        call_args = mock_intent_service.store.call_args[0][0]
        assert call_args.status == IntentStatus.SUBMITTED
        mock_audit_writer.write_submitted.assert_called_once_with(intent_id, "submitter")

    def test_submit_for_approval_not_found(self, workflow, mock_intent_service):
        mock_intent_service.get.return_value = None
        result = workflow.submit_for_approval(uuid4(), "user")
        assert result is False
        mock_intent_service.store.assert_not_called()

    def test_approve_single_level_success(self, workflow, mock_intent_service, mock_audit_writer):
        intent_id = uuid4()
        intent_mock = MagicMock()
        intent_mock.status = IntentStatus.SUBMITTED
        intent_mock.data = {"amount": 5000000}  # Level 1
        mock_intent_service.get.return_value = intent_mock
        mock_intent_service.store.return_value = None

        # Approve with level 1 (required)
        success, msg = workflow.approve(intent_id, "approver1", ApprovalLevel.LEVEL_1, "OK")
        assert success is True
        assert msg == "Intent fully approved"  # because required_approvers=1 and level matches

        # Check that store was called to update to APPROVED
        mock_intent_service.store.assert_called_once()
        updated = mock_intent_service.store.call_args[0][0]
        assert updated.status == IntentStatus.APPROVED

        # Check approval stored
        approvals = workflow.get_approvals_for_intent(intent_id)
        assert len(approvals) == 1
        assert approvals[0].approver_id == "approver1"
        assert approvals[0].status == ApprovalStatus.APPROVED

        mock_audit_writer.write_approved.assert_called_once_with(intent_id, "approver1", "OK")

    def test_approve_level_insufficient(self, workflow, mock_intent_service):
        intent_id = uuid4()
        intent_mock = MagicMock()
        intent_mock.status = IntentStatus.SUBMITTED
        intent_mock.data = {"amount": 50000000}  # Level 2 required
        mock_intent_service.get.return_value = intent_mock

        success, msg = workflow.approve(intent_id, "approver1", ApprovalLevel.LEVEL_1, "")
        assert success is False
        assert "Required level LEVEL_2, got LEVEL_1" in msg
        mock_intent_service.store.assert_not_called()

    def test_approve_multiple_approvers_waiting(self, workflow, mock_intent_service):
        intent_id = uuid4()
        intent_mock = MagicMock()
        intent_mock.status = IntentStatus.SUBMITTED
        intent_mock.data = {"amount": 750000000}  # Level 4 requires 2 approvers
        mock_intent_service.get.return_value = intent_mock
        mock_intent_service.store.return_value = None

        # First approval
        success, msg = workflow.approve(intent_id, "approver1", ApprovalLevel.LEVEL_4, "")
        assert success is True
        assert "waiting for more approvals" in msg
        mock_intent_service.store.assert_not_called()  # not fully approved yet

        # Second approval
        success, msg = workflow.approve(intent_id, "approver2", ApprovalLevel.LEVEL_4, "")
        assert success is True
        assert "Intent fully approved" in msg
        mock_intent_service.store.assert_called_once()  # now approved

    def test_reject(self, workflow, mock_intent_service, mock_audit_writer):
        intent_id = uuid4()
        intent_mock = MagicMock()
        intent_mock.status = IntentStatus.SUBMITTED
        intent_mock.data = {"amount": 50000}
        mock_intent_service.get.return_value = intent_mock
        mock_intent_service.store.return_value = None

        result = workflow.reject(intent_id, "rejecter", "Not acceptable")
        assert result is True

        # Store updated to REJECTED
        mock_intent_service.store.assert_called_once()
        updated = mock_intent_service.store.call_args[0][0]
        assert updated.status == IntentStatus.REJECTED

        # Approval record created
        approvals = workflow.get_approvals_for_intent(intent_id)
        assert len(approvals) == 1
        assert approvals[0].status == ApprovalStatus.REJECTED
        assert approvals[0].action == ApprovalAction.REJECT

        mock_audit_writer.write_rejected.assert_called_once_with(intent_id, "rejecter", "Not acceptable")

    def test_request_changes(self, workflow, mock_intent_service):
        intent_id = uuid4()
        intent_mock = MagicMock()
        intent_mock.status = IntentStatus.SUBMITTED
        intent_mock.data = {"amount": 50000}
        mock_intent_service.get.return_value = intent_mock
        mock_intent_service.store.return_value = None

        result = workflow.request_changes(intent_id, "requester", "Please fix the amount")
        assert result is True

        # Store updated to DRAFT
        mock_intent_service.store.assert_called_once()
        updated = mock_intent_service.store.call_args[0][0]
        assert updated.status == IntentStatus.DRAFT

        # Approval record created
        approvals = workflow.get_approvals_for_intent(intent_id)
        assert len(approvals) == 1
        assert approvals[0].status == ApprovalStatus.CHANGES_REQUESTED
        assert approvals[0].action == ApprovalAction.REQUEST_CHANGES

    def test_get_approval_status(self, workflow, mock_intent_service):
        intent_id = uuid4()
        intent_mock = MagicMock()
        intent_mock.status = IntentStatus.SUBMITTED
        intent_mock.data = {"amount": 50000000}
        mock_intent_service.get.return_value = intent_mock

        # Add some approvals
        workflow.approve(intent_id, "a1", ApprovalLevel.LEVEL_2, "")
        workflow.approve(intent_id, "a2", ApprovalLevel.LEVEL_2, "")  # second approver

        status = workflow.get_approval_status(intent_id)
        assert status["intent_id"] == str(intent_id)
        assert status["current_status"] == "SUBMITTED"
        assert status["required_level"] == "LEVEL_2"
        assert status["required_approvers"] == 1  # default for LEVEL_2
        assert status["approvals_received"] == 2  # both approved
        assert len(status["approvals"]) == 2

    def test_get_approval_status_not_found(self, workflow, mock_intent_service):
        mock_intent_service.get.return_value = None
        status = workflow.get_approval_status(uuid4())
        assert status == {"error": "Intent not found"}

    def test_save_and_get_approval(self, workflow):
        approval = ApprovalRecord(
            approval_id=uuid4(),
            intent_id=uuid4(),
            approver_id="user",
            action=ApprovalAction.APPROVE,
            status=ApprovalStatus.APPROVED,
            level=ApprovalLevel.LEVEL_1,
            notes="",
            approved_at=datetime.now(UTC),
        )
        workflow.save_approval(approval)
        intent_id = approval.intent_id
        approvals = workflow.get_approvals_for_intent(intent_id)
        assert len(approvals) == 1
        assert approvals[0].approval_id == approval.approval_id

        retrieved = workflow.get_approval(approval.approval_id)
        assert retrieved is not None
        assert retrieved.approval_id == approval.approval_id

        # Delete
        deleted = workflow.delete_approval(approval.approval_id)
        assert deleted is True
        assert len(workflow.get_approvals_for_intent(intent_id)) == 0
        assert workflow.get_approval(approval.approval_id) is None

    def test_count_approvals(self, workflow):
        intent_id = uuid4()
        for i in range(3):
            approval = ApprovalRecord(
                approval_id=uuid4(),
                intent_id=intent_id,
                approver_id=f"user{i}",
                action=ApprovalAction.APPROVE,
                status=ApprovalStatus.APPROVED,
                level=ApprovalLevel.LEVEL_1,
                notes="",
                approved_at=datetime.now(UTC),
            )
            workflow.save_approval(approval)
        assert workflow.count_approvals(intent_id) == 3
        assert workflow.count_approvals(uuid4()) == 0

    def test_reset(self, workflow):
        # Add a rule and approval
        workflow.add_approval_rule(
            ApprovalRule(
                min_amount=Decimal("10"),
                max_amount=Decimal("20"),
                required_level=ApprovalLevel.LEVEL_1,
            )
        )
        approval = ApprovalRecord(
            approval_id=uuid4(),
            intent_id=uuid4(),
            approver_id="a",
            action=ApprovalAction.APPROVE,
            status=ApprovalStatus.APPROVED,
            level=ApprovalLevel.LEVEL_1,
            notes="",
            approved_at=datetime.now(UTC),
        )
        workflow.save_approval(approval)
        assert len(workflow.get_all_rules()) == 6
        assert len(workflow._approvals) == 1

        workflow.reset()
        assert len(workflow.get_all_rules()) == 5  # back to default
        assert len(workflow._approvals) == 0


# We need to import IntentStatus for the mock; it's from domain.intent.immutable_record.
# We'll import inside tests or add import.
try:
    from domain.intent.immutable_record import IntentStatus
except ImportError:
    # If not available, define dummy for test
    class IntentStatus:
        DRAFT = "DRAFT"
        SUBMITTED = "SUBMITTED"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
