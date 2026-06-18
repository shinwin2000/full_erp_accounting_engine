#!/usr/bin/env python3
"""
Module: sovereignty_declaration.py
Layer: 1 - Foundation / Constitution
Responsibility: Deklarasi kedaulatan sistem.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class SovereigntyDomain(Enum):
    GENERAL_LEDGER = auto()
    SUBLEDGER_AR = auto()
    SUBLEDGER_AP = auto()
    INVENTORY = auto()
    FIXED_ASSET = auto()
    INTANGIBLE_ASSET = auto()
    TAX = auto()
    CORETAX = auto()
    USER_ACCESS = auto()
    AUDIT_TRAIL = auto()
    PERIOD_CONTROL = auto()
    APPROVAL_MATRIX = auto()
    POLICY_ENGINE = auto()
    CONSITUTION_ITSELF = auto()
    BANK_CASH = auto()
    PAYROLL = auto()
    MANUFACTURING = auto()
    PROJECT_SERVICES = auto()
    EQUITY_RETAINED = auto()
    LEGAL_ENTITY = auto()
    REPORTING = auto()


class SovereigntyStatus(Enum):
    SOVEREIGN = auto()
    DEGRADED = auto()
    OBSERVATION = auto()
    EMERGENCY_LOCKDOWN = auto()
    MAINTENANCE_MODE = auto()
    RECOVERY_MODE = auto()


class ExternalInterferenceType(Enum):
    UNAUTHORIZED_API_CALL = auto()
    DIRECT_DATABASE_MODIFICATION = auto()
    CONFIGURATION_TAMPERING = auto()
    CLOCK_TAMPERING = auto()
    CERTIFICATE_COMPROMISE = auto()
    UNAUTHORIZED_EXPORT = auto()
    POLICY_OVERRIDE_ATTEMPT = auto()
    DATA_EXFILTRATION = auto()
    MAN_IN_THE_MIDDLE = auto()
    REPLAY_ATTACK = auto()


class InterferenceSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


# === 2. EXCEPTIONS ===


class SovereigntyDeclarationError(Exception):
    pass


class ExternalInterferenceDetectedError(Exception):
    def __init__(
        self,
        interference_type: ExternalInterferenceType,
        source: str,
        details: str,
        evidence_hash: str,
        severity: InterferenceSeverity = InterferenceSeverity.HIGH,
    ):
        self.interference_type = interference_type
        self.source = source
        self.details = details
        self.evidence_hash = evidence_hash
        self.severity = severity
        super().__init__(
            f"External interference detected: {interference_type.name} from {source}. Details: {details}. Evidence hash: {evidence_hash}"
        )


class SovereigntyViolationError(Exception):
    pass


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class SovereigntyBoundary:
    # Required fields (no defaults)
    domain: SovereigntyDomain
    allowed_operations: set[str]
    allowed_sources: set[str]
    require_crypto_signature: bool
    audit_level: ConstitutionalSeverity
    # Optional fields (with defaults)
    max_external_calls_per_minute: int | None = None
    require_dual_control: bool = False
    min_approvers: int = 1
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if (
            self.max_external_calls_per_minute is not None
            and self.max_external_calls_per_minute < 0
        ):
            raise ValueError("max_external_calls_per_minute cannot be negative")
        if self.min_approvers < 1:
            raise ValueError("min_approvers must be at least 1")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "domain": self.domain.name,
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
                "domain": self.domain.name,
                "details": details,
            }
        )

    def create(self, created_by: str) -> SovereigntyBoundary:
        return self

    def update(self, updated_by: str, **kwargs) -> SovereigntyBoundary:
        new_boundary = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_boundary, key) and key not in ("domain", "version"):
                setattr(new_boundary, key, value)
        new_boundary.version = self.version + 1
        new_boundary._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_boundary

    def delete(self, deleted_by: str, reason: str | None = None) -> SovereigntyBoundary:
        new_boundary = self._copy()
        new_boundary.version = self.version + 1
        new_boundary._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_boundary

    def restore(self, restored_by: str) -> SovereigntyBoundary:
        new_boundary = self._copy()
        new_boundary.version = self.version + 1
        new_boundary._record_audit("RESTORE", restored_by, {})
        return new_boundary

    def activate(self, activated_by: str) -> SovereigntyBoundary:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> SovereigntyBoundary:
        return self

    def lock(self, locked_by: str, reason: str) -> SovereigntyBoundary:
        return self

    def unlock(self, unlocked_by: str) -> SovereigntyBoundary:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "domain": self.domain.name,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.name,
            "allowed_operations": list(self.allowed_operations),
            "allowed_sources": list(self.allowed_sources),
            "require_crypto_signature": self.require_crypto_signature,
            "max_external_calls_per_minute": self.max_external_calls_per_minute,
            "audit_level": self.audit_level.name,
            "require_dual_control": self.require_dual_control,
            "min_approvers": self.min_approvers,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SovereigntyBoundary:
        return cls(
            domain=SovereigntyDomain[data["domain"]],
            allowed_operations=set(data["allowed_operations"]),
            allowed_sources=set(data["allowed_sources"]),
            require_crypto_signature=data["require_crypto_signature"],
            max_external_calls_per_minute=data.get("max_external_calls_per_minute"),
            audit_level=ConstitutionalSeverity[data["audit_level"]],
            require_dual_control=data.get("require_dual_control", False),
            min_approvers=data.get("min_approvers", 1),
            version=data.get("version", 1),
        )

    def clone(self) -> SovereigntyBoundary:
        return SovereigntyBoundary(
            domain=self.domain,
            allowed_operations=self.allowed_operations.copy(),
            allowed_sources=self.allowed_sources.copy(),
            require_crypto_signature=self.require_crypto_signature,
            max_external_calls_per_minute=self.max_external_calls_per_minute,
            audit_level=self.audit_level,
            require_dual_control=self.require_dual_control,
            min_approvers=self.min_approvers,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "domain": self.domain.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SovereigntyBoundary:
        new_boundary = self._copy()
        new_boundary.version = self.version + 1
        new_boundary._record_audit("TOUCH", touched_by, {})
        return new_boundary

    def allows_operation(self, operation: str, source: str) -> bool:
        return operation in self.allowed_operations and source in self.allowed_sources

    def _copy(self) -> SovereigntyBoundary:
        return SovereigntyBoundary(
            domain=self.domain,
            allowed_operations=self.allowed_operations.copy(),
            allowed_sources=self.allowed_sources.copy(),
            require_crypto_signature=self.require_crypto_signature,
            max_external_calls_per_minute=self.max_external_calls_per_minute,
            audit_level=self.audit_level,
            require_dual_control=self.require_dual_control,
            min_approvers=self.min_approvers,
            version=self.version,
        )


@dataclass(kw_only=True)
class SovereigntyEvent:
    # Required fields (no defaults)
    event_id: UUID
    previous_status: SovereigntyStatus
    new_status: SovereigntyStatus
    reason: str
    initiated_by: str
    initiated_at: datetime
    approved_by: list[str]
    affected_domains: list[SovereigntyDomain]
    # Optional fields (with defaults)
    expiry_at: datetime | None = None
    cryptographic_signature: str = ""
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.initiated_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "event_id": str(self.event_id),
                "new_status": self.new_status.name,
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
                "event_id": str(self.event_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> SovereigntyEvent:
        return self

    def update(self, updated_by: str, **kwargs) -> SovereigntyEvent:
        raise AttributeError("SovereigntyEvent is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> SovereigntyEvent:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> SovereigntyEvent:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> SovereigntyEvent:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> SovereigntyEvent:
        return self

    def lock(self, locked_by: str, reason: str) -> SovereigntyEvent:
        return self

    def unlock(self, unlocked_by: str) -> SovereigntyEvent:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "event_id": str(self.event_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "previous_status": self.previous_status.name,
            "new_status": self.new_status.name,
            "reason": self.reason,
            "initiated_by": self.initiated_by,
            "initiated_at": self.initiated_at.isoformat(),
            "approved_by": self.approved_by,
            "expiry_at": self.expiry_at.isoformat() if self.expiry_at else None,
            "cryptographic_signature": self.cryptographic_signature[:16] + "...",
            "affected_domains": [d.name for d in self.affected_domains],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SovereigntyEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            previous_status=SovereigntyStatus[data["previous_status"]],
            new_status=SovereigntyStatus[data["new_status"]],
            reason=data["reason"],
            initiated_by=data["initiated_by"],
            initiated_at=datetime.fromisoformat(data["initiated_at"]),
            approved_by=data["approved_by"],
            expiry_at=datetime.fromisoformat(data["expiry_at"]) if data.get("expiry_at") else None,
            cryptographic_signature=data.get("cryptographic_signature", ""),
            affected_domains=[SovereigntyDomain[d] for d in data.get("affected_domains", [])],
            version=data.get("version", 1),
        )

    def clone(self) -> SovereigntyEvent:
        new_id = uuid4()
        return SovereigntyEvent(
            event_id=new_id,
            previous_status=self.previous_status,
            new_status=self.new_status,
            reason=self.reason,
            initiated_by=self.initiated_by,
            initiated_at=datetime.now(UTC),
            approved_by=self.approved_by.copy(),
            expiry_at=self.expiry_at,
            cryptographic_signature=self.cryptographic_signature,
            affected_domains=self.affected_domains.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "event_id": str(self.event_id),
            "new_status": self.new_status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SovereigntyEvent:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_active(self) -> bool:
        if self.expiry_at is None:
            return True
        return datetime.now(UTC) < self.expiry_at

    def compute_signature_content(self) -> str:
        domains_str = (
            ",".join(str(d.value) for d in self.affected_domains) if self.affected_domains else ""
        )
        return f"{self.event_id}|{self.previous_status.value}|{self.new_status.value}|{self.reason}|{self.initiated_by}|{self.initiated_at.isoformat()}|{','.join(self.approved_by)}|{self.expiry_at.isoformat() if self.expiry_at else ''}|{domains_str}"


@dataclass(kw_only=True)
class InterferenceRecord:
    # Required fields (no defaults)
    record_id: UUID
    interference_type: ExternalInterferenceType
    detected_at: datetime
    source_module: str
    payload_hash: str
    description: str
    mitigated: bool
    # Optional fields (with defaults)
    source_ip: str | None = None
    mitigated_at: datetime | None = None
    mitigated_by: str | None = None
    mitigation_action: str | None = None
    severity: InterferenceSeverity = InterferenceSeverity.MEDIUM
    evidence_store_path: str | None = None
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.source_module, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "record_id": str(self.record_id),
                "interference_type": self.interference_type.name,
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
                "record_id": str(self.record_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> InterferenceRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> InterferenceRecord:
        raise AttributeError("InterferenceRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> InterferenceRecord:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> InterferenceRecord:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> InterferenceRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> InterferenceRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> InterferenceRecord:
        return self

    def unlock(self, unlocked_by: str) -> InterferenceRecord:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "record_id": str(self.record_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "interference_type": self.interference_type.name,
            "detected_at": self.detected_at.isoformat(),
            "source_ip": self.source_ip,
            "source_module": self.source_module,
            "payload_hash": self.payload_hash[:16] + "...",
            "description": self.description,
            "mitigated": self.mitigated,
            "mitigated_at": self.mitigated_at.isoformat() if self.mitigated_at else None,
            "mitigated_by": self.mitigated_by,
            "mitigation_action": self.mitigation_action,
            "severity": self.severity.name,
            "evidence_store_path": self.evidence_store_path,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterferenceRecord:
        return cls(
            record_id=UUID(data["record_id"]),
            interference_type=ExternalInterferenceType[data["interference_type"]],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            source_ip=data.get("source_ip"),
            source_module=data["source_module"],
            payload_hash=data["payload_hash"],
            description=data["description"],
            mitigated=data["mitigated"],
            mitigated_at=datetime.fromisoformat(data["mitigated_at"])
            if data.get("mitigated_at")
            else None,
            mitigated_by=data.get("mitigated_by"),
            mitigation_action=data.get("mitigation_action"),
            severity=InterferenceSeverity[data["severity"]]
            if "severity" in data
            else InterferenceSeverity.MEDIUM,
            evidence_store_path=data.get("evidence_store_path"),
            version=data.get("version", 1),
        )

    def clone(self) -> InterferenceRecord:
        new_id = uuid4()
        return InterferenceRecord(
            record_id=new_id,
            interference_type=self.interference_type,
            detected_at=datetime.now(UTC),
            source_ip=self.source_ip,
            source_module=self.source_module,
            payload_hash=self.payload_hash,
            description=self.description,
            mitigated=False,
            mitigated_at=None,
            mitigated_by=None,
            mitigation_action=None,
            severity=self.severity,
            evidence_store_path=self.evidence_store_path,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "record_id": str(self.record_id),
            "interference_type": self.interference_type.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InterferenceRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def mark_mitigated(self, by: str, action: str) -> InterferenceRecord:
        if self.mitigated:
            raise ValueError("Already mitigated")
        new_record = self._copy()
        new_record.mitigated = True
        new_record.mitigated_at = datetime.now(UTC)
        new_record.mitigated_by = by
        new_record.mitigation_action = action
        new_record.version = self.version + 1
        new_record._record_audit("MITIGATE", by, {"action": action})
        return new_record

    def _copy(self) -> InterferenceRecord:
        return InterferenceRecord(
            record_id=self.record_id,
            interference_type=self.interference_type,
            detected_at=self.detected_at,
            source_ip=self.source_ip,
            source_module=self.source_module,
            payload_hash=self.payload_hash,
            description=self.description,
            mitigated=self.mitigated,
            mitigated_at=self.mitigated_at,
            mitigated_by=self.mitigated_by,
            mitigation_action=self.mitigation_action,
            severity=self.severity,
            evidence_store_path=self.evidence_store_path,
            version=self.version,
        )


@dataclass(kw_only=True)
class SovereigntyReport:
    # Required fields (no defaults)
    report_id: UUID
    generated_at: datetime
    current_status: SovereigntyStatus
    active_domains: list[SovereigntyDomain]
    recent_interferences: list[InterferenceRecord]
    recent_status_changes: list[SovereigntyEvent]
    seal_valid: bool
    recommendations: list[str]
    # Optional fields (with defaults)
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "report_id": str(self.report_id),
                "current_status": self.current_status.name,
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
                "report_id": str(self.report_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> SovereigntyReport:
        return self

    def update(self, updated_by: str, **kwargs) -> SovereigntyReport:
        raise AttributeError("SovereigntyReport is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> SovereigntyReport:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> SovereigntyReport:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> SovereigntyReport:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> SovereigntyReport:
        return self

    def lock(self, locked_by: str, reason: str) -> SovereigntyReport:
        return self

    def unlock(self, unlocked_by: str) -> SovereigntyReport:
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
            "report_id": str(self.report_id),
            "version": self.version,
        }

    def compute_hash(self) -> str:
        content = f"{self.report_id}|{self.generated_at.isoformat()}|{self.current_status.value}|{len(self.active_domains)}|{len(self.recent_interferences)}|{len(self.recent_status_changes)}|{self.seal_valid}|{','.join(self.recommendations)}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": str(self.report_id),
            "generated_at": self.generated_at.isoformat(),
            "current_status": self.current_status.name,
            "active_domains": [d.name for d in self.active_domains],
            "recent_interferences": [r.to_dict() for r in self.recent_interferences[:10]],
            "recent_status_changes": [e.to_dict() for e in self.recent_status_changes[:10]],
            "seal_valid": self.seal_valid,
            "recommendations": self.recommendations,
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SovereigntyReport:
        return cls(
            report_id=UUID(data["report_id"]),
            generated_at=datetime.fromisoformat(data["generated_at"]),
            current_status=SovereigntyStatus[data["current_status"]],
            active_domains=[SovereigntyDomain[d] for d in data.get("active_domains", [])],
            recent_interferences=[
                InterferenceRecord.from_dict(r) for r in data.get("recent_interferences", [])
            ],
            recent_status_changes=[
                SovereigntyEvent.from_dict(e) for e in data.get("recent_status_changes", [])
            ],
            seal_valid=data["seal_valid"],
            recommendations=data["recommendations"],
            cryptographic_hash=data.get("cryptographic_hash", ""),
            version=data.get("version", 1),
        )

    def clone(self) -> SovereigntyReport:
        new_id = uuid4()
        return SovereigntyReport(
            report_id=new_id,
            generated_at=datetime.now(UTC),
            current_status=self.current_status,
            active_domains=self.active_domains.copy(),
            recent_interferences=[r.clone() for r in self.recent_interferences],
            recent_status_changes=[e.clone() for e in self.recent_status_changes],
            seal_valid=self.seal_valid,
            recommendations=self.recommendations.copy(),
            cryptographic_hash="",
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "report_id": str(self.report_id),
            "current_status": self.current_status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SovereigntyReport:
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. SOVEREIGNTY DECLARATION AGGREGATE ===


@dataclass(kw_only=True)
class SovereigntyDeclaration:
    system_id: str
    system_name: str
    declaration_version: str
    declared_at: datetime
    declared_by: str
    cryptographic_seal: str
    boundaries: dict[SovereigntyDomain, SovereigntyBoundary] = field(default_factory=dict)
    status_history: list[SovereigntyEvent] = field(default_factory=list)
    interference_log: list[InterferenceRecord] = field(default_factory=list)
    _current_status: SovereigntyStatus = field(default=SovereigntyStatus.SOVEREIGN, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.boundaries:
            self._load_default_boundaries()
        if not self.status_history:
            initial_event = SovereigntyEvent(
                event_id=uuid4(),
                previous_status=SovereigntyStatus.SOVEREIGN,
                new_status=SovereigntyStatus.SOVEREIGN,
                reason="System initialization",
                initiated_by="system_bootstrap",
                initiated_at=self.declared_at,
                approved_by=["system_bootstrap"],
                expiry_at=None,
                cryptographic_signature="",
                affected_domains=list(self.boundaries.keys()),
                version=1,
            )
            self.status_history.append(initial_event)

    def _load_default_boundaries(self) -> None:
        default_boundaries = {
            SovereigntyDomain.GENERAL_LEDGER: SovereigntyBoundary(
                domain=SovereigntyDomain.GENERAL_LEDGER,
                allowed_operations={"CREATE", "READ", "UPDATE_VIA_REVERSAL_ONLY"},
                allowed_sources={"internal_api", "cli_authorized", "scheduled_job"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.CRITICAL,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.SUBLEDGER_AR: SovereigntyBoundary(
                domain=SovereigntyDomain.SUBLEDGER_AR,
                allowed_operations={"CREATE", "READ", "UPDATE_VIA_CREDIT_NOTE"},
                allowed_sources={"internal_api", "cli_authorized"},
                require_crypto_signature=True,
                max_external_calls_per_minute=10,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=False,
                min_approvers=1,
            ),
            SovereigntyDomain.SUBLEDGER_AP: SovereigntyBoundary(
                domain=SovereigntyDomain.SUBLEDGER_AP,
                allowed_operations={"CREATE", "READ", "UPDATE_VIA_CREDIT_NOTE"},
                allowed_sources={"internal_api", "cli_authorized"},
                require_crypto_signature=True,
                max_external_calls_per_minute=10,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=False,
                min_approvers=1,
            ),
            SovereigntyDomain.INVENTORY: SovereigntyBoundary(
                domain=SovereigntyDomain.INVENTORY,
                allowed_operations={"CREATE", "READ", "ADJUSTMENT_WITH_APPROVAL"},
                allowed_sources={"internal_api", "cli_authorized", "warehouse_scanner"},
                require_crypto_signature=False,
                max_external_calls_per_minute=100,
                audit_level=ConstitutionalSeverity.MEDIUM,
                require_dual_control=False,
                min_approvers=1,
            ),
            SovereigntyDomain.FIXED_ASSET: SovereigntyBoundary(
                domain=SovereigntyDomain.FIXED_ASSET,
                allowed_operations={"CREATE", "READ", "DEPRECIATE_ONLY"},
                allowed_sources={"internal_api", "scheduled_job"},
                require_crypto_signature=True,
                max_external_calls_per_minute=5,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.TAX: SovereigntyBoundary(
                domain=SovereigntyDomain.TAX,
                allowed_operations={"CREATE", "READ", "SUBMIT_TO_CORETAX"},
                allowed_sources={"internal_api", "coretax_webhook"},
                require_crypto_signature=True,
                max_external_calls_per_minute=30,
                audit_level=ConstitutionalSeverity.CRITICAL,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.CORETAX: SovereigntyBoundary(
                domain=SovereigntyDomain.CORETAX,
                allowed_operations={"CREATE", "READ", "SUBMIT", "QUERY"},
                allowed_sources={"internal_api", "coretax_webhook"},
                require_crypto_signature=True,
                max_external_calls_per_minute=60,
                audit_level=ConstitutionalSeverity.CRITICAL,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.USER_ACCESS: SovereigntyBoundary(
                domain=SovereigntyDomain.USER_ACCESS,
                allowed_operations={"CREATE", "READ", "UPDATE", "DELETE"},
                allowed_sources={"internal_api", "cli_authorized_only"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.CRITICAL,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.AUDIT_TRAIL: SovereigntyBoundary(
                domain=SovereigntyDomain.AUDIT_TRAIL,
                allowed_operations={"READ_ONLY"},
                allowed_sources={"internal_api", "audit_tool"},
                require_crypto_signature=False,
                max_external_calls_per_minute=20,
                audit_level=ConstitutionalSeverity.CRITICAL,
                require_dual_control=False,
                min_approvers=1,
            ),
            SovereigntyDomain.PERIOD_CONTROL: SovereigntyBoundary(
                domain=SovereigntyDomain.PERIOD_CONTROL,
                allowed_operations={"READ", "CLOSE", "REOPEN_WITH_AUDIT"},
                allowed_sources={"internal_api", "cli_dual_control"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.APPROVAL_MATRIX: SovereigntyBoundary(
                domain=SovereigntyDomain.APPROVAL_MATRIX,
                allowed_operations={"READ", "UPDATE_WITH_DUAL_APPROVAL"},
                allowed_sources={"internal_api"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.POLICY_ENGINE: SovereigntyBoundary(
                domain=SovereigntyDomain.POLICY_ENGINE,
                allowed_operations={"READ", "UPDATE_VIA_AMENDMENT"},
                allowed_sources={"internal_api", "policy_administrator"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.MEDIUM,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.CONSITUTION_ITSELF: SovereigntyBoundary(
                domain=SovereigntyDomain.CONSITUTION_ITSELF,
                allowed_operations={"READ_ONLY"},
                allowed_sources={"internal_api"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.CRITICAL,
                require_dual_control=True,
                min_approvers=3,
            ),
            SovereigntyDomain.BANK_CASH: SovereigntyBoundary(
                domain=SovereigntyDomain.BANK_CASH,
                allowed_operations={"CREATE", "READ", "RECONCILE"},
                allowed_sources={"internal_api", "bank_webhook"},
                require_crypto_signature=True,
                max_external_calls_per_minute=20,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.PAYROLL: SovereigntyBoundary(
                domain=SovereigntyDomain.PAYROLL,
                allowed_operations={"CREATE", "READ", "EXECUTE_RUN"},
                allowed_sources={"internal_api", "scheduled_job"},
                require_crypto_signature=True,
                max_external_calls_per_minute=5,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.MANUFACTURING: SovereigntyBoundary(
                domain=SovereigntyDomain.MANUFACTURING,
                allowed_operations={"CREATE", "READ", "UPDATE"},
                allowed_sources={"internal_api", "mes_webhook"},
                require_crypto_signature=False,
                max_external_calls_per_minute=50,
                audit_level=ConstitutionalSeverity.MEDIUM,
                require_dual_control=False,
                min_approvers=1,
            ),
            SovereigntyDomain.PROJECT_SERVICES: SovereigntyBoundary(
                domain=SovereigntyDomain.PROJECT_SERVICES,
                allowed_operations={"CREATE", "READ", "UPDATE"},
                allowed_sources={"internal_api", "pms_webhook"},
                require_crypto_signature=False,
                max_external_calls_per_minute=30,
                audit_level=ConstitutionalSeverity.MEDIUM,
                require_dual_control=False,
                min_approvers=1,
            ),
            SovereigntyDomain.EQUITY_RETAINED: SovereigntyBoundary(
                domain=SovereigntyDomain.EQUITY_RETAINED,
                allowed_operations={"READ", "UPDATE_WITH_DUAL_APPROVAL"},
                allowed_sources={"internal_api"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.CRITICAL,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.LEGAL_ENTITY: SovereigntyBoundary(
                domain=SovereigntyDomain.LEGAL_ENTITY,
                allowed_operations={"CREATE", "READ", "UPDATE_WITH_APPROVAL"},
                allowed_sources={"internal_api", "cli_authorized"},
                require_crypto_signature=True,
                max_external_calls_per_minute=0,
                audit_level=ConstitutionalSeverity.HIGH,
                require_dual_control=True,
                min_approvers=2,
            ),
            SovereigntyDomain.REPORTING: SovereigntyBoundary(
                domain=SovereigntyDomain.REPORTING,
                allowed_operations={"READ", "EXPORT"},
                allowed_sources={"internal_api", "reporting_tool"},
                require_crypto_signature=False,
                max_external_calls_per_minute=50,
                audit_level=ConstitutionalSeverity.MEDIUM,
                require_dual_control=False,
                min_approvers=1,
            ),
        }
        self.boundaries = default_boundaries

    @property
    def current_status(self) -> SovereigntyStatus:
        active_events = [e for e in self.status_history if e.is_active()]
        if not active_events:
            return SovereigntyStatus.SOVEREIGN
        latest = max(active_events, key=lambda e: e.initiated_at)
        return latest.new_status

    # ==================== REPOSITORY METHODS ====================
    def save_boundary(self, boundary: SovereigntyBoundary) -> None:
        with self._lock:
            self.boundaries[boundary.domain] = boundary

    def get_boundary(self, domain: SovereigntyDomain) -> SovereigntyBoundary | None:
        return self.boundaries.get(domain)

    def get_all_boundaries(self) -> list[SovereigntyBoundary]:
        return list(self.boundaries.values())

    def delete_boundary(self, domain: SovereigntyDomain) -> bool:
        with self._lock:
            if domain in self.boundaries:
                del self.boundaries[domain]
                return True
            return False

    def save_status_event(self, event: SovereigntyEvent) -> None:
        with self._lock:
            self.status_history.append(event)

    def get_status_events(self, limit: int = 100) -> list[SovereigntyEvent]:
        return self.status_history[-limit:]

    def delete_status_event(self, event_id: UUID) -> bool:
        with self._lock:
            for i, e in enumerate(self.status_history):
                if e.event_id == event_id:
                    self.status_history.pop(i)
                    return True
            return False

    def save_interference(self, record: InterferenceRecord) -> None:
        with self._lock:
            self.interference_log.append(record)

    def get_interferences(
        self, limit: int = 100, only_unmitigated: bool = False
    ) -> list[InterferenceRecord]:
        result = self.interference_log[-limit:]
        if only_unmitigated:
            result = [r for r in result if not r.mitigated]
        return result

    def delete_interference(self, record_id: UUID) -> bool:
        with self._lock:
            for i, r in enumerate(self.interference_log):
                if r.record_id == record_id:
                    self.interference_log.pop(i)
                    return True
            return False

    # ==================== BUSINESS METHODS ====================
    def change_status(
        self,
        new_status: SovereigntyStatus,
        reason: str,
        initiated_by: str,
        approved_by: list[str],
        expiry_at: datetime | None = None,
        affected_domains: list[SovereigntyDomain] | None = None,
        cryptographic_signer: Callable[[str], str] | None = None,
    ) -> SovereigntyEvent:
        with self._lock:
            downgrade_to = [
                SovereigntyStatus.DEGRADED,
                SovereigntyStatus.EMERGENCY_LOCKDOWN,
                SovereigntyStatus.RECOVERY_MODE,
            ]
            if new_status in downgrade_to and len(approved_by) < 2:
                raise SovereigntyDeclarationError(
                    f"Changing to {new_status.name} requires at least 2 approvers"
                )
            if new_status == SovereigntyStatus.EMERGENCY_LOCKDOWN:
                if initiated_by != "system" and not any(
                    a == "emergency_admin" for a in approved_by
                ):
                    raise SovereigntyDeclarationError(
                        "EMERGENCY_LOCKDOWN requires emergency_admin approval"
                    )
            previous = self.current_status
            event = SovereigntyEvent(
                event_id=uuid4(),
                previous_status=previous,
                new_status=new_status,
                reason=reason,
                initiated_by=initiated_by,
                initiated_at=datetime.now(UTC),
                approved_by=approved_by,
                expiry_at=expiry_at,
                cryptographic_signature="",
                affected_domains=affected_domains or list(self.boundaries.keys()),
                version=1,
            )
            if cryptographic_signer:
                sig_content = event.compute_signature_content()
                event = SovereigntyEvent(
                    event_id=event.event_id,
                    previous_status=event.previous_status,
                    new_status=event.new_status,
                    reason=event.reason,
                    initiated_by=event.initiated_by,
                    initiated_at=event.initiated_at,
                    approved_by=event.approved_by,
                    expiry_at=event.expiry_at,
                    cryptographic_signature=cryptographic_signer(sig_content),
                    affected_domains=event.affected_domains,
                    version=1,
                )
            self.status_history.append(event)
            self._notify_constitution(new_status)
            logger.warning(
                f"Sovereignty status changed: {previous.name} -> {new_status.name}. Reason: {reason}"
            )
            return event

    def _notify_constitution(self, new_status: SovereigntyStatus) -> None:
        try:
            supreme_law = get_supreme_law()
            if new_status == SovereigntyStatus.EMERGENCY_LOCKDOWN:
                supreme_law.check_violation(
                    principle=ConstitutionalPrinciple.GOING_CONCERN,
                    offending_module="sovereignty_declaration",
                    message="System entered EMERGENCY_LOCKDOWN",
                )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")

    def check_operation_permitted(
        self,
        domain: SovereigntyDomain,
        operation: str,
        source: str,
        user_roles: list[str] | None = None,
    ) -> tuple[bool, str]:
        boundary = self.boundaries.get(domain)
        if not boundary:
            return False, f"Unknown sovereignty domain: {domain.name}"
        status = self.current_status
        if status == SovereigntyStatus.EMERGENCY_LOCKDOWN:
            if operation != "READ":
                return False, "EMERGENCY_LOCKDOWN: only READ operations allowed"
            if domain not in [SovereigntyDomain.AUDIT_TRAIL, SovereigntyDomain.GENERAL_LEDGER]:
                return False, f"EMERGENCY_LOCKDOWN: domain {domain.name} not accessible"
        if status == SovereigntyStatus.MAINTENANCE_MODE:
            if source not in ["internal_api", "cli_authorized"]:
                return False, "MAINTENANCE_MODE: source not allowed"
        if status == SovereigntyStatus.OBSERVATION:
            if operation not in ["READ", "EXPORT_READONLY"]:
                return False, "OBSERVATION: write operation not allowed"
        if status == SovereigntyStatus.RECOVERY_MODE:
            if source not in ["internal_api", "recovery_tool"]:
                return False, "RECOVERY_MODE: source not allowed"
            if operation not in ["READ", "RECOVER"]:
                return False, "RECOVERY_MODE: operation not allowed"
        if not boundary.allows_operation(operation, source):
            return False, f"Operation {operation} on {domain.name} from {source} not allowed"
        return True, "OK"

    def record_interference(
        self,
        interference_type: ExternalInterferenceType,
        source_module: str,
        description: str,
        payload_hash: str,
        source_ip: str | None = None,
        severity: InterferenceSeverity = InterferenceSeverity.MEDIUM,
        evidence_store_path: str | None = None,
    ) -> InterferenceRecord:
        with self._lock:
            record = InterferenceRecord(
                record_id=uuid4(),
                interference_type=interference_type,
                detected_at=datetime.now(UTC),
                source_ip=source_ip,
                source_module=source_module,
                payload_hash=payload_hash,
                description=description,
                mitigated=False,
                mitigated_at=None,
                mitigated_by=None,
                mitigation_action=None,
                severity=severity,
                evidence_store_path=evidence_store_path,
                version=1,
            )
            self.interference_log.append(record)
            critical_types = [
                ExternalInterferenceType.DIRECT_DATABASE_MODIFICATION,
                ExternalInterferenceType.CONFIGURATION_TAMPERING,
                ExternalInterferenceType.CLOCK_TAMPERING,
                ExternalInterferenceType.DATA_EXFILTRATION,
            ]
            if interference_type in critical_types or severity in [
                InterferenceSeverity.CATASTROPHIC,
                InterferenceSeverity.CRITICAL,
            ]:
                try:
                    supreme_law = get_supreme_law()
                    supreme_law.check_violation(
                        ConstitutionalPrinciple.IMMUTABILITY,
                        source_module,
                        f"External interference: {interference_type.name} - {description}",
                    )
                except Exception as e:
                    logger.error(f"Failed to log interference: {e}")
                if (
                    severity == InterferenceSeverity.CATASTROPHIC
                    and self.current_status != SovereigntyStatus.EMERGENCY_LOCKDOWN
                ):
                    try:
                        self.change_status(
                            SovereigntyStatus.EMERGENCY_LOCKDOWN,
                            f"Auto-lockdown due to {interference_type.name}",
                            "system",
                            ["system_auto"],
                            datetime.now(UTC) + timedelta(hours=1),
                        )
                    except Exception as e:
                        logger.critical(f"Failed to auto-lockdown: {e}")
            return record

    def verify_seal(self) -> bool:
        content = f"{self.system_id}|{self.system_name}|{self.declaration_version}|{self.declared_at.isoformat()}|{self.declared_by}"
        computed = hashlib.sha3_256(content.encode()).hexdigest()
        return computed == self.cryptographic_seal

    def generate_report(self) -> SovereigntyReport:
        recent_interferences = self.interference_log[-20:] if self.interference_log else []
        recent_status_changes = self.status_history[-10:] if self.status_history else []
        recommendations = []
        if not self.verify_seal():
            recommendations.append("CRITICAL: Cryptographic seal is invalid!")
        if len([i for i in self.interference_log if not i.mitigated]) > 5:
            recommendations.append("Multiple unresolved interferences detected.")
        if self.current_status != SovereigntyStatus.SOVEREIGN:
            recommendations.append(
                f"System is in {self.current_status.name} mode. Plan restoration."
            )
        report = SovereigntyReport(
            report_id=uuid4(),
            generated_at=datetime.now(UTC),
            current_status=self.current_status,
            active_domains=list(self.boundaries.keys()),
            recent_interferences=recent_interferences,
            recent_status_changes=recent_status_changes,
            seal_valid=self.verify_seal(),
            recommendations=recommendations,
            cryptographic_hash="",
            version=1,
        )
        # Recompute hash after creation
        report = SovereigntyReport(
            report_id=report.report_id,
            generated_at=report.generated_at,
            current_status=report.current_status,
            active_domains=report.active_domains,
            recent_interferences=report.recent_interferences,
            recent_status_changes=report.recent_status_changes,
            seal_valid=report.seal_valid,
            recommendations=report.recommendations,
            cryptographic_hash=report.compute_hash(),
            version=1,
        )
        return report

    def get_interference_statistics(self) -> dict[str, Any]:
        total = len(self.interference_log)
        if total == 0:
            return {"total": 0}
        by_type = {
            it.name: len([i for i in self.interference_log if i.interference_type == it])
            for it in ExternalInterferenceType
            if any(i.interference_type == it for i in self.interference_log)
        }
        by_severity = {
            sev.name: len([i for i in self.interference_log if i.severity == sev])
            for sev in InterferenceSeverity
            if any(i.severity == sev for i in self.interference_log)
        }
        mitigated = len([i for i in self.interference_log if i.mitigated])
        unresolved = total - mitigated
        return {
            "total_interferences": total,
            "mitigated": mitigated,
            "unresolved": unresolved,
            "by_type": by_type,
            "by_severity": by_severity,
            "last_interference": self.interference_log[-1].detected_at.isoformat()
            if self.interference_log
            else None,
        }

    def get_statistics(self) -> dict[str, Any]:
        return {
            "boundaries_count": len(self.boundaries),
            "status_history_count": len(self.status_history),
            "current_status": self.current_status.name,
            "interference_statistics": self.get_interference_statistics(),
            "seal_valid": self.verify_seal(),
        }

    def reset(self) -> None:
        with self._lock:
            self.boundaries = {}
            self.status_history = []
            self.interference_log = []
            self._load_default_boundaries()
            initial_event = SovereigntyEvent(
                event_id=uuid4(),
                previous_status=SovereigntyStatus.SOVEREIGN,
                new_status=SovereigntyStatus.SOVEREIGN,
                reason="Reset",
                initiated_by="system",
                initiated_at=datetime.now(UTC),
                approved_by=["system"],
                expiry_at=None,
                cryptographic_signature="",
                affected_domains=list(self.boundaries.keys()),
                version=1,
            )
            self.status_history.append(initial_event)


# === 5. SOVEREIGNTY GUARDIAN SERVICE ===


class SovereigntyGuardian:
    _instance: SovereigntyGuardian | None = None
    _lock = threading.Lock()

    def __new__(cls) -> SovereigntyGuardian:
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
        self._init_declaration()

    def _init_declaration(self) -> None:
        now = datetime.now(UTC)
        content = (
            f"erp_system|Enterprise ERP Accounting Engine|1.0.0|{now.isoformat()}|system_bootstrap"
        )
        seal = hashlib.sha3_256(content.encode()).hexdigest()
        self._declaration = SovereigntyDeclaration(
            system_id="erp_system",
            system_name="Enterprise ERP Accounting Engine",
            declaration_version="1.0.0",
            declared_at=now,
            declared_by="system_bootstrap",
            cryptographic_seal=seal,
        )

    def guard(
        self,
        domain: SovereigntyDomain,
        operation: str,
        source: str,
        context: dict[str, Any],
        user_roles: list[str] | None = None,
    ) -> bool:
        if domain not in self._declaration.boundaries:
            raise SovereigntyViolationError(f"Unknown sovereignty domain: {domain}")
        permitted, reason = self._declaration.check_operation_permitted(
            domain, operation, source, user_roles
        )
        if not permitted:
            self._declaration.record_interference(
                ExternalInterferenceType.UNAUTHORIZED_API_CALL,
                source,
                f"Unauthorized {operation} on {domain.name}",
                hashlib.sha3_256(str(context).encode()).hexdigest(),
                severity=InterferenceSeverity.MEDIUM,
            )
            raise SovereigntyViolationError(reason)
        unresolved_critical = [
            i
            for i in self._declaration.interference_log[-10:]
            if not i.mitigated
            and i.severity in [InterferenceSeverity.CATASTROPHIC, InterferenceSeverity.CRITICAL]
        ]
        if unresolved_critical:
            r = unresolved_critical[0]
            raise ExternalInterferenceDetectedError(
                r.interference_type, r.source_module, r.description, r.payload_hash, r.severity
            )
        return True

    def get_current_status(self) -> SovereigntyStatus:
        return self._declaration.current_status

    def get_declaration(self) -> SovereigntyDeclaration:
        return self._declaration

    def is_system_operational(self) -> bool:
        status = self._declaration.current_status
        return status in [SovereigntyStatus.SOVEREIGN, SovereigntyStatus.OBSERVATION]

    def emergency_lockdown(self, reason: str, initiated_by: str) -> SovereigntyEvent:
        return self._declaration.change_status(
            SovereigntyStatus.EMERGENCY_LOCKDOWN,
            reason,
            initiated_by,
            [initiated_by],
            datetime.now(UTC) + timedelta(hours=1),
        )

    def record_interference(
        self,
        interference_type: ExternalInterferenceType,
        source_module: str,
        description: str,
        payload_hash: str,
        source_ip: str | None = None,
        severity: InterferenceSeverity = InterferenceSeverity.MEDIUM,
    ) -> InterferenceRecord:
        return self._declaration.record_interference(
            interference_type, source_module, description, payload_hash, source_ip, severity
        )

    def generate_report(self) -> SovereigntyReport:
        return self._declaration.generate_report()

    def get_boundary(self, domain: SovereigntyDomain) -> SovereigntyBoundary | None:
        return self._declaration.boundaries.get(domain)

    def get_statistics(self) -> dict[str, Any]:
        return self._declaration.get_statistics()

    def reset(self) -> None:
        self._declaration.reset()


def get_sovereignty_guardian() -> SovereigntyGuardian:
    global _sovereignty_guardian_instance
    if _sovereignty_guardian_instance is None:
        _sovereignty_guardian_instance = SovereigntyGuardian()
    return _sovereignty_guardian_instance


_sovereignty_guardian_instance: SovereigntyGuardian | None = None

__all__ = [
    "ExternalInterferenceDetectedError",
    "ExternalInterferenceType",
    "InterferenceRecord",
    "InterferenceSeverity",
    "SovereigntyBoundary",
    "SovereigntyDeclaration",
    "SovereigntyDeclarationError",
    "SovereigntyDomain",
    "SovereigntyEvent",
    "SovereigntyGuardian",
    "SovereigntyReport",
    "SovereigntyStatus",
    "SovereigntyViolationError",
    "get_sovereignty_guardian",
]
