#!/usr/bin/env python3
"""
Module: audit_log_security_events.py
Layer: Infrastructure (Security)
Responsibility: Mencatat security events ke audit log untuk compliance dan forensic.
               Event security yang dicatat meliputi: login attempts (success/failure),
               permission denied, role changes, user management, sensitive data access,
               configuration changes, dan security violations. Terintegrasi dengan
               event store dan alert system.
Dependencies:
- logging, datetime, uuid
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.telemetry.alert_manager_router
- infrastructure.telemetry.structured_json_logging
Audit: SEMUA security events WAJIB dicatat. Tidak boleh ada pengecualian.
       Security events digunakan untuk compliance (SOX, GDPR, PSAK).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

# Internal dependencies
from infrastructure.event_store.append_only_store import AppendOnlyStore, get_audit_store
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

AUDIT_STORE_NAME = "security_audit"


# Security event types
class SecurityEventType:
    AUTH_LOGIN_ATTEMPT = "security.auth.login_attempt"
    AUTH_LOGIN_SUCCESS = "security.auth.login_success"
    AUTH_LOGIN_FAILURE = "security.auth.login_failure"
    AUTH_LOGOUT = "security.auth.logout"
    AUTH_TOKEN_REFRESH = "security.auth.token_refresh"
    AUTH_TOKEN_REVOKED = "security.auth.token_revoked"
    AUTH_PASSWORD_CHANGE = "security.auth.password_change"
    AUTH_PASSWORD_RESET = "security.auth.password_reset"
    AUTH_MFA_ENABLED = "security.auth.mfa_enabled"
    AUTH_MFA_DISABLED = "security.auth.mfa_disabled"

    ACCESS_PERMISSION_DENIED = "security.access.permission_denied"
    ACCESS_SOD_VIOLATION = "security.access.sod_violation"
    ACCESS_UNAUTHORIZED_RESOURCE = "security.access.unauthorized_resource"

    USER_CREATED = "security.user.created"
    USER_UPDATED = "security.user.updated"
    USER_DELETED = "security.user.deleted"
    USER_ACTIVATED = "security.user.activated"
    USER_DEACTIVATED = "security.user.deactivated"
    USER_LOCKED = "security.user.locked"
    USER_UNLOCKED = "security.user.unlocked"
    USER_ROLE_ASSIGNED = "security.user.role_assigned"
    USER_ROLE_REVOKED = "security.user.role_revoked"

    ROLE_CREATED = "security.role.created"
    ROLE_UPDATED = "security.role.updated"
    ROLE_DELETED = "security.role.deleted"
    ROLE_PERMISSION_ASSIGNED = "security.role.permission_assigned"
    ROLE_PERMISSION_REVOKED = "security.role.permission_revoked"

    CONFIG_CHANGED = "security.config.changed"
    ENCRYPTION_KEY_ROTATED = "security.encryption.key_rotated"
    CERTIFICATE_RENEWED = "security.certificate.renewed"

    SENSITIVE_DATA_ACCESS = "security.sensitive_data.access"
    DATA_EXPORT = "security.data.export"
    DATA_IMPORT = "security.data.import"

    SECURITY_VIOLATION = "security.violation"
    INTRUSION_DETECTED = "security.intrusion.detected"
    RATE_LIMIT_EXCEEDED = "security.rate_limit.exceeded"


# Severity levels
class SecuritySeverity:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ============================================================================
# AUDIT LOGGER
# ============================================================================


class SecurityAuditLogger:
    """
    Security audit logger untuk mencatat security events.

    Fitur:
    - Mencatat berbagai jenis security events
    - Hash chain untuk integritas audit log
    - Alert trigger untuk events critical
    - Support correlation ID untuk tracing
    """

    def __init__(self):
        self._store: AppendOnlyStore | None = None
        self._last_hash: str | None = None

    async def _get_store(self) -> AppendOnlyStore:
        if self._store is None:
            self._store = await get_audit_store()
        return self._store

    async def _get_last_hash(self) -> str:
        """Get last hash for audit chain."""
        if self._last_hash:
            return self._last_hash
        try:
            store = await self._get_store()
            last_record = await store.get_last_record(AUDIT_STORE_NAME)
            if last_record and last_record.get("hash"):
                self._last_hash = last_record["hash"]
                return self._last_hash
        except Exception as e:
            logger.warning(f"Failed to get last audit hash: {e}")
        return "0" * 64

    def _compute_hash(self, record: dict[str, Any]) -> str:
        """Compute SHA-256 hash of audit record."""
        import json

        # Remove hash field before computing
        record_copy = {k: v for k, v in record.items() if k != "hash"}
        json_str = json.dumps(record_copy, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    async def _log(
        self,
        event_type: str,
        severity: str,
        user_id: UUID | None,
        details: dict[str, Any],
        correlation_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """
        Internal method to log security event.
        """
        event_id = uuid4()
        timestamp = datetime.now(UTC)
        previous_hash = await self._get_last_hash()

        record = {
            "id": str(event_id),
            "timestamp": timestamp.isoformat(),
            "event_type": event_type,
            "severity": severity,
            "user_id": str(user_id) if user_id else None,
            "details": details,
            "correlation_id": correlation_id or str(uuid4()),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "previous_hash": previous_hash,
        }

        record["hash"] = self._compute_hash(record)

        try:
            store = await self._get_store()
            await store.append(AUDIT_STORE_NAME, record)
            self._last_hash = record["hash"]

            # Also log to structured logger
            logger.info(f"Security event: {event_type}", extra={"security_event": record})

            # Trigger alert for critical events
            if severity == SecuritySeverity.CRITICAL:
                await trigger_alert(
                    title=f"Security: {event_type}",
                    message=json.dumps(details, default=str)[:500],
                    severity="critical",
                    source="SecurityAuditLogger",
                )

        except Exception as e:
            logger.error(f"Failed to log security event: {e}")

    # ========================================================================
    # AUTHENTICATION EVENTS
    # ========================================================================

    async def log_login_attempt(
        self, username: str, ip_address: str | None = None, user_agent: str | None = None
    ) -> None:
        await self._log(
            event_type=SecurityEventType.AUTH_LOGIN_ATTEMPT,
            severity=SecuritySeverity.INFO,
            user_id=None,
            details={"username": username},
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def log_login_success(
        self,
        user_id: UUID,
        username: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        await self._log(
            event_type=SecurityEventType.AUTH_LOGIN_SUCCESS,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"username": username},
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def log_login_failure(
        self,
        username: str,
        reason: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        await self._log(
            event_type=SecurityEventType.AUTH_LOGIN_FAILURE,
            severity=SecuritySeverity.WARNING,
            user_id=None,
            details={"username": username, "reason": reason},
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def log_logout(self, user_id: UUID, session_id: str | None = None) -> None:
        await self._log(
            event_type=SecurityEventType.AUTH_LOGOUT,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"session_id": session_id},
        )

    async def log_token_refresh(
        self, user_id: UUID, old_token_jti: str, new_token_jti: str
    ) -> None:
        await self._log(
            event_type=SecurityEventType.AUTH_TOKEN_REFRESH,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"old_token_jti": old_token_jti, "new_token_jti": new_token_jti},
        )

    async def log_token_revoked(self, user_id: UUID, token_jti: str, reason: str) -> None:
        await self._log(
            event_type=SecurityEventType.AUTH_TOKEN_REVOKED,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={"token_jti": token_jti, "reason": reason},
        )

    async def log_password_change(self, user_id: UUID, changed_by: UUID | None = None) -> None:
        await self._log(
            event_type=SecurityEventType.AUTH_PASSWORD_CHANGE,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"changed_by": str(changed_by) if changed_by else "self"},
        )

    # ========================================================================
    # ACCESS CONTROL EVENTS
    # ========================================================================

    async def log_permission_denied(
        self,
        user_id: UUID,
        resource: str,
        action: str,
        required_permission: str,
        ip_address: str | None = None,
    ) -> None:
        await self._log(
            event_type=SecurityEventType.ACCESS_PERMISSION_DENIED,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={
                "resource": resource,
                "action": action,
                "required_permission": required_permission,
                "ip_address": ip_address,
            },
        )

    async def log_sod_violation(self, user_id: UUID, violations: list[dict]) -> None:
        await self._log(
            event_type=SecurityEventType.ACCESS_SOD_VIOLATION,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={"violations": violations},
        )

    async def log_unauthorized_resource_access(
        self, user_id: UUID, resource: str, attempted_action: str, ip_address: str | None = None
    ) -> None:
        await self._log(
            event_type=SecurityEventType.ACCESS_UNAUTHORIZED_RESOURCE,
            severity=SecuritySeverity.ERROR,
            user_id=user_id,
            details={
                "resource": resource,
                "attempted_action": attempted_action,
                "ip_address": ip_address,
            },
        )

    # ========================================================================
    # USER MANAGEMENT EVENTS
    # ========================================================================

    async def log_user_created(self, user_id: UUID, created_by: UUID, username: str) -> None:
        await self._log(
            event_type=SecurityEventType.USER_CREATED,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"created_by": str(created_by), "username": username},
        )

    async def log_user_updated(self, user_id: UUID, updated_by: UUID, changes: dict) -> None:
        await self._log(
            event_type=SecurityEventType.USER_UPDATED,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"updated_by": str(updated_by), "changes": changes},
        )

    async def log_user_deleted(self, user_id: UUID, deleted_by: UUID, username: str) -> None:
        await self._log(
            event_type=SecurityEventType.USER_DELETED,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={"deleted_by": str(deleted_by), "username": username},
        )

    async def log_user_activated(self, user_id: UUID, activated_by: UUID) -> None:
        await self._log(
            event_type=SecurityEventType.USER_ACTIVATED,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"activated_by": str(activated_by)},
        )

    async def log_user_deactivated(
        self, user_id: UUID, deactivated_by: UUID, reason: str | None = None
    ) -> None:
        await self._log(
            event_type=SecurityEventType.USER_DEACTIVATED,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={"deactivated_by": str(deactivated_by), "reason": reason},
        )

    async def log_user_locked(self, user_id: UUID, reason: str) -> None:
        await self._log(
            event_type=SecurityEventType.USER_LOCKED,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={"reason": reason},
        )

    async def log_user_unlocked(self, user_id: UUID, unlocked_by: UUID) -> None:
        await self._log(
            event_type=SecurityEventType.USER_UNLOCKED,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={"unlocked_by": str(unlocked_by)},
        )

    async def log_user_role_assigned(
        self, user_id: UUID, role_id: UUID, role_name: str, assigned_by: UUID
    ) -> None:
        await self._log(
            event_type=SecurityEventType.USER_ROLE_ASSIGNED,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={
                "role_id": str(role_id),
                "role_name": role_name,
                "assigned_by": str(assigned_by),
            },
        )

    async def log_user_role_revoked(
        self, user_id: UUID, role_id: UUID, role_name: str, revoked_by: UUID
    ) -> None:
        await self._log(
            event_type=SecurityEventType.USER_ROLE_REVOKED,
            severity=SecuritySeverity.INFO,
            user_id=user_id,
            details={
                "role_id": str(role_id),
                "role_name": role_name,
                "revoked_by": str(revoked_by),
            },
        )

    # ========================================================================
    # ROLE & PERMISSION EVENTS
    # ========================================================================

    async def log_role_created(self, role_id: UUID, role_name: str, created_by: UUID) -> None:
        await self._log(
            event_type=SecurityEventType.ROLE_CREATED,
            severity=SecuritySeverity.INFO,
            user_id=None,
            details={
                "role_id": str(role_id),
                "role_name": role_name,
                "created_by": str(created_by),
            },
        )

    async def log_role_permission_assigned(
        self, role_id: UUID, permission: str, assigned_by: UUID
    ) -> None:
        await self._log(
            event_type=SecurityEventType.ROLE_PERMISSION_ASSIGNED,
            severity=SecuritySeverity.INFO,
            user_id=None,
            details={
                "role_id": str(role_id),
                "permission": permission,
                "assigned_by": str(assigned_by),
            },
        )

    # ========================================================================
    # CONFIGURATION & SECURITY EVENTS
    # ========================================================================

    async def log_config_changed(
        self, changed_by: UUID, config_key: str, old_value: Any, new_value: Any
    ) -> None:
        await self._log(
            event_type=SecurityEventType.CONFIG_CHANGED,
            severity=SecuritySeverity.WARNING,
            user_id=changed_by,
            details={
                "config_key": config_key,
                "old_value": str(old_value),
                "new_value": str(new_value),
            },
        )

    async def log_encryption_key_rotated(
        self, rotated_by: UUID, old_key_id: str, new_key_id: str
    ) -> None:
        await self._log(
            event_type=SecurityEventType.ENCRYPTION_KEY_ROTATED,
            severity=SecuritySeverity.INFO,
            user_id=rotated_by,
            details={"old_key_id": old_key_id, "new_key_id": new_key_id},
        )

    async def log_sensitive_data_access(
        self, user_id: UUID, data_type: str, data_id: str, reason: str | None = None
    ) -> None:
        await self._log(
            event_type=SecurityEventType.SENSITIVE_DATA_ACCESS,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={"data_type": data_type, "data_id": data_id, "reason": reason},
        )

    async def log_security_violation(
        self,
        user_id: UUID | None,
        violation_type: str,
        details: dict,
        severity: str = SecuritySeverity.ERROR,
    ) -> None:
        await self._log(
            event_type=SecurityEventType.SECURITY_VIOLATION,
            severity=severity,
            user_id=user_id,
            details={"violation_type": violation_type, "details": details},
        )

    async def log_intrusion_detected(
        self, ip_address: str, detection_type: str, details: dict
    ) -> None:
        await self._log(
            event_type=SecurityEventType.INTRUSION_DETECTED,
            severity=SecuritySeverity.CRITICAL,
            user_id=None,
            details={
                "ip_address": ip_address,
                "detection_type": detection_type,
                "details": details,
            },
        )

    async def log_rate_limit_exceeded(
        self, user_id: UUID | None, key: str, limit: int, ip_address: str | None = None
    ) -> None:
        await self._log(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
            severity=SecuritySeverity.WARNING,
            user_id=user_id,
            details={"key": key, "limit": limit, "ip_address": ip_address},
        )


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_security_audit_logger: SecurityAuditLogger | None = None


async def get_security_audit_logger() -> SecurityAuditLogger:
    """Get singleton instance of SecurityAuditLogger."""
    global _security_audit_logger
    if _security_audit_logger is None:
        _security_audit_logger = SecurityAuditLogger()
    return _security_audit_logger


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "SecurityAuditLogger",
    "SecurityEventType",
    "SecuritySeverity",
    "get_security_audit_logger",
]
