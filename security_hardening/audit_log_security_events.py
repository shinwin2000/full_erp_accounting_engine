#!/usr/bin/env python3
"""
Module: audit_log_security_events.py
Layer: Security Hardening

Responsibility:
    Pencatatan log keamanan untuk event sensitif (login, permission change,
    data access, config change). Mendukung immutable log dengan hash chain,
    sinkronisasi ke multiple backends, query log, verifikasi hash chain, dan export.

Metode yang ditambahkan:
- Untuk SecurityAuditLogger: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk storage backends: base class dengan entity methods.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Optional Kafka support
try:
    from kafka import KafkaProducer

    HAS_KAFKA = True
except ImportError:
    HAS_KAFKA = False


# ============================================================================
# Enums
# ============================================================================
class SecurityEventType(Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET = "password_reset"
    PERMISSION_GRANT = "permission_grant"
    PERMISSION_REVOKE = "permission_revoke"
    ROLE_ASSIGN = "role_assign"
    ROLE_REVOKE = "role_revoke"
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    CONFIGURATION_CHANGE = "configuration_change"
    USER_CREATED = "user_created"
    USER_DELETED = "user_deleted"
    USER_UPDATED = "user_updated"
    MFA_ENABLED = "mfa_enabled"
    MFA_DISABLED = "mfa_disabled"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    SESSION_EXPIRED = "session_expired"
    SESSION_REVOKED = "session_revoked"
    API_KEY_CREATED = "api_key_created"
    API_KEY_REVOKED = "api_key_revoked"
    EXPORT_DATA = "export_data"
    IMPERSONATION_START = "impersonation_start"
    IMPERSONATION_END = "impersonation_end"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    DISASTER_RECOVERY_TEST = "disaster_recovery_test"

    def display_name(self) -> str:
        names = {
            SecurityEventType.LOGIN_SUCCESS: "Login Berhasil",
            SecurityEventType.LOGIN_FAILURE: "Login Gagal",
            SecurityEventType.LOGOUT: "Logout",
            SecurityEventType.PASSWORD_CHANGE: "Ubah Password",
            SecurityEventType.PASSWORD_RESET: "Reset Password",
            SecurityEventType.PERMISSION_GRANT: "Izin Diberikan",
            SecurityEventType.PERMISSION_REVOKE: "Izin Dicabut",
            SecurityEventType.ROLE_ASSIGN: "Role Diberikan",
            SecurityEventType.ROLE_REVOKE: "Role Dicabut",
            SecurityEventType.SENSITIVE_DATA_ACCESS: "Akses Data Sensitif",
            SecurityEventType.CONFIGURATION_CHANGE: "Ubah Konfigurasi",
            SecurityEventType.USER_CREATED: "User Dibuat",
            SecurityEventType.USER_DELETED: "User Dihapus",
            SecurityEventType.USER_UPDATED: "User Diupdate",
            SecurityEventType.MFA_ENABLED: "MFA Diaktifkan",
            SecurityEventType.MFA_DISABLED: "MFA Dinonaktifkan",
            SecurityEventType.ACCOUNT_LOCKED: "Akun Terkunci",
            SecurityEventType.ACCOUNT_UNLOCKED: "Akun Terbuka Kunci",
            SecurityEventType.SESSION_EXPIRED: "Session Kadaluarsa",
            SecurityEventType.SESSION_REVOKED: "Session Dicabut",
            SecurityEventType.API_KEY_CREATED: "API Key Dibuat",
            SecurityEventType.API_KEY_REVOKED: "API Key Dicabut",
            SecurityEventType.EXPORT_DATA: "Ekspor Data",
            SecurityEventType.IMPERSONATION_START: "Mulai Impersonasi",
            SecurityEventType.IMPERSONATION_END: "Akhiri Impersonasi",
            SecurityEventType.BACKUP_CREATED: "Backup Dibuat",
            SecurityEventType.BACKUP_RESTORED: "Backup Dipulihkan",
            SecurityEventType.DISASTER_RECOVERY_TEST: "Tes DR",
        }
        return names.get(self, self.value)


class AuditLogSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    def display_name(self) -> str:
        names = {
            AuditLogSeverity.INFO: "Informasi",
            AuditLogSeverity.WARNING: "Peringatan",
            AuditLogSeverity.ERROR: "Error",
            AuditLogSeverity.CRITICAL: "Kritis",
        }
        return names.get(self, self.value)


# ============================================================================
# BaseAuditStorage (dengan entity dasar)
# ============================================================================
class BaseAuditStorage:
    """Base class untuk storage backend."""

    def __init__(self, name: str):
        self.name = name
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "storage": self.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def write(self, event: dict) -> None:
        raise NotImplementedError

    def query(self, filters: dict, limit: int) -> list[dict]:
        raise NotImplementedError

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseAuditStorage:
        raise NotImplementedError

    def clone(self) -> BaseAuditStorage:
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self._version,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BaseAuditStorage:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# FileAuditStorage (dengan entity dasar)
# ============================================================================
class FileAuditStorage(BaseAuditStorage):
    def __init__(self, file_path: str):
        super().__init__(f"file:{file_path}")
        self.file_path = file_path

    def write(self, event: dict) -> None:
        import os

        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def query(self, filters: dict, limit: int) -> list[dict]:
        events = []
        try:
            with open(self.file_path) as f:
                for line in f:
                    if len(events) >= limit:
                        break
                    try:
                        event = json.loads(line.strip())
                        if self._matches(event, filters):
                            events.append(event)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return events

    def _matches(self, event: dict, filters: dict) -> bool:
        for key, value in filters.items():
            if key in event and event[key] != value:
                return False
        return True

    # ==================== ENTITY DASAR METHODS ====================
    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["file_path"] = self.file_path
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileAuditStorage:
        instance = cls(data["file_path"])
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> FileAuditStorage:
        new = FileAuditStorage(self.file_path)
        new._version = self._version + 1
        return new


# ============================================================================
# DatabaseAuditStorage (dengan entity dasar)
# ============================================================================
class DatabaseAuditStorage(BaseAuditStorage):
    def __init__(self, db_connection, table_name: str = "audit_logs"):
        super().__init__(f"db:{table_name}")
        self.conn = db_connection
        self.table_name = table_name

    def write(self, event: dict) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""INSERT INTO {self.table_name} (event_id, event_type, timestamp, user_id, source_ip, user_agent, details, severity, hash, previous_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                event["event_id"],
                event["event_type"],
                event["timestamp"],
                event.get("user_id"),
                event.get("source_ip"),
                event.get("user_agent"),
                json.dumps(event.get("details", {})),
                event.get("severity", "info"),
                event.get("hash"),
                event.get("previous_hash"),
            ),
        )
        self.conn.commit()

    def query(self, filters: dict, limit: int) -> list[dict]:
        # Simplified implementation
        return []

    # ==================== ENTITY DASAR METHODS ====================
    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["table_name"] = self.table_name
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseAuditStorage:
        instance = cls(None, data["table_name"])
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> DatabaseAuditStorage:
        new = DatabaseAuditStorage(self.conn, self.table_name)
        new._version = self._version + 1
        return new


# ============================================================================
# KafkaAuditStorage (dengan entity dasar)
# ============================================================================
class KafkaAuditStorage(BaseAuditStorage):
    def __init__(self, bootstrap_servers: str, topic: str = "security-audit"):
        super().__init__(f"kafka:{topic}")
        if not HAS_KAFKA:
            raise ImportError("kafka-python not installed")
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
        )
        self.topic = topic

    def write(self, event: dict) -> None:
        self.producer.send(self.topic, value=event)

    def query(self, filters: dict, limit: int) -> list[dict]:
        return []

    # ==================== ENTITY DASAR METHODS ====================
    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["topic"] = self.topic
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KafkaAuditStorage:
        instance = cls(data["bootstrap_servers"], data["topic"])
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> KafkaAuditStorage:
        new = KafkaAuditStorage(self.producer.config["bootstrap_servers"], self.topic)
        new._version = self._version + 1
        return new


# ============================================================================
# SecurityAuditLogger Core (dengan entity dasar)
# ============================================================================
class SecurityAuditLogger:
    """
    Logger untuk event keamanan dengan immutable hash chain.
    Mendukung multiple storage backends secara simultan.
    """

    def __init__(self, enable_hash_chain: bool = True):
        self._enable_hash_chain = enable_hash_chain
        self._last_hash: str | None = None
        self._lock = threading.RLock()
        self._storage_backends: list[BaseAuditStorage] = []
        self._callbacks: list[Callable[[dict], None]] = []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "enable_hash_chain": self._enable_hash_chain,
                "last_hash": self._last_hash,
                "backends_count": len(self._storage_backends),
                "callbacks_count": len(self._callbacks),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def add_storage_backend(self, backend: BaseAuditStorage) -> None:
        self._storage_backends.append(backend)
        self._record_audit("ADD_STORAGE_BACKEND", "system", {"backend": backend.name})

    def add_callback(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    def _compute_hash(self, event: dict, previous_hash: str | None) -> str:
        event_copy = event.copy()
        event_copy["previous_hash"] = previous_hash
        sorted_json = json.dumps(event_copy, sort_keys=True, default=str)
        return hashlib.sha256(sorted_json.encode()).hexdigest()

    def log(
        self,
        event_type: SecurityEventType,
        user_id: UUID | None,
        details: dict[str, Any],
        source_ip: str | None = None,
        user_agent: str | None = None,
        severity: AuditLogSeverity = AuditLogSeverity.INFO,
    ) -> str:
        event_id = uuid4()
        timestamp = datetime.now(UTC)
        event = {
            "event_id": str(event_id),
            "event_type": event_type.value,
            "timestamp": timestamp.isoformat() + "Z",
            "user_id": str(user_id) if user_id else None,
            "source_ip": source_ip,
            "user_agent": user_agent,
            "details": details,
            "severity": severity.value,
        }

        if self._enable_hash_chain:
            with self._lock:
                event["hash"] = self._compute_hash(event, self._last_hash)
                event["previous_hash"] = self._last_hash
                self._last_hash = event["hash"]

        # Write to all storage backends
        for backend in self._storage_backends:
            try:
                backend.write(event)
            except Exception as e:
                logger.error(f"Failed to write audit log to backend {backend.name}: {e}")

        # Trigger callbacks
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Callback failed: {e}")

        self._record_audit(
            "LOG", str(user_id), {"event_type": event_type.value, "event_id": str(event_id)}
        )
        logger.info(f"Audit event logged: {event_type.value} (id={event_id})")
        return str(event_id)

    def query_logs(
        self,
        event_type: SecurityEventType | None = None,
        user_id: UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        severity: AuditLogSeverity | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters = {}
        if event_type:
            filters["event_type"] = event_type.value
        if user_id:
            filters["user_id"] = str(user_id)
        if severity:
            filters["severity"] = severity.value
        if start_time:
            filters["timestamp_start"] = start_time.isoformat()
        if end_time:
            filters["timestamp_end"] = end_time.isoformat()

        all_results = []
        for backend in self._storage_backends:
            try:
                results = backend.query(filters, limit)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"Failed to query backend {backend.name}: {e}")
        all_results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return all_results[:limit]

    def verify_hash_chain(self) -> tuple[bool, str | None]:
        """Verifikasi integritas seluruh chain log (untuk storage yang mendukung urutan)."""
        if not self._enable_hash_chain:
            return True, "Hash chain disabled"
        for backend in self._storage_backends:
            if isinstance(backend, FileAuditStorage):
                logs = backend.query({}, 1000000)
                prev_hash = None
                for log in logs:
                    expected_hash = log.get("hash")
                    if not expected_hash:
                        return False, "Missing hash in log entry"
                    recomputed = self._compute_hash(log, log.get("previous_hash"))
                    if recomputed != expected_hash:
                        return False, f"Hash mismatch at event {log.get('event_id')}"
                    prev_hash = expected_hash
                return True, "Chain verified"
        return True, "No verifiable backend found"

    def get_last_hash(self) -> str | None:
        return self._last_hash

    def generate_report(self) -> dict:
        return {
            "hash_chain_enabled": self._enable_hash_chain,
            "last_hash": self._last_hash,
            "storage_backends": len(self._storage_backends),
            "callbacks": len(self._callbacks),
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._enable_hash_chain and not self._last_hash:
            # Genesis hash is acceptable
            pass
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_hash_chain": self._enable_hash_chain,
            "last_hash": self._last_hash,
            "backends": [b.to_dict() for b in self._storage_backends],
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityAuditLogger:
        instance = cls(enable_hash_chain=data.get("enable_hash_chain", True))
        instance._last_hash = data.get("last_hash")
        instance._version = data.get("version", 1)
        for backend_data in data.get("backends", []):
            backend_type = backend_data.get("name", "").split(":")[0]
            if backend_type == "file":
                instance.add_storage_backend(FileAuditStorage.from_dict(backend_data))
            elif backend_type == "db":
                instance.add_storage_backend(DatabaseAuditStorage.from_dict(backend_data))
            elif backend_type == "kafka":
                instance.add_storage_backend(KafkaAuditStorage.from_dict(backend_data))
        return instance

    def clone(self) -> SecurityAuditLogger:
        new = SecurityAuditLogger(enable_hash_chain=self._enable_hash_chain)
        new._last_hash = self._last_hash
        for backend in self._storage_backends:
            new.add_storage_backend(backend.clone())
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "enable_hash_chain": self._enable_hash_chain,
            "last_hash": self._last_hash[:16] + "..." if self._last_hash else None,
            "backends_count": len(self._storage_backends),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SecurityAuditLogger:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._last_hash = None
        self._storage_backends.clear()
        self._callbacks.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    logger = SecurityAuditLogger(enable_hash_chain=True)
    file_backend = FileAuditStorage("/var/log/security_audit.log")
    logger.add_storage_backend(file_backend)

    event_id = logger.log(
        event_type=SecurityEventType.LOGIN_SUCCESS,
        user_id=uuid4(),
        details={"ip": "192.168.1.1", "method": "password"},
        source_ip="192.168.1.1",
        severity=AuditLogSeverity.INFO,
    )
    print(f"Logged event: {event_id}")

    valid, msg = logger.verify_hash_chain()
    print(f"Hash chain verification: {valid} - {msg}")

    logs = logger.query_logs(limit=10)
    print(f"Retrieved {len(logs)} logs")
