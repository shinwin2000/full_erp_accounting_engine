# test_audit_hook_injector.py
# Comprehensive tests for kernel/audit_hook_injector.py

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kernel.audit_hook_injector import (
    AuditContext,
    AuditEventType,
    AuditHookInjector,
    AuditSeverity,
    BaseAuditHookInjector,
    _FallbackAuditEvent,
    _FallbackEventStore,
    _get_digital_signer,
    _get_event_store,
    audit,
    get_audit_hook_injector,
)
from kernel.command_envelope import CommandEnvelope


# -------------------- Fixtures --------------------
@pytest.fixture
def mock_event_store():
    with patch("kernel.audit_hook_injector._get_event_store") as mock:
        store = AsyncMock(spec=_FallbackEventStore)
        mock.return_value = store
        yield store


@pytest.fixture
def mock_signer():
    with patch("kernel.audit_hook_injector._get_digital_signer") as mock:
        signer = MagicMock()
        signer.sign.return_value = "signature"
        mock.return_value = signer
        yield signer


@pytest.fixture
def envelope():
    # CommandEnvelope expects positional arguments in this order:
    # command_id, command_data, command_type, user_id, legal_entity_id,
    # correlation_id, causation_id, idempotency_key, timestamp, execution_time_ms
    return CommandEnvelope(
        uuid4(),  # command_id
        {"foo": "bar"},  # command_data
        "TestCommand",  # command_type
        "test_user",  # user_id
        uuid4(),  # legal_entity_id
        "corr-123",  # correlation_id
        uuid4(),  # causation_id
        "idempotent",  # idempotency_key
        datetime.now(UTC),  # timestamp
        0,  # execution_time_ms
    )


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton before and after each test."""
    AuditHookInjector._instance = None
    yield
    AuditHookInjector._instance = None


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_audit_event_type(self):
        assert AuditEventType.COMMAND_RECEIVED.name == "COMMAND_RECEIVED"
        assert AuditEventType.COMMAND_SUCCESS.name == "COMMAND_SUCCESS"
        assert AuditEventType.COMMAND_FAILURE.name == "COMMAND_FAILURE"

    def test_audit_severity(self):
        assert AuditSeverity.DEBUG.value == 0
        assert AuditSeverity.INFO.value == 10
        assert AuditSeverity.WARNING.value == 20
        assert AuditSeverity.ERROR.value == 30
        assert AuditSeverity.CRITICAL.value == 40
        assert AuditSeverity.ALERT.value == 50


# -------------------- Tests for Fallback Classes --------------------
class TestFallbackClasses:
    def test_fallback_audit_event(self):
        event = _FallbackAuditEvent(
            event_id=uuid4(),
            aggregate_id=uuid4(),
            event_type="test",
            version=1,
            data={"key": "value"},
            metadata={"meta": "data"},
            user_id="user",
            timestamp=datetime.now(UTC),
        )
        assert event.signature is None
        hash_val = event.compute_hash()
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64

    def test_fallback_event_store(self):
        store = _FallbackEventStore()
        event = _FallbackAuditEvent(
            event_id=uuid4(),
            aggregate_id=uuid4(),
            event_type="test",
            version=1,
            data={},
            metadata={},
            user_id="user",
            timestamp=datetime.now(UTC),
        )
        asyncio.run(store.append(event))
        events = asyncio.run(store.get_events(limit=10))
        assert len(events) == 1
        assert events[0] is event

    def test_get_event_store(self):
        store = _get_event_store()
        assert isinstance(store, _FallbackEventStore)

    def test_get_digital_signer(self):
        signer = _get_digital_signer()
        sig = signer.sign("test")
        assert sig.startswith("sig_")


# -------------------- Tests for AuditContext --------------------
class TestAuditContext:
    def test_construction(self, envelope):
        context = AuditContext(
            command_id=envelope.command_id,
            command_type=envelope.command_type,
            user_id=envelope.user_id,
            legal_entity_id=envelope.legal_entity_id,
            correlation_id=envelope.correlation_id,
            timestamp=envelope.timestamp,
        )
        assert context.command_id == envelope.command_id
        assert context.events == []


# -------------------- Tests for BaseAuditHookInjector --------------------
class TestBaseAuditHookInjector:
    def test_abstract_methods(self):
        # Concrete implementation that overrides all abstract methods including reset
        class ConcreteInjector(BaseAuditHookInjector):
            def start_context(self, envelope):
                return MagicMock(spec=AuditContext)

            def before_execution(self, envelope):
                pass

            def after_execution(self, envelope, result):
                pass

            def on_error(self, envelope, error):
                pass

            async def flush_all(self):
                pass

            async def shutdown(self):
                pass

            def reset(self):
                pass

        injector = ConcreteInjector()
        assert injector.validate() == {"is_valid": True, "errors": []}
        assert injector.to_dict() == {}
        new_inj = injector.from_dict({})
        assert isinstance(new_inj, ConcreteInjector)
        assert injector.clone() is injector
        assert injector.snapshot() == {}
        assert injector.version() == 1
        assert injector.audit_trail() == []
        assert injector.touch("user") is injector
        assert injector.get_statistics() == {}
        injector.reset()


# -------------------- Tests for AuditHookInjector --------------------
class TestAuditHookInjector:
    def test_singleton(self):
        i1 = AuditHookInjector()
        i2 = AuditHookInjector()
        assert i1 is i2

    def test_initialization(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        assert injector._initialized is True
        assert injector._event_store == mock_event_store
        assert injector._digital_signer == mock_signer
        assert injector._active_contexts == {}
        assert injector._async_queue.qsize() == 0
        assert injector._worker_task is None
        assert injector._shutting_down is False
        assert injector._version == 1

    @pytest.mark.asyncio
    async def test_ensure_worker_with_loop(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        injector._ensure_worker()
        assert injector._worker_task is not None
        assert not injector._worker_task.done()
        old_task = injector._worker_task
        injector._ensure_worker()
        assert injector._worker_task is old_task
        injector._worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await injector._worker_task

    def test_ensure_worker_no_loop(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        injector._ensure_worker()
        assert injector._worker_task is None

    @pytest.mark.asyncio
    async def test_start_context(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        assert context.command_id == envelope.command_id
        assert len(context.events) == 1
        assert context.events[0]["event_type"] == AuditEventType.COMMAND_RECEIVED.name
        assert injector._active_contexts[envelope.command_id] is context
        assert injector._worker_task is not None

    @pytest.mark.asyncio
    async def test_before_execution(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        injector.before_execution(envelope)
        assert len(context.events) == 2
        assert context.events[1]["event_type"] == AuditEventType.COMMAND_EXECUTION_START.name
        new_envelope = envelope
        new_envelope.command_id = uuid4()
        injector.before_execution(new_envelope)
        assert new_envelope.command_id in injector._active_contexts
        new_context = injector._active_contexts[new_envelope.command_id]
        assert len(new_context.events) == 2

    @pytest.mark.asyncio
    async def test_after_execution(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        injector.before_execution(envelope)
        result = {"status": "ok"}
        envelope.execution_time_ms = 123
        injector.after_execution(envelope, result)
        assert envelope.command_id not in injector._active_contexts
        assert injector._async_queue.qsize() == 1
        queued_context = injector._async_queue.get_nowait()
        assert queued_context is context
        assert context.events[-2]["event_type"] == AuditEventType.COMMAND_EXECUTION_END.name
        assert context.events[-1]["event_type"] == AuditEventType.COMMAND_SUCCESS.name

    @pytest.mark.asyncio
    async def test_after_execution_context_missing(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        injector.after_execution(envelope, "result")
        assert injector._async_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_on_error(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        error = ValueError("test error")
        envelope.execution_time_ms = 456
        injector.on_error(envelope, error)
        assert envelope.command_id not in injector._active_contexts
        assert injector._async_queue.qsize() == 1
        queued_context = injector._async_queue.get_nowait()
        assert queued_context is context
        assert context.events[-1]["event_type"] == AuditEventType.COMMAND_FAILURE.name
        assert context.events[-1]["data"]["error_message"] == "test error"

    @pytest.mark.asyncio
    async def test_on_error_context_missing(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        injector.on_error(envelope, Exception("bad"))
        assert injector._async_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_record_state_before(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        agg_id = uuid4()
        state = {"field": "value"}
        injector.record_state_before(envelope.command_id, agg_id, "Aggregate", state)
        assert len(context.events) == 2
        event = context.events[1]
        assert event["event_type"] == AuditEventType.STATE_BEFORE.name
        assert event["data"]["aggregate_id"] == str(agg_id)
        assert "state" in event["data"]

    @pytest.mark.asyncio
    async def test_record_state_before_no_context(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        injector.record_state_before(uuid4(), uuid4(), "Agg", {})
        assert injector._async_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_record_state_after(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        agg_id = uuid4()
        state = {"field": "new"}
        changes = {"field": "old->new"}
        injector.record_state_after(envelope.command_id, agg_id, "Agg", state, changes)
        assert len(context.events) == 2
        event = context.events[1]
        assert event["event_type"] == AuditEventType.STATE_AFTER.name
        assert "changes" in event["data"]

    @pytest.mark.asyncio
    async def test_record_data_access(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        injector.record_data_access(envelope.command_id, "SELECT", {"limit": 10}, 5)
        assert len(context.events) == 2
        event = context.events[1]
        assert event["event_type"] == AuditEventType.DATA_ACCESS.name
        assert event["data"]["query_type"] == "SELECT"
        assert event["data"]["result_count"] == 5

    @pytest.mark.asyncio
    async def test_record_security_event_with_context(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        context = injector.start_context(envelope)
        injector.record_security_event(envelope.command_id, "LOGIN_FAIL", {"ip": "1.2.3.4"}, AuditSeverity.WARNING)
        assert len(context.events) == 2
        event = context.events[1]
        assert event["event_type"] == AuditEventType.SECURITY_EVENT.name
        assert event["severity"] == "WARNING"
        assert event["data"]["security_event_type"] == "LOGIN_FAIL"

    @pytest.mark.asyncio
    async def test_record_security_event_no_context(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        asyncio.get_running_loop()
        cmd_id = uuid4()
        injector.record_security_event(cmd_id, "UNAUTHORIZED", {"user": "hacker"}, AuditSeverity.ALERT)
        assert injector._async_queue.qsize() == 1
        queued = injector._async_queue.get_nowait()
        assert queued.command_id == cmd_id
        assert queued.command_type == "SECURITY"
        assert len(queued.events) == 1
        assert queued.events[0]["event_type"] == AuditEventType.SECURITY_EVENT.name
        assert queued.events[0]["severity"] == "ALERT"

    @pytest.mark.asyncio
    async def test_flush_context(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        context = injector.start_context(envelope)
        injector.before_execution(envelope)
        await injector._flush_context(context)
        assert mock_event_store.append.call_count == 2
        assert mock_signer.sign.call_count == 2

    @pytest.mark.asyncio
    async def test_flush_all(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        context = injector.start_context(envelope)
        injector.before_execution(envelope)
        injector._async_queue.put_nowait(context)
        await injector.flush_all()
        assert injector._async_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_shutdown(self, mock_event_store, mock_signer, envelope):
        injector = AuditHookInjector()
        context = injector.start_context(envelope)
        injector.before_execution(envelope)
        injector._async_queue.put_nowait(context)
        await injector.shutdown()
        assert injector._shutting_down is True
        assert injector._worker_task is None
        assert injector._async_queue.qsize() == 0
        assert len(injector._active_contexts) == 0
        assert mock_event_store.append.call_count >= 2

    @pytest.mark.asyncio
    async def test_shutdown_already_shutting_down(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        injector._shutting_down = True
        await injector.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_with_worker_cancellation(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        async def fake_worker():
            await asyncio.sleep(100)
        injector._worker_task = asyncio.create_task(fake_worker())
        await injector.shutdown()
        assert injector._worker_task is None
        assert injector._shutting_down is True

    # ---------- Entity methods ----------
    def test_validate(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        result = injector.validate()
        assert result["is_valid"] is False
        assert "Worker task is not running" in result["errors"]

    def test_to_dict(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        d = injector.to_dict()
        assert "active_contexts" in d
        assert "queue_size" in d
        assert "worker_running" in d
        assert d["version"] == 1

    def test_from_dict(self):
        injector = AuditHookInjector.from_dict({})
        assert isinstance(injector, AuditHookInjector)

    def test_clone(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        old_version = injector._version
        clone = injector.clone()
        # clone returns the same singleton instance but with version incremented
        assert clone is injector
        assert clone._version == old_version + 1

    def test_snapshot(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        snap = injector.snapshot()
        assert "version" in snap
        assert "active_contexts" in snap
        assert "queue_size" in snap
        assert "timestamp" in snap

    def test_version(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        assert injector.version() == 1
        injector._version = 5
        assert injector.version() == 5

    def test_audit_trail(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        injector._record_audit("TEST", "user", {"foo": "bar"})
        trail = injector.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "user"

    def test_touch(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        old_version = injector._version
        touched = injector.touch("tester")
        assert touched._version == old_version + 1
        trail = injector.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    def test_get_statistics(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        stats = injector.get_statistics()
        assert stats["active_contexts"] == 0
        assert stats["queue_size"] == 0
        assert stats["version"] == 1

    def test_reset(self, mock_event_store, mock_signer):
        injector = AuditHookInjector()
        injector._active_contexts["id"] = "context"
        injector._audit_trail.append({"test": True})
        injector._version = 10
        injector.reset()
        assert injector._active_contexts == {}
        assert injector._audit_trail == []
        assert injector._version == 1

    # ---------- inject method ----------
    class TestClass:
        @audit("test_action")
        def method(self, arg1, arg2=None):
            return f"arg1={arg1}, arg2={arg2}"

    def test_inject(self, mock_event_store, mock_signer, caplog):
        injector = AuditHookInjector()
        obj = self.TestClass()
        assert hasattr(obj.method, "_audit_action")
        assert obj.method._audit_action == "test_action"
        injector.inject(obj)
        with caplog.at_level(logging.INFO):
            result = obj.method("hello", arg2="world")
            assert result == "arg1=hello, arg2=world"
            assert "arg2" in caplog.text
            assert "AUDIT: test_action" in caplog.text

    def test_inject_with_custom_logger(self, mock_event_store, mock_signer):
        custom_logger = MagicMock()
        injector = AuditHookInjector()
        # Set custom logger directly on the instance (singleton)
        injector._custom_logger = custom_logger
        obj = self.TestClass()
        injector.inject(obj)
        obj.method("test")
        custom_logger.log.assert_called_once()
        log_entry = custom_logger.log.call_args[0][0]
        assert log_entry["action"] == "test_action"
        assert "timestamp" in log_entry

    def test_inject_no_audit_action(self, mock_event_store, mock_signer):
        class NoAudit:
            def method(self):
                return "ok"
        injector = AuditHookInjector()
        obj = NoAudit()
        injector.inject(obj)
        assert obj.method() == "ok"

    def test_inject_handles_unprintable_args(self, mock_event_store, mock_signer):
        class Unprintable:
            def __str__(self):
                raise Exception("unprintable")
        class Test:
            @audit("test")
            def method(self, arg):
                return arg
        injector = AuditHookInjector()
        obj = Test()
        injector.inject(obj)
        result = obj.method(Unprintable())
        assert isinstance(result, Unprintable)

    # ---------- Decorator audit ----------
    def test_audit_decorator(self):
        @audit("my_action")
        def func():
            return "ok"
        assert func._audit_action == "my_action"
        assert func() == "ok"


# -------------------- Tests for module-level getter --------------------
def test_get_audit_hook_injector():
    AuditHookInjector._instance = None
    i1 = get_audit_hook_injector()
    i2 = get_audit_hook_injector()
    assert i1 is i2
    assert isinstance(i1, AuditHookInjector)