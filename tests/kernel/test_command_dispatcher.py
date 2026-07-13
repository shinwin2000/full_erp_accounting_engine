
#!/usr/bin/env python3
import asyncio
import threading
from uuid import uuid4

import pytest

from kernel.command_dispatcher import (
    BaseCommandDispatcher,
    CommandDispatcher,
    DispatchPriority,
    DispatchStrategy,
    QueuedCommand,
    get_command_dispatcher,
)
from kernel.command_envelope import CommandEnvelope, CommandStatus
from kernel.command_handler_registry import HandlerNotFoundError


@pytest.fixture
def sample_legal_entity_id():
    return uuid4()


@pytest.fixture
def sample_envelope(sample_legal_entity_id):
    return CommandEnvelope.create(
        command_type="TestCommand",
        command_data={"key": "value"},
        user_id="test_user",
        legal_entity_id=sample_legal_entity_id,
    )


@pytest.fixture
def dispatcher():
    CommandDispatcher._instance = None
    return CommandDispatcher()


class TestDispatchPriority:
    def test_all_members_exist(self):
        assert hasattr(DispatchPriority, 'CRITICAL')
        assert hasattr(DispatchPriority, 'HIGH')
        assert hasattr(DispatchPriority, 'NORMAL')
        assert hasattr(DispatchPriority, 'LOW')
        assert hasattr(DispatchPriority, 'BACKGROUND')

    def test_member_values_are_integers(self):
        assert isinstance(DispatchPriority.CRITICAL.value, int)
        assert isinstance(DispatchPriority.HIGH.value, int)

    def test_member_values_order(self):
        assert DispatchPriority.CRITICAL.value == 0
        assert DispatchPriority.HIGH.value == 1
        assert DispatchPriority.NORMAL.value == 2
        assert DispatchPriority.LOW.value == 3
        assert DispatchPriority.BACKGROUND.value == 4

    def test_member_is_instance(self):
        assert isinstance(DispatchPriority.CRITICAL, DispatchPriority)


class TestDispatchStrategy:
    def test_all_members_exist(self):
        assert hasattr(DispatchStrategy, 'DIRECT')
        assert hasattr(DispatchStrategy, 'QUEUE')
        assert hasattr(DispatchStrategy, 'PRIORITY_QUEUE')
        assert hasattr(DispatchStrategy, 'ROUND_ROBIN')

    def test_member_is_instance(self):
        assert isinstance(DispatchStrategy.DIRECT, DispatchStrategy)

    def test_auto_values_are_unique(self):
        values = [s.value for s in DispatchStrategy]
        assert len(values) == len(set(values))


class TestQueuedCommand:
    def test_construction_with_required_fields(self, sample_envelope):
        queued = QueuedCommand(
            priority=DispatchPriority.HIGH.value,
            sequence=1,
            envelope=sample_envelope,
        )
        assert queued.priority == 1
        assert queued.sequence == 1
        assert queued.envelope is sample_envelope
        assert isinstance(queued.created_at, float)

    def test_ordering_by_priority_then_sequence(self, sample_envelope):
        q1 = QueuedCommand(priority=2, sequence=1, envelope=sample_envelope)
        q2 = QueuedCommand(priority=1, sequence=2, envelope=sample_envelope)
        q3 = QueuedCommand(priority=1, sequence=1, envelope=sample_envelope)
        assert q3 < q2
        assert q2 < q1


class TestBaseCommandDispatcher:
    def test_class_is_importable(self):
        assert BaseCommandDispatcher is not None

    def test_class_is_abstract(self):
        with pytest.raises(TypeError):
            BaseCommandDispatcher()

    def test_declares_abstract_methods(self):
        abstract_methods = BaseCommandDispatcher.__abstractmethods__
        assert 'start_workers' in abstract_methods
        assert 'stop_workers' in abstract_methods
        assert 'dispatch' in abstract_methods
        assert 'clear_queue' in abstract_methods
        assert 'get_statistics' in abstract_methods


class TestCommandDispatcherConstruction:
    def test_singleton_pattern(self):
        CommandDispatcher._instance = None
        d1 = CommandDispatcher()
        d2 = CommandDispatcher()
        assert d1 is d2

    def test_get_command_dispatcher_returns_singleton(self):
        CommandDispatcher._instance = None
        d1 = get_command_dispatcher()
        d2 = get_command_dispatcher()
        assert d1 is d2

    def test_initial_state(self):
        CommandDispatcher._instance = None
        dispatcher = CommandDispatcher()
        assert dispatcher._worker_count == 4
        assert dispatcher._running is False
        assert dispatcher._strategy == DispatchStrategy.PRIORITY_QUEUE
        assert dispatcher.get_queue_size() == 0


class TestCommandDispatcherStartStopWorkers:
    @pytest.mark.asyncio
    async def test_start_workers_sets_running_flag(self, dispatcher):
        assert dispatcher._running is False
        dispatcher.start_workers(worker_count=2)
        assert dispatcher._running is True
        # Clean up workers to avoid unraisable exception warnings
        await dispatcher.stop_workers()

    @pytest.mark.asyncio
    async def test_start_workers_creates_tasks(self, dispatcher):
        dispatcher.start_workers(worker_count=3)
        assert len(dispatcher._workers) == 3
        for task in dispatcher._workers:
            assert isinstance(task, asyncio.Task)
        # Clean up workers
        await dispatcher.stop_workers()

    @pytest.mark.asyncio
    async def test_stop_workers_sets_running_false(self, dispatcher):
        dispatcher.start_workers(worker_count=2)
        await dispatcher.stop_workers()
        assert dispatcher._running is False

    @pytest.mark.asyncio
    async def test_stop_workers_clears_workers_list(self, dispatcher):
        dispatcher.start_workers(worker_count=2)
        await dispatcher.stop_workers()
        assert len(dispatcher._workers) == 0


class TestCommandDispatcherDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_direct_no_handler_raises(self, dispatcher, sample_envelope):
        with pytest.raises(HandlerNotFoundError):
            await dispatcher.dispatch(sample_envelope, strategy=DispatchStrategy.DIRECT)

    @pytest.mark.asyncio
    async def test_dispatch_queue_adds_to_queue(self, dispatcher, sample_envelope):
        initial_size = dispatcher.get_queue_size()
        await dispatcher.dispatch(sample_envelope, strategy=DispatchStrategy.QUEUE)
        assert dispatcher.get_queue_size() == initial_size + 1

    @pytest.mark.asyncio
    async def test_dispatch_rejects_when_queue_full(self, dispatcher, sample_envelope):
        dispatcher._max_queue_size = 1
        await dispatcher.dispatch(sample_envelope, strategy=DispatchStrategy.QUEUE)
        env2 = CommandEnvelope.create("Test2", {}, "user", uuid4())
        result = await dispatcher.dispatch(env2, strategy=DispatchStrategy.QUEUE)
        assert result.status == CommandStatus.REJECTED

    @pytest.mark.asyncio
    async def test_dispatch_default_strategy(self, dispatcher, sample_envelope):
        dispatcher.set_strategy(DispatchStrategy.QUEUE)
        await dispatcher.dispatch(sample_envelope)
        assert dispatcher.get_queue_size() == 1


class TestCommandDispatcherQueueOperations:
    def test_get_queue_size_empty(self, dispatcher):
        assert dispatcher.get_queue_size() == 0

    def test_clear_queue_removes_all_items(self, dispatcher, sample_legal_entity_id):
        for i in range(3):
            env = CommandEnvelope.create(f"C{i}", {}, "user", sample_legal_entity_id)
            asyncio.run(dispatcher._enqueue(env, DispatchPriority.NORMAL))
        assert dispatcher.get_queue_size() == 3
        cleared = dispatcher.clear_queue()
        assert cleared == 3
        assert dispatcher.get_queue_size() == 0


class TestCommandDispatcherStatistics:
    def test_get_statistics_structure(self, dispatcher):
        stats = dispatcher.get_statistics()
        assert "queue_size" in stats
        assert "worker_count" in stats
        assert "running" in stats

    def test_get_statistics_counts_by_status(self, dispatcher):
        dispatcher._dispatch_history = [
            {"status": "SUCCESS", "command_type": "Cmd1"},
            {"status": "FAILED", "command_type": "Cmd1"},
        ]
        stats = dispatcher.get_statistics()
        assert stats["success_count"] == 1
        assert stats["failed_count"] == 1


class TestCommandDispatcherStrategy:
    def test_set_strategy_changes_default(self, dispatcher):
        dispatcher.set_strategy(DispatchStrategy.DIRECT)
        assert dispatcher._strategy == DispatchStrategy.DIRECT

    def test_set_max_queue_size(self, dispatcher):
        dispatcher.set_max_queue_size(500)
        assert dispatcher._max_queue_size == 500


class TestCommandDispatcherEntityMethods:
    def test_validate_success(self, dispatcher):
        result = dispatcher.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_with_invalid_data(self, dispatcher):
        # Use the dispatcher fixture to avoid singleton pollution
        # Set invalid state - no need to start workers for validation test
        dispatcher._max_queue_size = -1
        result = dispatcher.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_to_dict_structure(self, dispatcher):
        result = dispatcher.to_dict()
        assert "worker_count" in result
        assert "version" in result
        assert "running" in result
        assert "strategy" in result

    def test_from_dict_creates_instance(self, dispatcher):
        data = {"worker_count": 8, "strategy": "DIRECT", "version": 5}
        new_d = CommandDispatcher.from_dict(data)
        assert new_d._worker_count == 8
        assert new_d._strategy == DispatchStrategy.DIRECT
        assert new_d._version == 5

    def test_version_returns_current_version(self, dispatcher):
        # Version starts at 1
        assert dispatcher.version() == 1
        # Touch increments version
        dispatcher.touch("test_user")
        assert dispatcher.version() == 2
        # Multiple touches continue incrementing
        dispatcher.touch("another_user")
        assert dispatcher.version() == 3

    def test_touch_adds_audit_trail_entry(self, dispatcher):
        initial_trail_len = len(dispatcher.audit_trail())
        dispatcher.touch("audit_test_user")
        trail = dispatcher.audit_trail()
        assert len(trail) == initial_trail_len + 1
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "audit_test_user"
        assert "timestamp" in trail[-1]

    def test_snapshot_returns_state_dict(self, dispatcher):
        snapshot = dispatcher.snapshot()
        assert "version" in snapshot
        assert "queue_size" in snapshot
        assert "running" in snapshot
        assert "worker_count" in snapshot
        assert "timestamp" in snapshot

    def test_clone_creates_new_instance_with_different_config(self, dispatcher):
        # Note: Due to singleton pattern, clone() returns the same instance
        # but with updated configuration. We test that config is properly copied.
        original_worker_count = dispatcher._worker_count
        original_max_queue = dispatcher._max_queue_size
        original_version = dispatcher._version

        cloned = dispatcher.clone()

        # Singleton means same instance
        assert cloned is dispatcher
        # But version should be incremented
        assert cloned._version == original_version + 1
        # Config should be preserved
        assert cloned._worker_count == original_worker_count
        assert cloned._max_queue_size == original_max_queue

    def test_reset_clears_state(self, dispatcher):
        # Set up some state
        dispatcher._dispatch_history = [{"status": "SUCCESS"}]
        dispatcher._version = 10
        dispatcher.touch("before_reset")

        dispatcher.reset()

        assert dispatcher.get_queue_size() == 0
        assert dispatcher._dispatch_history == []
        assert dispatcher._running is False
        assert dispatcher._version == 1
        assert dispatcher._workers == []


class TestCommandDispatcherAsyncOperations:
    @pytest.mark.asyncio
    async def test_dequeue_from_empty_queue(self, dispatcher):
        result = await dispatcher._dequeue()
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_queued_command_no_handler(self, dispatcher, sample_envelope):
        queued = QueuedCommand(priority=1, sequence=1, envelope=sample_envelope)
        await dispatcher._execute_queued_command(queued)
        assert sample_envelope.status == CommandStatus.REJECTED


class TestModuleFunctions:
    def test_get_command_dispatcher_returns_singleton(self):
        CommandDispatcher._instance = None
        d1 = get_command_dispatcher()
        d2 = get_command_dispatcher()
        assert d1 is d2

    def test_get_command_dispatcher_thread_safe(self):
        CommandDispatcher._instance = None
        instances = []
        def get_instance():
            instances.append(get_command_dispatcher())
        threads = []
        for _ in range(10):
            t = threading.Thread(target=get_instance)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert all(i is instances[0] for i in instances)
