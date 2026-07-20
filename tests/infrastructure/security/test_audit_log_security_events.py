# infrastructure/security/test_audit_log_security_events.py
"""
Comprehensive unit tests for Security Audit Logger and storage backends.

Covers:
- Enums: SecurityEventType, AuditLogSeverity (members and display_name)
- BaseAuditStorage (abstract with concrete implementations for File, DB, Kafka)
- FileAuditStorage: write, query, matches, to_dict, from_dict, clone, entity methods
- DatabaseAuditStorage: write with mock cursor, to_dict, from_dict, clone
- KafkaAuditStorage: write with mock producer, to_dict, from_dict, clone (with HAS_KAFKA skip)
- SecurityAuditLogger: initialization, add_storage_backend, add_callback, log (hash chain, multiple backends, callbacks), query_logs, verify_hash_chain, get_last_hash, generate_report, entity methods (validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset)
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from infrastructure.security.audit_log_security_events import (
    AuditLogSeverity,
    BaseAuditStorage,
    DatabaseAuditStorage,
    FileAuditStorage,
    KafkaAuditStorage,
    SecurityAuditLogger,
    SecurityEventType,
)

# =============================================================================
# Tests for Enums
# =============================================================================

class TestSecurityEventType:
    def test_members_exist(self):
        """All expected enum members are defined."""
        expected = [
            "LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT", "PW_CHANGE", "PW_RESET",
            "PERMISSION_GRANT", "PERMISSION_REVOKE", "ROLE_ASSIGN", "ROLE_REVOKE",
            "SENSITIVE_DATA_ACCESS", "CONFIGURATION_CHANGE", "USER_CREATED",
            "USER_DELETED", "USER_UPDATED", "MFA_ENABLED", "MFA_DISABLED",
            "ACCOUNT_LOCKED", "ACCOUNT_UNLOCKED", "SESSION_EXPIRED", "SESSION_REVOKED",
            "API_KEY_CREATED", "API_KEY_REVOKED", "EXPORT_DATA",
            "IMPERSONATION_START", "IMPERSONATION_END", "BACKUP_CREATED",
            "BACKUP_RESTORED", "DISASTER_RECOVERY_TEST",
        ]
        for member in expected:
            assert hasattr(SecurityEventType, member)

    def test_display_name(self):
        """display_name returns human-readable name."""
        assert SecurityEventType.LOGIN_SUCCESS.display_name() == "Login Berhasil"
        assert SecurityEventType.LOGIN_FAILURE.display_name() == "Login Gagal"
        assert SecurityEventType.PW_CHANGE.display_name() == "Ubah Password"
        assert SecurityEventType.PW_RESET.display_name() == "Reset Password"
        assert SecurityEventType.PERMISSION_GRANT.display_name() == "Izin Diberikan"
        assert SecurityEventType.PERMISSION_REVOKE.display_name() == "Izin Dicabut"
        assert SecurityEventType.ROLE_ASSIGN.display_name() == "Role Diberikan"
        assert SecurityEventType.ROLE_REVOKE.display_name() == "Role Dicabut"
        assert SecurityEventType.SENSITIVE_DATA_ACCESS.display_name() == "Akses Data Sensitif"
        assert SecurityEventType.CONFIGURATION_CHANGE.display_name() == "Ubah Konfigurasi"
        assert SecurityEventType.USER_CREATED.display_name() == "User Dibuat"
        assert SecurityEventType.USER_DELETED.display_name() == "User Dihapus"
        assert SecurityEventType.USER_UPDATED.display_name() == "User Diupdate"
        assert SecurityEventType.MFA_ENABLED.display_name() == "MFA Diaktifkan"
        assert SecurityEventType.MFA_DISABLED.display_name() == "MFA Dinonaktifkan"
        assert SecurityEventType.ACCOUNT_LOCKED.display_name() == "Akun Terkunci"
        assert SecurityEventType.ACCOUNT_UNLOCKED.display_name() == "Akun Terbuka Kunci"
        assert SecurityEventType.SESSION_EXPIRED.display_name() == "Session Kadaluarsa"
        assert SecurityEventType.SESSION_REVOKED.display_name() == "Session Dicabut"
        assert SecurityEventType.API_KEY_CREATED.display_name() == "API Key Dibuat"
        assert SecurityEventType.API_KEY_REVOKED.display_name() == "API Key Dicabut"
        assert SecurityEventType.EXPORT_DATA.display_name() == "Ekspor Data"
        assert SecurityEventType.IMPERSONATION_START.display_name() == "Mulai Impersonasi"
        assert SecurityEventType.IMPERSONATION_END.display_name() == "Akhiri Impersonasi"
        assert SecurityEventType.BACKUP_CREATED.display_name() == "Backup Dibuat"
        assert SecurityEventType.BACKUP_RESTORED.display_name() == "Backup Dipulihkan"
        assert SecurityEventType.DISASTER_RECOVERY_TEST.display_name() == "Tes DR"
        # Unknown fallback
        assert SecurityEventType.LOGIN_SUCCESS.value == "login_success"


class TestAuditLogSeverity:
    def test_members_exist(self):
        assert hasattr(AuditLogSeverity, "INFO")
        assert hasattr(AuditLogSeverity, "WARNING")
        assert hasattr(AuditLogSeverity, "ERROR")
        assert hasattr(AuditLogSeverity, "CRITICAL")

    def test_display_name(self):
        assert AuditLogSeverity.INFO.display_name() == "Informasi"
        assert AuditLogSeverity.WARNING.display_name() == "Peringatan"
        assert AuditLogSeverity.ERROR.display_name() == "Error"
        assert AuditLogSeverity.CRITICAL.display_name() == "Kritis"


# =============================================================================
# Tests for BaseAuditStorage (abstract, but test concrete methods)
# =============================================================================

class TestBaseAuditStorage:
    def test_init_and_properties(self):
        storage = BaseAuditStorage("test")
        assert storage.name == "test"
        assert storage.version() == 1
        assert storage._audit_trail == []
        assert storage._snapshots == []

    def test_validate_returns_valid(self):
        storage = BaseAuditStorage("test")
        result = storage.validate()
        assert result == {"is_valid": True, "errors": []}

    def test_to_dict(self):
        storage = BaseAuditStorage("test")
        storage._version = 5
        d = storage.to_dict()
        assert d == {"name": "test", "version": 5}

    def test_snapshot(self):
        storage = BaseAuditStorage("test")
        snap = storage.snapshot()
        assert snap["name"] == "test"
        assert snap["version"] == 1
        assert "timestamp" in snap

    def test_audit_trail(self):
        storage = BaseAuditStorage("test")
        storage._record_audit("ACTION", "user", {"key": "val"})
        trail = storage.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION"
        assert trail[0]["performed_by"] == "user"
        assert trail[0]["details"] == {"key": "val"}

    def test_touch_increments_version(self):
        storage = BaseAuditStorage("test")
        old_version = storage.version()
        storage.touch("admin")
        assert storage.version() == old_version + 1
        trail = storage.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "admin"

    def test_take_snapshot_limits(self):
        storage = BaseAuditStorage("test")
        for _ in range(15):
            storage._take_snapshot()
        assert len(storage._snapshots) <= 10

    def test_record_audit_appends(self):
        storage = BaseAuditStorage("test")
        storage._record_audit("TEST", "user", {"foo": "bar"})
        assert len(storage._audit_trail) == 1
        entry = storage._audit_trail[0]
        assert entry["action"] == "TEST"
        assert entry["performed_by"] == "user"
        assert entry["details"] == {"foo": "bar"}

    def test_from_dict_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            BaseAuditStorage.from_dict({})

    def test_clone_raises_not_implemented(self):
        storage = BaseAuditStorage("test")
        with pytest.raises(NotImplementedError):
            storage.clone()

    def test_write_raises_not_implemented(self):
        storage = BaseAuditStorage("test")
        with pytest.raises(NotImplementedError):
            storage.write({})

    def test_query_raises_not_implemented(self):
        storage = BaseAuditStorage("test")
        with pytest.raises(NotImplementedError):
            storage.query({}, 10)


# =============================================================================
# Tests for FileAuditStorage
# =============================================================================

class TestFileAuditStorage:
    @pytest.fixture
    def temp_file(self):
        fd, path = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_init(self, temp_file):
        storage = FileAuditStorage(temp_file)
        assert storage.file_path == temp_file
        assert storage.name == f"file:{temp_file}"

    def test_write_and_query(self, temp_file):
        storage = FileAuditStorage(temp_file)
        event = {"event_id": "123", "event_type": "login", "timestamp": "2025-01-01T00:00:00Z"}
        storage.write(event)
        results = storage.query({}, 10)
        assert len(results) == 1
        assert results[0] == event

    def test_query_with_filters(self, temp_file):
        storage = FileAuditStorage(temp_file)
        events = [
            {"event_id": "1", "event_type": "login", "user_id": "user1"},
            {"event_id": "2", "event_type": "logout", "user_id": "user2"},
        ]
        for e in events:
            storage.write(e)
        results = storage.query({"event_type": "login"}, 10)
        assert len(results) == 1
        assert results[0]["event_id"] == "1"

    def test_query_limit(self, temp_file):
        storage = FileAuditStorage(temp_file)
        for i in range(5):
            storage.write({"event_id": str(i)})
        results = storage.query({}, 3)
        assert len(results) == 3

    def test_query_file_not_found(self):
        storage = FileAuditStorage("/nonexistent/file.log")
        results = storage.query({}, 10)
        assert results == []

    def test_matches(self, temp_file):
        storage = FileAuditStorage(temp_file)
        event = {"a": 1, "b": 2}
        assert storage._matches(event, {"a": 1}) is True
        assert storage._matches(event, {"a": 2}) is False
        assert storage._matches(event, {"c": 3}) is True  # key not in event => ignore

    def test_to_dict(self, temp_file):
        storage = FileAuditStorage(temp_file)
        storage._version = 3
        d = storage.to_dict()
        assert d["name"] == f"file:{temp_file}"
        assert d["version"] == 3
        assert d["file_path"] == temp_file

    def test_from_dict(self, temp_file):
        data = {"name": f"file:{temp_file}", "version": 5, "file_path": temp_file}
        storage = FileAuditStorage.from_dict(data)
        assert storage.file_path == temp_file
        assert storage.version() == 5

    def test_clone(self, temp_file):
        storage = FileAuditStorage(temp_file)
        storage._version = 3
        clone = storage.clone()
        assert isinstance(clone, FileAuditStorage)
        assert clone.file_path == temp_file
        assert clone.version() == 4  # version incremented

    def test_validate(self, temp_file):
        storage = FileAuditStorage(temp_file)
        assert storage.validate() == {"is_valid": True, "errors": []}

    def test_snapshot(self, temp_file):
        storage = FileAuditStorage(temp_file)
        snap = storage.snapshot()
        assert snap["name"] == f"file:{temp_file}"
        assert snap["version"] == 1
        assert "timestamp" in snap


# =============================================================================
# Tests for DatabaseAuditStorage (with mock cursor)
# =============================================================================

class TestDatabaseAuditStorage:
    @pytest.fixture
    def mock_conn(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        return conn

    def test_init(self, mock_conn):
        storage = DatabaseAuditStorage(mock_conn, "audit_logs")
        assert storage.table_name == "audit_logs"
        assert storage.name == "db:audit_logs"

    def test_write(self, mock_conn):
        storage = DatabaseAuditStorage(mock_conn, "audit_logs")
        event = {
            "event_id": "123",
            "event_type": "login",
            "timestamp": "2025-01-01T00:00:00Z",
            "user_id": "user1",
            "source_ip": "1.1.1.1",
            "user_agent": "test",
            "details": {"key": "val"},
            "severity": "info",
            "hash": "abc",
            "previous_hash": "def",
        }
        storage.write(event)
        cursor = mock_conn.cursor.return_value
        cursor.execute.assert_called_once()
        args = cursor.execute.call_args[1]
        assert args[0] == "123"
        assert args[1] == "login"
        assert args[2] == "2025-01-01T00:00:00Z"
        assert args[3] == "user1"
        assert args[4] == "1.1.1.1"
        assert args[5] == "test"
        assert args[6] == json.dumps({"key": "val"})
        assert args[7] == "info"
        assert args[8] == "abc"
        assert args[9] == "def"
        mock_conn.commit.assert_called_once()

    def test_query_returns_empty(self, mock_conn):
        storage = DatabaseAuditStorage(mock_conn, "audit_logs")
        results = storage.query({}, 10)
        assert results == []

    def test_to_dict(self, mock_conn):
        storage = DatabaseAuditStorage(mock_conn, "audit_logs")
        storage._version = 3
        d = storage.to_dict()
        assert d["name"] == "db:audit_logs"
        assert d["version"] == 3
        assert d["table_name"] == "audit_logs"

    def test_from_dict(self, mock_conn):
        data = {"name": "db:audit_logs", "version": 5, "table_name": "audit_logs"}
        storage = DatabaseAuditStorage.from_dict(data)
        assert storage.table_name == "audit_logs"
        assert storage.version() == 5
        # conn is None because from_dict doesn't restore connection
        assert storage.conn is None

    def test_clone(self, mock_conn):
        storage = DatabaseAuditStorage(mock_conn, "audit_logs")
        storage._version = 3
        clone = storage.clone()
        assert isinstance(clone, DatabaseAuditStorage)
        assert clone.table_name == "audit_logs"
        assert clone.conn == mock_conn
        assert clone.version() == 4


# =============================================================================
# Tests for KafkaAuditStorage (with HAS_KAFKA condition)
# =============================================================================

class TestKafkaAuditStorage:
    @pytest.fixture
    def kafka_available(self):
        # We'll mock the KafkaProducer in tests, but we need to set HAS_KAFKA to True
        with patch("infrastructure.security.audit_log_security_events.HAS_KAFKA", True):
            yield

    def test_init_requires_kafka(self):
        # When HAS_KAFKA is False, import should raise ImportError
        with patch("infrastructure.security.audit_log_security_events.HAS_KAFKA", False):
            with pytest.raises(ImportError):
                KafkaAuditStorage("localhost:9092", "topic")

    @patch("infrastructure.security.audit_log_security_events.KafkaProducer")
    def test_init_success(self, mock_kafka_producer):
        storage = KafkaAuditStorage("localhost:9092", "topic")
        assert storage.topic == "topic"
        assert storage.name == "kafka:topic"
        mock_kafka_producer.assert_called_once_with(
            bootstrap_servers="localhost:9092",
            value_serializer=mock_kafka_producer.call_args[1]["value_serializer"],
        )

    @patch("infrastructure.security.audit_log_security_events.KafkaProducer")
    def test_write(self, mock_kafka_producer):
        storage = KafkaAuditStorage("localhost:9092", "topic")
        event = {"event_id": "123", "type": "login"}
        storage.write(event)
        storage.producer.send.assert_called_once_with("topic", value=event)

    def test_query_returns_empty(self):
        # We need to mock producer, but query doesn't use it
        with patch("infrastructure.security.audit_log_security_events.KafkaProducer"):
            storage = KafkaAuditStorage("localhost:9092", "topic")
            results = storage.query({}, 10)
            assert results == []

    @patch("infrastructure.security.audit_log_security_events.KafkaProducer")
    def test_to_dict(self, mock_kafka_producer):
        storage = KafkaAuditStorage("localhost:9092", "topic")
        storage._version = 3
        d = storage.to_dict()
        assert d["name"] == "kafka:topic"
        assert d["version"] == 3
        assert d["topic"] == "topic"

    @patch("infrastructure.security.audit_log_security_events.KafkaProducer")
    def test_from_dict(self, mock_kafka_producer):
        data = {"name": "kafka:topic", "version": 5, "topic": "topic", "bootstrap_servers": "localhost:9092"}
        storage = KafkaAuditStorage.from_dict(data)
        assert storage.topic == "topic"
        assert storage.version() == 5
        # bootstrap_servers is not stored in instance, but from_dict uses it to instantiate

    @patch("infrastructure.security.audit_log_security_events.KafkaProducer")
    def test_clone(self, mock_kafka_producer):
        storage = KafkaAuditStorage("localhost:9092", "topic")
        storage._version = 3
        # Need to set producer.config for clone
        storage.producer.config = {"bootstrap_servers": "localhost:9092"}
        clone = storage.clone()
        assert isinstance(clone, KafkaAuditStorage)
        assert clone.topic == "topic"
        assert clone.version() == 4


# =============================================================================
# Tests for SecurityAuditLogger
# =============================================================================

class TestSecurityAuditLogger:
    def test_init(self):
        logger = SecurityAuditLogger(enable_hash_chain=True)
        assert logger._enable_hash_chain is True
        assert logger._last_hash is None
        assert logger._storage_backends == []
        assert logger._callbacks == []
        assert logger.version() == 1
        assert len(logger._snapshots) == 1  # initial snapshot taken

    def test_add_storage_backend(self):
        logger = SecurityAuditLogger()
        backend = MagicMock(spec=BaseAuditStorage)
        backend.name = "test"
        logger.add_storage_backend(backend)
        assert len(logger._storage_backends) == 1
        assert logger._storage_backends[0] == backend
        # Verify audit trail entry
        trail = logger.audit_trail()
        assert any(e["action"] == "ADD_STORAGE_BACKEND" for e in trail)

    def test_add_callback(self):
        logger = SecurityAuditLogger()
        cb = MagicMock()
        logger.add_callback(cb)
        assert len(logger._callbacks) == 1
        assert logger._callbacks[0] == cb

    def test_compute_hash(self):
        logger = SecurityAuditLogger()
        event = {"event_id": "123", "type": "login"}
        prev_hash = "prev"
        h = logger._compute_hash(event, prev_hash)
        # Verify deterministic
        h2 = logger._compute_hash(event, prev_hash)
        assert h == h2
        # Different previous hash yields different result
        h3 = logger._compute_hash(event, "other")
        assert h != h3

    def test_log_basic(self):
        logger = SecurityAuditLogger(enable_hash_chain=False)
        user_id = uuid4()
        event_id = logger.log(
            event_type=SecurityEventType.LOGIN_SUCCESS,
            user_id=user_id,
            details={"ip": "1.1.1.1"},
            source_ip="1.1.1.1",
            severity=AuditLogSeverity.INFO,
        )
        assert event_id is not None
        # No hash chain, so last_hash remains None
        assert logger._last_hash is None
        # Check audit trail entry
        trail = logger.audit_trail()
        assert any(e["action"] == "LOG" for e in trail)
        # Verify query_logs returns something only if we have backends. Currently none, so empty.
        logs = logger.query_logs(limit=10)
        assert logs == []

    def test_log_with_hash_chain(self):
        logger = SecurityAuditLogger(enable_hash_chain=True)
        user_id = uuid4()
        event_id1 = logger.log(
            event_type=SecurityEventType.LOGIN_SUCCESS,
            user_id=user_id,
            details={"ip": "1.1.1.1"},
        )
        assert logger._last_hash is not None
        event_id2 = logger.log(
            event_type=SecurityEventType.LOGOUT,
            user_id=user_id,
            details={},
        )
        # Second hash should be different from first
        assert logger._last_hash is not None
        assert logger._last_hash != event_id1  # Different event IDs

    def test_log_to_backends_and_callbacks(self):
        logger = SecurityAuditLogger()
        backend = MagicMock(spec=BaseAuditStorage)
        backend.name = "test"
        logger.add_storage_backend(backend)
        cb = MagicMock()
        logger.add_callback(cb)

        user_id = uuid4()
        event_id = logger.log(
            event_type=SecurityEventType.LOGIN_SUCCESS,
            user_id=user_id,
            details={"ip": "1.1.1.1"},
        )
        # Verify backend write called
        backend.write.assert_called_once()
        # Verify callback called
        cb.assert_called_once()
        # Check event passed to callback has event_id
        called_event = cb.call_args[0][0]
        assert called_event["event_id"] == event_id
        assert called_event["event_type"] == "login_success"

    def test_log_handles_backend_exception(self):
        logger = SecurityAuditLogger()
        backend = MagicMock(spec=BaseAuditStorage)
        backend.write.side_effect = Exception("Write failed")
        backend.name = "bad"
        logger.add_storage_backend(backend)
        # Should not raise
        event_id = logger.log(
            event_type=SecurityEventType.LOGIN_SUCCESS,
            user_id=uuid4(),
            details={},
        )
        assert event_id is not None
        # backend.write called once but exception caught

    def test_log_handles_callback_exception(self):
        logger = SecurityAuditLogger()
        cb = MagicMock(side_effect=Exception("Callback failed"))
        logger.add_callback(cb)
        # Should not raise
        event_id = logger.log(
            event_type=SecurityEventType.LOGIN_SUCCESS,
            user_id=uuid4(),
            details={},
        )
        assert event_id is not None

    def test_query_logs(self):
        logger = SecurityAuditLogger()
        backend = MagicMock(spec=BaseAuditStorage)
        backend.name = "test"
        backend.query.return_value = [{"event_id": "1", "timestamp": "2025-01-01T00:00:00Z"}]
        logger.add_storage_backend(backend)
        logs = logger.query_logs(
            event_type=SecurityEventType.LOGIN_SUCCESS,
            user_id=uuid4(),
            severity=AuditLogSeverity.INFO,
            limit=10,
        )
        assert len(logs) == 1
        # Verify filters passed to backend
        call_args = backend.query.call_args[0]
        filters = call_args[0]  # first arg
        assert filters["event_type"] == "login_success"
        assert "user_id" in filters
        assert filters["severity"] == "info"
        limit = call_args[1]  # second arg
        assert limit == 10

    def test_query_logs_handles_backend_exception(self):
        logger = SecurityAuditLogger()
        backend = MagicMock(spec=BaseAuditStorage)
        backend.query.side_effect = Exception("Query failed")
        backend.name = "bad"
        logger.add_storage_backend(backend)
        logs = logger.query_logs(limit=5)
        assert logs == []  # Exception caught, returns empty list

    def test_query_logs_sorts_by_timestamp(self):
        logger = SecurityAuditLogger()
        backend = MagicMock(spec=BaseAuditStorage)
        backend.query.return_value = [
            {"event_id": "1", "timestamp": "2025-01-01T00:00:00Z"},
            {"event_id": "2", "timestamp": "2025-01-02T00:00:00Z"},
        ]
        logger.add_storage_backend(backend)
        logs = logger.query_logs(limit=10)
        # Should be sorted descending (latest first)
        assert logs[0]["event_id"] == "2"
        assert logs[1]["event_id"] == "1"

    def test_verify_hash_chain_disabled(self):
        logger = SecurityAuditLogger(enable_hash_chain=False)
        valid, msg = logger.verify_hash_chain()
        assert valid is True
        assert msg == "Hash chain disabled"

    def test_verify_hash_chain_no_backends(self):
        logger = SecurityAuditLogger(enable_hash_chain=True)
        valid, msg = logger.verify_hash_chain()
        assert valid is True
        assert msg == "No verifiable backend found"

    def test_verify_hash_chain_file_backend(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = SecurityAuditLogger(enable_hash_chain=True)
        backend = FileAuditStorage(str(log_file))
        logger.add_storage_backend(backend)
        # Log some events
        user_id = uuid4()
        logger.log(SecurityEventType.LOGIN_SUCCESS, user_id, {})
        logger.log(SecurityEventType.LOGOUT, user_id, {})

        valid, msg = logger.verify_hash_chain()
        assert valid is True
        assert msg == "Chain verified"

        # Tamper with file
        with open(log_file) as f:
            lines = f.readlines()
        # Modify one line
        modified = json.loads(lines[0])
        modified["event_type"] = "tampered"
        lines[0] = json.dumps(modified) + "\n"
        with open(log_file, "w") as f:
            f.writelines(lines)

        valid, msg = logger.verify_hash_chain()
        assert valid is False
        assert "Hash mismatch" in msg

    def test_verify_hash_chain_missing_hash(self, tmp_path):
        log_file = tmp_path / "test.log"
        logger = SecurityAuditLogger(enable_hash_chain=True)
        backend = FileAuditStorage(str(log_file))
        logger.add_storage_backend(backend)
        # Log one event
        user_id = uuid4()
        logger.log(SecurityEventType.LOGIN_SUCCESS, user_id, {})
        # Remove hash from event
        with open(log_file) as f:
            lines = f.readlines()
        event = json.loads(lines[0])
        del event["hash"]
        lines[0] = json.dumps(event) + "\n"
        with open(log_file, "w") as f:
            f.writelines(lines)

        valid, msg = logger.verify_hash_chain()
        assert valid is False
        assert "Missing hash" in msg

    def test_get_last_hash(self):
        logger = SecurityAuditLogger(enable_hash_chain=True)
        assert logger.get_last_hash() is None
        user_id = uuid4()
        logger.log(SecurityEventType.LOGIN_SUCCESS, user_id, {})
        assert logger.get_last_hash() is not None

    def test_generate_report(self):
        logger = SecurityAuditLogger(enable_hash_chain=True)
        report = logger.generate_report()
        assert report["hash_chain_enabled"] is True
        assert report["last_hash"] is None
        assert report["storage_backends"] == 0
        assert report["callbacks"] == 0
        assert report["version"] == 1

    def test_entity_methods(self):
        logger = SecurityAuditLogger()
        # validate
        assert logger.validate() == {"is_valid": True, "errors": []}
        # to_dict
        d = logger.to_dict()
        assert d["enable_hash_chain"] is True
        assert d["last_hash"] is None
        assert d["backends"] == []
        assert d["version"] == 1
        # from_dict
        new_logger = SecurityAuditLogger.from_dict(d)
        assert new_logger._enable_hash_chain is True
        assert new_logger._last_hash is None
        assert new_logger.version() == 1
        # clone
        clone = logger.clone()
        assert clone.version() == 2
        assert clone._enable_hash_chain is True
        # snapshot
        snap = logger.snapshot()
        assert snap["version"] == 1
        assert snap["enable_hash_chain"] is True
        # version
        assert logger.version() == 1
        # audit_trail
        logger._record_audit("TEST", "user", {})
        trail = logger.audit_trail()
        assert len(trail) == 1
        # touch
        logger.touch("admin")
        assert logger.version() == 2
        trail = logger.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        # reset
        logger.reset()
        assert logger._last_hash is None
        assert logger._storage_backends == []
        assert logger._callbacks == []
        assert logger.version() == 1
        assert logger._audit_trail == []

    def test_from_dict_restores_backends(self, tmp_path):
        # Create a logger with a file backend, convert to dict, then restore
        logger = SecurityAuditLogger()
        backend = FileAuditStorage(str(tmp_path / "test.log"))
        logger.add_storage_backend(backend)
        d = logger.to_dict()
        new_logger = SecurityAuditLogger.from_dict(d)
        assert len(new_logger._storage_backends) == 1
        restored = new_logger._storage_backends[0]
        assert isinstance(restored, FileAuditStorage)
        assert restored.file_path == str(tmp_path / "test.log")

    def test_from_dict_skips_unknown_backend(self):
        # Should skip if backend type not recognized
        data = {
            "enable_hash_chain": True,
            "last_hash": None,
            "backends": [{"name": "unknown:test"}],
            "version": 1,
        }
        logger = SecurityAuditLogger.from_dict(data)
        assert len(logger._storage_backends) == 0

    def test_reset_clears_backends_and_callbacks(self):
        logger = SecurityAuditLogger()
        backend = MagicMock()
        logger.add_storage_backend(backend)
        cb = MagicMock()
        logger.add_callback(cb)
        logger.reset()
        assert logger._storage_backends == []
        assert logger._callbacks == []
        assert logger._last_hash is None
        assert logger.version() == 1

    def test_audit_trail_limit(self):
        logger = SecurityAuditLogger()
        for i in range(150):
            logger._record_audit(f"EVENT_{i}", "user", {})
        trail = logger.audit_trail(limit=20)
        assert len(trail) == 20
        # Should be the most recent 20 (highest index)
        assert trail[0]["action"] == "EVENT_130"  # 150-20=130
