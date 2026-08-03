#!/usr/bin/env python3
"""
Module: event_types_catalog.py
Layer: Audit
Responsibility: Mendefinisikan katalog event types untuk audit trail. Setiap event
               memiliki tipe, severity, dan metadata schema. Juga menyediakan
               helper untuk validasi event type.
Dependencies:
- enum, typing
- infrastructure.telemetry.structured_json_logging
Audit: Katalog event type digunakan untuk standardisasi audit event.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar

# ============================================================================
# AUDIT EVENT TYPES
# ============================================================================


class AuditEventType(str, Enum):
    """Jenis-jenis event audit."""

    # Authentication events
    AUTH_LOGIN_SUCCESS = "auth.login.success"
    AUTH_LOGIN_FAILURE = "auth.login.failure"
    AUTH_LOGOUT = "auth.logout"
    AUTH_PASSWORD_CHANGE = "auth.password.change"
    AUTH_PASSWORD_RESET = "auth.password.reset"
    AUTH_TOKEN_REFRESH = "auth.token.refresh"
    AUTH_TOKEN_REVOKED = "auth.token.revoked"
    AUTH_MFA_ENABLED = "auth.mfa.enabled"
    AUTH_MFA_DISABLED = "auth.mfa.disabled"

    # Access control events
    ACCESS_PERMISSION_DENIED = "access.permission.denied"
    ACCESS_UNAUTHORIZED_RESOURCE = "access.unauthorized.resource"
    ACCESS_SOD_VIOLATION = "access.sod.violation"
    ACCESS_GRANTED = "access.granted"

    # Data events
    DATA_CREATE = "data.create"
    DATA_UPDATE = "data.update"
    DATA_DELETE = "data.delete"
    DATA_READ = "data.read"  # For sensitive data
    DATA_EXPORT = "data.export"
    DATA_IMPORT = "data.import"
    DATA_CHANGE = "data.change"

    # Configuration events
    CONFIG_CHANGE = "config.change"
    CONFIG_EXPORT = "config.export"
    CONFIG_IMPORT = "config.import"

    # User management events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_ACTIVATED = "user.activated"
    USER_DEACTIVATED = "user.deactivated"
    USER_LOCKED = "user.locked"
    USER_UNLOCKED = "user.unlocked"
    USER_ROLE_ASSIGNED = "user.role.assigned"
    USER_ROLE_REVOKED = "user.role.revoked"

    # Role management events
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"
    ROLE_PERMISSION_ASSIGNED = "role.permission.assigned"
    ROLE_PERMISSION_REVOKED = "role.permission.revoked"

    # Business process events
    JOURNAL_POSTED = "business.journal.posted"
    JOURNAL_APPROVED = "business.journal.approved"
    JOURNAL_REVERSED = "business.journal.reversed"
    PERIOD_CLOSED = "business.period.closed"
    PERIOD_REOPENED = "business.period.reopened"
    BANK_RECONCILIATION = "business.bank.reconciliation"
    PAYMENT_PROCESSED = "business.payment.processed"
    DEPRECIATION_RUN = "business.depreciation.run"
    PAYROLL_RUN = "business.payroll.run"
    TAX_FILING = "business.tax.filing"
    REPORT_GENERATED = "business.report.generated"

    # System events
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_BACKUP = "system.backup"
    SYSTEM_RESTORE = "system.restore"
    SYSTEM_MIGRATION = "system.migration"
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"

    # Security events
    SECURITY_ACCESS = "security.access"
    SECURITY_ACCESS_DENIED = "security.access.denied"
    SECURITY_VIOLATION = "security.violation"
    SECURITY_ATTACK_DETECTED = "security.attack.detected"
    SECURITY_INTEGRITY_CHECK = "security.integrity.check"

    # Compliance events
    COMPLIANCE_AUDIT = "compliance.audit"
    COMPLIANCE_RETENTION = "compliance.retention"
    COMPLIANCE_ATTESTATION = "compliance.attestation"

    # Integration events
    INTEGRATION_WEBHOOK_RECEIVED = "integration.webhook.received"
    INTEGRATION_WEBHOOK_PROCESSED = "integration.webhook.processed"
    INTEGRATION_API_CALL = "integration.api.call"
    INTEGRATION_SYNC = "integration.sync"


# ============================================================================
# AUDIT SEVERITY
# ============================================================================


class AuditSeverity(str, Enum):
    """Tingkat keparahan audit event."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ============================================================================
# EVENT METADATA SCHEMA
# ============================================================================


class EventMetadataSchema:
    """Schema untuk metadata setiap event type."""

    SCHEMAS: ClassVar[dict[str, dict[str, Any]]] = {
        AuditEventType.AUTH_LOGIN_SUCCESS: {
            "required_fields": ["username", "ip_address"],
            "recommended_fields": ["user_agent", "method"],
        },
        AuditEventType.AUTH_LOGIN_FAILURE: {
            "required_fields": ["username", "ip_address", "reason"],
            "recommended_fields": ["user_agent"],
        },
        AuditEventType.DATA_UPDATE: {
            "required_fields": ["target_type", "target_id", "changes"],
            "recommended_fields": ["old_value", "new_value"],
        },
        AuditEventType.DATA_DELETE: {
            "required_fields": ["target_type", "target_id"],
            "recommended_fields": ["deleted_value"],
        },
        AuditEventType.CONFIG_CHANGE: {
            "required_fields": ["config_key", "old_value", "new_value"],
            "recommended_fields": [],
        },
        AuditEventType.PERIOD_CLOSED: {
            "required_fields": ["fiscal_year", "period", "status"],
            "recommended_fields": ["journal_id"],
        },
        AuditEventType.JOURNAL_POSTED: {
            "required_fields": ["journal_id", "voucher_number", "total_amount"],
            "recommended_fields": ["lines_count"],
        },
    }

    @classmethod
    def get_schema(cls, event_type: str) -> dict[str, Any]:
        """Get schema for event type."""
        return cls.SCHEMAS.get(event_type, {"required_fields": [], "recommended_fields": []})

    @classmethod
    def validate_event(cls, event_type: str, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate event data against schema."""
        schema = cls.get_schema(event_type)
        missing = [f for f in schema.get("required_fields", []) if f not in data]
        return len(missing) == 0, missing


# ============================================================================
# EVENT TYPE CATALOG
# ============================================================================


class EventTypeCatalog:
    """
    Katalog untuk audit event types.

    Fitur:
    - Mendaftarkan semua event types
    - Validasi event type
    - Mendapatkan severity default
    - Mendapatkan deskripsi event type
    """

    _descriptions: ClassVar[dict[str, str]] = {
        AuditEventType.AUTH_LOGIN_SUCCESS: "User login successful",
        AuditEventType.AUTH_LOGIN_FAILURE: "User login failed",
        AuditEventType.AUTH_LOGOUT: "User logged out",
        AuditEventType.AUTH_PASSWORD_CHANGE: "User changed password",
        AuditEventType.AUTH_PASSWORD_RESET: "User reset password",
        AuditEventType.DATA_CREATE: "New record created",
        AuditEventType.DATA_UPDATE: "Record updated",
        AuditEventType.DATA_DELETE: "Record deleted",
        AuditEventType.DATA_READ: "Sensitive data accessed",
        AuditEventType.CONFIG_CHANGE: "System configuration changed",
        AuditEventType.PERIOD_CLOSED: "Accounting period closed",
        AuditEventType.JOURNAL_POSTED: "Journal entry posted",
        AuditEventType.SYSTEM_ERROR: "System error occurred",
        AuditEventType.SECURITY_VIOLATION: "Security policy violation",
        AuditEventType.COMPLIANCE_AUDIT: "Compliance audit event",
    }

    _default_severity: ClassVar[dict[str, str]] = {
        AuditEventType.AUTH_LOGIN_SUCCESS: AuditSeverity.INFO,
        AuditEventType.AUTH_LOGIN_FAILURE: AuditSeverity.WARNING,
        AuditEventType.DATA_DELETE: AuditSeverity.WARNING,
        AuditEventType.CONFIG_CHANGE: AuditSeverity.WARNING,
        AuditEventType.SYSTEM_ERROR: AuditSeverity.ERROR,
        AuditEventType.SECURITY_VIOLATION: AuditSeverity.CRITICAL,
        AuditEventType.ACCESS_PERMISSION_DENIED: AuditSeverity.WARNING,
    }

    @classmethod
    def get_description(cls, event_type: str) -> str:
        """Get description for event type."""
        return cls._descriptions.get(event_type, "Unknown event type")

    @classmethod
    def get_default_severity(cls, event_type: str) -> str:
        """Get default severity for event type."""
        return cls._default_severity.get(event_type, AuditSeverity.INFO)

    @classmethod
    def is_valid_type(cls, event_type: str) -> bool:
        """Check if event type is valid."""
        return event_type in [e.value for e in AuditEventType]

    @classmethod
    def list_all_types(cls) -> list[str]:
        """List all event types."""
        return [e.value for e in AuditEventType]

    @classmethod
    def list_by_category(cls, category: str) -> list[str]:
        """
        List event types by category prefix.

        Args:
            category: e.g., "auth", "data", "config", "user", "business", "system", "security"
        """
        return [e.value for e in AuditEventType if e.value.startswith(f"{category}.")]


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["AuditEventType", "AuditSeverity", "EventMetadataSchema", "EventTypeCatalog"]
