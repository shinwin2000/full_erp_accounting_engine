# tests/kernel/test_sealed_gate.py
"""
Comprehensive tests for kernel/sealed_gate.py
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constitution.enforcement_engine import EnforcementResult
from constitution.supreme_law import ConstitutionalViolationError
from kernel.command_envelope import CommandEnvelope, CommandStatus
from kernel.sealed_gate import (
    BaseSealedGate,
    GateViolationError,
    SealedGate,
    UnitOfWorkProtocol,
    _FallbackUnitOfWork,
    get_sealed_gate,
)
from kernel.transactional_executor import ExecutionStatus
from kernel.validation_pipeline import ValidationStatus


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
        SealedGate._instance = None
        yield
        SealedGate._instance = None

    @pytest.fixture
    def gate(self):
        return SealedGate()

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
        result = gate.enforce({"type": "POST_JOURNAL", "user": "admin"})
        assert result is None

    def test_enforce_allowed_other_command(self, gate):
        result = gate.enforce({"type": "OTHER"})
        assert result is None

    def test_enforce_mutation_always_raises(self, gate):
        with pytest.raises(GateViolationError, match="Cannot mutate immutable record"):
            gate.enforce_mutation({})

    def test_enforce_sensitive_action_with_2_approvals(self, gate):
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
        result = gate.enforce_write_off({"attachments": ["file1.pdf"]})
        assert result is None

    def test_enforce_write_off_no_attachments_raises(self, gate):
        with pytest.raises(GateViolationError, match="Write-off requires supporting evidence"):
            gate.enforce_write_off({})

    def test_enforce_period_change_valid(self, gate):
        result = gate.enforce_period_change({"period": 5, "current_period": 3})
        assert result is None

    def test_enforce_period_change_retroactive_raises(self, gate):
        with pytest.raises(GateViolationError, match="Cannot change closed/retroactive period"):
            gate.enforce_period_change({"period": 2, "current_period": 3})

    def test_enforce_period_change_missing_fields(self, gate):
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
        result = gate.enforce_integrity({"data": "test"})
        assert result is None
        verifier.assert_called_once_with({"data": "test"})

    def test_enforce_integrity_with_verifier_failure(self, gate):
        verifier = MagicMock(return_value=False)
        gate.set_hash_chain_verifier(verifier)
        with pytest.raises(GateViolationError, match="Hash chain verification failed"):
            gate.enforce_integrity({"data": "test"})

    def test_enforce_integrity_without_verifier(self, gate):
        result = gate.enforce_integrity({})
        assert result is None

    # ---- Test execute with mocked dependencies ----
    @pytest.fixture
    def gate_with_mocks(self):
        with patch("kernel.sealed_gate.get_validation_pipeline") as mock_vp, \
             patch("kernel.sealed_gate.get_transactional_executor") as mock_te, \
             patch("kernel.sealed_gate.get_circuit_breaker") as mock_cb, \
             patch("kernel.sealed_gate.get_audit_hook_injector") as mock_ah, \
             patch("kernel.sealed_gate.get_context_holder") as mock_ch, \
             patch("kernel.sealed_gate.get_metric_collector") as mock_mc, \
             patch("kernel.sealed_gate.get_enforcement_engine") as mock_ee, \
             patch("kernel.sealed_gate._get_uow") as mock_uow, \
             patch("kernel.sealed_gate.time") as mock_time:

            # Mock time.time untuk memastikan execution_time_ms > 0
            mock_time.time.side_effect = [1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0, 1006.0, 1007.0, 1008.0, 1009.0]

            # Mock circuit breaker
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

            # Mock validation pipeline
            mock_vp_instance = AsyncMock()
            mock_vp_instance.validate.return_value = MagicMock(
                overall_status=ValidationStatus.PASS,
                rejection_reason=None,
            )
            mock_vp.return_value = mock_vp_instance

            # Mock transactional executor - default akan memanggil callback dan return SUCCESS
            mock_te_instance = AsyncMock()

            async def execute_side_effect(uow_callback, command_id=None, idempotency_key=None, **kwargs):
                # Buat uow dummy
                uow = MagicMock(spec=UnitOfWorkProtocol)
                try:
                    if asyncio.iscoroutinefunction(uow_callback):
                        result = await uow_callback(uow)
                    else:
                        result = uow_callback(uow)
                    return MagicMock(status=ExecutionStatus.SUCCESS, result=result, error_message=None)
                except Exception as e:
                    return MagicMock(status=ExecutionStatus.FAILED, result=None, error_message=str(e))

            mock_te_instance.execute.side_effect = execute_side_effect
            mock_te.return_value = mock_te_instance

            # Mock audit hook
            mock_ah_instance = MagicMock()
            mock_ah.return_value = mock_ah_instance

            # Mock context holder
            mock_ch_instance = MagicMock()
            mock_ch.return_value = mock_ch_instance

            # Mock metric collector
            mock_mc_instance = MagicMock()
            mock_mc.return_value = mock_mc_instance

            # Mock enforcement engine
            mock_ee_instance = MagicMock()
            mock_ee_instance.enforce.return_value = MagicMock(
                final_result=EnforcementResult.PASS,
                rejection_reason=None,
            )
            mock_ee.return_value = mock_ee_instance

            # Mock UOW
            mock_uow_instance = MagicMock()
            mock_uow.return_value = mock_uow_instance

            # Create gate dan set internal attributes dengan mock kita
            gate = SealedGate()
            gate._circuit_breaker = mock_cb_instance
            gate._validation_pipeline = mock_vp_instance
            gate._transactional_executor = mock_te_instance
            gate._audit_hook = mock_ah_instance
            gate._context_holder = mock_ch_instance
            gate._metric_collector = mock_mc_instance
            gate._enforcement_engine = mock_ee_instance
            gate._uow = mock_uow_instance

            yield {
                "gate": gate,
                "circuit_breaker": mock_cb_instance,
                "validation_pipeline": mock_vp_instance,
                "transactional_executor": mock_te_instance,
                "audit_hook": mock_ah_instance,
                "context_holder": mock_ch_instance,
                "metric_collector": mock_mc_instance,
                "enforcement_engine": mock_ee_instance,
                "uow": mock_uow_instance,
                "time": mock_time,
            }

    @pytest.mark.asyncio
    async def test_execute_circuit_breaker_open(self, gate_with_mocks):
        mocks = gate_with_mocks
        mocks["circuit_breaker"].allow_request.return_value = False

        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
            await mocks["gate"].execute("TEST", {}, "user", MagicMock())

        mocks["metric_collector"].increment_counter.assert_called_with(
            "gate_rejected_total", {"reason": "circuit_open"}
        )
        assert mocks["gate"]._command_history[0].status == CommandStatus.REJECTED
        assert mocks["gate"]._command_history[0].error == "Circuit breaker is open"
        mocks["validation_pipeline"].validate.assert_not_called()
        mocks["enforcement_engine"].enforce.assert_not_called()
        mocks["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_idempotency_hit(self, gate_with_mocks):
        mocks = gate_with_mocks
        gate = mocks["gate"]

        existing = CommandEnvelope.create(
            command_type="TEST",
            command_data={},
            user_id="user",
            legal_entity_id=MagicMock(),
        )
        existing.status = CommandStatus.SUCCESS
        existing.result = {"cached": "result"}
        gate._idempotency_store["key123"] = existing

        result_envelope = await gate.execute(
            "TEST", {}, "user", MagicMock(), idempotency_key="key123"
        )
        assert result_envelope.result == {"cached": "result"}
        assert result_envelope.status == CommandStatus.SUCCESS
        mocks["metric_collector"].increment_counter.assert_any_call(
            "gate_idempotent_hits_total", {"command_type": "TEST"}
        )
        mocks["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_validation_fails(self, gate_with_mocks):
        mocks = gate_with_mocks
        mocks["validation_pipeline"].validate.return_value = MagicMock(
            overall_status=ValidationStatus.FAIL,
            rejection_reason="Invalid data",
        )

        async def handler(*args):
            return {"ok": True}
        mocks["gate"].register_handler("TEST", handler)

        with pytest.raises(ValueError, match="Validation failed: Invalid data"):
            await mocks["gate"].execute("TEST", {}, "user", MagicMock())

        assert mocks["gate"]._command_history[0].status == CommandStatus.FAILED
        assert mocks["gate"]._command_history[0].error == "Validation failed: Invalid data"
        mocks["metric_collector"].increment_counter.assert_any_call(
            "gate_rejected_total", {"reason": "validation_failed"}
        )
        mocks["enforcement_engine"].enforce.assert_not_called()
        mocks["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_enforcement_fails(self, gate_with_mocks):
        mocks = gate_with_mocks
        mocks["enforcement_engine"].enforce.return_value = MagicMock(
            final_result=EnforcementResult.REJECTED,
            rejection_reason="Constitutional violation",
        )

        async def handler(*args):
            return {"ok": True}
        mocks["gate"].register_handler("TEST", handler)

        with pytest.raises(ConstitutionalViolationError):
            await mocks["gate"].execute("TEST", {}, "user", MagicMock())

        assert mocks["gate"]._command_history[0].status == CommandStatus.REJECTED
        assert "Constitutional violation" in mocks["gate"]._command_history[0].error
        mocks["metric_collector"].increment_counter.assert_any_call(
            "gate_rejected_total", {"reason": "enforcement_failed"}
        )
        mocks["transactional_executor"].execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_handler_not_found(self, gate_with_mocks):
        mocks = gate_with_mocks

        with pytest.raises(ValueError, match="No handler for TEST"):
            await mocks["gate"].execute("TEST", {}, "user", MagicMock())

        assert mocks["gate"]._command_history[0].status == CommandStatus.FAILED
        assert mocks["gate"]._command_history[0].error == "No handler for TEST"
        mocks["metric_collector"].increment_counter.assert_called_with(
            "gate_failure_total", {"command_type": "TEST"}
        )

    @pytest.mark.asyncio
    async def test_execute_success(self, gate_with_mocks):
        mocks = gate_with_mocks

        async def handler(command_data, ctx, uow):
            return {"result": "success"}
        mocks["gate"].register_handler("TEST", handler)

        envelope = await mocks["gate"].execute("TEST", {"foo": "bar"}, "user", MagicMock())

        assert envelope.status == CommandStatus.SUCCESS
        assert envelope.result == {"result": "success"}
        assert envelope.execution_time_ms > 0

        mocks["transactional_executor"].execute.assert_called_once()
        mocks["audit_hook"].before_execution.assert_called_once()
        mocks["audit_hook"].after_execution.assert_called_once()
        mocks["context_holder"].set_context.assert_called_once()
        mocks["context_holder"].clear_context.assert_called_once()
        mocks["metric_collector"].record_histogram.assert_called_once()
        mocks["metric_collector"].increment_counter.assert_any_call(
            "gate_requests_total", {"command_type": "TEST"}
        )
        mocks["metric_collector"].increment_counter.assert_any_call(
            "gate_success_total", {"command_type": "TEST"}
        )
        mocks["circuit_breaker"].record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_success_with_idempotency(self, gate_with_mocks):
        mocks = gate_with_mocks

        async def handler(command_data, ctx, uow):
            return {"result": "success"}
        mocks["gate"].register_handler("TEST", handler)

        envelope = await mocks["gate"].execute(
            "TEST", {}, "user", MagicMock(), idempotency_key="key456"
        )
        assert envelope.status == CommandStatus.SUCCESS
        assert "key456" in mocks["gate"]._idempotency_store
        # Karena idempotensi, envelope yang disimpan adalah yang dikembalikan
        # Setiap panggilan execute akan menghasilkan envelope baru (karena CommandEnvelope.create),
        # tapi result di-copy. Jadi kita tidak bisa assert is, tapi kita assert key ada dan result sama.
        mocks["transactional_executor"].execute.reset_mock()
        envelope2 = await mocks["gate"].execute(
            "TEST", {}, "user", MagicMock(), idempotency_key="key456"
        )
        # Karena idempotency hit, execute tidak dipanggil, dan result di-copy dari yang disimpan
        assert envelope2.result == envelope.result
        assert envelope2.status == envelope.status
        assert envelope2.idempotency_key == envelope.idempotency_key
        mocks["transactional_executor"].execute.assert_not_called()
        mocks["metric_collector"].increment_counter.assert_any_call(
            "gate_idempotent_hits_total", {"command_type": "TEST"}
        )

    @pytest.mark.asyncio
    async def test_execute_sync_handler(self, gate_with_mocks):
        mocks = gate_with_mocks

        def handler(command_data, ctx, uow):
            return {"result": "sync"}
        mocks["gate"].register_handler("TEST", handler)

        envelope = await mocks["gate"].execute("TEST", {}, "user", MagicMock())
        assert envelope.status == CommandStatus.SUCCESS
        assert envelope.result == {"result": "sync"}
        mocks["transactional_executor"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_handler_raises_error(self, gate_with_mocks):
        mocks = gate_with_mocks

        # side_effect default sudah menangani exception dan return FAILED
        async def handler(command_data, ctx, uow):
            raise ValueError("Handler error")
        mocks["gate"].register_handler("TEST", handler)

        envelope = await mocks["gate"].execute("TEST", {}, "user", MagicMock())
        assert envelope.status == CommandStatus.FAILED
        assert envelope.error == "Handler error"
        mocks["circuit_breaker"].record_failure.assert_called_once()
        mocks["metric_collector"].increment_counter.assert_called_with(
            "gate_failure_total", {"command_type": "TEST"}
        )
        mocks["audit_hook"].on_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_transactional_executor_failure(self, gate_with_mocks):
        mocks = gate_with_mocks
        # Hapus side_effect agar return_value bisa digunakan
        mocks["transactional_executor"].execute.side_effect = None
        mocks["transactional_executor"].execute.return_value = MagicMock(
            status=ExecutionStatus.FAILED,
            result=None,
            error_message="DB error",
        )

        async def handler(command_data, ctx, uow):
            return {"ok": True}
        mocks["gate"].register_handler("TEST", handler)

        envelope = await mocks["gate"].execute("TEST", {}, "user", MagicMock())
        assert envelope.status == CommandStatus.FAILED
        assert envelope.error == "DB error"
        mocks["circuit_breaker"].record_failure.assert_called_once()
        mocks["metric_collector"].increment_counter.assert_called_with(
            "gate_failure_total", {"command_type": "TEST"}
        )

    # ---- get_command_history ----
    def test_get_command_history(self, gate):
        for _i in range(5):
            env = CommandEnvelope.create("TEST", {}, "user", MagicMock())
            env.status = CommandStatus.SUCCESS
            env.execution_time_ms = 10.0
            gate._command_history.append(env)

        env2 = CommandEnvelope.create("OTHER", {}, "user", MagicMock())
        env2.status = CommandStatus.FAILED
        gate._command_history.append(env2)

        result = gate.get_command_history(limit=10)
        assert len(result) == 6

        result2 = gate.get_command_history(command_type="TEST")
        assert len(result2) == 5

        result3 = gate.get_command_history(status=CommandStatus.FAILED)
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
        for i in range(10):
            env = CommandEnvelope.create("TEST", {}, "user", MagicMock())
            env.status = CommandStatus.SUCCESS if i % 2 == 0 else CommandStatus.FAILED
            env.execution_time_ms = 5.0 * i
            gate._command_history.append(env)

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
        with patch.object(gate, '_circuit_breaker') as mock_cb:
            gate.reset()
            mock_cb.reset.assert_called_once()
            assert gate._command_history == []
            assert gate._idempotency_store == {}
            assert gate._version == 2  # initial 1 + 1
            assert len(gate._audit_trail) == 1
            assert gate._audit_trail[0]["action"] == "RESET"

    # ---- force_close_circuit / force_open_circuit ----
    def test_force_close_circuit(self, gate):
        with patch.object(gate, '_circuit_breaker') as mock_cb:
            gate.force_close_circuit()
            mock_cb.force_close.assert_called_once()
            assert gate._audit_trail[-1]["action"] == "FORCE_CLOSE_CIRCUIT"

    def test_force_open_circuit(self, gate):
        with patch.object(gate, '_circuit_breaker') as mock_cb:
            gate.force_open_circuit()
            mock_cb.force_open.assert_called_once()
            assert gate._audit_trail[-1]["action"] == "FORCE_OPEN_CIRCUIT"

    # ---- Entity methods ----
    def test_validate_valid(self, gate):
        result = gate.validate()
        assert result["is_valid"] is False
        assert "No command handlers registered" in result["errors"]

        gate.register_handler("TEST", lambda: None)
        result2 = gate.validate()
        assert result2["is_valid"] is True
        assert result2["errors"] == []

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
        env = CommandEnvelope.create("TEST", {}, "user", MagicMock())
        gate._record_history(env)
        assert gate._command_history[-1] is env

        gate._max_history = 2
        for _i in range(5):
            gate._record_history(CommandEnvelope.create("TEST", {}, "user", MagicMock()))
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
