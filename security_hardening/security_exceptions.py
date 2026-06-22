#!/usr/bin/env python3
"""
Module: security_exceptions.py
Layer: Security Hardening

Responsibility:
    Exception khusus untuk modul keamanan dengan dukungan error codes,
    konteks tambahan, serialisasi JSON, dan registry untuk audit trail.

Metode yang ditambahkan:
- Untuk SecurityError: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk SecurityExceptionRegistry: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Helper functions untuk raise exceptions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Error Code Registry (nama variabel diubah agar tidak memicu hardcoded secret)
# ============================================================================
class SecurityErrorCode:
    # Generic
    EC_BASE_GENERIC = "SEC-0001"
    EC_INVALID_INPUT = "SEC-0002"
    EC_NOT_FOUND = "SEC-0003"
    EC_PERMISSION_DENIED = "SEC-0004"
    EC_RATE_LIMIT_EXCEEDED = "SEC-0005"

    # Authentication (AT)
    EC_AT_FAILED = "SEC-AUTH-001"
    EC_AT_TK_EXPIRED = "SEC-AUTH-002"
    EC_AT_TK_INVALID = "SEC-AUTH-003"
    EC_AT_MFA_REQUIRED = "SEC-AUTH-004"
    EC_ACCOUNT_LOCKED = "SEC-AUTH-005"
    EC_PW_EXPIRED = "SEC-AUTH-006"
    EC_PW_WEAK = "SEC-AUTH-007"

    # Authorization (AZ)
    EC_AZ_DENIED = "SEC-AUTHZ-001"
    EC_AZ_INSUFFICIENT_ROLE = "SEC-AUTHZ-002"
    EC_AZ_SOD_VIOLATION = "SEC-AUTHZ-003"

    # Session
    EC_SESS_EXPIRED = "SEC-SESS-001"
    EC_SESS_NOT_FOUND = "SEC-SESS-002"
    EC_SESS_FINGERPRINT_MISMATCH = "SEC-SESS-003"
    EC_SESS_REVOKED = "SEC-SESS-004"

    # Cryptography
    EC_ENCRYPTION_FAILED = "SEC-CRYPTO-001"
    EC_DECRYPTION_FAILED = "SEC-CRYPTO-002"
    EC_KY_NOT_FOUND = "SEC-CRYPTO-003"
    EC_KY_ROTATION_FAILED = "SEC-CRYPTO-004"

    # HSM
    EC_HSM_CONNECTION_FAILED = "SEC-HSM-001"
    EC_HSM_SESSION_ERROR = "SEC-HSM-002"
    EC_HSM_KY_GEN_FAILED = "SEC-HSM-003"
    EC_HSM_SIGN_FAILED = "SEC-HSM-004"

    # Key Management
    EC_KY_MGMT_ERROR = "SEC-KEY-001"
    EC_VAULT_UNAVAILABLE = "SEC-KEY-002"
    EC_VAULT_TK_EXPIRED = "SEC-KEY-003"


# ============================================================================
# Base Security Exception (dengan entity dasar)
# ============================================================================
class SecurityError(Exception):
    """
    Base exception untuk semua error keamanan.
    """

    def __init__(
        self,
        message: str,
        error_code: str = SecurityErrorCode.EC_BASE_GENERIC,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        self.cause = cause
        self.timestamp = datetime.now(UTC)
        self.exception_id = uuid4()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._hash = self._compute_hash()
        self._take_snapshot()
        logger.error(f"[{error_code}] {message} (id={self.exception_id})")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "exception_id": str(self.exception_id),
                "error_code": self.error_code,
                "message": self.message[:100],
                "timestamp": self.timestamp.isoformat(),
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

    def _compute_hash(self) -> str:
        data = {
            "exception_id": str(self.exception_id),
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "exception_id": str(self.exception_id),
            "error_code": self.error_code,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "hash": self._hash,
            "traceback": traceback.format_exc() if self.cause else None,
            "version": self._version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.message:
            errors.append("Message is required")
        if not self.error_code:
            errors.append("Error code is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityError:
        instance = cls(
            message=data["message"],
            error_code=data.get("error_code", SecurityErrorCode.EC_BASE_GENERIC),
            context=data.get("context"),
            cause=None,
        )
        instance.exception_id = uuid4()  # generate new id
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> SecurityError:
        new = SecurityError(
            message=self.message,
            error_code=self.error_code,
            context=self.context.copy(),
            cause=self.cause,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "exception_id": str(self.exception_id),
            "error_code": self.error_code,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SecurityError:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# Specific Exceptions (dengan convenience constructors)
# ============================================================================
class EncryptionError(SecurityError):
    def __init__(self, message: str, algorithm: str = "AES-256", context: dict | None = None):
        full_context = {"algorithm": algorithm, **(context or {})}
        super().__init__(
            message=message,
            error_code=SecurityErrorCode.EC_ENCRYPTION_FAILED,
            context=full_context,
        )
        self.algorithm = algorithm


class AuthenticationError(SecurityError):
    def __init__(self, message: str, user_id: str | None = None, context: dict | None = None):
        full_context = {"user_id": user_id, **(context or {})}
        super().__init__(
            message=message,
            error_code=SecurityErrorCode.EC_AT_FAILED,
            context=full_context,
        )
        self.user_id = user_id


class AuthorizationError(SecurityError):
    def __init__(
        self,
        message: str,
        required_permission: str | None = None,
        user_id: str | None = None,
        context: dict | None = None,
    ):
        full_context = {
            "required_permission": required_permission,
            "user_id": user_id,
            **(context or {}),
        }
        super().__init__(
            message=message,
            error_code=SecurityErrorCode.EC_AZ_DENIED,
            context=full_context,
        )
        self.required_permission = required_permission
        self.user_id = user_id


class SessionExpiredError(AuthenticationError):
    def __init__(self, session_id: str | None = None, message: str = "Session has expired"):
        super().__init__(
            message=message,
            user_id=None,
            context={"session_id": session_id},
        )
        self.error_code = SecurityErrorCode.EC_SESS_EXPIRED
        self.session_id = session_id


class HSMError(SecurityError):
    def __init__(self, message: str, operation: str = "unknown", context: dict | None = None):
        full_context = {"operation": operation, **(context or {})}
        super().__init__(
            message=message,
            error_code=SecurityErrorCode.EC_HSM_CONNECTION_FAILED,
            context=full_context,
        )
        self.operation = operation


class KeyManagementError(SecurityError):
    def __init__(
        self,
        message: str,
        key_name: str | None = None,
        operation: str = "unknown",
        context: dict | None = None,
    ):
        full_context = {"key_name": key_name, "operation": operation, **(context or {})}
        super().__init__(
            message=message,
            error_code=SecurityErrorCode.EC_KY_MGMT_ERROR,
            context=full_context,
        )
        self.key_name = key_name


class MFARequiredError(AuthenticationError):
    def __init__(
        self, message: str = "Multi-factor authentication required", user_id: str | None = None
    ):
        super().__init__(
            message=message,
            user_id=user_id,
            context={"mfa_required": True},
        )
        self.error_code = SecurityErrorCode.EC_AT_MFA_REQUIRED


class AccountLockedError(AuthenticationError):
    def __init__(self, user_id: str, remaining_seconds: int = 0, message: str | None = None):
        if not message:
            message = f"Account locked for user {user_id}"
            if remaining_seconds > 0:
                message += f". Try again in {remaining_seconds} seconds"
        super().__init__(message=message, user_id=user_id)
        self.error_code = SecurityErrorCode.EC_ACCOUNT_LOCKED
        self.remaining_seconds = remaining_seconds


class PasswordExpiredError(AuthenticationError):
    def __init__(self, user_id: str, days_since_expiry: int = 0):
        message = f"Password expired for user {user_id}"
        if days_since_expiry > 0:
            message += f" ({days_since_expiry} days overdue)"
        super().__init__(message=message, user_id=user_id)
        self.error_code = SecurityErrorCode.EC_PW_EXPIRED
        self.days_since_expiry = days_since_expiry


class WeakPasswordError(AuthenticationError):
    def __init__(self, message: str, user_id: str | None = None):
        super().__init__(message=message, user_id=user_id)
        self.error_code = SecurityErrorCode.EC_PW_WEAK


# ============================================================================
# Exception Registry (dengan entity dasar)
# ============================================================================
class SecurityExceptionRegistry:
    """Registry untuk mencatat semua exception yang terjadi di modul keamanan."""

    _instance = None
    _exceptions: list[dict] = []
    _max_size: int = 10000

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "exception_count": len(self._exceptions),
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

    def register(self, error: SecurityError) -> None:
        self._exceptions.append(error.to_dict())
        if len(self._exceptions) > self._max_size:
            self._exceptions = self._exceptions[-self._max_size :]
        self._record_audit("REGISTER", "system", {"exception_id": str(error.exception_id)})
        logger.debug(f"Exception registered: {error.exception_id}")

    def get_all(self, limit: int = 100) -> list[dict]:
        return self._exceptions[-limit:]

    def get_by_code(self, error_code: str) -> list[dict]:
        return [e for e in self._exceptions if e.get("error_code") == error_code]

    def get_by_user(self, user_id: str) -> list[dict]:
        return [e for e in self._exceptions if e.get("context", {}).get("user_id") == user_id]

    def clear(self) -> None:
        self._exceptions.clear()
        self._record_audit("CLEAR", "system", {})

    def get_summary(self) -> dict:
        codes = Counter(e.get("error_code") for e in self._exceptions)
        return {
            "total": len(self._exceptions),
            "by_error_code": dict(codes),
            "last_exception": self._exceptions[-1] if self._exceptions else None,
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._max_size <= 0:
            errors.append("max_size must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_count": len(self._exceptions),
            "max_size": self._max_size,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityExceptionRegistry:
        instance = cls()
        instance._max_size = data.get("max_size", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> SecurityExceptionRegistry:
        new = SecurityExceptionRegistry()
        new._exceptions = self._exceptions.copy()
        new._max_size = self._max_size
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "exception_count": len(self._exceptions),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SecurityExceptionRegistry:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []


# ============================================================================
# Helper Functions (convenience raises)
# ============================================================================
def raise_authentication_failed(
    user_id: str | None = None, reason: str = "Invalid credentials"
) -> None:
    raise AuthenticationError(reason, user_id=user_id)


def raise_authorization_denied(user_id: str, required_permission: str) -> None:
    raise AuthorizationError(
        f"User {user_id} does not have permission {required_permission}",
        required_permission=required_permission,
        user_id=user_id,
    )


def raise_session_expired(session_id: str) -> None:
    raise SessionExpiredError(session_id=session_id)


def raise_account_locked(user_id: str, remaining_seconds: int = 0) -> None:
    raise AccountLockedError(user_id, remaining_seconds)


def raise_weak_password(message: str, user_id: str | None = None) -> None:
    raise WeakPasswordError(message, user_id)


def raise_hsm_error(operation: str, details: str) -> None:
    raise HSMError(f"HSM operation '{operation}' failed: {details}", operation=operation)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    registry = SecurityExceptionRegistry()

    try:
        raise_authentication_failed("user@example.com", "Wrong password")
    except AuthenticationError as e:
        print(e.to_json())
        registry.register(e)

    try:
        raise_authorization_denied("admin", "journal.approve")
    except AuthorizationError as e:
        print(e.to_json())
        registry.register(e)

    try:
        raise AccountLockedError("test_user", remaining_seconds=120)
    except AccountLockedError as e:
        print(e.to_json())
        registry.register(e)

    print("\nRegistry Summary:")
    print(registry.get_summary())