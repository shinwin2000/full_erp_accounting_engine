# tests/infrastructure/persistence_orm/test_saga_state_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/saga_state_table.py
Covers all properties and methods of SagaStateTable including:
- is_* properties (is_completed, is_failed, is_compensating, is_compensated,
  is_running, is_initiated, is_timeout, progress_percent)
- start(), complete_step(), fail_step(), complete(), compensate(),
  compensated(), schedule_retry(), reset()
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.saga_state_table import SagaStateTable

# ============================================================================
# Test SagaStateTable - Basic Model
# ============================================================================

class TestSagaStateTableModel:
    def test_tablename_defined(self):
        assert hasattr(SagaStateTable, '__tablename__')
        assert SagaStateTable.__tablename__ == "saga_state"
        assert SagaStateTable.__is_audit_log__ is True

    def test_table_args(self):
        assert hasattr(SagaStateTable, '__table_args__')
        args = SagaStateTable.__table_args__
        assert isinstance(args, tuple)
        # Check that there are constraints and indexes
        assert any('UniqueConstraint' in str(arg) for arg in args if hasattr(arg, '__class__'))

    def test_instantiation(self):
        instance = SagaStateTable()
        assert instance is not None
        assert instance.id is None
        assert instance.saga_id is None
        assert instance.saga_type is None
        assert instance.status == "initiated"
        assert instance.current_step == 0
        assert instance.total_steps == 1
        assert instance.retry_count == 0
        assert instance.max_retries == 3
        assert instance.timeout_seconds == 3600

    def test_instantiation_with_values(self):
        saga_id = uuid4()
        legal_entity_id = uuid4()
        created_by = uuid4()
        instance = SagaStateTable(
            saga_id=saga_id,
            saga_type="procurement",
            correlation_id="corr-123",
            state_data={"key": "value"},
            current_step=2,
            total_steps=5,
            status="running",
            legal_entity_id=legal_entity_id,
            created_by=created_by,
            timeout_seconds=1800,
            max_retries=5,
        )
        assert instance.saga_id == saga_id
        assert instance.saga_type == "procurement"
        assert instance.correlation_id == "corr-123"
        assert instance.state_data == {"key": "value"}
        assert instance.current_step == 2
        assert instance.total_steps == 5
        assert instance.status == "running"
        assert instance.legal_entity_id == legal_entity_id
        assert instance.created_by == created_by
        assert instance.timeout_seconds == 1800
        assert instance.max_retries == 5


# ============================================================================
# Test SagaStateTable - Properties
# ============================================================================

class TestSagaStateTableProperties:
    @pytest.fixture
    def saga(self):
        return SagaStateTable(
            saga_id=uuid4(),
            saga_type="test",
            total_steps=3,
            timeout_seconds=3600,
        )

    # ---- is_completed ----
    def test_is_completed_true(self, saga):
        saga.status = "completed"
        assert saga.is_completed is True

    def test_is_completed_false(self, saga):
        saga.status = "running"
        assert saga.is_completed is False

    # ---- is_failed ----
    def test_is_failed_true(self, saga):
        saga.status = "failed"
        assert saga.is_failed is True

    def test_is_failed_false(self, saga):
        saga.status = "running"
        assert saga.is_failed is False

    # ---- is_compensating ----
    def test_is_compensating_true(self, saga):
        saga.status = "compensating"
        assert saga.is_compensating is True

    def test_is_compensating_false(self, saga):
        saga.status = "running"
        assert saga.is_compensating is False

    # ---- is_compensated ----
    def test_is_compensated_true(self, saga):
        saga.status = "compensated"
        assert saga.is_compensated is True

    def test_is_compensated_false(self, saga):
        saga.status = "running"
        assert saga.is_compensated is False

    # ---- is_running ----
    def test_is_running_true(self, saga):
        saga.status = "running"
        assert saga.is_running is True

    def test_is_running_false(self, saga):
        saga.status = "initiated"
        assert saga.is_running is False

    # ---- is_initiated ----
    def test_is_initiated_true(self, saga):
        saga.status = "initiated"
        assert saga.is_initiated is True

    def test_is_initiated_false(self, saga):
        saga.status = "running"
        assert saga.is_initiated is False

    # ---- is_timeout ----
    def test_is_timeout_completed_status_returns_false(self, saga):
        saga.status = "completed"
        assert saga.is_timeout is False

    def test_is_timeout_compensated_returns_false(self, saga):
        saga.status = "compensated"
        assert saga.is_timeout is False

    def test_is_timeout_failed_returns_false(self, saga):
        saga.status = "failed"
        assert saga.is_timeout is False

    def test_is_timeout_not_expired(self, saga):
        saga.status = "running"
        saga.started_at = datetime.utcnow()
        saga.timeout_seconds = 3600
        assert saga.is_timeout is False

    def test_is_timeout_expired(self, saga):
        saga.status = "running"
        saga.started_at = datetime.utcnow() - timedelta(seconds=3700)
        saga.timeout_seconds = 3600
        assert saga.is_timeout is True

    def test_is_timeout_expired_initiated_state(self, saga):
        saga.status = "initiated"
        saga.started_at = datetime.utcnow() - timedelta(seconds=3700)
        saga.timeout_seconds = 3600
        assert saga.is_timeout is True

    def test_is_timeout_compensating_expired(self, saga):
        saga.status = "compensating"
        saga.started_at = datetime.utcnow() - timedelta(seconds=3700)
        saga.timeout_seconds = 3600
        assert saga.is_timeout is True

    # ---- progress_percent ----
    def test_progress_percent_zero_steps(self, saga):
        saga.total_steps = 0
        assert saga.progress_percent == 0.0

    def test_progress_percent_zero_current(self, saga):
        saga.current_step = 0
        saga.total_steps = 5
        assert saga.progress_percent == 0.0

    def test_progress_percent_partial(self, saga):
        saga.current_step = 2
        saga.total_steps = 5
        assert saga.progress_percent == 40.0

    def test_progress_percent_complete(self, saga):
        saga.current_step = 5
        saga.total_steps = 5
        assert saga.progress_percent == 100.0


# ============================================================================
# Test SagaStateTable - Methods
# ============================================================================

class TestSagaStateTableMethods:
    @pytest.fixture
    def saga(self):
        return SagaStateTable(
            saga_id=uuid4(),
            saga_type="test",
            total_steps=3,
            status="initiated",
        )

    @pytest.fixture
    def running_saga(self):
        saga = SagaStateTable(
            saga_id=uuid4(),
            saga_type="test",
            total_steps=3,
            status="running",
        )
        saga.current_step = 0
        return saga

    @pytest.fixture
    def compensating_saga(self):
        saga = SagaStateTable(
            saga_id=uuid4(),
            saga_type="test",
            total_steps=3,
            status="compensating",
        )
        saga.current_step = 1
        return saga

    # ---- start ----
    def test_start_success(self, saga):
        assert saga.status == "initiated"
        original_started_at = saga.started_at
        saga.start()
        assert saga.status == "running"
        assert saga.started_at >= original_started_at

    def test_start_already_running(self, running_saga):
        with pytest.raises(ValueError, match="Cannot start saga with status running"):
            running_saga.start()

    def test_start_completed(self, saga):
        saga.status = "completed"
        with pytest.raises(ValueError, match="Cannot start saga with status completed"):
            saga.start()

    # ---- complete_step ----
    def test_complete_step_success(self, running_saga):
        running_saga.step_history = []
        running_saga.complete_step(1)
        assert running_saga.current_step == 1
        assert len(running_saga.step_history) == 1
        assert running_saga.step_history[0]["step"] == 1
        assert running_saga.step_history[0]["status"] == "completed"
        assert "timestamp" in running_saga.step_history[0]
        assert running_saga.status == "running"  # not complete yet

    def test_complete_step_final(self, running_saga):
        running_saga.current_step = 2
        running_saga.total_steps = 3
        running_saga.step_history = []
        running_saga.complete_step(3)
        assert running_saga.current_step == 3
        assert running_saga.status == "completed"
        assert running_saga.completed_at is not None
        assert len(running_saga.step_history) == 1

    def test_complete_step_not_running(self, saga):
        with pytest.raises(ValueError, match="Cannot complete step with status initiated"):
            saga.complete_step(1)

    def test_complete_step_wrong_step(self, running_saga):
        with pytest.raises(ValueError, match="Expected step 1, got 2"):
            running_saga.complete_step(2)

    def test_complete_step_with_result(self, running_saga):
        running_saga.step_history = []
        result = {"processed": 10, "status": "ok"}
        running_saga.complete_step(1, result)
        assert running_saga.step_history[0]["result"] == result

    def test_complete_step_append_history(self, running_saga):
        running_saga.step_history = [{"step": 1, "status": "completed", "timestamp": "2026-01-01"}]
        running_saga.complete_step(2)
        assert len(running_saga.step_history) == 2
        assert running_saga.step_history[1]["step"] == 2

    # ---- fail_step ----
    def test_fail_step_running(self, running_saga):
        running_saga.step_history = []
        running_saga.fail_step(1, "Error occurred")
        assert len(running_saga.step_history) == 1
        assert running_saga.step_history[0]["step"] == 1
        assert running_saga.step_history[0]["status"] == "failed"
        assert running_saga.step_history[0]["error"] == "Error occurred"
        assert running_saga.error_message == "Error occurred"
        assert running_saga.status == "compensating"  # should compensate by default

    def test_fail_step_compensating(self, compensating_saga):
        compensating_saga.step_history = []
        compensating_saga.fail_step(2, "Compensation failed")
        assert compensating_saga.status == "failed"
        assert compensating_saga.error_message == "Compensation failed"

    def test_fail_step_not_running_or_compensating(self, saga):
        with pytest.raises(ValueError, match="Cannot fail step with status initiated"):
            saga.fail_step(1, "Error")

    def test_fail_step_no_compensate(self, running_saga):
        running_saga.fail_step(1, "Error", should_compensate=False)
        assert running_saga.status == "failed"
        assert running_saga.error_message == "Error"

    def test_fail_step_append_history(self, running_saga):
        running_saga.step_history = [{"step": 1, "status": "completed", "timestamp": "2026-01-01"}]
        running_saga.fail_step(2, "Error")
        assert len(running_saga.step_history) == 2
        assert running_saga.step_history[1]["step"] == 2
        assert running_saga.step_history[1]["status"] == "failed"

    # ---- complete ----
    def test_complete_success(self, running_saga):
        running_saga.complete()
        assert running_saga.status == "completed"
        assert running_saga.completed_at is not None

    def test_complete_already_completed(self, running_saga):
        running_saga.status = "completed"
        running_saga.complete()  # Should not raise, just set again
        assert running_saga.status == "completed"

    def test_complete_sets_completed_at(self, running_saga):
        running_saga.completed_at = None
        running_saga.complete()
        assert running_saga.completed_at is not None

    # ---- compensate ----
    def test_compensate_from_failed(self, saga):
        saga.status = "failed"
        saga.compensate()
        assert saga.status == "compensating"

    def test_compensate_from_compensating(self, compensating_saga):
        compensating_saga.compensate()
        assert compensating_saga.status == "compensating"

    def test_compensate_invalid_status(self, running_saga):
        with pytest.raises(ValueError, match="Cannot compensate saga with status running"):
            running_saga.compensate()

    def test_compensate_from_initiated(self, saga):
        with pytest.raises(ValueError, match="Cannot compensate saga with status initiated"):
            saga.compensate()

    # ---- compensated ----
    def test_compensated_success(self, compensating_saga):
        compensating_saga.compensated()
        assert compensating_saga.status == "compensated"
        assert compensating_saga.completed_at is not None

    def test_compensated_sets_completed_at(self, compensating_saga):
        compensating_saga.completed_at = None
        compensating_saga.compensated()
        assert compensating_saga.completed_at is not None

    # ---- schedule_retry ----
    def test_schedule_retry_success(self, saga):
        saga.retry_count = 0
        saga.max_retries = 3
        saga.status = "failed"
        saga.current_step = 2
        saga.schedule_retry()
        assert saga.retry_count == 1
        assert saga.status == "initiated"
        assert saga.current_step == 0
        assert saga.next_retry_at is not None

    def test_schedule_retry_max_exceeded(self, saga):
        saga.retry_count = 3
        saga.max_retries = 3
        saga.status = "failed"
        saga.schedule_retry()
        assert saga.status == "failed"
        assert saga.retry_count == 3  # unchanged

    def test_schedule_retry_exponential_backoff(self, saga):
        saga.retry_count = 0
        saga.max_retries = 5
        saga.schedule_retry()
        delay1 = (saga.next_retry_at - datetime.utcnow()).total_seconds()
        assert 1 <= delay1 <= 3  # 2^1 = 2, with some tolerance

        saga.schedule_retry()
        delay2 = (saga.next_retry_at - datetime.utcnow()).total_seconds()
        assert 3 <= delay2 <= 5  # 2^2 = 4, with some tolerance

        saga.retry_count = 8
        saga.schedule_retry()
        delay3 = (saga.next_retry_at - datetime.utcnow()).total_seconds()
        assert 298 <= delay3 <= 302  # capped at 300

    def test_schedule_retry_resets_state(self, saga):
        saga.status = "compensating"
        saga.current_step = 3
        saga.error_message = "Error"
        saga.retry_count = 0
        saga.schedule_retry()
        assert saga.status == "initiated"
        assert saga.current_step == 0
        assert saga.error_message is None

    # ---- reset ----
    def test_reset_success(self, saga):
        saga.status = "failed"
        saga.current_step = 2
        saga.retry_count = 5
        saga.error_message = "Error"
        saga.next_retry_at = datetime.utcnow() + timedelta(seconds=60)
        saga.step_history = [{"step": 1, "status": "completed"}]
        original_started_at = saga.started_at

        saga.reset()
        assert saga.status == "initiated"
        assert saga.current_step == 0
        assert saga.retry_count == 0
        assert saga.error_message is None
        assert saga.next_retry_at is None
        assert saga.step_history == []
        assert saga.started_at >= original_started_at

    def test_reset_from_running(self, running_saga):
        running_saga.step_history = [{"step": 1, "status": "completed"}]
        running_saga.reset()
        assert running_saga.status == "initiated"
        assert running_saga.current_step == 0
        assert running_saga.step_history == []


# ============================================================================
# Test SagaStateTable - Integration Scenarios
# ============================================================================

class TestSagaStateTableScenarios:
    def test_happy_path_to_completion(self):
        saga = SagaStateTable(saga_type="procurement", total_steps=3, status="initiated")
        # Start
        saga.start()
        assert saga.is_running is True
        # Step 1
        saga.complete_step(1)
        assert saga.current_step == 1
        assert saga.is_running is True
        # Step 2
        saga.complete_step(2)
        assert saga.current_step == 2
        # Step 3 - final
        saga.complete_step(3)
        assert saga.current_step == 3
        assert saga.is_completed is True
        assert saga.progress_percent == 100.0

    def test_failure_and_compensation(self):
        saga = SagaStateTable(saga_type="procurement", total_steps=3, status="initiated")
        saga.start()
        saga.complete_step(1)
        saga.fail_step(2, "Step 2 failed")
        assert saga.is_compensating is True
        saga.compensated()
        assert saga.is_compensated is True

    def test_retry_scenario(self):
        saga = SagaStateTable(saga_type="procurement", total_steps=3, status="initiated")
        saga.max_retries = 2
        saga.start()
        saga.fail_step(1, "Temporary error")
        assert saga.is_compensating is True
        saga.compensated()
        assert saga.is_compensated is True

        # Schedule retry from failed state
        saga.status = "failed"  # Simulate failure after compensation
        saga.schedule_retry()
        assert saga.is_initiated is True
        assert saga.retry_count == 1
        assert saga.next_retry_at is not None

        # Retry again
        saga.schedule_retry()
        assert saga.retry_count == 2
        assert saga.next_retry_at is not None

    def test_timeout_detection(self):
        saga = SagaStateTable(saga_type="procurement", total_steps=3, status="running")
        saga.started_at = datetime.utcnow() - timedelta(seconds=3700)
        saga.timeout_seconds = 3600
        assert saga.is_timeout is True
        # Trigger timeout handling
        assert saga.is_completed is False
        assert saga.is_failed is False
