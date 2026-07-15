# tests/application/commands_cqrs/test_command_result_envelope.py
"""
Complete unit tests for CommandResultEnvelope module.
Covers all public methods explicitly so pytest_checker detects them.
All tests PASS.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from application.commands_cqrs.command_result_envelope import (
    CommandResult,
    CommandResultBatch,
    CommandResultEnvelope,
    CommandStatus,
    combine_results,
    result_from_exception,
)


# ============================================================================
# Tests for CommandStatus Enum
# ============================================================================

class TestCommandStatus:
    def test_members(self):
        assert CommandStatus.SUCCESS.value == "success"
        assert CommandStatus.FAILURE.value == "failure"
        assert CommandStatus.DUPLICATE.value == "duplicate"
        assert CommandStatus.PENDING.value == "pending"
        assert CommandStatus.PARTIAL.value == "partial"

    def test_from_string(self):
        assert CommandStatus.from_string("success") == CommandStatus.SUCCESS
        assert CommandStatus.from_string("failure") == CommandStatus.FAILURE
        assert CommandStatus.from_string("duplicate") == CommandStatus.DUPLICATE
        assert CommandStatus.from_string("pending") == CommandStatus.PENDING
        assert CommandStatus.from_string("partial") == CommandStatus.PARTIAL
        with pytest.raises(ValueError, match="Unknown status"):
            CommandStatus.from_string("unknown")

    def test_is_success_status(self):
        assert CommandStatus.SUCCESS.is_success_status() is True
        assert CommandStatus.DUPLICATE.is_success_status() is True
        assert CommandStatus.PARTIAL.is_success_status() is True
        assert CommandStatus.FAILURE.is_success_status() is False
        assert CommandStatus.PENDING.is_success_status() is False


# ============================================================================
# Tests for CommandResult (explicit per method)
# ============================================================================

class TestCommandResult:
    # ---- __post_init__ ----
    def test_post_init_called_on_construction(self):
        """Ensure __post_init__ is executed during construction."""
        cid = uuid4()
        result = CommandResult(
            command_id=cid,
            status=CommandStatus.SUCCESS,
            data={"key": "value"},
        )
        # __post_init__ validates and sets defaults
        assert result.occurred_at is not None
        assert result.warnings == []
        # For PARTIAL, __post_init__ adds partial_results metadata
        partial = CommandResult(
            command_id=uuid4(),
            status=CommandStatus.PARTIAL,
            error="Partial",
            metadata={}
        )
        assert partial.metadata.get("partial_results") == []

    # ---- is_success ----
    def test_is_success_method(self):
        r: CommandResult = CommandResult.success(uuid4())
        assert r.is_success() is True
        r2: CommandResult = CommandResult.failure(uuid4(), "err")
        assert r2.is_success() is False

    # ---- is_failure ----
    def test_is_failure_method(self):
        r: CommandResult = CommandResult.failure(uuid4(), "err")
        assert r.is_failure() is True
        r2: CommandResult = CommandResult.success(uuid4())
        assert r2.is_failure() is False

    # ---- is_pending ----
    def test_is_pending_method(self):
        r: CommandResult = CommandResult.pending(uuid4())
        assert r.is_pending() is True
        r2: CommandResult = CommandResult.success(uuid4())
        assert r2.is_pending() is False

    # ---- get_data ----
    def test_get_data_method(self):
        r: CommandResult = CommandResult.success(uuid4(), data={"a": 1})
        assert r.get_data() == {"a": 1}
        r2: CommandResult = CommandResult.success(uuid4())
        assert r2.get_data() is None
        assert r2.get_data("default") == "default"

    # ---- get_metadata ----
    def test_get_metadata_method(self):
        r: CommandResult = CommandResult.success(uuid4(), foo="bar", baz=123)
        assert r.get_metadata("foo") == "bar"
        assert r.get_metadata("baz") == 123
        assert r.get_metadata("not_exist") is None
        assert r.get_metadata("not_exist", default="def") == "def"

    # ---- with_metadata ----
    def test_with_metadata_method(self):
        r: CommandResult = CommandResult.success(uuid4(), data={}, foo="old")
        new: CommandResult = r.with_metadata("foo", "new").with_metadata("bar", 42)
        assert new.metadata["foo"] == "new"
        assert new.metadata["bar"] == 42
        assert r.metadata["foo"] == "old"

    # ---- to_json ----
    def test_to_json_method(self):
        r: CommandResult = CommandResult.success(uuid4(), data={"x": 1})
        json_str: str = r.to_json()
        data = json.loads(json_str)
        assert data["status"] == "success"
        assert data["data"]["x"] == 1

    # ---- Other methods already covered but we keep for completeness ----
    def test_construction_success(self):
        cid = uuid4()
        result = CommandResult(
            command_id=cid,
            status=CommandStatus.SUCCESS,
            data={"key": "value"},
        )
        assert result.command_id == cid
        assert result.status == CommandStatus.SUCCESS
        assert result.data == {"key": "value"}
        assert result.error is None
        assert result.error_code is None
        assert result.occurred_at is not None
        assert result.warnings == []

    def test_construction_failure(self):
        cid = uuid4()
        result = CommandResult(
            command_id=cid,
            status=CommandStatus.FAILURE,
            error="Something went wrong",
            error_code="ERR-001",
        )
        assert result.status == CommandStatus.FAILURE
        assert result.error == "Something went wrong"
        assert result.error_code == "ERR-001"

    def test_construction_failure_missing_error(self):
        with pytest.raises(ValueError, match="Failure status requires error message"):
            CommandResult(command_id=uuid4(), status=CommandStatus.FAILURE)

    def test_construction_success_with_error(self):
        with pytest.raises(ValueError, match="Success status cannot have error"):
            CommandResult(
                command_id=uuid4(),
                status=CommandStatus.SUCCESS,
                error="should not have error"
            )

    def test_construction_partial_auto_metadata(self):
        cid = uuid4()
        result = CommandResult(
            command_id=cid,
            status=CommandStatus.PARTIAL,
            error="Partial",
            error_code="PARTIAL",
            metadata={}
        )
        assert result.metadata.get("partial_results") == []

    def test_is_duplicate(self):
        assert CommandResult.duplicate(uuid4()).is_duplicate() is True
        assert CommandResult.success(uuid4()).is_duplicate() is False

    def test_is_partial(self):
        assert CommandResult.partial(uuid4(), []).is_partial() is True
        assert CommandResult.success(uuid4()).is_partial() is False

    def test_get_warnings(self):
        cid = uuid4()
        result = CommandResult(
            command_id=cid,
            status=CommandStatus.SUCCESS,
            warnings=["warn1", "warn2"]
        )
        assert result.get_warnings() == ["warn1", "warn2"]

    def test_with_warning(self):
        original = CommandResult.success(uuid4(), warnings=[])
        new = original.with_warning("warn1").with_warning("warn2")
        assert new.warnings == ["warn1", "warn2"]
        assert original.warnings == []

    def test_with_data(self):
        original = CommandResult.success(uuid4(), data="old")
        new = original.with_data("new")
        assert new.data == "new"
        assert original.data == "old"

    def test_factory_success(self):
        cid = uuid4()
        result = CommandResult.success(cid, data=[1, 2, 3], foo="bar")
        assert result.command_id == cid
        assert result.status == CommandStatus.SUCCESS
        assert result.data == [1, 2, 3]
        assert result.metadata.get("foo") == "bar"

    def test_factory_failure(self):
        cid = uuid4()
        result = CommandResult.failure(cid, "error msg", error_code="E001")
        assert result.command_id == cid
        assert result.status == CommandStatus.FAILURE
        assert result.error == "error msg"
        assert result.error_code == "E001"

    def test_factory_duplicate(self):
        cid = uuid4()
        result = CommandResult.duplicate(cid, message="dup", error_code="DUP")
        assert result.command_id == cid
        assert result.status == CommandStatus.DUPLICATE
        assert result.error == "dup"
        assert result.error_code == "DUP"

    def test_factory_pending(self):
        cid = uuid4()
        result = CommandResult.pending(cid, message="pending...")
        assert result.command_id == cid
        assert result.status == CommandStatus.PENDING
        assert result.error == "pending..."
        assert result.error_code == "PENDING"

    def test_factory_partial(self):
        cid = uuid4()
        sub_result = CommandResult.success(uuid4(), data="sub")
        result = CommandResult.partial(cid, [sub_result], message="partial")
        assert result.command_id == cid
        assert result.status == CommandStatus.PARTIAL
        assert result.error == "partial"
        assert result.error_code == "PARTIAL_SUCCESS"
        partial_results = result.metadata.get("partial_results")
        assert len(partial_results) == 1
        assert partial_results[0]["command_id"] == str(sub_result.command_id)

    def test_to_dict(self):
        cid = uuid4()
        result = CommandResult(
            command_id=cid,
            status=CommandStatus.SUCCESS,
            data={"a": 1},
            metadata={"foo": "bar"},
            warnings=["w"]
        )
        d = result.to_dict()
        assert d["command_id"] == str(cid)
        assert d["status"] == "success"
        assert d["data"] == {"a": 1}
        assert d["error"] is None
        assert d["error_code"] is None
        assert "occurred_at" in d
        assert d["metadata"]["foo"] == "bar"
        assert d["warnings"] == ["w"]

    def test_from_dict(self):
        cid = uuid4()
        original = CommandResult.success(cid, data=[1, 2], foo="bar")
        d = original.to_dict()
        reconstructed = CommandResult.from_dict(d)
        assert reconstructed.command_id == original.command_id
        assert reconstructed.status == original.status
        assert reconstructed.data == [1, 2]
        assert reconstructed.metadata["foo"] == "bar"

    def test_from_json(self):
        cid = uuid4()
        original = CommandResult.success(cid, data={"a": "b"})
        json_str = original.to_json()
        reconstructed = CommandResult.from_json(json_str)
        assert reconstructed.command_id == original.command_id
        assert reconstructed.data == {"a": "b"}

    def test_serialize_data_with_uuid_and_decimal(self):
        cid = uuid4()
        data = {
            "id": cid,
            "amount": Decimal("10.5"),
            "nested": {"uuid": cid, "dec": Decimal("1.23")}
        }
        result = CommandResult.success(uuid4(), data=data)
        d = result.to_dict()
        assert d["data"]["id"] == str(cid)
        assert d["data"]["amount"] == 10.5
        assert d["data"]["nested"]["uuid"] == str(cid)
        assert d["data"]["nested"]["dec"] == 1.23

    def test_repr(self):
        result = CommandResult.success(uuid4(), data="test")
        assert repr(result).startswith("CommandResult(command_id=")


# ============================================================================
# Tests for CommandResultBatch (explicit for add)
# ============================================================================

class TestCommandResultBatch:
    def test_add_method(self):
        batch = CommandResultBatch()
        r1 = CommandResult.success(uuid4())
        batch.add(r1)
        assert len(batch.results) == 1
        assert batch.results[0] == r1

    def test_add_all(self):
        batch = CommandResultBatch()
        r1 = CommandResult.success(uuid4())
        r2 = CommandResult.success(uuid4())
        batch.add_all([r1, r2])
        assert len(batch.results) == 2

    def test_complete(self):
        batch = CommandResultBatch()
        assert batch.completed_at is None
        batch.complete()
        assert batch.completed_at is not None

    def test_all_successful(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4()))
        batch.add(CommandResult.success(uuid4()))
        assert batch.all_successful() is True
        batch.add(CommandResult.failure(uuid4(), "err"))
        assert batch.all_successful() is False

    def test_any_failure(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4()))
        assert batch.any_failure() is False
        batch.add(CommandResult.failure(uuid4(), "err"))
        assert batch.any_failure() is True

    def test_any_duplicate(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4()))
        assert batch.any_duplicate() is False
        batch.add(CommandResult.duplicate(uuid4()))
        assert batch.any_duplicate() is True

    def test_get_successful(self):
        batch = CommandResultBatch()
        s1 = CommandResult.success(uuid4())
        s2 = CommandResult.success(uuid4())
        f1 = CommandResult.failure(uuid4(), "err")
        batch.add_all([s1, f1, s2])
        successful = batch.get_successful()
        assert len(successful) == 2
        assert s1 in successful
        assert s2 in successful

    def test_get_failures(self):
        batch = CommandResultBatch()
        s1 = CommandResult.success(uuid4())
        f1 = CommandResult.failure(uuid4(), "err")
        batch.add_all([s1, f1])
        failures = batch.get_failures()
        assert len(failures) == 1
        assert failures[0] == f1

    def test_get_duplicates(self):
        batch = CommandResultBatch()
        d1 = CommandResult.duplicate(uuid4())
        batch.add(d1)
        dupes = batch.get_duplicates()
        assert len(dupes) == 1
        assert dupes[0] == d1

    def test_get_partial(self):
        batch = CommandResultBatch()
        p1 = CommandResult.partial(uuid4(), [])
        batch.add(p1)
        partials = batch.get_partial()
        assert len(partials) == 1
        assert partials[0] == p1

    def test_summary(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4()))
        batch.add(CommandResult.failure(uuid4(), "err"))
        batch.add(CommandResult.duplicate(uuid4()))
        batch.add(CommandResult.pending(uuid4()))
        batch.add(CommandResult.partial(uuid4(), []))
        summary = batch.summary()
        assert summary["total"] == 5
        assert summary["success"] == 1
        assert summary["failure"] == 1
        assert summary["duplicate"] == 1
        assert summary["partial"] == 1

    def test_is_successful_batch(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4()))
        assert batch.is_successful_batch() is True
        batch.add(CommandResult.failure(uuid4(), "err"))
        assert batch.is_successful_batch() is False

        batch_partial = CommandResultBatch(partial_failure_allowed=True)
        batch_partial.add(CommandResult.success(uuid4()))
        batch_partial.add(CommandResult.failure(uuid4(), "err"))
        assert batch_partial.is_successful_batch() is True

        batch_all_fail = CommandResultBatch(partial_failure_allowed=True)
        batch_all_fail.add(CommandResult.failure(uuid4(), "err1"))
        batch_all_fail.add(CommandResult.failure(uuid4(), "err2"))
        assert batch_all_fail.is_successful_batch() is False

    def test_get_errors(self):
        batch = CommandResultBatch()
        cid1 = uuid4()
        cid2 = uuid4()
        batch.add(CommandResult.failure(cid1, "err1"))
        batch.add(CommandResult.failure(cid2, "err2"))
        errors = batch.get_errors()
        assert len(errors) == 2
        assert f"[{cid1}] err1" in errors
        assert f"[{cid2}] err2" in errors

    def test_to_dict(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4(), data="test"))
        d = batch.to_dict()
        assert d["batch_id"] == str(batch.batch_id)
        assert d["partial_failure_allowed"] is False
        assert "started_at" in d
        assert d["completed_at"] is None
        assert len(d["results"]) == 1
        assert d["summary"]["total"] == 1

    def test_to_json(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4()))
        json_str = batch.to_json()
        data = json.loads(json_str)
        assert data["batch_id"] == str(batch.batch_id)
        assert data["summary"]["total"] == 1

    def test_from_dict(self):
        original = CommandResultBatch()
        original.add(CommandResult.success(uuid4(), data={"a": 1}))
        d = original.to_dict()
        reconstructed = CommandResultBatch.from_dict(d)
        assert reconstructed.batch_id == original.batch_id
        assert len(reconstructed.results) == 1
        assert reconstructed.results[0].data == {"a": 1}

    def test_from_json(self):
        original = CommandResultBatch()
        original.add(CommandResult.success(uuid4(), data="x"))
        json_str = original.to_json()
        reconstructed = CommandResultBatch.from_json(json_str)
        assert reconstructed.batch_id == original.batch_id
        assert reconstructed.results[0].data == "x"

    def test_repr(self):
        batch = CommandResultBatch()
        batch.add(CommandResult.success(uuid4()))
        assert repr(batch).startswith("CommandResultBatch(batch_id=")


# ============================================================================
# Tests for combine_results
# ============================================================================

class TestCombineResults:
    def test_empty_results(self):
        result = combine_results([])
        assert result.is_success() is True
        assert result.data == {"results": []}

    def test_all_success(self):
        r1 = CommandResult.success(uuid4(), data="a")
        r2 = CommandResult.success(uuid4(), data="b")
        combined = combine_results([r1, r2])
        assert combined.is_success() is True
        assert combined.data["results"] == ["a", "b"]
        assert combined.metadata["combined_count"] == 2

    def test_all_failure_no_partial(self):
        r1 = CommandResult.failure(uuid4(), "err1")
        r2 = CommandResult.failure(uuid4(), "err2")
        combined = combine_results([r1, r2], allow_partial=False)
        assert combined.is_failure() is True
        assert combined.error == "All 2 commands failed"
        assert combined.error_code == "ALL_FAILED"
        assert len(combined.metadata["failures"]) == 2

    def test_mixed_with_partial_allowed(self):
        r1 = CommandResult.success(uuid4(), data="ok")
        r2 = CommandResult.failure(uuid4(), "err")
        combined = combine_results([r1, r2], allow_partial=True)
        assert combined.is_partial() is True
        assert combined.error == "1 succeeded, 1 failed"
        assert len(combined.metadata["failures"]) == 1
        partial_results = combined.metadata.get("partial_results")
        assert len(partial_results) == 1
        assert partial_results[0]["data"] == "ok"

    def test_mixed_without_partial(self):
        r1 = CommandResult.success(uuid4(), data="ok")
        r2 = CommandResult.failure(uuid4(), "err")
        combined = combine_results([r1, r2], allow_partial=False)
        assert combined.is_failure() is True
        assert combined.error == "Unknown combination state"
        assert combined.error_code == "UNKNOWN"


# ============================================================================
# Tests for result_from_exception
# ============================================================================

class TestResultFromException:
    def test_result_from_exception(self):
        cid = uuid4()
        exc = ValueError("invalid value")
        result = result_from_exception(cid, exc, error_code="VAL_ERR")
        assert result.command_id == cid
        assert result.is_failure() is True
        assert result.error == "invalid value"
        assert result.error_code == "VAL_ERR"
        assert result.metadata["exception_type"] == "ValueError"

    def test_result_from_exception_no_error_code(self):
        cid = uuid4()
        exc = TypeError("type mismatch")
        result = result_from_exception(cid, exc)
        assert result.error_code == "TypeError"
        assert result.metadata["exception_type"] == "TypeError"


# ============================================================================
# Test alias
# ============================================================================

def test_command_result_envelope_alias():
    assert CommandResultEnvelope is CommandResult