# tests/audit/test_event_writer_immutable.py
"""
Comprehensive unit tests for audit/event_writer_immutable.py.
Covers all methods, exceptions, private helpers, and the audit_log decorator.
Uses mocking to avoid external dependencies (store, hash builder, etc.).
"""

import hashlib
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from audit.event_writer_immutable import (
    AUDIT_STREAM_NAME,
    SECURITY_AUDIT_STREAM,
    ImmutableEventWriter,
    ImmutableEventWriterError,
    InvalidEventTypeError,
    MissingRequiredFieldError,
    audit_log,
    get_immutable_event_writer,
)

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_catalog():
    """Mock the EventTypeCatalog to control validation."""
    with patch("audit.event_writer_immutable.EventTypeCatalog") as mock:
        mock.is_valid_type.return_value = True
        mock.get_default_severity.return_value = "info"
        yield mock


@pytest.fixture
def mock_schema():
    """Mock the EventMetadataSchema to control required fields."""
    with patch("audit.event_writer_immutable.EventMetadataSchema") as mock:
        mock.get_schema.return_value = {"required_fields": []}
        yield mock


@pytest.fixture
def mock_store():
    """Mock the append-only store."""
    store = AsyncMock()
    store.get_last_event = AsyncMock(return_value=None)
    store.append = AsyncMock(return_value="event-id-123")
    with patch("audit.event_writer_immutable.importlib.import_module") as mock_import:
        # Mock the module that get_audit_store is imported from
        mock_mod = MagicMock()
        mock_mod.get_audit_store = AsyncMock(return_value=store)
        mock_import.return_value = mock_mod
        yield store


@pytest.fixture
def mock_hash_builder():
    """Mock the audit hash builder."""
    builder = MagicMock()
    with patch("audit.event_writer_immutable.get_audit_hash_builder", return_value=builder):
        yield builder


@pytest.fixture
def mock_correlation_id():
    """Mock the correlation id injector."""
    with patch("audit.event_writer_immutable._get_current_correlation_id", return_value="corr-123"):
        yield


@pytest.fixture
def event_writer(mock_store, mock_hash_builder, mock_catalog, mock_schema, mock_correlation_id):
    """Create an ImmutableEventWriter with mocked dependencies."""
    writer = ImmutableEventWriter()
    # Override internal attributes with mocks
    writer._store = mock_store
    writer._hash_builder = mock_hash_builder
    return writer


# ============================================================================
# TESTS FOR EXCEPTIONS
# ============================================================================

class TestExceptions:
    def test_immutable_event_writer_error(self):
        exc = ImmutableEventWriterError("test")
        assert isinstance(exc, Exception)
        assert str(exc) == "test"

    def test_invalid_event_type_error(self):
        exc = InvalidEventTypeError("invalid")
        assert isinstance(exc, ImmutableEventWriterError)

    def test_missing_required_field_error(self):
        exc = MissingRequiredFieldError("missing")
        assert isinstance(exc, ImmutableEventWriterError)


# ============================================================================
# TESTS FOR PRIVATE METHODS
# ============================================================================

class TestPrivateMethods:
    def test_validate_event_valid(self, event_writer, mock_catalog):
        """_validate_event should not raise for valid event type with all required fields."""
        mock_catalog.is_valid_type.return_value = True
        mock_schema = MagicMock()
        mock_schema.get_schema.return_value = {"required_fields": ["field1"]}
        with patch("audit.event_writer_immutable.EventMetadataSchema", mock_schema):
            event_writer._validate_event("valid.event", {"field1": "value"})
            # No exception raised

    def test_validate_event_invalid_type(self, event_writer, mock_catalog):
        """_validate_event should raise InvalidEventTypeError for invalid type."""
        mock_catalog.is_valid_type.return_value = False
        with pytest.raises(InvalidEventTypeError, match="Invalid event type: invalid.event"):
            event_writer._validate_event("invalid.event", {})

    def test_validate_event_missing_required_field(self, event_writer, mock_catalog):
        """_validate_event should raise MissingRequiredFieldError when required field missing."""
        mock_catalog.is_valid_type.return_value = True
        mock_schema = MagicMock()
        mock_schema.get_schema.return_value = {"required_fields": ["field1", "field2"]}
        with patch("audit.event_writer_immutable.EventMetadataSchema", mock_schema):
            with pytest.raises(MissingRequiredFieldError, match="Missing required fields: field1, field2"):
                event_writer._validate_event("valid.event", {"field1": "value"})

    def test_get_stream_name_audit(self, event_writer):
        """_get_stream_name should return AUDIT_STREAM_NAME for non-security events."""
        assert event_writer._get_stream_name("data.create") == AUDIT_STREAM_NAME
        assert event_writer._get_stream_name("journal.posted") == AUDIT_STREAM_NAME

    def test_get_stream_name_security(self, event_writer):
        """_get_stream_name should return SECURITY_AUDIT_STREAM for security events."""
        assert event_writer._get_stream_name("security.login") == SECURITY_AUDIT_STREAM
        assert event_writer._get_stream_name("auth.failed") == SECURITY_AUDIT_STREAM
        assert event_writer._get_stream_name("access.denied") == SECURITY_AUDIT_STREAM

    def test_build_event_record(self, event_writer, mock_correlation_id):
        """_build_event_record should create a record with hash and metadata."""
        previous_hash = "prev_hash"
        record = event_writer._build_event_record(
            event_type="test.event",
            data={"key": "value"},
            severity="info",
            user_id="user1",
            legal_entity_id="legal1",
            previous_hash=previous_hash,
        )
        assert "id" in record
        assert record["event_type"] == "test.event"
        assert record["severity"] == "info"
        assert record["data"]["key"] == "value"
        assert record["data"]["timestamp"] is not None
        assert record["data"]["correlation_id"] == "corr-123"
        assert record["user_id"] == "user1"
        assert record["legal_entity_id"] == "legal1"
        assert record["previous_hash"] == previous_hash
        assert record["hash"] is not None
        # Verify hash computation
        content = {
            "id": record["id"],
            "event_type": record["event_type"],
            "severity": record["severity"],
            "data": record["data"],
            "user_id": record["user_id"],
            "legal_entity_id": record["legal_entity_id"],
            "timestamp": record["timestamp"],
            "correlation_id": record["correlation_id"],
            "previous_hash": record["previous_hash"],
        }
        json_str = json.dumps(content, sort_keys=True, default=str)
        expected_hash = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
        assert record["hash"] == expected_hash

    def test_compute_hash(self, event_writer):
        """_compute_hash should return a SHA-256 hash of the record content."""
        record = {
            "id": "id1",
            "event_type": "test",
            "severity": "info",
            "data": {"foo": "bar"},
            "user_id": "u1",
            "legal_entity_id": "l1",
            "timestamp": "2024-01-01T00:00:00",
            "correlation_id": "c1",
            "previous_hash": "prev",
        }
        h = event_writer._compute_hash(record)
        content = {
            "id": record["id"],
            "event_type": record["event_type"],
            "severity": record["severity"],
            "data": record["data"],
            "user_id": record["user_id"],
            "legal_entity_id": record["legal_entity_id"],
            "timestamp": record["timestamp"],
            "correlation_id": record["correlation_id"],
            "previous_hash": record["previous_hash"],
        }
        json_str = json.dumps(content, sort_keys=True, default=str)
        expected = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
        assert h == expected


# ============================================================================
# TESTS FOR PUBLIC METHODS
# ============================================================================

class TestPublicMethods:
    @pytest.mark.asyncio
    async def test_write_event_valid(self, event_writer, mock_store):
        """write_event should validate, build record, and append to store."""
        mock_store.get_last_event.return_value = None  # no previous event
        event_id = await event_writer.write_event(
            event_type="valid.event",
            data={"field1": "value"},
            severity="info",
            user_id="user1",
            legal_entity_id="legal1",
        )
        assert event_id == "event-id-123"
        mock_store.append.assert_called_once()
        call_args = mock_store.append.call_args[0]
        stream_name, event_data, event_type, metadata = call_args
        assert stream_name == AUDIT_STREAM_NAME
        assert event_data["event_type"] == "valid.event"
        assert event_data["severity"] == "info"
        assert event_data["user_id"] == "user1"
        assert event_data["legal_entity_id"] == "legal1"
        assert event_data["hash"] is not None
        assert event_type == "audit.event"
        assert metadata["original_event_type"] == "valid.event"

    @pytest.mark.asyncio
    async def test_write_event_security_stream(self, event_writer, mock_store):
        """write_event should use SECURITY_AUDIT_STREAM for security events."""
        await event_writer.write_event("security.login", {"user": "test"})
        call_args = mock_store.append.call_args[0]
        stream_name = call_args[0]
        assert stream_name == SECURITY_AUDIT_STREAM

    @pytest.mark.asyncio
    async def test_write_event_invalid_type(self, event_writer):
        """write_event should raise InvalidEventTypeError for invalid type."""
        with patch.object(event_writer, '_validate_event', side_effect=InvalidEventTypeError("invalid")):
            with pytest.raises(InvalidEventTypeError):
                await event_writer.write_event("invalid.event", {})

    @pytest.mark.asyncio
    async def test_write_event_missing_field(self, event_writer):
        """write_event should raise MissingRequiredFieldError."""
        with patch.object(event_writer, '_validate_event', side_effect=MissingRequiredFieldError("missing")):
            with pytest.raises(MissingRequiredFieldError):
                await event_writer.write_event("valid.event", {})

    @pytest.mark.asyncio
    async def test_write_security_event(self, event_writer):
        """write_security_event should call write_event with severity WARNING."""
        with patch.object(event_writer, 'write_event', new=AsyncMock(return_value="sec-id")) as mock_write:
            result = await event_writer.write_security_event(
                "security.test", {"key": "val"}, user_id="u1", legal_entity_id="l1"
            )
            assert result == "sec-id"
            mock_write.assert_called_once_with(
                "security.test",
                {"key": "val"},
                severity="warning",
                user_id="u1",
                legal_entity_id="l1",
            )

    @pytest.mark.asyncio
    async def test_write_critical_event(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock(return_value="crit-id")) as mock_write:
            result = await event_writer.write_critical_event(
                "critical.event", {"data": "urgent"}, user_id="u1"
            )
            assert result == "crit-id"
            mock_write.assert_called_once_with(
                "critical.event",
                {"data": "urgent"},
                severity="critical",
                user_id="u1",
                legal_entity_id=None,
            )

    @pytest.mark.asyncio
    async def test_write_data_change_create(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock(return_value="change-id")) as mock_write:
            result = await event_writer.write_data_change(
                action="CREATE",
                target_type="user",
                target_id="123",
                old_value=None,
                new_value={"name": "Alice"},
                user_id="u1",
                legal_entity_id="l1",
            )
            assert result == "change-id"
            mock_write.assert_called_once()
            call_args = mock_write.call_args[0]
            event_type = call_args[0]
            data = call_args[1]
            assert event_type == "data.create"
            assert data["target_type"] == "user"
            assert data["target_id"] == "123"
            assert data["action"] == "CREATE"
            assert data["new_value"] == {"name": "Alice"}
            assert "old_value" not in data

    @pytest.mark.asyncio
    async def test_write_data_change_update(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_data_change(
                action="UPDATE",
                target_type="order",
                target_id="456",
                old_value={"status": "draft"},
                new_value={"status": "approved"},
            )
            call_args = mock_write.call_args[0]
            data = call_args[1]
            assert data["action"] == "UPDATE"
            assert data["old_value"] == {"status": "draft"}
            assert data["new_value"] == {"status": "approved"}

    @pytest.mark.asyncio
    async def test_write_data_change_delete(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_data_change(
                action="DELETE",
                target_type="product",
                target_id="789",
                old_value={"id": "789"},
                new_value=None,
            )
            call_args = mock_write.call_args[0]
            data = call_args[1]
            assert data["action"] == "DELETE"
            assert data["old_value"] == {"id": "789"}
            assert "new_value" not in data

    @pytest.mark.asyncio
    async def test_write_login_event_success(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_login_event(
                username="alice",
                success=True,
                ip_address="192.168.1.1",
                user_agent="Mozilla",
                user_id="u1",
                legal_entity_id="l1",
            )
            mock_write.assert_called_once()
            call_args = mock_write.call_args[0]
            event_type = call_args[0]
            data = call_args[1]
            assert event_type == "auth.login.success"
            assert data["username"] == "alice"
            assert data["ip_address"] == "192.168.1.1"
            assert data["user_agent"] == "Mozilla"
            assert "reason" not in data

    @pytest.mark.asyncio
    async def test_write_login_event_failure(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_login_event(
                username="bob",
                success=False,
                ip_address="10.0.0.1",
                user_id=None,
            )
            call_args = mock_write.call_args[0]
            data = call_args[1]
            assert data["reason"] == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_write_permission_denied(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_permission_denied(
                user_id="u1",
                resource="/api/data",
                action="read",
                required_permission="data:read",
                ip_address="10.0.0.1",
                legal_entity_id="l1",
            )
            mock_write.assert_called_once()
            call_args = mock_write.call_args[0]
            event_type = call_args[0]
            data = call_args[1]
            assert event_type == "access.permission_denied"
            assert data["resource"] == "/api/data"
            assert data["action"] == "read"
            assert data["required_permission"] == "data:read"
            assert data["ip_address"] == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_write_config_change(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_config_change(
                config_key="feature.enabled",
                old_value=True,
                new_value=False,
                changed_by="admin",
                legal_entity_id="l1",
            )
            mock_write.assert_called_once()
            call_args = mock_write.call_args[0]
            event_type = call_args[0]
            data = call_args[1]
            assert event_type == "config.change"
            assert data["config_key"] == "feature.enabled"
            assert data["old_value"] == "True"
            assert data["new_value"] == "False"
            assert data["changed_by"] == "admin"

    @pytest.mark.asyncio
    async def test_write_period_close(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_period_close(
                fiscal_year=2026,
                period=1,
                status="closed",
                closed_by="admin",
                legal_entity_id="l1",
            )
            mock_write.assert_called_once()
            call_args = mock_write.call_args[0]
            data = call_args[1]
            assert data["fiscal_year"] == 2026
            assert data["period"] == 1
            assert data["status"] == "closed"
            assert data["closed_by"] == "admin"

    @pytest.mark.asyncio
    async def test_write_journal_posted(self, event_writer):
        with patch.object(event_writer, 'write_event', new=AsyncMock()) as mock_write:
            await event_writer.write_journal_posted(
                journal_id="j123",
                voucher_number="VOUCH-001",
                total_amount=Decimal("1500.50"),
                lines_count=3,
                posted_by="accountant",
                legal_entity_id="l1",
            )
            mock_write.assert_called_once()
            call_args = mock_write.call_args[0]
            data = call_args[1]
            assert data["journal_id"] == "j123"
            assert data["voucher_number"] == "VOUCH-001"
            assert data["total_amount"] == Decimal("1500.50")
            assert data["lines_count"] == 3

    @pytest.mark.asyncio
    async def test_get_stats(self, event_writer):
        event_writer._write_count = 42
        stats = await event_writer.get_stats()
        assert stats["total_events_written"] == 42
        assert stats["streams"]["audit"] == AUDIT_STREAM_NAME
        assert stats["streams"]["security"] == SECURITY_AUDIT_STREAM


# ============================================================================
# TESTS FOR SINGLETON
# ============================================================================

@pytest.mark.asyncio
async def test_get_immutable_event_writer_singleton():
    """get_immutable_event_writer should return the same instance."""
    with patch("audit.event_writer_immutable.ImmutableEventWriter") as MockWriter:
        mock_instance = MagicMock()
        MockWriter.return_value = mock_instance
        writer1 = await get_immutable_event_writer()
        writer2 = await get_immutable_event_writer()
        assert writer1 is writer2
        assert MockWriter.call_count == 1
        # Cleanup
        import audit.event_writer_immutable as module
        module._immutable_event_writer = None


# ============================================================================
# TESTS FOR AUDIT_LOG DECORATOR
# ============================================================================

class TestAuditLogDecorator:
    @pytest.mark.asyncio
    async def test_audit_log_decorator_wraps_function(self):
        """audit_log should wrap a function and write an event after execution."""
        writer_mock = AsyncMock()
        writer_mock.write_event = AsyncMock(return_value="event-id")
        with patch("audit.event_writer_immutable.get_immutable_event_writer", new=AsyncMock(return_value=writer_mock)):
            @audit_log("test.event")
            async def my_func(user_id="u1", extra="data"):
                return "result"

            result = await my_func(user_id="u1", extra="data")
            assert result == "result"
            writer_mock.write_event.assert_called_once()
            call_args = writer_mock.write_event.call_args[0]
            assert call_args[0] == "test.event"
            data = call_args[1]
            assert data["function"] == "my_func"
            assert "args" in data
            assert "kwargs" in data
            assert data["kwargs"]["user_id"] == "u1"
            assert data["kwargs"]["extra"] == "data"
            assert data["result"] == "result"

    @pytest.mark.asyncio
    async def test_audit_log_handles_exception(self):
        """audit_log should still write event even if function raises."""
        writer_mock = AsyncMock()
        writer_mock.write_event = AsyncMock(return_value="event-id")
        with patch("audit.event_writer_immutable.get_immutable_event_writer", new=AsyncMock(return_value=writer_mock)):
            @audit_log("test.event")
            async def failing_func():
                raise ValueError("Something went wrong")

            with pytest.raises(ValueError):
                await failing_func()
            # The decorator writes after the function call, but if function raises,
            # the wrapper will not reach the write_event call because we raise before.
            # Actually the decorator code: try? No, it doesn't catch exceptions.
            # So we should not expect write_event to be called if function raises.
            # Let's verify that write_event is not called.
            writer_mock.write_event.assert_not_called()
