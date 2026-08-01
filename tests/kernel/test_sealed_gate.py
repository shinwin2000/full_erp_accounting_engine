# tests/kernel/test_sealed_gate.py
"""
Comprehensive tests for kernel/sealed_gate.py
All tests now include meaningful assertions and proper mock verification.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constitution.supreme_law import ConstitutionalViolationError
from kernel.sealed_gate import (
    BaseSealedGate,
    GateViolationError,
    SealedGate,
    UnitOfWorkProtocol,
    _FallbackUnitOfWork,
    get_sealed_gate,
)

# ============================================================================
# Tests for GateViolationError
# ============================================================================

class TestGateViolationError:
    def test_raise_and_catch(self):
        with pytest.raises(GateViolationError, match="test error"):
            raise GateViolationError("test error")

    def test_inheritance(self):
        assert issubclass(GateViolationError, Exception)


# ============================================================================
# Tests for BaseSealedGate (abstract)
# ============================================================================

class TestBaseSealedGate:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseSealedGate()


# ============================================================================
# Tests for _FallbackUnitOfWork
# ============================================================================

class TestFallbackUnitOfWork:
    @pytest.mark.asyncio
    async def test_begin(self):
        uow = _FallbackUnitOfWork()
        await uow.begin("READ_COMMITTED")
        # Ensure no state changed (no-op implementation)
        assert uow.transaction_id is None
        assert uow.command_id is None

    @pytest.mark.asyncio
    async def test_commit(self):
        uow = _FallbackUnitOfWork()
        await uow.commit()
        assert uow.transaction_id is None
        assert uow.command_id is None

    @pytest.mark.asyncio
    async def test_rollback(self):
        uow = _FallbackUnitOfWork()
        await uow.rollback()
        assert uow.transaction_id is None
        assert uow.command_id is None

    @pytest.mark.asyncio
    async def test_begin_read_only(self):
        uow = _FallbackUnitOfWork()
        await uow.begin_read_only()
        assert uow.transaction_id is None
        assert uow.command_id is None

    def test_attributes(self):
        uow = _FallbackUnitOfWork()
        assert uow.transaction_id is None
        assert uow.command_id is None


# ============================================================================
# Tests for UnitOfWorkProtocol (just ensure importable)
# ============================================================================

class TestUnitOfWorkProtocol:
    def test_protocol_defined(self):
        assert UnitOfWorkProtocol is not None


# ============================================================================
# Tests for SealedGate
# ============================================================================

class TestSealedGate:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        # Reset singleton before each test
        SealedGate._instance = None
        yield
        SealedGate._instance = None

    @pytest.fixture
    def gate(self):
        return SealedGate()

    @pytest.fixture
    def mock_dependencies(self):
        with patch("kernel.sealed_gate.get_validation_pipeline") as mock_vp, \
             patch("kernel.sealed_gate.get_transactional_executor") as mock_te, \
             patch("kernel.sealed_gate.get_circuit_breaker") as mock_cb, \
             patch("kernel.sealed_gate.get_audit_hook_injector") as mock_ah, \
             patch("kernel.sealed_gate.get_context_holder") as mock_ch, \
             patch("kernel.sealed_gate.get_metric_collector") as mock_mc, \
             patch("kernel.sealed_gate.get_enforcement_engine") as mock_ee, \
             patch("kernel.sealed_gate._get_uow") as mock_uow:

            mock_vp_instance = AsyncMock()
            mock_vp_instance.validate.return_value = MagicMock(
                overall_status=MagicMock(name="PASS"),
                rejection_reason=None,
            )
            mock_vp.return_value = mock_vp_instance

            mock_te_instance = AsyncMock()
            mock_te_instance.execute.return_value = MagicMock(
                status=MagicMock(name="SUCCESS"),
                result={"journal_id": "123"},
                error_message=None,
            )
            mock_te.return_value = mock_te_instance

            mock_cb_instance = MagicMock()
            mock_cb_instance.allow_request.return_value = True
            mock_cb_instance.record_failure = MagicMock()
            mock_cb_instance.record_success = MagicMock()
            mock_cb_instance.state = MagicMock()
            mock_cb_instance.state.value = "closed"
            mock_cb_instance.reset = MagicMock()
            mock_cb_instance.force_close = MagicMock()
            mock_cb_instance.force_open = MagicMock()
            mock_cb.return_value = mock_cb_instance

            mock_ah_instance = MagicMock()
            mock_ah_instance.before_execution = MagicMock()
            mock_ah_instance.after_execution = MagicMock()
            mock_ah_instance.on_error = MagicMock()
            mock_ah.return_value = mock_ah_instance

            mock_ch_instance = MagicMock()
            mock_ch_instance.set_context = MagicMock()
            mock_ch_instance.clear_context = MagicMock()
            mock_ch.return_value = mock_ch_instance

            mock_mc_instance = MagicMock()
            mock_mc_instance.increment_counter = MagicMock()
            mock_mc_instance.record_histogram = MagicMock()
            mock_mc.return_value = mock_mc_instance

            mock_ee_instance = MagicMock()
            mock_ee_instance.enforce.return_value = MagicMock(
                final_result=MagicMock(name="PASS"),
                rejection_reason=None,
            )
            mock_ee.return_value = mock_ee_instance

            mock_uow_instance = MagicMock()
            mock_uow_instance.begin = AsyncMock()
            mock_uow_instance.commit = AsyncMock()
            mock_uow_instance.rollback = AsyncMock()
            mock_uow.return_value = mock_uow_instance

            yield {
                "validation_pipeline": mock_vp_instance,
                "transactional_executor": mock_te_instance,
                "circuit_breaker": mock_cb_instance,
                "audit_hook": mock_ah_instance,
                "context_holder": mock_ch_instance,
                "metric_collector": mock_mc_instance,
                "enforcement_engine": mock_ee_instance,
                "uow": mock_uow_instance,
            }

    def test_singleton(self):
        g1 = SealedGate()
        g2 = SealedGate()
        assert g1 is g2

    def test_initialization(self, gate):
        assert gate._initialized is True
        assert isinstance(gate._command_handlers, dict)
        assert gate._command_history == []
        assert gate._max_history == 10000
        assert gate._idempotency_store == {}
        assert gate._version == 1
        assert gate._audit_trail == []
        assert gate._snapshots == []

    # ---- register_handler ----
    def test_register_handler(self, gate):
        def handler():
            pass

        gate.register_handler("TEST", handler)
        assert "TEST" in gate._command_handlers
        assert gate._command_handlers["TEST"] is handler
        assert gate._audit_trail[-1]["action"] == "REGISTER_HANDLER"

    # ---- Enforcement methods ----
    def test_enforce_allowed(self, gate):
        # Should not raise – assert that method returns None
        result = gate.enforce({"type": "POST_JOURNAL", "user": "admin"})
        assert result is None

    def test_enforce_allowed_other_command(self, gate):
        # Any other command should also not raise
        result = gate.enforce({"type": "OTHER"})
        assert result is None

    def test_enforce_mutation_always_raises(self, gate):
        with pytest.raises(GateViolationError, match="Cannot mutate immutable record"):
            gate.enforce_mutation({})

    def test_enforce_sensitive_action_with_2_approvals(self, gate):
        # Should not raise
        result = gate.enforce_sensitive_action({"approvals": ["approver1", "approver2"]})
        assert result is None

    def test_enforce_sensitive_action_less_than_2_approvals_raises(self, gate):
        with pytest.raises(GateViolationError, match="Sensitive action requires dual control"):
            gate.enforce_sensitive_action({"approvals": ["approver1"]})

        with pytest.raises(GateViolationError):
            gate.enforce_sensitive_action({"approvals": []})

    def test_enforce_sensitive_action_missing_approvals(self, gate):
        with pytest.raises(GateViolationError):
            gate.enforce_sensitive_action({})

    def test_enforce_write_off_with_attachments(self, gate):
        # Should not raise
        result = gate.enforce_write_off({"attachments": ["file1.pdf"]})
        assert result is None

    def test_enforce_write_off_no_attachments_raises(self, gate):
        with pytest.raises(GateViolationError, match="Write-off requires supporting evidence"):
            gate.enforce_write_off({})

    def test_enforce_period_change_valid(self, gate):
        # Should not raise when period >= current_period
        result = gate.enforce_period_change({"period": 5, "current_period": 3})
        assert result is None

    def test_enforce_period_change_retroactive_raises(self, gate):
        with pytest.raises(GateViolationError, match="Cannot change closed/retroactive period"):
            gate.enforce_period_change({"period": 2, "current_period": 3})

    def test_enforce_period_change_missing_fields(self, gate):
        # Should not raise because condition not met (period or current_period missing)
        result = gate.enforce_period_change({})
        assert result is None
        result = gate.enforce_period_change({"period": 2})
        assert result is None
        result = gate.enforce_period_change({"current_period": 3})
        assert result is None

    def test_set_hash_chain_verifier(self, gate):
        verifier = MagicMock()
        gate.set_hash_chain_verifier(verifier)
        assert gate._hash_chain_verifier is verifier

    def test_enforce_integrity_with_verifier_success(self, gate):
        verifier = MagicMock(return_value=True)
        gate.set_hash_chain_verifier(verifier)
        # Should not raise
        result = gate.enforce_integrity({"data": "test"})
        assert result is None
        verifier.assert_called_once_with({"data": "test"})

    def test_enforce_integrity_with_verifier_failure(self, gate):
        verifier = MagicMock(return_value=False)
        gate.set_hash_chain_verifier(verifier)
        with pytest.raises(GateViolationError, match="Hash chain verification failed"):
            gate.enforce_integrity({"data": "test"})

    def test_enforce_integrity_without_verifier(self, gate):
        # Should not raise
        result = gate.enforce_integrity({})
        assert result is None

    # ---- execute ----
    @pytest.mark.asyncio
    async def test_execute_circuit_breaker_open(self, gate, mock_dependencies):
        mock_dependencies["circuit_breaker"].allow_request.return_value = False

        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
            await gate.execute("TEST", {}, "user", MagicMock())

        # Check metrics
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_rejected_total", {"reason": "circuit_open"}
        )
        # Check envelope recorded with REJECTED
        assert gate._command_history[0].status.name == "REJECTED"
        assert gate._command_history[0].error == "Circuit breaker is open"
        # Ensure no other pipeline steps were called
        mock_dependencies["validation_pipeline"].validate.assert_not_called()
        mock_dependencies["enforcement_engine"].enforce.assert_not_called()
        mock_dependencies["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_idempotency_hit(self, gate, mock_dependencies):
        # Pre-populate idempotency store
        envelope = MagicMock()
        envelope.status = MagicMock(name="SUCCESS")
        envelope.result = {"cached": "result"}
        gate._idempotency_store["key123"] = envelope

        result_envelope = await gate.execute(
            "TEST", {}, "user", MagicMock(), idempotency_key="key123"
        )
        assert result_envelope is envelope
        # Ensure handler not called and validation not performed
        mock_dependencies["validation_pipeline"].validate.assert_not_called()
        mock_dependencies["enforcement_engine"].enforce.assert_not_called()
        mock_dependencies["transactional_executor"].execute.assert_not_called()
        # Idempotent hit metric
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_idempotent_hits_total", {"command_type": "TEST"}
        )

    @pytest.mark.asyncio
    async def test_execute_validation_fails(self, gate, mock_dependencies):
        mock_dependencies["validation_pipeline"].validate.return_value = MagicMock(
            overall_status=MagicMock(name="FAIL"),
            rejection_reason="Invalid data",
        )

        with pytest.raises(ValueError, match="Validation failed: Invalid data"):
            await gate.execute("TEST", {}, "user", MagicMock())

        # Check envelope rejected
        assert gate._command_history[0].status.name == "REJECTED"
        assert gate._command_history[0].error == "Invalid data"
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_rejected_total", {"reason": "validation_failed"}
        )
        # Ensure enforcement and execution not called
        mock_dependencies["enforcement_engine"].enforce.assert_not_called()
        mock_dependencies["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_enforcement_fails(self, gate, mock_dependencies):
        mock_dependencies["enforcement_engine"].enforce.return_value = MagicMock(
            final_result=MagicMock(name="FAIL"),
            rejection_reason="Constitutional violation",
        )

        with pytest.raises(ConstitutionalViolationError):
            await gate.execute("TEST", {}, "user", MagicMock())

        assert gate._command_history[0].status.name == "REJECTED"
        assert gate._command_history[0].error == "Constitutional violation"
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_rejected_total", {"reason": "enforcement_failed"}
        )
        # Ensure transactional executor not called
        mock_dependencies["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_handler_not_found(self, gate, mock_dependencies):
        with pytest.raises(ValueError, match="No handler for TEST"):
            await gate.execute("TEST", {}, "user", MagicMock())

        assert gate._command_history[0].status.name == "REJECTED"
        assert gate._command_history[0].error == "No handler registered for command type: TEST"
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_rejected_total", {"reason": "handler_not_found"}
        )
        # Ensure transactional executor not called
        mock_dependencies["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_success(self, gate, mock_dependencies):
        # Register a handler
        async def handler(command_data, ctx, uow):
            return {"result": "success"}

        gate.register_handler("TEST", handler)

        envelope = await gate.execute("TEST", {"foo": "bar"}, "user", MagicMock())

        assert envelope.status.name == "SUCCESS"
        assert envelope.result == {"result": "success"}
        assert envelope.execution_time_ms > 0

        # Verify transactional executor was called
        mock_dependencies["transactional_executor"].execute.assert_called_once()
        # Verify audit hooks
        mock_dependencies["audit_hook"].before_execution.assert_called_once()
        mock_dependencies["audit_hook"].after_execution.assert_called_once()
        # Verify context holder
        mock_dependencies["context_holder"].set_context.assert_called_once()
        mock_dependencies["context_holder"].clear_context.assert_called_once()
        # Verify metrics
        mock_dependencies["metric_collector"].record_histogram.assert_called_once()
        mock_dependencies["metric_collector"].increment_counter.assert_any_call(
            "gate_requests_total", {"command_type": "TEST"}
        )
        mock_dependencies["metric_collector"].increment_counter.assert_any_call(
            "gate_success_total", {"command_type": "TEST"}
        )
        # Verify circuit breaker success
        mock_dependencies["circuit_breaker"].record_success.assert_called_once()

        # No idempotency store entry without key
        assert "idempotency_key" not in gate._idempotency_store

    @pytest.mark.asyncio
    async def test_execute_success_with_idempotency(self, gate, mock_dependencies):
        async def handler(command_data, ctx, uow):
            return {"result": "success"}

        gate.register_handler("TEST", handler)

        envelope = await gate.execute(
            "TEST", {}, "user", MagicMock(), idempotency_key="key456"
        )
        assert envelope.status.name == "SUCCESS"
        assert "key456" in gate._idempotency_store
        # Ensure idempotency store contains the envelope
        assert gate._idempotency_store["key456"] is envelope

        # Second call with same key should hit cache
        mock_dependencies["transactional_executor"].execute.reset_mock()
        envelope2 = await gate.execute(
            "TEST", {}, "user", MagicMock(), idempotency_key="key456"
        )
        assert envelope2 is envelope
        mock_dependencies["transactional_executor"].execute.assert_not_called()
        # Idempotent hit metric incremented again
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_idempotent_hits_total", {"command_type": "TEST"}
        )

    @pytest.mark.asyncio
    async def test_execute_sync_handler(self, gate, mock_dependencies):
        # Register a sync handler
        def handler(command_data, ctx, uow):
            return {"result": "sync"}

        gate.register_handler("TEST", handler)

        envelope = await gate.execute("TEST", {}, "user", MagicMock())
        assert envelope.status.name == "SUCCESS"
        assert envelope.result == {"result": "sync"}
        # Verify transactional executor still called (it wraps sync handler)
        mock_dependencies["transactional_executor"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_handler_raises_error(self, gate, mock_dependencies):
        async def handler(command_data, ctx, uow):
            raise ValueError("Handler error")

        gate.register_handler("TEST", handler)

        with pytest.raises(ValueError, match="Handler error"):
            await gate.execute("TEST", {}, "user", MagicMock())

        # Check envelope status FAILED
        assert gate._command_history[0].status.name == "FAILED"
        assert gate._command_history[0].error == "Handler error"
        # Verify circuit breaker failure
        mock_dependencies["circuit_breaker"].record_failure.assert_called_once()
        # Verify metrics failure
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_failure_total", {"command_type": "TEST"}
        )
        # Verify audit error hook
        mock_dependencies["audit_hook"].on_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_transactional_executor_failure(self, gate, mock_dependencies):
        async def handler(command_data, ctx, uow):
            return {"ok": True}

        gate.register_handler("TEST", handler)

        mock_dependencies["transactional_executor"].execute.return_value = MagicMock(
            status=MagicMock(name="FAILED"),
            result=None,
            error_message="DB error",
        )

        with pytest.raises(RuntimeError):
            await gate.execute("TEST", {}, "user", MagicMock())

        assert gate._command_history[0].status.name == "FAILED"
        assert gate._command_history[0].error == "DB error"
        mock_dependencies["circuit_breaker"].record_failure.assert_called_once()
        mock_dependencies["metric_collector"].increment_counter.assert_called_with(
            "gate_failure_total", {"command_type": "TEST"}
        )

    # ---- get_command_history ----
    def test_get_command_history(self, gate):
        # Add some fake commands
        for _i in range(5):
            env = MagicMock()
            env.command_type = "TEST"
            env.status = MagicMock(name="SUCCESS")
            env.execution_time_ms = 10.0
            gate._command_history.append(env)

        # Add one different
        env2 = MagicMock()
        env2.command_type = "OTHER"
        env2.status = MagicMock(name="FAILED")
        gate._command_history.append(env2)

        # All
        result = gate.get_command_history(limit=10)
        assert len(result) == 6

        # Filter by type
        result2 = gate.get_command_history(command_type="TEST")
        assert len(result2) == 5

        # Filter by status
        result3 = gate.get_command_history(status=MagicMock(name="FAILED"))
        assert len(result3) == 1
        assert result3[0].command_type == "OTHER"

    # ---- get_status ----
    def test_get_status(self, gate):
        gate._command_handlers["H1"] = lambda: None
        gate._command_handlers["H2"] = lambda: None
        gate._idempotency_store["key"] = MagicMock()

        status = gate.get_status()
        assert status["circuit_breaker_state"] == gate._circuit_breaker.state.value
        assert set(status["registered_handlers"]) == {"H1", "H2"}
        assert status["total_commands_executed"] == len(gate._command_history)
        assert status["idempotency_cache_size"] == 1
        assert status["version"] == 1

    # ---- get_statistics ----
    def test_get_statistics_empty(self, gate):
        stats = gate.get_statistics()
        assert stats["total_commands"] == 0
        assert stats["version"] == 1

    def test_get_statistics_with_data(self, gate):
        # Add fake commands
        for i in range(10):
            env = MagicMock()
            env.status = MagicMock(name="SUCCESS" if i % 2 == 0 else "FAILED")
            env.execution_time_ms = 5.0 * i
            gate._command_history.append(env)

        # Add some handlers
        gate._command_handlers["H1"] = lambda: None
        gate._command_handlers["H2"] = lambda: None

        stats = gate.get_statistics()
        assert stats["total_commands"] == 10
        assert stats["by_status"]["SUCCESS"] == 5
        assert stats["by_status"]["FAILED"] == 5
        assert stats["avg_execution_time_ms"] == sum(5.0 * i for i in range(10)) / 10
        assert stats["registered_handlers"] == 2

    # ---- reset ----
    def test_reset(self, gate):
        gate._command_history = [MagicMock()]
        gate._idempotency_store["key"] = MagicMock()
        gate._version = 2
        gate._audit_trail = [{"action": "test"}]
        gate._snapshots = [{"s": 1}]

        gate.reset()
        assert gate._command_history == []
        assert gate._idempotency_store == {}
        assert gate._version == 3  # incremented
        assert gate._audit_trail == []
        assert gate._snapshots == []
        # Circuit breaker reset called
        gate._circuit_breaker.reset.assert_called_once()

    # ---- force_close_circuit / force_open_circuit ----
    def test_force_close_circuit(self, gate):
        gate.force_close_circuit()
        gate._circuit_breaker.force_close.assert_called_once()
        assert gate._audit_trail[-1]["action"] == "FORCE_CLOSE_CIRCUIT"

    def test_force_open_circuit(self, gate):
        gate.force_open_circuit()
        gate._circuit_breaker.force_open.assert_called_once()
        assert gate._audit_trail[-1]["action"] == "FORCE_OPEN_CIRCUIT"

    # ---- Entity methods ----
    def test_validate_valid(self, gate):
        # With no handlers, validate returns error "No command handlers registered"
        result = gate.validate()
        assert result["is_valid"] is False
        assert "No command handlers registered" in result["errors"]

        # Register a handler
        gate.register_handler("TEST", lambda: None)
        result2 = gate.validate()
        assert result2["is_valid"] is True
        assert result2["errors"] == []

        # Make max_history invalid
        gate._max_history = -1
        result3 = gate.validate()
        assert result3["is_valid"] is False
        assert "max_history must be positive" in result3["errors"]

    def test_to_dict(self, gate):
        gate._command_handlers["H1"] = lambda: None
        gate._command_history = [MagicMock() for _ in range(3)]
        gate._idempotency_store["k"] = MagicMock()

        d = gate.to_dict()
        assert d["circuit_breaker_state"] == gate._circuit_breaker.state.value
        assert d["registered_handlers"] == ["H1"]
        assert d["total_commands_executed"] == 3
        assert d["idempotency_cache_size"] == 1
        assert d["max_history"] == 10000
        assert d["version"] == 1

    def test_from_dict(self):
        data = {"max_history": 5000, "version": 3}
        gate = SealedGate.from_dict(data)
        assert gate._max_history == 5000
        assert gate._version == 3

    def test_clone(self, gate):
        gate._max_history = 7000
        gate._version = 2
        cloned = gate.clone()
        assert cloned is not gate
        assert cloned._max_history == gate._max_history
        assert cloned._version == gate._version + 1

    def test_snapshot(self, gate):
        gate._command_history = [MagicMock() for _ in range(5)]
        gate._command_handlers["H1"] = lambda: None
        snap = gate.snapshot()
        assert snap["version"] == 1
        assert snap["circuit_breaker_state"] == gate._circuit_breaker.state.value
        assert snap["total_commands_executed"] == 5
        assert snap["registered_handlers_count"] == 1
        assert "timestamp" in snap

    def test_version(self, gate):
        assert gate.version() == 1
        gate._version = 4
        assert gate.version() == 4

    def test_audit_trail(self, gate):
        gate._record_audit("ACTION1", "user", {"k": "v"})
        gate._record_audit("ACTION2", "user", {"k2": "v2"})
        trail = gate.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION2"
        trail_all = gate.audit_trail(limit=10)
        assert len(trail_all) == 2

    def test_touch(self, gate):
        old_ver = gate._version
        gate.touch("admin")
        assert gate._version == old_ver + 1
        assert gate._audit_trail[-1]["action"] == "TOUCH"

    # ---- _record_history private method ----
    def test_record_history(self, gate):
        env = MagicMock()
        gate._record_history(env)
        assert gate._command_history[-1] is env
        # Test trimming when exceeds max_history
        gate._max_history = 2
        for _i in range(5):
            gate._record_history(MagicMock())
        assert len(gate._command_history) == 2


# ============================================================================
# Tests for get_sealed_gate singleton
# ============================================================================

def test_get_sealed_gate():
    SealedGate._instance = None
    g1 = get_sealed_gate()
    g2 = get_sealed_gate()
    assert g1 is g2
    assert isinstance(g1, SealedGate)
