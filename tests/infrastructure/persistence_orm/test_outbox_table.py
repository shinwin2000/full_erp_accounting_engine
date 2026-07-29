# tests/infrastructure/persistence_orm/test_outbox_table.py
"""
Comprehensive unit tests for infrastructure/persistence_orm/outbox_table.py.
Covers all properties, methods, state transitions, and edge cases.
Uses direct instantiation without a DB session for testing model logic.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.outbox_table import OutboxStatus, OutboxTable

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_outbox():
    """Create an OutboxTable instance with default values."""
    return OutboxTable(
        id=uuid4(),
        event_type="test.event",
        aggregate_id=uuid4(),
        aggregate_type="TestAggregate",
        payload='{"key": "value"}',
        status="pending",
        retry_count=0,
        last_error=None,
        next_retry_at=None,
        sent_at=None,
        legal_entity_id=uuid4(),
        event_id=uuid4(),
        idempotency_key="idem-001",
        processed_at=None,
        version=0,
        priority=0,
        scheduled_at=None,
        correlation_id="corr-001",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )


@pytest.fixture
def sample_processing_outbox(sample_outbox):
    """Return an outbox in processing state."""
    outbox = sample_outbox
    outbox.status = "processing"
    return outbox


@pytest.fixture
def sample_sent_outbox(sample_outbox):
    """Return an outbox in sent state."""
    outbox = sample_outbox
    outbox.status = "sent"
    outbox.sent_at = datetime.now(UTC)
    return outbox


@pytest.fixture
def sample_failed_outbox(sample_outbox):
    """Return an outbox in failed state (pending with retry)."""
    outbox = sample_outbox
    outbox.status = "pending"
    outbox.retry_count = 2
    outbox.last_error = "Connection timeout"
    outbox.next_retry_at = datetime.now(UTC) + timedelta(seconds=30)
    return outbox


@pytest.fixture
def sample_dead_letter_outbox(sample_outbox):
    """Return an outbox in dead_letter state."""
    outbox = sample_outbox
    outbox.status = "dead_letter"
    outbox.last_error = "Fatal error"
    outbox.next_retry_at = None
    return outbox


# ============================================================================
# TESTS FOR OUTBOXSTATUS (enum-like class)
# ============================================================================

class TestOutboxStatus:
    def test_constants(self):
        assert OutboxStatus.PENDING == "pending"
        assert OutboxStatus.PROCESSING == "processing"
        assert OutboxStatus.PUBLISHED == "sent"
        assert OutboxStatus.PUBLISHED_DUPLICATE == "sent"
        assert OutboxStatus.FAILED == "failed"
        assert OutboxStatus.DEAD_LETTER == "dead_letter"


# ============================================================================
# TABLE METADATA TESTS
# ============================================================================

class TestOutboxTableMetadata:
    def test_tablename_defined(self):
        assert hasattr(OutboxTable, "__tablename__")
        assert OutboxTable.__tablename__ == "outbox"

    def test_table_args_defined(self):
        assert hasattr(OutboxTable, "__table_args__")
        args = OutboxTable.__table_args__
        assert isinstance(args, tuple)
        # Check for constraints and indexes
        constraints = [arg for arg in args if hasattr(arg, "name")]
        assert len(constraints) > 0


# ============================================================================
# INSTANTIATION TESTS
# ============================================================================

class TestOutboxTableInstantiation:
    def test_instantiation(self, sample_outbox):
        assert isinstance(sample_outbox, OutboxTable)
        assert sample_outbox.event_type == "test.event"
        assert sample_outbox.status == "pending"
        assert sample_outbox.retry_count == 0
        assert sample_outbox.version == 0
        assert sample_outbox.event_id is not None

    def test_instantiation_with_defaults(self):
        outbox = OutboxTable(
            event_type="test",
            aggregate_id=uuid4(),
            aggregate_type="Agg",
            payload="{}",
        )
        assert outbox.status == "pending"
        assert outbox.retry_count == 0
        assert outbox.version == 0
        assert outbox.event_id is not None
        assert outbox.idempotency_key is None


# ============================================================================
# PROPERTY TESTS
# ============================================================================

class TestOutboxTableProperties:
    def test_is_pending(self, sample_outbox, sample_processing_outbox, sample_sent_outbox):
        assert sample_outbox.is_pending is True
        assert sample_processing_outbox.is_pending is False
        assert sample_sent_outbox.is_pending is False

    def test_is_processing(self, sample_outbox, sample_processing_outbox):
        assert sample_outbox.is_processing is False
        assert sample_processing_outbox.is_processing is True

    def test_is_sent(self, sample_outbox, sample_sent_outbox):
        assert sample_outbox.is_sent is False
        assert sample_sent_outbox.is_sent is True

    def test_is_failed(self, sample_outbox, sample_failed_outbox):
        # failed is actually "pending" with retry; not a separate status
        # The property checks status == "failed", but we don't have that status
        # In our model, failed is still pending with retry info.
        # The property is_failed returns status == "failed", so it will be False for pending.
        sample_outbox.status = "failed"
        assert sample_outbox.is_failed is True
        assert sample_failed_outbox.is_failed is False  # because status is pending

    def test_is_dead_letter(self, sample_dead_letter_outbox):
        assert sample_dead_letter_outbox.is_dead_letter is True
        sample_dead_letter_outbox.status = "pending"
        assert sample_dead_letter_outbox.is_dead_letter is False

    @patch("infrastructure.persistence_orm.outbox_table.datetime")
    def test_is_ready_for_retry(self, mock_datetime, sample_outbox, sample_failed_outbox):
        # For pending with next_retry_at None -> ready
        mock_datetime.now.return_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert sample_outbox.is_ready_for_retry is True

        # For pending with next_retry_at in future -> not ready
        sample_outbox.next_retry_at = datetime(2026, 1, 1, 12, 10, 0, tzinfo=UTC)
        assert sample_outbox.is_ready_for_retry is False

        # For pending with next_retry_at in past -> ready
        sample_outbox.next_retry_at = datetime(2026, 1, 1, 11, 50, 0, tzinfo=UTC)
        assert sample_outbox.is_ready_for_retry is True

        # For non-pending status, always False
        sample_outbox.status = "processing"
        assert sample_outbox.is_ready_for_retry is False
        sample_outbox.status = "sent"
        assert sample_outbox.is_ready_for_retry is False
        sample_outbox.status = "dead_letter"
        assert sample_outbox.is_ready_for_retry is False


# ============================================================================
# METHOD TESTS
# ============================================================================

class TestOutboxTableMethods:
    def test_mark_processing_success(self, sample_outbox):
        sample_outbox.mark_processing()
        assert sample_outbox.status == "processing"
        # No version increment in this method, it's just a status change

    def test_mark_processing_invalid_state(self, sample_processing_outbox):
        with pytest.raises(ValueError, match="Cannot mark as processing with status processing"):
            sample_processing_outbox.mark_processing()

    def test_mark_processing_already_sent(self, sample_sent_outbox):
        with pytest.raises(ValueError, match="Cannot mark as processing with status sent"):
            sample_sent_outbox.mark_processing()

    def test_mark_sent_success(self, sample_processing_outbox):
        with patch("infrastructure.persistence_orm.outbox_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = fixed_now
            sample_processing_outbox.mark_sent()
        assert sample_processing_outbox.status == "sent"
        assert sample_processing_outbox.sent_at == fixed_now

    def test_mark_sent_invalid_state(self, sample_outbox):
        with pytest.raises(ValueError, match="Cannot mark as sent with status pending"):
            sample_outbox.mark_sent()

    def test_mark_sent_already_sent(self, sample_sent_outbox):
        with pytest.raises(ValueError, match="Cannot mark as sent with status sent"):
            sample_sent_outbox.mark_sent()

    def test_mark_failed_from_processing_with_retry(self, sample_processing_outbox):
        error_msg = "Network error"
        old_retry_count = sample_processing_outbox.retry_count
        with patch("infrastructure.persistence_orm.outbox_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = fixed_now
            sample_processing_outbox.mark_failed(error_msg, schedule_retry=True)
        assert sample_processing_outbox.status == "pending"
        assert sample_processing_outbox.retry_count == old_retry_count + 1
        assert sample_processing_outbox.last_error == error_msg
        # Next retry with exponential backoff: 2^(retry_count) seconds, capped at 60
        expected_delay = min(2**(old_retry_count + 1), 60)
        expected_next_retry = fixed_now + timedelta(seconds=expected_delay)
        assert sample_processing_outbox.next_retry_at == expected_next_retry

    def test_mark_failed_from_pending_without_retry(self, sample_outbox):
        error_msg = "Permanent error"
        old_retry_count = sample_outbox.retry_count
        sample_outbox.mark_failed(error_msg, schedule_retry=False)
        assert sample_outbox.status == "pending"
        assert sample_outbox.retry_count == old_retry_count + 1
        assert sample_outbox.last_error == error_msg
        assert sample_outbox.next_retry_at is None

    def test_mark_failed_invalid_state(self, sample_sent_outbox):
        with pytest.raises(ValueError, match="Cannot mark as failed with status sent"):
            sample_sent_outbox.mark_failed("error")

    def test_mark_failed_from_processing_with_high_retry_cap(self, sample_processing_outbox):
        # Set retry_count high to test cap
        sample_processing_outbox.retry_count = 10
        old_retry_count = sample_processing_outbox.retry_count
        with patch("infrastructure.persistence_orm.outbox_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = fixed_now
            sample_processing_outbox.mark_failed("error", schedule_retry=True)
        expected_delay = min(2**(old_retry_count + 1), 60)
        expected_next_retry = fixed_now + timedelta(seconds=expected_delay)
        assert expected_delay == 60  # capped
        assert sample_processing_outbox.next_retry_at == expected_next_retry

    def test_mark_dead_letter(self, sample_processing_outbox):
        error_msg = "Fatal error"
        sample_processing_outbox.mark_dead_letter(error_msg)
        assert sample_processing_outbox.status == "dead_letter"
        assert sample_processing_outbox.last_error == error_msg
        assert sample_processing_outbox.next_retry_at is None

    def test_mark_dead_letter_from_pending(self, sample_outbox):
        error_msg = "Fatal"
        sample_outbox.mark_dead_letter(error_msg)
        assert sample_outbox.status == "dead_letter"
        assert sample_outbox.last_error == error_msg

    def test_reset_retry(self, sample_failed_outbox):
        sample_failed_outbox.reset_retry()
        assert sample_failed_outbox.retry_count == 0
        assert sample_failed_outbox.last_error is None
        assert sample_failed_outbox.next_retry_at is None
        assert sample_failed_outbox.status == "pending"

    def test_reset_retry_on_clean_outbox(self, sample_outbox):
        # Already clean, but it should still work
        sample_outbox.reset_retry()
        assert sample_outbox.retry_count == 0
        assert sample_outbox.last_error is None
        assert sample_outbox.next_retry_at is None
        assert sample_outbox.status == "pending"

    def test_mark_failed_preserves_idempotency_key(self, sample_outbox):
        original_key = sample_outbox.idempotency_key
        sample_outbox.mark_failed("error")
        assert sample_outbox.idempotency_key == original_key

    def test_mark_dead_letter_preserves_fields(self, sample_processing_outbox):
        event_id = sample_processing_outbox.event_id
        correlation = sample_processing_outbox.correlation_id
        sample_processing_outbox.mark_dead_letter("Fatal")
        assert sample_processing_outbox.event_id == event_id
        assert sample_processing_outbox.correlation_id == correlation


# ============================================================================
# TO_DICT TESTS
# ============================================================================

class TestOutboxTableToDict:
    def test_to_dict(self, sample_outbox):
        d = sample_outbox.to_dict()
        assert d["id"] == str(sample_outbox.id)
        assert d["event_id"] == str(sample_outbox.event_id)
        assert d["event_type"] == "test.event"
        assert d["aggregate_id"] == str(sample_outbox.aggregate_id)
        assert d["aggregate_type"] == "TestAggregate"
        assert d["payload"] == '{"key": "value"}'
        assert d["status"] == "pending"
        assert d["retry_count"] == 0
        assert d["last_error"] is None
        assert d["next_retry_at"] is None
        assert d["sent_at"] is None
        assert d["legal_entity_id"] == str(sample_outbox.legal_entity_id)
        assert d["idempotency_key"] == "idem-001"
        assert d["processed_at"] is None
        assert d["version"] == 0
        assert d["priority"] == 0
        assert d["scheduled_at"] is None
        assert d["correlation_id"] == "corr-001"
        assert "created_at" in d
        assert "updated_at" in d
        assert "deleted_at" in d

    def test_to_dict_with_none_values(self):
        outbox = OutboxTable(
            event_type="test",
            aggregate_id=uuid4(),
            aggregate_type="Agg",
            payload="{}",
            legal_entity_id=None,
            idempotency_key=None,
            processed_at=None,
            scheduled_at=None,
            correlation_id=None,
        )
        d = outbox.to_dict()
        assert d["legal_entity_id"] is None
        assert d["idempotency_key"] is None
        assert d["processed_at"] is None
        assert d["scheduled_at"] is None
        assert d["correlation_id"] is None


# ============================================================================
# ALIAS TESTS
# ============================================================================

class TestAliases:
    def test_outbox_record_alias(self):
        from infrastructure.persistence_orm.outbox_table import OutboxRecord
        assert OutboxRecord is OutboxTable
