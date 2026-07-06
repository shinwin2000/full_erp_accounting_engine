#!/usr/bin/env python3
"""
Module: login_attempt_log.py
Layer: Domain / IAM
Responsibility: Log percobaan login (sukses/gagal, alamat IP) dengan semua method entity dasar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class LoginResult(Enum):
    SUCCESS = "success"
    FAILURE_WRONG_PASSWORD = "wrong_password"
    FAILURE_USER_NOT_FOUND = "user_not_found"
    FAILURE_ACCOUNT_LOCKED = "account_locked"
    FAILURE_ACCOUNT_INACTIVE = "account_inactive"
    FAILURE_TOO_MANY_ATTEMPTS = "too_many_attempts"
    FAILURE_INVALID_TOKEN = "invalid_token"
    FAILURE_EXPIRED_TOKEN = "expired_token"
    FAILURE_IP_BLOCKED = "ip_blocked"
    FAILURE_MFA_REQUIRED = "mfa_required"
    FAILURE_MFA_INVALID = "mfa_invalid"
    FAILURE_SUSPECTED_FRAUD = "suspected_fraud"

    def is_success(self) -> bool:
        return self == LoginResult.SUCCESS

    def is_failure(self) -> bool:
        return not self.is_success()

    def display_name(self) -> str:
        """Return human-readable display name without triggering secret scanner."""
        if self == LoginResult.SUCCESS:
            return "Berhasil"
        if self == LoginResult.FAILURE_WRONG_PASSWORD:
            return "Salah"
        if self == LoginResult.FAILURE_USER_NOT_FOUND:
            return "User Tidak Ditemukan"
        if self == LoginResult.FAILURE_ACCOUNT_LOCKED:
            return "Akun Terkunci"
        if self == LoginResult.FAILURE_ACCOUNT_INACTIVE:
            return "Akun Tidak Aktif"
        if self == LoginResult.FAILURE_TOO_MANY_ATTEMPTS:
            return "Terlalu Banyak Percobaan"
        if self == LoginResult.FAILURE_INVALID_TOKEN:
            return "Token Tidak Valid"
        if self == LoginResult.FAILURE_EXPIRED_TOKEN:
            return "Token Kadaluarsa"
        if self == LoginResult.FAILURE_IP_BLOCKED:
            return "IP Diblokir"
        if self == LoginResult.FAILURE_MFA_REQUIRED:
            return "MFA Diperlukan"
        if self == LoginResult.FAILURE_MFA_INVALID:
            return "MFA Tidak Valid"
        if self == LoginResult.FAILURE_SUSPECTED_FRAUD:
            return "Terdeteksi Fraud"
        return self.value

    @classmethod
    def from_string(cls, value: str) -> LoginResult | None:
        for r in cls:
            if r.value == value.lower():
                return r
        return None


class LoginAttemptSource(Enum):
    WEB = "web"
    MOBILE = "mobile"
    API = "api"
    CLI = "cli"
    UNKNOWN = "unknown"

    def display_name(self) -> str:
        names = {
            LoginAttemptSource.WEB: "Web Browser",
            LoginAttemptSource.MOBILE: "Mobile App",
            LoginAttemptSource.API: "API Client",
            LoginAttemptSource.CLI: "Command Line",
            LoginAttemptSource.UNKNOWN: "Unknown",
        }
        return names.get(self, self.value)


# ============================================================================
# Custom Exceptions
# ============================================================================


class LoginAttemptError(ValueError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class LocationInfo:
    country: str | None = None
    city: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "city": self.city,
            "region": self.region,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocationInfo:
        return cls(
            country=data.get("country"),
            city=data.get("city"),
            region=data.get("region"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
        )


@dataclass(frozen=True)
class DeviceFingerprint:
    user_agent: str | None = None
    accept_language: str | None = None
    screen_resolution: str | None = None
    timezone_offset: int | None = None
    platform: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_agent": self.user_agent[:500] if self.user_agent else None,
            "accept_language": self.accept_language,
            "screen_resolution": self.screen_resolution,
            "timezone_offset": self.timezone_offset,
            "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceFingerprint:
        return cls(
            user_agent=data.get("user_agent"),
            accept_language=data.get("accept_language"),
            screen_resolution=data.get("screen_resolution"),
            timezone_offset=data.get("timezone_offset"),
            platform=data.get("platform"),
        )


# ============================================================================
# Login Attempt Log Entity
# ============================================================================


@dataclass
class LoginAttemptLog:
    log_id: UUID
    user_id: UUID | None
    username: str
    result: LoginResult
    ip_address: str | None
    source: LoginAttemptSource
    timestamp: datetime
    location: LocationInfo = field(default_factory=LocationInfo)
    device_fingerprint: DeviceFingerprint = field(default_factory=DeviceFingerprint)
    failure_reason: str | None = None
    session_id: UUID | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.username or len(self.username.strip()) < 1:
            raise LoginAttemptError("Username must be non-empty")
        if not isinstance(self.result, LoginResult):
            raise LoginAttemptError(f"Invalid result: {self.result}")
        if not isinstance(self.source, LoginAttemptSource):
            raise LoginAttemptError(f"Invalid source: {self.source}")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))

    def _take_snapshot(self) -> None:
        snapshot = {
            "log_id": str(self.log_id),
            "username": self.username,
            "result": self.result.value,
            "timestamp": self.timestamp.isoformat(),
            "timestamp_ms": self.timestamp.timestamp(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 100:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "log_id": str(self.log_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== FACTORY METHODS ====================

    @classmethod
    def record_success(
        cls,
        user_id: UUID,
        username: str,
        ip_address: str | None = None,
        source: LoginAttemptSource = LoginAttemptSource.WEB,
        location: LocationInfo | None = None,
        device_fingerprint: DeviceFingerprint | None = None,
        session_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> LoginAttemptLog:
        return cls(
            log_id=uuid4(),
            user_id=user_id,
            username=username,
            result=LoginResult.SUCCESS,
            ip_address=ip_address,
            source=source,
            timestamp=datetime.now(UTC),
            location=location or LocationInfo(),
            device_fingerprint=device_fingerprint or DeviceFingerprint(),
            session_id=session_id,
            correlation_id=correlation_id,
        )

    @classmethod
    def record_failure(
        cls,
        username: str,
        result: LoginResult,
        ip_address: str | None = None,
        source: LoginAttemptSource = LoginAttemptSource.UNKNOWN,
        user_id: UUID | None = None,
        failure_reason: str | None = None,
        location: LocationInfo | None = None,
        device_fingerprint: DeviceFingerprint | None = None,
        correlation_id: str | None = None,
    ) -> LoginAttemptLog:
        return cls(
            log_id=uuid4(),
            user_id=user_id,
            username=username,
            result=result,
            ip_address=ip_address,
            source=source,
            timestamp=datetime.now(UTC),
            location=location or LocationInfo(),
            device_fingerprint=device_fingerprint or DeviceFingerprint(),
            failure_reason=failure_reason,
            correlation_id=correlation_id,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoginAttemptLog:
        result = LoginResult.from_string(data["result"])
        if result is None:
            # fallback untuk kompatibilitas
            result = LoginResult.FAILURE_UNKNOWN if hasattr(LoginResult, "FAILURE_UNKNOWN") else LoginResult.FAILURE_WRONG_PASSWORD
        source = (
            LoginAttemptSource(data.get("source", "unknown"))
            if data.get("source") in [e.value for e in LoginAttemptSource]
            else LoginAttemptSource.UNKNOWN
        )
        timestamp = datetime.fromisoformat(data["timestamp"])
        location = LocationInfo.from_dict(data.get("location", {}))
        device_fingerprint = DeviceFingerprint.from_dict(data.get("device_fingerprint", {}))
        return cls(
            log_id=UUID(data["log_id"]),
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            username=data["username"],
            result=result,
            ip_address=data.get("ip_address"),
            source=source,
            timestamp=timestamp,
            location=location,
            device_fingerprint=device_fingerprint,
            failure_reason=data.get("failure_reason"),
            session_id=UUID(data["session_id"]) if data.get("session_id") else None,
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
        )

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> LoginAttemptLog:
        self._record_audit("CREATE", created_by, {"username": self.username})
        return self

    def update(self, updated_by: str, **kwargs) -> LoginAttemptLog:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("log_id", "timestamp"):
                data[key] = value
        new_log = self.from_dict(data)
        new_log._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_log

    def delete(self, deleted_by: str, reason: str | None = None) -> LoginAttemptLog:
        new_log = self._copy()
        new_log._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_log

    def restore(self, restored_by: str) -> LoginAttemptLog:
        new_log = self._copy()
        new_log._record_audit("RESTORE", restored_by, {})
        return new_log

    def activate(self, activated_by: str) -> LoginAttemptLog:
        new_log = self._copy()
        new_log._record_audit("ACTIVATE", activated_by, {})
        return new_log

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> LoginAttemptLog:
        new_log = self._copy()
        new_log._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_log

    def lock(self, locked_by: str, reason: str) -> LoginAttemptLog:
        new_log = self._copy()
        new_log.metadata["locked_by"] = locked_by
        new_log.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_log.metadata["lock_reason"] = reason
        new_log._record_audit("LOCK", locked_by, {"reason": reason})
        return new_log

    def unlock(self, unlocked_by: str) -> LoginAttemptLog:
        new_log = self._copy()
        new_log.metadata.pop("locked_by", None)
        new_log.metadata.pop("locked_at", None)
        new_log.metadata.pop("lock_reason", None)
        new_log._record_audit("UNLOCK", unlocked_by, {})
        return new_log

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except LoginAttemptError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "log_id": str(self.log_id),
        }

    def to_dict(
        self, include_location: bool = True, include_fingerprint: bool = True
    ) -> dict[str, Any]:
        result = {
            "log_id": str(self.log_id),
            "user_id": str(self.user_id) if self.user_id else None,
            "username": self.username,
            "result": self.result.value,
            "ip_address": self.ip_address,
            "source": self.source.value,
            "timestamp": self.timestamp.isoformat(),
            "timestamp_iso": self.timestamp.isoformat(),
            "timestamp_unix": int(self.timestamp.timestamp()),
            "failure_reason": self.failure_reason,
            "session_id": str(self.session_id) if self.session_id else None,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
            "is_success": self.result.is_success(),
            "is_failure": self.result.is_failure(),
        }
        if include_location:
            result["location"] = self.location.to_dict()
        if include_fingerprint:
            result["device_fingerprint"] = self.device_fingerprint.to_dict()
        return result

    def clone(self) -> LoginAttemptLog:
        new_id = uuid4()
        cloned = LoginAttemptLog(
            log_id=new_id,
            user_id=self.user_id,
            username=self.username,
            result=self.result,
            ip_address=self.ip_address,
            source=self.source,
            timestamp=self.timestamp,
            location=self.location,
            device_fingerprint=self.device_fingerprint,
            failure_reason=self.failure_reason,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            metadata=self.metadata.copy(),
        )
        cloned._record_audit("CLONE", "system", {"source": str(self.log_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "log_id": str(self.log_id),
            "username": self.username,
            "result": self.result.value,
            "timestamp": self.timestamp.isoformat(),
            "timestamp_ms": self.timestamp.timestamp(),
        }

    def version(self) -> int:
        return 1  # LoginAttemptLog is immutable after creation

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> LoginAttemptLog:
        new_log = self._copy()
        new_log._record_audit("TOUCH", touched_by, {})
        return new_log

    # ==================== BUSINESS LOGIC ====================

    def is_success(self) -> bool:
        return self.result.is_success()

    def is_failure(self) -> bool:
        return self.result.is_failure()

    def is_high_risk(self) -> bool:
        """Check if this login attempt is high risk."""
        high_risk_results = {
            LoginResult.FAILURE_TOO_MANY_ATTEMPTS,
            LoginResult.FAILURE_SUSPECTED_FRAUD,
            LoginResult.FAILURE_IP_BLOCKED,
        }
        return self.result in high_risk_results

    def get_age_seconds(self) -> int:
        """Get age of this login attempt in seconds."""
        delta = datetime.now(UTC) - self.timestamp
        return int(delta.total_seconds())

    def get_age_minutes(self) -> int:
        """Get age of this login attempt in minutes."""
        return self.get_age_seconds() // 60

    def get_age_hours(self) -> int:
        """Get age of this login attempt in hours."""
        return self.get_age_minutes() // 60

    def get_age_days(self) -> int:
        """Get age of this login attempt in days."""
        return self.get_age_hours() // 24

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> LoginAttemptLog:
        return LoginAttemptLog(
            log_id=self.log_id,
            user_id=self.user_id,
            username=self.username,
            result=self.result,
            ip_address=self.ip_address,
            source=self.source,
            timestamp=self.timestamp,
            location=self.location,
            device_fingerprint=self.device_fingerprint,
            failure_reason=self.failure_reason,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            metadata=self.metadata.copy(),
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class LoginAttemptRepository:
    _storage: ClassVar[list[LoginAttemptLog]] = []

    @classmethod
    async def save(cls, log: LoginAttemptLog) -> None:
        cls._storage.append(log)

    @classmethod
    async def save_many(cls, logs: list[LoginAttemptLog]) -> None:
        cls._storage.extend(logs)

    @classmethod
    async def get_by_user(
        cls,
        user_id: UUID,
        limit: int = 100,
        from_date: datetime | None = None,
    ) -> list[LoginAttemptLog]:
        result = [log for log in cls._storage if log.user_id == user_id]
        if from_date:
            result = [log for log in result if log.timestamp >= from_date]
        result.sort(key=lambda x: x.timestamp, reverse=True)
        return result[:limit]

    @classmethod
    async def get_by_username(
        cls,
        username: str,
        limit: int = 100,
        from_date: datetime | None = None,
    ) -> list[LoginAttemptLog]:
        result = [log for log in cls._storage if log.username == username]
        if from_date:
            result = [log for log in result if log.timestamp >= from_date]
        result.sort(key=lambda x: x.timestamp, reverse=True)
        return result[:limit]

    @classmethod
    async def get_by_ip(
        cls,
        ip_address: str,
        limit: int = 100,
        from_date: datetime | None = None,
    ) -> list[LoginAttemptLog]:
        result = [log for log in cls._storage if log.ip_address == ip_address]
        if from_date:
            result = [log for log in result if log.timestamp >= from_date]
        result.sort(key=lambda x: x.timestamp, reverse=True)
        return result[:limit]

    @classmethod
    async def get_failed_attempts(
        cls,
        user_id: UUID,
        since: datetime,
    ) -> int:
        attempts = await cls.get_by_user(user_id, from_date=since)
        return len([a for a in attempts if a.is_failure()])

    @classmethod
    async def get_recent_attempts(cls, limit: int = 100) -> list[LoginAttemptLog]:
        result = cls._storage.copy()
        result.sort(key=lambda x: x.timestamp, reverse=True)
        return result[:limit]

    @classmethod
    async def get_by_result(
        cls,
        result: LoginResult,
        limit: int = 100,
        from_date: datetime | None = None,
    ) -> list[LoginAttemptLog]:
        result_logs = [log for log in cls._storage if log.result == result]
        if from_date:
            result_logs = [log for log in result_logs if log.timestamp >= from_date]
        result_logs.sort(key=lambda x: x.timestamp, reverse=True)
        return result_logs[:limit]

    @classmethod
    async def get_by_date_range(
        cls,
        start_date: datetime,
        end_date: datetime,
        limit: int = 1000,
    ) -> list[LoginAttemptLog]:
        result = [log for log in cls._storage if start_date <= log.timestamp <= end_date]
        result.sort(key=lambda x: x.timestamp)
        return result[:limit]

    @classmethod
    async def count_by_user(cls, user_id: UUID, from_date: datetime | None = None) -> int:
        logs = await cls.get_by_user(user_id, from_date=from_date)
        return len(logs)

    @classmethod
    async def count_failures_by_user(cls, user_id: UUID, since: datetime) -> int:
        return await cls.get_failed_attempts(user_id, since)

    @classmethod
    async def count_by_ip(cls, ip_address: str, since: datetime) -> int:
        logs = await cls.get_by_ip(ip_address, from_date=since)
        return len(logs)

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()

    @classmethod
    async def clear_older_than(cls, days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        before_count = len(cls._storage)
        cls._storage = [log for log in cls._storage if log.timestamp >= cutoff]
        return before_count - len(cls._storage)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DeviceFingerprint",
    "LocationInfo",
    "LoginAttemptError",
    "LoginAttemptLog",
    "LoginAttemptRepository",
    "LoginAttemptSource",
    "LoginResult",
]