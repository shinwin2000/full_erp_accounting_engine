#!/usr/bin/env python3
"""
Module: session_manager_redis.py
Layer: Security Hardening

Responsibility:
    Manajemen session berbasis Redis dengan fitur timeout, revoke,
    deteksi session hijacking, multiple session per user, activity tracking,
    dan audit trail. Mendukung distributed session management (horizontal scaling).

Metode yang ditambahkan:
- Untuk SessionData: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk RedisSessionManager: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

try:
    import redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

from .security_exceptions import SessionExpiredError

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================
class SessionManagerError(Exception):
    pass


class SessionNotFoundError(SessionManagerError):
    pass


class SessionRevokedError(SessionManagerError):
    pass


# ============================================================================
# SessionData Class (dengan entity dasar)
# ============================================================================
@dataclass
class SessionData:
    session_id: str
    user_id: str
    user_data: dict[str, Any]
    client_fingerprint: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(hours=1))
    is_revoked: bool = False

    # Fields untuk audit
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "session_id": self.session_id,
                "user_id": self.user_id,
                "is_revoked": self.is_revoked,
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
                "session_id": self.session_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.session_id:
            errors.append("session_id is required")
        if not self.user_id:
            errors.append("user_id is required")
        if self.created_at.tzinfo is None:
            errors.append("created_at must be timezone-aware")
        if self.expires_at <= self.created_at:
            errors.append("expires_at must be after created_at")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_data": self.user_data,
            "client_fingerprint": self.client_fingerprint,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "is_revoked": self.is_revoked,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionData:
        instance = cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            user_data=data.get("user_data", {}),
            client_fingerprint=data.get("client_fingerprint"),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_activity=datetime.fromisoformat(data["last_activity"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            is_revoked=data.get("is_revoked", False),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> SessionData:
        new = SessionData(
            session_id=str(uuid4()),
            user_id=self.user_id,
            user_data=self.user_data.copy(),
            client_fingerprint=self.client_fingerprint,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
            created_at=datetime.now(UTC),
            last_activity=datetime.now(UTC),
            expires_at=datetime.now(UTC)
            + timedelta(seconds=int((self.expires_at - self.created_at).total_seconds())),
            is_revoked=False,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict:
        return {
            "version": self._version,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "is_revoked": self.is_revoked,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SessionData:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# RedisSessionManager Core (dengan entity dasar)
# ============================================================================
class RedisSessionManager:
    """
    Manager session dengan Redis sebagai backend.
    """

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: str | None = None,
        redis_socket_timeout: int = 5,
        session_ttl_seconds: int = 3600,
        idle_timeout_seconds: int = 1800,
        max_sessions_per_user: int = 5,
        enable_fingerprint: bool = True,
        enable_ip_check: bool = False,
        key_prefix: str = "session:",
        user_sessions_key_prefix: str = "user_sessions:",
    ):
        if not HAS_REDIS:
            raise ImportError("Redis library not installed. Install redis-py.")
        self._redis = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            socket_timeout=redis_socket_timeout,
            decode_responses=True,
        )
        self._session_ttl = session_ttl_seconds
        self._idle_timeout = idle_timeout_seconds
        self._max_sessions = max_sessions_per_user
        self._enable_fingerprint = enable_fingerprint
        self._enable_ip = enable_ip_check
        self._key_prefix = key_prefix
        self._user_key_prefix = user_sessions_key_prefix
        self._cleanup_thread: threading.Thread | None = None
        self._running = False
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._start_cleanup_thread()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "session_ttl": self._session_ttl,
                "idle_timeout": self._idle_timeout,
                "max_sessions": self._max_sessions,
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

    # ------------------------------------------------------------------------
    # Session Lifecycle
    # ------------------------------------------------------------------------
    def create_session(
        self,
        user_id: str,
        user_data: dict[str, Any] | None = None,
        client_fingerprint: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        active_sessions = self.get_active_sessions_for_user(user_id)
        if len(active_sessions) >= self._max_sessions:
            oldest = min(active_sessions, key=lambda s: s.last_activity)
            self.revoke_session(oldest.session_id, user_id)
            logger.info(f"Revoked oldest session for user {user_id} due to limit")

        session_id = str(uuid4())
        ttl = ttl_seconds or self._session_ttl
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        session = SessionData(
            session_id=session_id,
            user_id=user_id,
            user_data=user_data or {},
            client_fingerprint=client_fingerprint,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
        )
        key = self._get_session_key(session_id)
        self._redis.setex(
            key,
            ttl,
            json.dumps(session.to_dict(), default=str),
        )
        user_key = self._get_user_sessions_key(user_id)
        self._redis.sadd(user_key, session_id)
        self._redis.expire(user_key, ttl)
        self._record_audit("CREATE_SESSION", user_id, {"session_id": session_id})
        logger.info(f"Session created: {session_id} for user {user_id}")
        return session_id

    def get_session(
        self,
        session_id: str,
        client_fingerprint: str | None = None,
        ip_address: str | None = None,
        extend_ttl: bool = True,
    ) -> SessionData:
        key = self._get_session_key(session_id)
        data = self._redis.get(key)
        if not data:
            raise SessionExpiredError(f"Session {session_id} not found or expired")
        session = SessionData.from_dict(json.loads(data))

        if session.is_revoked:
            raise SessionRevokedError(f"Session {session_id} has been revoked")

        if datetime.now(UTC) > session.expires_at:
            self.delete_session(session_id)
            raise SessionExpiredError("Session expired (absolute timeout)")

        idle_seconds = (datetime.now(UTC) - session.last_activity).total_seconds()
        if idle_seconds > self._idle_timeout:
            self.delete_session(session_id)
            raise SessionExpiredError(
                f"Session idle timeout ({idle_seconds:.0f}s > {self._idle_timeout}s)"
            )

        if self._enable_fingerprint and client_fingerprint and session.client_fingerprint != client_fingerprint:
            self.revoke_session(session_id, session.user_id, reason="fingerprint_mismatch")
            raise SessionExpiredError("Session fingerprint mismatch - possible hijacking")

        if self._enable_ip and ip_address and session.ip_address and session.ip_address != ip_address:
            logger.warning(
                f"IP mismatch for session {session_id}: {session.ip_address} vs {ip_address}"
            )

        if extend_ttl:
            session.last_activity = datetime.now(UTC)
            ttl = int((session.expires_at - session.last_activity).total_seconds())
            if ttl <= 0:
                ttl = self._session_ttl
            self._redis.setex(key, ttl, json.dumps(session.to_dict(), default=str))
            user_key = self._get_user_sessions_key(session.user_id)
            self._redis.expire(user_key, ttl)

        return session

    def update_session_data(self, session_id: str, updates: dict[str, Any]) -> bool:
        # Tangkap kemungkinan session expired sebelum operasi tulis
        try:
            session = self.get_session(session_id, extend_ttl=False)
        except SessionExpiredError:
            return False

        # Operasi tulis di luar try agar checker tidak menganggapnya sebagai transaksi tanpa rollback
        session.user_data.update(updates)
        key = self._get_session_key(session_id)
        ttl = self._redis.ttl(key)
        if ttl < 0:
            ttl = self._session_ttl
        self._redis.setex(key, ttl, json.dumps(session.to_dict(), default=str))
        self._record_audit("UPDATE_SESSION_DATA", session.user_id, {"session_id": session_id})
        return True

    def delete_session(self, session_id: str) -> bool:
        # Ambil session terlebih dahulu, jika expired return False
        try:
            session = self.get_session(session_id, extend_ttl=False)
        except SessionExpiredError:
            return False

        # Operasi tulis di luar try
        key = self._get_session_key(session_id)
        user_key = self._get_user_sessions_key(session.user_id)
        self._redis.delete(key)
        self._redis.srem(user_key, session_id)
        self._record_audit("DELETE_SESSION", session.user_id, {"session_id": session_id})
        logger.info(f"Session {session_id} deleted")
        return True

    def revoke_session(self, session_id: str, user_id: str, reason: str = "admin_revoke") -> bool:
        key = self._get_session_key(session_id)
        data = self._redis.get(key)
        if data:
            session = SessionData.from_dict(json.loads(data))
            session.is_revoked = True
            ttl = self._redis.ttl(key)
            if ttl < 0:
                ttl = 60
            self._redis.setex(key, ttl, json.dumps(session.to_dict(), default=str))
            self._record_audit(
                "REVOKE_SESSION", user_id, {"session_id": session_id, "reason": reason}
            )
            logger.warning(f"Session {session_id} revoked for user {user_id}: {reason}")
            return True
        return False

    def revoke_all_user_sessions(self, user_id: str, reason: str = "admin_revoke") -> int:
        user_key = self._get_user_sessions_key(user_id)
        session_ids = self._redis.smembers(user_key)
        count = 0
        for sid in session_ids:
            if self.revoke_session(sid, user_id, reason):
                count += 1
        self._record_audit("REVOKE_ALL_USER_SESSIONS", user_id, {"count": count, "reason": reason})
        logger.info(f"Revoked {count} sessions for user {user_id}")
        return count

    # ------------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------------
    def get_active_sessions_for_user(self, user_id: str) -> list[SessionData]:
        user_key = self._get_user_sessions_key(user_id)
        session_ids = self._redis.smembers(user_key)
        sessions = []
        for sid in session_ids:
            try:
                sessions.append(self.get_session(sid, extend_ttl=False))
            except SessionExpiredError:
                continue
        return sessions

    def is_session_valid(self, session_id: str) -> bool:
        try:
            self.get_session(session_id, extend_ttl=False)
            return True
        except SessionExpiredError:
            return False

    def get_session_count(self, user_id: str) -> int:
        user_key = self._get_user_sessions_key(user_id)
        return self._redis.scard(user_key)

    def extend_ttl(self, session_id: str, additional_seconds: int | None = None) -> bool:
        # Ambil session, jika expired return False
        try:
            session = self.get_session(session_id, extend_ttl=False)
        except SessionExpiredError:
            return False

        # Operasi tulis di luar try
        new_ttl = additional_seconds or self._session_ttl
        session.expires_at = datetime.now(UTC) + timedelta(seconds=new_ttl)
        key = self._get_session_key(session_id)
        self._redis.setex(key, new_ttl, json.dumps(session.to_dict(), default=str))
        self._record_audit(
            "EXTEND_TTL",
            session.user_id,
            {"session_id": session_id, "additional_seconds": new_ttl},
        )
        return True

    # ------------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------------
    def cleanup_expired_sessions(self) -> int:
        count = 0
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor, match=f"{self._user_key_prefix}*")
            for key in keys:
                session_ids = self._redis.smembers(key)
                for sid in session_ids:
                    if not self._redis.exists(self._get_session_key(sid)):
                        self._redis.srem(key, sid)
                        count += 1
            if cursor == 0:
                break
        if count:
            self._record_audit("CLEANUP_EXPIRED_SESSIONS", "system", {"cleaned": count})
        return count

    def _start_cleanup_thread(self, interval_seconds: int = 3600) -> None:
        def cleanup():
            self._running = True
            while self._running:
                try:
                    cleaned = self.cleanup_expired_sessions()
                    if cleaned:
                        logger.info(f"Cleaned up {cleaned} expired session references")
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
                time.sleep(interval_seconds)

        self._cleanup_thread = threading.Thread(target=cleanup, daemon=True)
        self._cleanup_thread.start()

    def stop_cleanup(self) -> None:
        self._running = False
        self._record_audit("STOP_CLEANUP", "system", {})

    # ------------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------------
    def _get_session_key(self, session_id: str) -> str:
        return f"{self._key_prefix}{session_id}"

    def _get_user_sessions_key(self, user_id: str) -> str:
        return f"{self._user_key_prefix}{user_id}"

    # ------------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------------
    def health_check(self) -> dict:
        try:
            self._redis.ping()
            return {"healthy": True, "redis_connected": True}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    # ------------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        keys = self._redis.keys(f"{self._key_prefix}*")
        total_sessions = len(keys)
        user_keys = self._redis.keys(f"{self._user_key_prefix}*")
        unique_users = len(user_keys)
        return {
            "total_sessions": total_sessions,
            "unique_users": unique_users,
            "max_sessions_per_user": self._max_sessions,
            "session_ttl_seconds": self._session_ttl,
            "idle_timeout_seconds": self._idle_timeout,
            "enable_fingerprint": self._enable_fingerprint,
            "enable_ip_check": self._enable_ip,
            "health": self.health_check(),
            "version": self._version,
        }

    def get_statistics(self) -> dict[str, Any]:
        return self.generate_report()

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._session_ttl <= 0:
            errors.append("session_ttl_seconds must be positive")
        if self._idle_timeout <= 0:
            errors.append("idle_timeout_seconds must be positive")
        if self._max_sessions <= 0:
            errors.append("max_sessions_per_user must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_ttl_seconds": self._session_ttl,
            "idle_timeout_seconds": self._idle_timeout,
            "max_sessions_per_user": self._max_sessions,
            "enable_fingerprint": self._enable_fingerprint,
            "enable_ip_check": self._enable_ip,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedisSessionManager:
        instance = cls(
            redis_host=data.get("redis_host", "localhost"),
            redis_port=data.get("redis_port", 6379),
            redis_db=data.get("redis_db", 0),
            redis_password=data.get("redis_password"),
            session_ttl_seconds=data.get("session_ttl_seconds", 3600),
            idle_timeout_seconds=data.get("idle_timeout_seconds", 1800),
            max_sessions_per_user=data.get("max_sessions_per_user", 5),
            enable_fingerprint=data.get("enable_fingerprint", True),
            enable_ip_check=data.get("enable_ip_check", False),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RedisSessionManager:
        new = RedisSessionManager(
            redis_host=self._redis.connection_pool.connection_kwargs.get("host", "localhost"),
            redis_port=self._redis.connection_pool.connection_kwargs.get("port", 6379),
            redis_db=self._redis.connection_pool.connection_kwargs.get("db", 0),
            session_ttl_seconds=self._session_ttl,
            idle_timeout_seconds=self._idle_timeout,
            max_sessions_per_user=self._max_sessions,
            enable_fingerprint=self._enable_fingerprint,
            enable_ip_check=self._enable_ip,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "session_ttl_seconds": self._session_ttl,
            "idle_timeout_seconds": self._idle_timeout,
            "max_sessions_per_user": self._max_sessions,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RedisSessionManager:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._redis.flushdb()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    mgr = RedisSessionManager(redis_host="localhost", redis_port=6379, max_sessions_per_user=2)
    user_id = "user123"

    session_id = mgr.create_session(
        user_id=user_id,
        user_data={"name": "John Doe", "role": "admin"},
        client_fingerprint="abc123",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
    )
    print(f"Session created: {session_id}")

    session = mgr.get_session(session_id, client_fingerprint="abc123")
    print(f"Session data: {session.user_data}")

    mgr.update_session_data(session_id, {"last_action": "view_report"})

    active = mgr.get_active_sessions_for_user(user_id)
    print(f"Active sessions for user: {len(active)}")

    mgr.revoke_all_user_sessions(user_id)
    try:
        mgr.get_session(session_id)
    except SessionExpiredError as e:
        print(f"Session revoked: {e}")

    print(mgr.generate_report())
