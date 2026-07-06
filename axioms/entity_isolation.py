#!/usr/bin/env python3
"""
Module: entity_isolation.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: data antar entitas hukum terisolasi secara ketat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class EntityIsolationViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class InterEntityAuthorizationType(Enum):
    CONSOLIDATION = auto()
    INTERCOMPANY = auto()
    SHARED_SERVICE = auto()
    REPORTING = auto()
    AUDIT = auto()
    TAX = auto()
    CASH_POOLING = auto()


class EntityIsolationCheckLevel(Enum):
    STRICT = auto()
    MODERATE = auto()
    PERMISSIVE = auto()


# === 2. EXCEPTIONS ===


class EntityIsolationViolationError(Exception):
    def __init__(
        self,
        message: str,
        source_entity_id: UUID,
        target_entity_id: UUID,
        attempted_operation: str,
        severity: EntityIsolationViolationSeverity,
    ):
        self.source_entity_id = source_entity_id
        self.target_entity_id = target_entity_id
        self.attempted_operation = attempted_operation
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | Source: {source_entity_id}, Target: {target_entity_id}, Op: {attempted_operation}"
        )


class InterEntityAuthorizationError(Exception):
    pass


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class LegalEntityDefinition:
    entity_id: UUID
    entity_code: str
    entity_name: str
    tax_id: str
    functional_currency: str
    fiscal_year_start: int
    country_code: str
    is_active: bool
    parent_entity_id: UUID | None = None
    consolidation_group: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if len(self.entity_code) < 2:
            raise ValueError("Entity code too short")
        if len(self.tax_id) < 5:
            raise ValueError("Tax ID too short")
        if self.fiscal_year_start < 1 or self.fiscal_year_start > 12:
            raise ValueError("Fiscal year start must be 1-12")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.entity_id}|{self.entity_code}|{self.entity_name}|{self.tax_id}|{self.functional_currency}|{self.fiscal_year_start}|{self.country_code}|{self.is_active}|{self.parent_entity_id}|{self.consolidation_group}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "entity_id": str(self.entity_id),
                "entity_code": self.entity_code,
                "is_active": self.is_active,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "entity_id": str(self.entity_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> LegalEntityDefinition:
        return self

    def update(self, updated_by: str, **kwargs) -> LegalEntityDefinition:
        new_entity = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_entity, key) and key not in ("entity_id", "created_at", "version"):
                setattr(new_entity, key, value)
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_entity

    def delete(self, deleted_by: str, reason: str | None = None) -> LegalEntityDefinition:
        new_entity = self._copy()
        new_entity.deleted_at = datetime.now(UTC)
        new_entity.deleted_by = deleted_by
        new_entity.is_active = False
        new_entity.version = self.version + 1
        new_entity._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_entity

    def restore(self, restored_by: str) -> LegalEntityDefinition:
        if self.deleted_at is None:
            raise ValueError("Entity not deleted")
        new_entity = self._copy()
        new_entity.deleted_at = None
        new_entity.deleted_by = None
        new_entity.is_active = True
        new_entity.version = self.version + 1
        new_entity._record_audit("RESTORE", restored_by, {})
        return new_entity

    def activate(self, activated_by: str) -> LegalEntityDefinition:
        if self.is_active:
            return self
        new_entity = self._copy()
        new_entity.is_active = True
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("ACTIVATE", activated_by, {})
        return new_entity

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> LegalEntityDefinition:
        if not self.is_active:
            return self
        new_entity = self._copy()
        new_entity.is_active = False
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_entity

    def lock(self, locked_by: str, reason: str) -> LegalEntityDefinition:
        # No lock state for entity, just return self
        return self

    def unlock(self, unlocked_by: str) -> LegalEntityDefinition:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "entity_id": str(self.entity_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": str(self.entity_id),
            "entity_code": self.entity_code,
            "entity_name": self.entity_name,
            "tax_id": self.tax_id,
            "functional_currency": self.functional_currency,
            "fiscal_year_start": self.fiscal_year_start,
            "country_code": self.country_code,
            "is_active": self.is_active,
            "parent_entity_id": str(self.parent_entity_id) if self.parent_entity_id else None,
            "consolidation_group": self.consolidation_group,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalEntityDefinition:
        return cls(
            entity_id=UUID(data["entity_id"]),
            entity_code=data["entity_code"],
            entity_name=data["entity_name"],
            tax_id=data["tax_id"],
            functional_currency=data["functional_currency"],
            fiscal_year_start=data["fiscal_year_start"],
            country_code=data["country_code"],
            is_active=data["is_active"],
            parent_entity_id=UUID(data["parent_entity_id"])
            if data.get("parent_entity_id")
            else None,
            consolidation_group=data.get("consolidation_group"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> LegalEntityDefinition:
        new_id = uuid4()
        return LegalEntityDefinition(
            entity_id=new_id,
            entity_code=f"{self.entity_code}_COPY",
            entity_name=f"{self.entity_name} (COPY)",
            tax_id=self.tax_id,
            functional_currency=self.functional_currency,
            fiscal_year_start=self.fiscal_year_start,
            country_code=self.country_code,
            is_active=False,
            parent_entity_id=self.entity_id,
            consolidation_group=self.consolidation_group,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "entity_id": str(self.entity_id),
            "entity_code": self.entity_code,
            "is_active": self.is_active,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> LegalEntityDefinition:
        new_entity = self._copy()
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("TOUCH", touched_by, {})
        return new_entity

    def _copy(self) -> LegalEntityDefinition:
        return LegalEntityDefinition(
            entity_id=self.entity_id,
            entity_code=self.entity_code,
            entity_name=self.entity_name,
            tax_id=self.tax_id,
            functional_currency=self.functional_currency,
            fiscal_year_start=self.fiscal_year_start,
            country_code=self.country_code,
            is_active=self.is_active,
            parent_entity_id=self.parent_entity_id,
            consolidation_group=self.consolidation_group,
            created_at=self.created_at,
            updated_at=self.updated_at,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class InterEntityAuthorization:
    auth_id: UUID
    from_entity_id: UUID
    to_entity_id: UUID
    auth_type: InterEntityAuthorizationType
    granted_by: str
    granted_at: datetime
    expires_at: datetime | None
    approvers: list[str]
    purpose: str
    allowed_operations: list[str]
    cryptographic_hash: str = ""
    version: int = 1
    revoked: bool = False
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.granted_by, {})

    def _validate(self) -> None:
        if not self.allowed_operations:
            raise ValueError("At least one allowed operation required")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.auth_id}|{self.from_entity_id}|{self.to_entity_id}|{self.auth_type.value}|{self.purpose}|{','.join(self.allowed_operations)}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "auth_id": str(self.auth_id),
                "auth_type": self.auth_type.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "auth_id": str(self.auth_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> InterEntityAuthorization:
        return self

    def update(self, updated_by: str, **kwargs) -> InterEntityAuthorization:
        new_auth = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_auth, key) and key not in (
                "auth_id",
                "granted_at",
                "granted_by",
                "version",
            ):
                setattr(new_auth, key, value)
        new_auth.version = self.version + 1
        new_auth._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_auth

    def delete(self, deleted_by: str, reason: str | None = None) -> InterEntityAuthorization:
        new_auth = self._copy()
        new_auth.revoked = True
        new_auth.revoked_at = datetime.now(UTC)
        new_auth.revoked_by = deleted_by
        new_auth.version = self.version + 1
        new_auth._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_auth

    def restore(self, restored_by: str) -> InterEntityAuthorization:
        if not self.revoked:
            raise ValueError("Authorization not revoked")
        new_auth = self._copy()
        new_auth.revoked = False
        new_auth.revoked_at = None
        new_auth.revoked_by = None
        new_auth.version = self.version + 1
        new_auth._record_audit("RESTORE", restored_by, {})
        return new_auth

    def activate(self, activated_by: str) -> InterEntityAuthorization:
        if self.revoked:
            return self.restore(activated_by)
        return self

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> InterEntityAuthorization:
        if not self.revoked:
            return self.delete(deactivated_by, reason)
        return self

    def lock(self, locked_by: str, reason: str) -> InterEntityAuthorization:
        return self

    def unlock(self, unlocked_by: str) -> InterEntityAuthorization:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "auth_id": str(self.auth_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "auth_id": str(self.auth_id),
            "from_entity_id": str(self.from_entity_id),
            "to_entity_id": str(self.to_entity_id),
            "auth_type": self.auth_type.name,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "approvers": self.approvers,
            "purpose": self.purpose,
            "allowed_operations": self.allowed_operations,
            "version": self.version,
            "revoked": self.revoked,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revoked_by": self.revoked_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterEntityAuthorization:
        return cls(
            auth_id=UUID(data["auth_id"]),
            from_entity_id=UUID(data["from_entity_id"]),
            to_entity_id=UUID(data["to_entity_id"]),
            auth_type=InterEntityAuthorizationType[data["auth_type"]],
            granted_by=data["granted_by"],
            granted_at=datetime.fromisoformat(data["granted_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            approvers=data["approvers"],
            purpose=data["purpose"],
            allowed_operations=data["allowed_operations"],
            version=data.get("version", 1),
            revoked=data.get("revoked", False),
            revoked_at=datetime.fromisoformat(data["revoked_at"])
            if data.get("revoked_at")
            else None,
            revoked_by=data.get("revoked_by"),
        )

    def clone(self) -> InterEntityAuthorization:
        new_id = uuid4()
        return InterEntityAuthorization(
            auth_id=new_id,
            from_entity_id=self.from_entity_id,
            to_entity_id=self.to_entity_id,
            auth_type=self.auth_type,
            granted_by=self.granted_by,
            granted_at=self.granted_at,
            expires_at=self.expires_at,
            approvers=self.approvers.copy(),
            purpose=self.purpose,
            allowed_operations=self.allowed_operations.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "auth_id": str(self.auth_id),
            "auth_type": self.auth_type.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InterEntityAuthorization:
        new_auth = self._copy()
        new_auth.version = self.version + 1
        new_auth._record_audit("TOUCH", touched_by, {})
        return new_auth

    def is_valid(self, at_date: datetime | None = None) -> bool:
        check = at_date or datetime.now(UTC)
        if self.revoked:
            return False
        if self.expires_at and check > self.expires_at:
            return False
        return True

    def allows_operation(self, operation: str) -> bool:
        return operation.upper() in [op.upper() for op in self.allowed_operations]

    def _copy(self) -> InterEntityAuthorization:
        return InterEntityAuthorization(
            auth_id=self.auth_id,
            from_entity_id=self.from_entity_id,
            to_entity_id=self.to_entity_id,
            auth_type=self.auth_type,
            granted_by=self.granted_by,
            granted_at=self.granted_at,
            expires_at=self.expires_at,
            approvers=self.approvers.copy(),
            purpose=self.purpose,
            allowed_operations=self.allowed_operations.copy(),
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            revoked=self.revoked,
            revoked_at=self.revoked_at,
            revoked_by=self.revoked_by,
        )


@dataclass(kw_only=True)
class EntityIsolationViolation:
    violation_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    attempted_operation: str
    user_id: UUID | None
    module: str
    severity: EntityIsolationViolationSeverity
    message: str
    was_blocked: bool
    detected_at: datetime
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.violation_id}|{self.source_entity_id}|{self.target_entity_id}|{self.attempted_operation}|{self.was_blocked}|{self.severity.value}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "violation_id": str(self.violation_id),
                "severity": self.severity.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "violation_id": str(self.violation_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> EntityIsolationViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> EntityIsolationViolation:
        raise AttributeError("EntityIsolationViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> EntityIsolationViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> EntityIsolationViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> EntityIsolationViolation:
        return self

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> EntityIsolationViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> EntityIsolationViolation:
        return self

    def unlock(self, unlocked_by: str) -> EntityIsolationViolation:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "violation_id": str(self.violation_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "source_entity_id": str(self.source_entity_id),
            "target_entity_id": str(self.target_entity_id),
            "attempted_operation": self.attempted_operation,
            "user_id": str(self.user_id) if self.user_id else None,
            "module": self.module,
            "severity": self.severity.name,
            "message": self.message,
            "was_blocked": self.was_blocked,
            "detected_at": self.detected_at.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EntityIsolationViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            source_entity_id=UUID(data["source_entity_id"]),
            target_entity_id=UUID(data["target_entity_id"]),
            attempted_operation=data["attempted_operation"],
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            module=data["module"],
            severity=EntityIsolationViolationSeverity[data["severity"]],
            message=data["message"],
            was_blocked=data["was_blocked"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            version=data.get("version", 1),
        )

    def clone(self) -> EntityIsolationViolation:
        new_id = uuid4()
        return EntityIsolationViolation(
            violation_id=new_id,
            source_entity_id=self.source_entity_id,
            target_entity_id=self.target_entity_id,
            attempted_operation=self.attempted_operation,
            user_id=self.user_id,
            module=self.module,
            severity=self.severity,
            message=self.message,
            was_blocked=self.was_blocked,
            detected_at=self.detected_at,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EntityIsolationViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str) -> EntityIsolationViolation:
        if self.resolved:
            raise ValueError("Already resolved")
        new_violation = self._copy()
        new_violation.resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.version = self.version + 1
        new_violation._record_audit("RESOLVE", by, {})
        return new_violation

    def _copy(self) -> EntityIsolationViolation:
        return EntityIsolationViolation(
            violation_id=self.violation_id,
            source_entity_id=self.source_entity_id,
            target_entity_id=self.target_entity_id,
            attempted_operation=self.attempted_operation,
            user_id=self.user_id,
            module=self.module,
            severity=self.severity,
            message=self.message,
            was_blocked=self.was_blocked,
            detected_at=self.detected_at,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. VALIDATOR ===


class EntityIsolationValidator:
    @classmethod
    def validate_access(
        cls,
        source_entity_id: UUID,
        target_entity_id: UUID,
        operation: str,
        user_authorizations: list[InterEntityAuthorization],
        user_id: UUID | None = None,
        module: str = "unknown",
        check_level: EntityIsolationCheckLevel = EntityIsolationCheckLevel.STRICT,
    ) -> tuple[bool, EntityIsolationViolation | None]:
        if source_entity_id == target_entity_id:
            return True, None
        has_auth = any(a.is_valid() and a.allows_operation(operation) for a in user_authorizations)
        if not has_auth:
            if check_level == EntityIsolationCheckLevel.PERMISSIVE:
                return True, None
            severity = cls._determine_severity(operation, check_level)
            was_blocked = (
                check_level != EntityIsolationCheckLevel.MODERATE or operation.upper() != "READ"
            )
            violation = cls._create_violation(
                source_entity_id,
                target_entity_id,
                operation,
                user_id,
                module,
                severity,
                "Unauthorized cross-entity access",
                was_blocked,
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return not was_blocked, violation
        return True, None

    @classmethod
    def _determine_severity(
        cls, operation: str, check_level: EntityIsolationCheckLevel
    ) -> EntityIsolationViolationSeverity:
        if check_level == EntityIsolationCheckLevel.MODERATE and operation.upper() == "READ":
            return EntityIsolationViolationSeverity.MEDIUM
        op = operation.upper()
        if op in ("WRITE", "UPDATE", "DELETE", "TRANSFER"):
            return EntityIsolationViolationSeverity.CRITICAL
        elif op in ("CONSOLIDATE", "AGGREGATE"):
            return EntityIsolationViolationSeverity.HIGH
        elif op in ("READ", "SELECT", "QUERY"):
            return EntityIsolationViolationSeverity.MEDIUM
        return EntityIsolationViolationSeverity.LOW

    @classmethod
    def _create_violation(
        cls,
        source_entity_id: UUID,
        target_entity_id: UUID,
        attempted_operation: str,
        user_id: UUID | None,
        module: str,
        severity: EntityIsolationViolationSeverity,
        message: str,
        was_blocked: bool,
    ) -> EntityIsolationViolation:
        return EntityIsolationViolation(
            violation_id=uuid4(),
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            attempted_operation=attempted_operation,
            user_id=user_id,
            module=module,
            severity=severity,
            message=message,
            was_blocked=was_blocked,
            detected_at=datetime.now(UTC),
            resolved=False,
            resolved_at=None,
            resolved_by=None,
        )

    @classmethod
    def _log_violation(cls, violation: EntityIsolationViolation) -> None:
        log_msg = f"[{violation.severity.name}] Entity isolation violation: {violation.message}"
        if violation.severity.value >= EntityIsolationViolationSeverity.CRITICAL.value:
            logger.critical(log_msg)
        elif violation.severity.value >= EntityIsolationViolationSeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: EntityIsolationViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                EntityIsolationViolationSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                EntityIsolationViolationSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                EntityIsolationViolationSeverity.HIGH: ConstitutionalSeverity.HIGH,
                EntityIsolationViolationSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                EntityIsolationViolationSeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.ENTITY_ISOLATION,
                offending_module=violation.module,
                message=violation.message,
                offending_user=str(violation.user_id) if violation.user_id else None,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 5. AXIOM SERVICE ===


class EntityIsolationAxiom:
    _instance: EntityIsolationAxiom | None = None
    _entities: dict[UUID, LegalEntityDefinition] = {}
    _authorizations: dict[tuple[UUID, UUID], list[InterEntityAuthorization]] = {}
    _violation_history: list[EntityIsolationViolation] = []
    _check_level: EntityIsolationCheckLevel = EntityIsolationCheckLevel.STRICT
    _lock = threading.Lock()

    def __new__(cls) -> EntityIsolationAxiom:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._entities = {}
        self._authorizations = {}
        self._violation_history = []
        self._check_level = EntityIsolationCheckLevel.STRICT

    # ==================== REPOSITORY METHODS ====================
    def save_entity(self, entity: LegalEntityDefinition) -> None:
        with self._lock:
            self._entities[entity.entity_id] = entity

    def get_entity(self, entity_id: UUID) -> LegalEntityDefinition | None:
        return self._entities.get(entity_id)

    def get_entity_by_code(self, entity_code: str) -> LegalEntityDefinition | None:
        for e in self._entities.values():
            if e.entity_code == entity_code:
                return e
        return None

    def get_all_entities(self, active_only: bool = True) -> list[LegalEntityDefinition]:
        result = list(self._entities.values())
        if active_only:
            result = [e for e in result if e.is_active and e.deleted_at is None]
        return result

    def delete_entity(self, entity_id: UUID) -> bool:
        with self._lock:
            if entity_id in self._entities:
                del self._entities[entity_id]
                return True
            return False

    def save_authorization(self, auth: InterEntityAuthorization) -> None:
        with self._lock:
            key = (auth.from_entity_id, auth.to_entity_id)
            if key not in self._authorizations:
                self._authorizations[key] = []
            self._authorizations[key].append(auth)

    def get_authorizations(
        self, from_entity_id: UUID, to_entity_id: UUID, only_valid: bool = True
    ) -> list[InterEntityAuthorization]:
        key = (from_entity_id, to_entity_id)
        auths = self._authorizations.get(key, [])
        if only_valid:
            auths = [a for a in auths if a.is_valid()]
        return auths

    def get_authorizations_by_entity(
        self, entity_id: UUID, as_source: bool = True, only_valid: bool = True
    ) -> list[InterEntityAuthorization]:
        result = []
        for (src, tgt), auths in self._authorizations.items():
            if (as_source and src == entity_id) or (not as_source and tgt == entity_id):
                result.extend(auths)
        if only_valid:
            result = [a for a in result if a.is_valid()]
        return result

    def delete_authorization(self, auth_id: UUID) -> bool:
        with self._lock:
            for key, auths in self._authorizations.items():
                for i, a in enumerate(auths):
                    if a.auth_id == auth_id:
                        self._authorizations[key].pop(i)
                        return True
            return False

    def save_violation(self, violation: EntityIsolationViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        min_severity: EntityIsolationViolationSeverity | None = None,
        source_entity_id: UUID | None = None,
        target_entity_id: UUID | None = None,
        unresolved_only: bool = False,
    ) -> list[EntityIsolationViolation]:
        result = self._violation_history[-limit:]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if source_entity_id:
            result = [v for v in result if v.source_entity_id == source_entity_id]
        if target_entity_id:
            result = [v for v in result if v.target_entity_id == target_entity_id]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str
    ) -> EntityIsolationViolation | None:
        with self._lock:
            for i, v in enumerate(self._violation_history):
                if v.violation_id == violation_id and not v.resolved:
                    resolved = v.resolve(resolved_by)
                    self._violation_history[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS ====================
    def set_check_level(self, level: EntityIsolationCheckLevel) -> None:
        with self._lock:
            self._check_level = level

    def get_check_level(self) -> EntityIsolationCheckLevel:
        return self._check_level

    def register_entity(self, entity: LegalEntityDefinition) -> None:
        self.save_entity(entity)

    def grant_authorization(
        self,
        from_entity_id: UUID,
        to_entity_id: UUID,
        auth_type: InterEntityAuthorizationType,
        granted_by: str,
        approvers: list[str],
        purpose: str,
        allowed_operations: list[str],
        expires_at: datetime | None = None,
    ) -> InterEntityAuthorization:
        if not approvers:
            raise InterEntityAuthorizationError("At least one approver required")
        auth = InterEntityAuthorization(
            auth_id=uuid4(),
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            auth_type=auth_type,
            granted_by=granted_by,
            granted_at=datetime.now(UTC),
            expires_at=expires_at,
            approvers=approvers,
            purpose=purpose,
            allowed_operations=allowed_operations,
        )
        self.save_authorization(auth)
        return auth

    def enforce_access(
        self,
        source_entity_id: UUID,
        target_entity_id: UUID,
        operation: str,
        user_id: UUID | None = None,
        module: str = "unknown",
        raise_on_violation: bool = True,
    ) -> tuple[bool, EntityIsolationViolation | None]:
        auths = self.get_authorizations(source_entity_id, target_entity_id, only_valid=True)
        is_allowed, violation = EntityIsolationValidator.validate_access(
            source_entity_id, target_entity_id, operation, auths, user_id, module, self._check_level
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= EntityIsolationViolationSeverity.CRITICAL.value
            ):
                raise EntityIsolationViolationError(
                    violation.message,
                    violation.source_entity_id,
                    violation.target_entity_id,
                    violation.attempted_operation,
                    violation.severity,
                )
        return is_allowed, violation

    def is_same_entity(self, entity_id1: UUID, entity_id2: UUID) -> bool:
        return entity_id1 == entity_id2

    def is_related_entity(self, entity_id1: UUID, entity_id2: UUID) -> bool:
        if entity_id1 == entity_id2:
            return True
        ent1 = self.get_entity(entity_id1)
        ent2 = self.get_entity(entity_id2)
        if not ent1 or not ent2:
            return False
        if ent1.parent_entity_id == entity_id2 or ent2.parent_entity_id == entity_id1:
            return True
        if (
            ent1.consolidation_group
            and ent2.consolidation_group
            and ent1.consolidation_group == ent2.consolidation_group
        ):
            return True
        return False

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_entities = len(self._entities)
            active_entities = len([e for e in self._entities.values() if e.is_active])
            total_auths = sum(len(auths) for auths in self._authorizations.values())
            valid_auths = sum(
                len([a for a in auths if a.is_valid()]) for auths in self._authorizations.values()
            )
            total_violations = len(self._violation_history)
            unresolved = len([v for v in self._violation_history if not v.resolved])
            return {
                "total_entities": total_entities,
                "active_entities": active_entities,
                "total_authorizations": total_auths,
                "valid_authorizations": valid_auths,
                "total_violations": total_violations,
                "unresolved_violations": unresolved,
                "check_level": self._check_level.name,
            }

    def reset(self) -> None:
        with self._lock:
            self._entities = {}
            self._authorizations = {}
            self._violation_history = []
            self._check_level = EntityIsolationCheckLevel.STRICT


# === 6. SINGLETON ACCESSOR ===

_entity_isolation_axiom_instance: EntityIsolationAxiom | None = None


def get_entity_isolation_axiom() -> EntityIsolationAxiom:
    global _entity_isolation_axiom_instance
    if _entity_isolation_axiom_instance is None:
        _entity_isolation_axiom_instance = EntityIsolationAxiom()
    return _entity_isolation_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_legal_entity(
    entity_code: str,
    entity_name: str,
    tax_id: str,
    functional_currency: str,
    fiscal_year_start: int,
    country_code: str,
    parent_entity_id: UUID | None = None,
    consolidation_group: str | None = None,
) -> LegalEntityDefinition:
    return LegalEntityDefinition(
        entity_id=uuid4(),
        entity_code=entity_code,
        entity_name=entity_name,
        tax_id=tax_id,
        functional_currency=functional_currency.upper(),
        fiscal_year_start=fiscal_year_start,
        country_code=country_code.upper(),
        is_active=True,
        parent_entity_id=parent_entity_id,
        consolidation_group=consolidation_group,
    )


def create_inter_entity_authorization_dict(
    from_entity_id: UUID,
    to_entity_id: UUID,
    auth_type: str,
    purpose: str,
    allowed_operations: list[str],
    expires_in_days: int | None = None,
) -> dict[str, Any]:
    expires_at = None
    if expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
    return {
        "from_entity_id": from_entity_id,
        "to_entity_id": to_entity_id,
        "auth_type": auth_type,
        "purpose": purpose,
        "allowed_operations": allowed_operations,
        "expires_at": expires_at,
    }


__all__ = [
    "EntityIsolationAxiom",
    "EntityIsolationCheckLevel",
    "EntityIsolationValidator",
    "EntityIsolationViolation",
    "EntityIsolationViolationError",
    "EntityIsolationViolationSeverity",
    "InterEntityAuthorization",
    "InterEntityAuthorizationError",
    "InterEntityAuthorizationType",
    "LegalEntityDefinition",
    "create_inter_entity_authorization_dict",
    "create_legal_entity",
    "get_entity_isolation_axiom",
]