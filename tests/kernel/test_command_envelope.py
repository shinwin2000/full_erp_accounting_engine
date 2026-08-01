#!/usr/bin/env python3
"""
Tests for kernel/command_envelope.py
Tests CommandStatus enum, CommandResult value object, and CommandEnvelope model.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from kernel.command_envelope import CommandEnvelope, CommandResult, CommandStatus


class TestCommandStatus:
    """Tests for the CommandStatus enum."""

    def test_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(CommandStatus, 'PENDING')
        assert hasattr(CommandStatus, 'VALIDATING')
        assert hasattr(CommandStatus, 'EXECUTING')
        assert hasattr(CommandStatus, 'COMMITTING')
        assert hasattr(CommandStatus, 'SUCCESS')
        assert hasattr(CommandStatus, 'FAILED')
        assert hasattr(CommandStatus, 'REJECTED')
        assert hasattr(CommandStatus, 'RETRYING')

    def test_member_is_instance(self):
        """Enum members are instances of the enum class."""
        assert isinstance(CommandStatus.PENDING, CommandStatus)
        assert isinstance(CommandStatus.SUCCESS, CommandStatus)
        assert isinstance(CommandStatus.FAILED, CommandStatus)

    def test_auto_values_are_unique(self):
        """Each enum member has a unique auto-generated value."""
        values = [status.value for status in CommandStatus]
        assert len(values) == len(set(values)), "Enum values should be unique"

    def test_all_members_count(self):
        """Verify total number of status members."""
        assert len(list(CommandStatus)) == 8

    def test_can_access_by_name(self):
        """Can access enum members by name."""
        assert CommandStatus['PENDING'] is CommandStatus.PENDING
        assert CommandStatus['SUCCESS'] is CommandStatus.SUCCESS

    def test_iteration_over_members(self):
        """Can iterate over all enum members."""
        members = list(CommandStatus)
        assert CommandStatus.PENDING in members
        assert CommandStatus.SUCCESS in members


class TestCommandResult:
    """Tests for the CommandResult value object / model."""

    def _build_success_kwargs(self):
        return {'success': True, 'data': {"key": "value"}, 'error': None}

    def _build_failure_kwargs(self):
        return {'success': False, 'data': None, 'error': "Something went wrong"}

    # --- Construction Tests ---

    def test_construction_success_result(self):
        """CommandResult can be constructed with success=True."""
        kwargs = self._build_success_kwargs()
        instance = CommandResult(**kwargs)
        assert isinstance(instance, CommandResult)
        assert instance.success is True
        assert instance.data == {"key": "value"}
        assert instance.error is None

    def test_construction_failure_result(self):
        """CommandResult can be constructed with success=False."""
        kwargs = self._build_failure_kwargs()
        instance = CommandResult(**kwargs)
        assert isinstance(instance, CommandResult)
        assert instance.success is False
        assert instance.data is None
        assert instance.error == "Something went wrong"

    def test_construction_with_none_data(self):
        """CommandResult can have None data on success."""
        instance = CommandResult(success=True, data=None)
        assert instance.success is True
        assert instance.data is None

    def test_default_values(self):
        """CommandResult has correct default values."""
        instance = CommandResult(success=True)
        assert instance.data is None
        assert instance.error is None

    # --- Class Method Tests ---

    def test_success_classmethod(self):
        """CommandResult.success() creates a success result."""
        data = {"result": "ok"}
        instance = CommandResult.success(data)
        assert instance.success is True
        assert instance.data == data
        assert instance.error is None

    def test_success_classmethod_no_data(self):
        """CommandResult.success() works without data."""
        instance = CommandResult.success()
        assert instance.success is True
        assert instance.data is None

    def test_failure_classmethod(self):
        """CommandResult.failure() creates a failure result."""
        error_msg = "Test error"
        instance = CommandResult.failure(error_msg)
        assert instance.success is False
        assert instance.error == error_msg
        assert instance.data is None

    # --- Property Tests ---

    def test_is_success_property_true(self):
        """is_success returns True for successful results."""
        instance = CommandResult.success({"data": "test"})
        assert instance.is_success is True

    def test_is_success_property_false(self):
        """is_success returns False for failed results."""
        instance = CommandResult.failure("error")
        assert instance.is_success is False

    def test_is_failure_property_true(self):
        """is_failure returns True for failed results."""
        instance = CommandResult.failure("error")
        assert instance.is_failure is True

    def test_is_failure_property_false(self):
        """is_failure returns False for successful results."""
        instance = CommandResult.success({"data": "test"})
        assert instance.is_failure is False

    # --- validate() Method Tests ---

    def test_validate_success_without_error(self):
        """validate() passes for success result without error."""
        instance = CommandResult(success=True, data={"x": 1}, error=None)
        result = instance.validate()
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_failure_with_error(self):
        """validate() passes for failure result with error."""
        instance = CommandResult(success=False, data=None, error="Error msg")
        result = instance.validate()
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_success_with_error_invalid(self):
        """validate() fails when success has error message."""
        instance = CommandResult(success=True, data={"x": 1}, error="Unexpected error")
        result = instance.validate()
        assert result["is_valid"] is False
        assert "Success result cannot have error" in result["errors"]

    def test_validate_failure_without_error_invalid(self):
        """validate() fails when failure has no error message."""
        instance = CommandResult(success=False, data=None, error=None)
        result = instance.validate()
        assert result["is_valid"] is False
        assert "Failure result must have error message" in result["errors"]

    # --- to_dict() Method Tests ---

    def test_to_dict_success(self):
        """to_dict() serializes success result correctly."""
        data = {"key": "value"}
        instance = CommandResult(success=True, data=data)
        result = instance.to_dict()
        assert result == {
            "success": True,
            "data": data,
            "error": None,
        }

    def test_to_dict_failure(self):
        """to_dict() serializes failure result correctly."""
        instance = CommandResult.failure("test error")
        result = instance.to_dict()
        assert result == {
            "success": False,
            "data": None,
            "error": "test error",
        }

    # --- from_dict() Method Tests ---

    def test_from_dict_success(self):
        """from_dict() deserializes success result correctly."""
        data = {
            "success": True,
            "data": {"result": "ok"},
            "error": None,
        }
        instance = CommandResult.from_dict(data)
        assert instance.success is True
        assert instance.data == {"result": "ok"}
        assert instance.error is None

    def test_from_dict_failure(self):
        """from_dict() deserializes failure result correctly."""
        data = {
            "success": False,
            "data": None,
            "error": "Deserialization error",
        }
        instance = CommandResult.from_dict(data)
        assert instance.success is False
        assert instance.error == "Deserialization error"

    def test_from_dict_missing_optional_fields(self):
        """from_dict() handles missing optional fields."""
        data = {"success": True}
        instance = CommandResult.from_dict(data)
        assert instance.success is True
        assert instance.data is None
        assert instance.error is None

    # --- clone() Method Tests ---

    def test_clone_creates_new_instance(self):
        """clone() creates a new instance with same values."""
        original = CommandResult(success=True, data={"x": 1})
        cloned = original.clone()
        assert cloned is not original
        assert cloned.success == original.success
        assert cloned.data == original.data
        assert cloned.error == original.error

    def test_clone_independent_modification(self):
        """clone() creates independent copy."""
        original = CommandResult(success=True, data={"x": 1})
        cloned = original.clone()
        cloned.data = {"modified": True}
        assert original.data == {"x": 1}
        assert cloned.data == {"modified": True}

    # --- snapshot() Method Tests ---

    def test_snapshot_success(self):
        """snapshot() returns summary dict for success."""
        instance = CommandResult(success=True, data={"data": "test"})
        result = instance.snapshot()
        assert result == {
            "success": True,
            "has_data": True,
            "has_error": False,
        }

    def test_snapshot_failure(self):
        """snapshot() returns summary dict for failure."""
        instance = CommandResult.failure("error")
        result = instance.snapshot()
        assert result == {
            "success": False,
            "has_data": False,
            "has_error": True,
        }

    def test_snapshot_with_none_data(self):
        """snapshot() correctly reports has_data=False when data is None."""
        instance = CommandResult(success=True, data=None)
        result = instance.snapshot()
        assert result["has_data"] is False

    # --- version() Method Tests ---

    def test_version_returns_one(self):
        """version() returns 1 for CommandResult."""
        instance = CommandResult.success()
        assert instance.version() == 1

    # --- audit_trail() Method Tests ---

    def test_audit_trail_returns_empty_list(self):
        """audit_trail() returns empty list for CommandResult."""
        instance = CommandResult.success()
        result = instance.audit_trail()
        assert result == []

    def test_audit_trail_with_limit(self):
        """audit_trail() accepts limit parameter."""
        instance = CommandResult.success()
        result = instance.audit_trail(limit=50)
        assert result == []

    # --- touch() Method Tests ---

    def test_touch_returns_clone(self):
        """touch() returns a cloned instance."""
        original = CommandResult.success({"data": "test"})
        touched = original.touch("user123")
        assert touched is not original
        assert touched.success == original.success
        assert touched.data == original.data

    def test_touch_preserves_values(self):
        """touch() preserves all values."""
        original = CommandResult(success=False, error="original error")
        touched = original.touch("admin")
        assert touched.success is False
        assert touched.error == "original error"


class TestCommandEnvelope:
    """Tests for the CommandEnvelope value object / model."""

    def _build_valid_kwargs(self):
        """Build valid kwargs for CommandEnvelope construction."""
        return {
            'command_id': uuid4(),
            'command_type': "CreateTransaction",
            'command_data': {"amount": 100, "currency": "IDR"},
            'idempotency_key': "idem-key-123",
            'user_id': "user-123",
            'legal_entity_id': uuid4(),
            'timestamp': datetime.now(UTC),
            'correlation_id': "corr-123",
            'causation_id': uuid4(),
            'status': CommandStatus.PENDING,
            'result': None,
            'error': None,
            'execution_time_ms': 0.0,
            'retry_count': 0,
            'command': MagicMock(),
        }

    # --- Construction Tests ---

    def test_construction_success(self):
        """CommandEnvelope can be constructed with valid field values."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        assert isinstance(instance, CommandEnvelope)
        assert instance.command_id == kwargs['command_id']
        assert instance.command_type == kwargs['command_type']

    def test_construction_minimal_required_fields(self):
        """CommandEnvelope requires specific fields for construction."""
        kwargs = self._build_valid_kwargs()
        # All fields are required in dataclass, so we test with complete data
        instance = CommandEnvelope(**kwargs)
        assert instance is not None

    def test_default_values(self):
        """CommandEnvelope has correct default values."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        assert instance.status == CommandStatus.PENDING
        assert instance.result is None
        assert instance.error is None
        assert instance.execution_time_ms == 0.0
        assert instance.retry_count == 0

    # --- create() Class Method Tests ---

    def test_create_generates_uuid(self):
        """create() generates a new command_id UUID."""
        entity_id = uuid4()
        envelope = CommandEnvelope.create(
            command_type="TestCommand",
            command_data={"key": "value"},
            user_id="user-123",
            legal_entity_id=entity_id,
        )
        assert isinstance(envelope.command_id, UUID)

    def test_create_sets_timestamp(self):
        """create() sets current UTC timestamp."""
        before = datetime.now(UTC)
        envelope = CommandEnvelope.create(
            command_type="TestCommand",
            command_data={},
            user_id="user-123",
            legal_entity_id=uuid4(),
        )
        after = datetime.now(UTC)
        assert before <= envelope.timestamp <= after
        assert envelope.timestamp.tzinfo == UTC

    def test_create_default_status_pending(self):
        """create() sets initial status to PENDING."""
        envelope = CommandEnvelope.create(
            command_type="TestCommand",
            command_data={},
            user_id="user-123",
            legal_entity_id=uuid4(),
        )
        assert envelope.status == CommandStatus.PENDING

    def test_create_generates_correlation_id_if_not_provided(self):
        """create() generates correlation_id if not provided."""
        envelope = CommandEnvelope.create(
            command_type="TestCommand",
            command_data={},
            user_id="user-123",
            legal_entity_id=uuid4(),
        )
        assert envelope.correlation_id is not None

    def test_create_uses_provided_correlation_id(self):
        """create() uses provided correlation_id."""
        custom_corr_id = "custom-corr-id"
        envelope = CommandEnvelope.create(
            command_type="TestCommand",
            command_data={},
            user_id="user-123",
            legal_entity_id=uuid4(),
            correlation_id=custom_corr_id,
        )
        assert envelope.correlation_id == custom_corr_id

    def test_create_with_optional_params(self):
        """create() handles optional parameters correctly."""
        idem_key = "idempotency-key"
        causation = uuid4()
        cmd_mock = MagicMock()
        envelope = CommandEnvelope.create(
            command_type="TestCommand",
            command_data={"x": 1},
            user_id="user-123",
            legal_entity_id=uuid4(),
            idempotency_key=idem_key,
            correlation_id="corr-id",
            causation_id=causation,
            command=cmd_mock,
        )
        assert envelope.idempotency_key == idem_key
        assert envelope.causation_id == causation
        assert envelope.command is cmd_mock

    # --- to_dict() Method Tests ---

    def test_to_dict_contains_all_serializable_fields(self):
        """to_dict() contains all serializable fields."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.to_dict()
        assert "command_id" in result
        assert "command_type" in result
        assert "user_id" in result
        assert "legal_entity_id" in result
        assert "status" in result
        assert "timestamp" in result

    def test_to_dict_uuids_as_strings(self):
        """to_dict() converts UUIDs to strings."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.to_dict()
        assert isinstance(result["command_id"], str)
        assert isinstance(result["legal_entity_id"], str)

    def test_to_dict_status_as_string(self):
        """to_dict() converts status to string name."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.to_dict()
        assert result["status"] == "PENDING"

    def test_to_dict_timestamp_as_isoformat(self):
        """to_dict() formats timestamp as ISO string."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.to_dict()
        assert result["timestamp"] == instance.timestamp.isoformat()

    def test_to_dict_causation_id_none_handled(self):
        """to_dict() handles None causation_id."""
        kwargs = self._build_valid_kwargs()
        kwargs["causation_id"] = None
        instance = CommandEnvelope(**kwargs)
        result = instance.to_dict()
        assert result["causation_id"] is None

    # --- from_dict() Method Tests ---

    def test_from_dict_reconstructs_envelope(self):
        """from_dict() reconstructs envelope from dict."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        data = original.to_dict()
        reconstructed = CommandEnvelope.from_dict(data)
        assert reconstructed.command_id == original.command_id
        assert reconstructed.command_type == original.command_type
        assert reconstructed.user_id == original.user_id

    def test_from_dict_parses_uuids(self):
        """from_dict() parses UUID strings back to UUID objects."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        data = original.to_dict()
        reconstructed = CommandEnvelope.from_dict(data)
        assert isinstance(reconstructed.command_id, UUID)
        assert isinstance(reconstructed.legal_entity_id, UUID)

    def test_from_dict_parses_status(self):
        """from_dict() parses status string back to enum."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        data = original.to_dict()
        reconstructed = CommandEnvelope.from_dict(data)
        assert isinstance(reconstructed.status, CommandStatus)
        assert reconstructed.status == original.status

    def test_from_dict_parses_timestamp(self):
        """from_dict() parses ISO timestamp back to datetime."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        data = original.to_dict()
        reconstructed = CommandEnvelope.from_dict(data)
        assert isinstance(reconstructed.timestamp, datetime)

    def test_from_dict_defaults_missing_fields(self):
        """from_dict() provides defaults for missing optional fields."""
        minimal_data = {
            "command_id": str(uuid4()),
            "command_type": "TestCommand",
            "user_id": "user-123",
            "legal_entity_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        envelope = CommandEnvelope.from_dict(minimal_data)
        assert envelope.status == CommandStatus.PENDING
        assert envelope.execution_time_ms == 0.0
        assert envelope.retry_count == 0

    # --- validate() Method Tests ---

    def test_validate_passes_for_valid_envelope(self):
        """validate() passes for valid envelope."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.validate()
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_fails_empty_command_type(self):
        """validate() fails when command_type is empty."""
        kwargs = self._build_valid_kwargs()
        kwargs["command_type"] = ""
        instance = CommandEnvelope(**kwargs)
        result = instance.validate()
        assert result["is_valid"] is False
        assert "command_type is required" in result["errors"]

    def test_validate_fails_empty_user_id(self):
        """validate() fails when user_id is empty."""
        kwargs = self._build_valid_kwargs()
        kwargs["user_id"] = ""
        instance = CommandEnvelope(**kwargs)
        result = instance.validate()
        assert result["is_valid"] is False
        assert "user_id is required" in result["errors"]

    def test_validate_fails_missing_legal_entity_id(self):
        """validate() fails when legal_entity_id is None/missing."""
        kwargs = self._build_valid_kwargs()
        kwargs["legal_entity_id"] = None
        instance = CommandEnvelope(**kwargs)
        result = instance.validate()
        assert result["is_valid"] is False
        assert "legal_entity_id is required" in result["errors"]

    def test_validate_success_cannot_have_error(self):
        """validate() fails when SUCCESS status has error."""
        kwargs = self._build_valid_kwargs()
        kwargs["status"] = CommandStatus.SUCCESS
        kwargs["error"] = "Some error"
        instance = CommandEnvelope(**kwargs)
        result = instance.validate()
        assert result["is_valid"] is False
        assert "Success status cannot have error" in result["errors"]

    def test_validate_failed_must_have_error(self):
        """validate() fails when FAILED status has no error."""
        kwargs = self._build_valid_kwargs()
        kwargs["status"] = CommandStatus.FAILED
        kwargs["error"] = None
        instance = CommandEnvelope(**kwargs)
        result = instance.validate()
        assert result["is_valid"] is False
        assert "Failed status must have error" in result["errors"]

    # --- clone() Method Tests ---

    def test_clone_creates_new_envelope_with_new_id(self):
        """clone() creates new envelope with different command_id."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        cloned = original.clone()
        assert cloned.command_id != original.command_id
        assert cloned is not original

    def test_clone_preserves_core_attributes(self):
        """clone() preserves core attributes like command_type, user_id."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        cloned = original.clone()
        assert cloned.command_type == original.command_type
        assert cloned.user_id == original.user_id
        assert cloned.legal_entity_id == original.legal_entity_id
        assert cloned.command_data == original.command_data

    def test_clone_copies_command_data_dict(self):
        """clone() creates a copy of command_data dict."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        cloned = original.clone()
        assert cloned.command_data == original.command_data
        assert cloned.command_data is not original.command_data

    def test_clone_resets_status_to_pending(self):
        """clone() resets status to PENDING."""
        kwargs = self._build_valid_kwargs()
        kwargs["status"] = CommandStatus.SUCCESS
        original = CommandEnvelope(**kwargs)
        cloned = original.clone()
        assert cloned.status == CommandStatus.PENDING

    def test_clone_clears_result_and_error(self):
        """clone() clears result and error."""
        kwargs = self._build_valid_kwargs()
        kwargs["result"] = CommandResult.success({"data": "test"})
        kwargs["error"] = "Original error"
        original = CommandEnvelope(**kwargs)
        cloned = original.clone()
        assert cloned.result is None
        assert cloned.error is None

    def test_clone_resets_execution_metrics(self):
        """clone() resets execution_time_ms and retry_count."""
        kwargs = self._build_valid_kwargs()
        kwargs["execution_time_ms"] = 150.5
        kwargs["retry_count"] = 3
        original = CommandEnvelope(**kwargs)
        cloned = original.clone()
        assert cloned.execution_time_ms == 0.0
        assert cloned.retry_count == 0

    def test_clone_sets_causation_id_to_original_command_id(self):
        """clone() sets causation_id to original's command_id."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        cloned = original.clone()
        assert cloned.causation_id == original.command_id

    # --- snapshot() Method Tests ---

    def test_snapshot_returns_summary_dict(self):
        """snapshot() returns a summary dictionary."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.snapshot()
        assert "command_id" in result
        assert "command_type" in result
        assert "status" in result
        assert "execution_time_ms" in result
        assert "timestamp" in result

    def test_snapshot_status_as_string(self):
        """snapshot() includes status as string name."""
        kwargs = self._build_valid_kwargs()
        kwargs["status"] = CommandStatus.EXECUTING
        instance = CommandEnvelope(**kwargs)
        result = instance.snapshot()
        assert result["status"] == "EXECUTING"

    # --- version() Method Tests ---

    def test_version_returns_one(self):
        """version() returns 1 for CommandEnvelope."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        assert instance.version() == 1

    # --- audit_trail() Method Tests ---

    def test_audit_trail_returns_list_with_current_state(self):
        """audit_trail() returns list containing current state."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.audit_trail()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["command_id"] == str(instance.command_id)

    def test_audit_trail_with_limit(self):
        """audit_trail() accepts limit parameter."""
        kwargs = self._build_valid_kwargs()
        instance = CommandEnvelope(**kwargs)
        result = instance.audit_trail(limit=10)
        assert isinstance(result, list)

    # --- touch() Method Tests ---

    def test_touch_updates_timestamp(self):
        """touch() updates the timestamp to current time."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        original_timestamp = original.timestamp
        touched = original.touch("user-456")
        assert touched.timestamp >= original_timestamp

    def test_touch_preserves_command_id(self):
        """touch() preserves the command_id."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        touched = original.touch("user-456")
        assert touched.command_id == original.command_id

    def test_touch_preserves_all_attributes(self):
        """touch() preserves all other attributes."""
        kwargs = self._build_valid_kwargs()
        kwargs["status"] = CommandStatus.EXECUTING
        kwargs["execution_time_ms"] = 100.0
        kwargs["retry_count"] = 2
        original = CommandEnvelope(**kwargs)
        touched = original.touch("admin")
        assert touched.command_type == original.command_type
        assert touched.user_id == original.user_id
        assert touched.status == original.status
        assert touched.execution_time_ms == original.execution_time_ms
        assert touched.retry_count == original.retry_count

    def test_touch_returns_new_instance(self):
        """touch() returns a new instance (immutable)."""
        kwargs = self._build_valid_kwargs()
        original = CommandEnvelope(**kwargs)
        touched = original.touch("user-789")
        assert touched is not original


class TestCommandEnvelopeIntegration:
    """Integration tests for CommandEnvelope workflow."""

    def test_full_lifecycle_create_validate_serialize_deserialize(self):
        """Test full lifecycle: create -> validate -> serialize -> deserialize."""
        # Create
        entity_id = uuid4()
        envelope = CommandEnvelope.create(
            command_type="TransferFunds",
            command_data={"amount": 1000, "from": "A", "to": "B"},
            user_id="user-123",
            legal_entity_id=entity_id,
            idempotency_key="idem-001",
        )

        # Validate
        validation = envelope.validate()
        assert validation["is_valid"] is True

        # Serialize
        data = envelope.to_dict()
        assert isinstance(data, dict)

        # Deserialize
        restored = CommandEnvelope.from_dict(data)
        assert restored.command_id == envelope.command_id
        assert restored.command_type == envelope.command_type
        assert restored.user_id == envelope.user_id

    def test_status_transitions(self):
        """Test that envelope status can be updated through lifecycle."""
        envelope = CommandEnvelope.create(
            command_type="TestCommand",
            command_data={},
            user_id="user-123",
            legal_entity_id=uuid4(),
        )

        # Initial status
        assert envelope.status == CommandStatus.PENDING

        # Simulate status transitions (by creating new envelopes with updated status)
        validating = CommandEnvelope(
            **{**envelope.__dict__, "status": CommandStatus.VALIDATING}
        )
        assert validating.status == CommandStatus.VALIDATING

        executing = CommandEnvelope(
            **{**validating.__dict__, "status": CommandStatus.EXECUTING}
        )
        assert executing.status == CommandStatus.EXECUTING

        success = CommandEnvelope(
            **{**executing.__dict__, "status": CommandStatus.SUCCESS}
        )
        assert success.status == CommandStatus.SUCCESS

    def test_clone_and_modify_workflow(self):
        """Test cloning envelope for retry workflow."""
        original = CommandEnvelope.create(
            command_type="RetryableCommand",
            command_data={"attempt": 1},
            user_id="user-123",
            legal_entity_id=uuid4(),
        )

        # Simulate failure
        failed = CommandEnvelope(
            **{**original.__dict__, "status": CommandStatus.FAILED, "error": "Network error"}
        )

        # Clone for retry
        retry_envelope = failed.clone()
        assert retry_envelope.status == CommandStatus.PENDING
        assert retry_envelope.error is None
        assert retry_envelope.causation_id == failed.command_id
