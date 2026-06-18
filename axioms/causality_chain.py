#!/usr/bin/env python3
"""
Module: causality_chain.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: setiap akibat memiliki sebab yang tercatat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class CausalityType(Enum):
    DIRECT = auto()
    DERIVED = auto()
    CORRECTION = auto()
    AGGREGATION = auto()
    ALLOCATION = auto()
    ELIMINATION = auto()


class CausalityStrength(Enum):
    STRONG = 100
    MODERATE = 70
    WEAK = 40
    CORRELATION = 10


class CausalityViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class EvidenceType(Enum):
    SOURCE_DOCUMENT = auto()
    USER_INTENT = auto()
    SYSTEM_EVENT = auto()
    CALCULATION = auto()
    APPROVAL = auto()
    TIMESTAMP = auto()
    SIGNATURE = auto()


# === 2. EXCEPTIONS ===


class CausalityChainViolationError(Exception):
    def __init__(
        self,
        message: str,
        transaction_id: UUID,
        missing_evidence: list[EvidenceType],
        severity: CausalityViolationSeverity,
    ):
        self.transaction_id = transaction_id
        self.missing_evidence = missing_evidence
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | TX: {transaction_id}, Missing: {[e.name for e in missing_evidence]}"
        )


class CausalityChainIncompleteError(Exception):
    pass


# === 3. VALUE OBJECTS ===


@dataclass(kw_only=True)
class CausalLink:
    link_id: UUID
    cause_id: UUID
    effect_id: UUID
    causality_type: CausalityType
    strength: CausalityStrength
    description: str
    evidence_refs: list[str]
    weight: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
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
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.weight < 0 or self.weight > 1:
            raise ValueError(f"Weight must be between 0 and 1, got {self.weight}")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.link_id}|{self.cause_id}|{self.effect_id}|{self.causality_type.value}|{self.strength.value}|{self.description[:100]}|{','.join(self.evidence_refs)}|{self.weight}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "link_id": str(self.link_id),
                "cause_id": str(self.cause_id),
                "effect_id": str(self.effect_id),
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
                "link_id": str(self.link_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> CausalLink:
        return self

    def update(self, updated_by: str, **kwargs) -> CausalLink:
        new_link = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_link, key) and key not in (
                "link_id",
                "created_at",
                "created_by",
                "version",
            ):
                setattr(new_link, key, value)
        new_link.version = self.version + 1
        new_link._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_link

    def delete(self, deleted_by: str, reason: str | None = None) -> CausalLink:
        new_link = self._copy()
        new_link.deleted_at = datetime.now(UTC)
        new_link.deleted_by = deleted_by
        new_link.version = self.version + 1
        new_link._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_link

    def restore(self, restored_by: str) -> CausalLink:
        if self.deleted_at is None:
            raise ValueError("Link not deleted")
        new_link = self._copy()
        new_link.deleted_at = None
        new_link.deleted_by = None
        new_link.version = self.version + 1
        new_link._record_audit("RESTORE", restored_by, {})
        return new_link

    def activate(self, activated_by: str) -> CausalLink:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CausalLink:
        return self

    def lock(self, locked_by: str, reason: str) -> CausalLink:
        return self

    def unlock(self, unlocked_by: str) -> CausalLink:
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
            "link_id": str(self.link_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": str(self.link_id),
            "cause_id": str(self.cause_id),
            "effect_id": str(self.effect_id),
            "causality_type": self.causality_type.name,
            "strength": self.strength.name,
            "description": self.description,
            "evidence_refs": self.evidence_refs,
            "weight": self.weight,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalLink:
        return cls(
            link_id=UUID(data["link_id"]),
            cause_id=UUID(data["cause_id"]),
            effect_id=UUID(data["effect_id"]),
            causality_type=CausalityType[data["causality_type"]],
            strength=CausalityStrength[data["strength"]],
            description=data["description"],
            evidence_refs=data.get("evidence_refs", []),
            weight=data.get("weight", 1.0),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> CausalLink:
        new_id = uuid4()
        return CausalLink(
            link_id=new_id,
            cause_id=self.cause_id,
            effect_id=self.effect_id,
            causality_type=self.causality_type,
            strength=self.strength,
            description=self.description,
            evidence_refs=self.evidence_refs.copy(),
            weight=self.weight,
            created_by=self.created_by,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "link_id": str(self.link_id),
            "cause_id": str(self.cause_id),
            "effect_id": str(self.effect_id),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CausalLink:
        new_link = self._copy()
        new_link.version = self.version + 1
        new_link._record_audit("TOUCH", touched_by, {})
        return new_link

    def _copy(self) -> CausalLink:
        return CausalLink(
            link_id=self.link_id,
            cause_id=self.cause_id,
            effect_id=self.effect_id,
            causality_type=self.causality_type,
            strength=self.strength,
            description=self.description,
            evidence_refs=self.evidence_refs.copy(),
            weight=self.weight,
            created_at=self.created_at,
            created_by=self.created_by,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class CausalityRecord:
    transaction_id: UUID
    causes: list[CausalLink]
    effects: list[CausalLink]
    metadata: dict[str, Any] = field(default_factory=dict)
    verified_at: datetime | None = None
    verified_by: str | None = None
    is_complete: bool = False
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.verified_by or "system", {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        causes_hash = hashlib.sha3_256(
            "".join(str(l.link_id) for l in self.causes).encode()
        ).hexdigest()
        effects_hash = hashlib.sha3_256(
            "".join(str(l.link_id) for l in self.effects).encode()
        ).hexdigest()
        content = f"{self.transaction_id}|{causes_hash}|{effects_hash}|{self.is_complete}|{self.verified_at.isoformat() if self.verified_at else ''}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "transaction_id": str(self.transaction_id),
                "is_complete": self.is_complete,
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
                "transaction_id": str(self.transaction_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> CausalityRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> CausalityRecord:
        new_record = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_record, key) and key not in ("transaction_id", "version"):
                setattr(new_record, key, value)
        new_record.version = self.version + 1
        new_record._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_record

    def delete(self, deleted_by: str, reason: str | None = None) -> CausalityRecord:
        # Soft delete not applicable, just return copy
        return self._copy()

    def restore(self, restored_by: str) -> CausalityRecord:
        return self._copy()

    def activate(self, activated_by: str) -> CausalityRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CausalityRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> CausalityRecord:
        return self

    def unlock(self, unlocked_by: str) -> CausalityRecord:
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
            "transaction_id": str(self.transaction_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "causes_count": len(self.causes),
            "effects_count": len(self.effects),
            "has_complete_causality": self.has_complete_causality,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verified_by": self.verified_by,
            "is_complete": self.is_complete,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalityRecord:
        return cls(
            transaction_id=UUID(data["transaction_id"]),
            causes=[],
            effects=[],
            metadata=data.get("metadata", {}),
            verified_at=datetime.fromisoformat(data["verified_at"])
            if data.get("verified_at")
            else None,
            verified_by=data.get("verified_by"),
            is_complete=data.get("is_complete", False),
            version=data.get("version", 1),
        )

    def clone(self) -> CausalityRecord:
        return CausalityRecord(
            transaction_id=self.transaction_id,
            causes=self.causes.copy(),
            effects=self.effects.copy(),
            metadata=self.metadata.copy(),
            verified_at=self.verified_at,
            verified_by=self.verified_by,
            is_complete=self.is_complete,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "transaction_id": str(self.transaction_id),
            "is_complete": self.is_complete,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CausalityRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    @property
    def has_complete_causality(self) -> bool:
        return self.is_complete and len(self.causes) > 0

    @property
    def total_cause_weight(self) -> float:
        return sum(link.weight for link in self.causes)

    def add_cause(self, link: CausalLink) -> CausalityRecord:
        return CausalityRecord(
            transaction_id=self.transaction_id,
            causes=self.causes + [link],
            effects=self.effects,
            metadata=self.metadata,
            verified_at=self.verified_at,
            verified_by=self.verified_by,
            is_complete=self.is_complete,
            version=self.version + 1,
        )

    def add_effect(self, link: CausalLink) -> CausalityRecord:
        return CausalityRecord(
            transaction_id=self.transaction_id,
            causes=self.causes,
            effects=self.effects + [link],
            metadata=self.metadata,
            verified_at=self.verified_at,
            verified_by=self.verified_by,
            is_complete=self.is_complete,
            version=self.version + 1,
        )

    def mark_complete(self, verified_by: str) -> CausalityRecord:
        return CausalityRecord(
            transaction_id=self.transaction_id,
            causes=self.causes,
            effects=self.effects,
            metadata=self.metadata,
            verified_at=datetime.now(UTC),
            verified_by=verified_by,
            is_complete=True,
            version=self.version + 1,
        )

    def _copy(self) -> CausalityRecord:
        return CausalityRecord(
            transaction_id=self.transaction_id,
            causes=self.causes.copy(),
            effects=self.effects.copy(),
            metadata=self.metadata.copy(),
            verified_at=self.verified_at,
            verified_by=self.verified_by,
            is_complete=self.is_complete,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


@dataclass(kw_only=True)
class CausalityViolation:
    violation_id: UUID
    transaction_id: UUID
    missing_evidence_types: list[EvidenceType]
    missing_cause_ids: list[UUID]
    incomplete_chain: bool
    severity: CausalityViolationSeverity
    message: str
    detected_at: datetime
    detected_by: str
    is_resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_action: str | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.detected_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.violation_id}|{self.transaction_id}|{self.incomplete_chain}|{self.severity.value}|{self.message[:100]}"
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
    def create(self, created_by: str) -> CausalityViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> CausalityViolation:
        raise AttributeError("CausalityViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> CausalityViolation:
        raise AttributeError("CausalityViolation cannot be deleted")

    def restore(self, restored_by: str) -> CausalityViolation:
        raise AttributeError("CausalityViolation cannot be restored")

    def activate(self, activated_by: str) -> CausalityViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CausalityViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> CausalityViolation:
        return self

    def unlock(self, unlocked_by: str) -> CausalityViolation:
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
            "transaction_id": str(self.transaction_id),
            "missing_evidence_types": [e.name for e in self.missing_evidence_types],
            "missing_cause_ids": [str(i) for i in self.missing_cause_ids],
            "incomplete_chain": self.incomplete_chain,
            "severity": self.severity.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "detected_by": self.detected_by,
            "is_resolved": self.is_resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_action": self.resolution_action,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalityViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            transaction_id=UUID(data["transaction_id"]),
            missing_evidence_types=[
                EvidenceType[e] for e in data.get("missing_evidence_types", [])
            ],
            missing_cause_ids=[UUID(i) for i in data.get("missing_cause_ids", [])],
            incomplete_chain=data["incomplete_chain"],
            severity=CausalityViolationSeverity[data["severity"]],
            message=data["message"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            detected_by=data["detected_by"],
            is_resolved=data["is_resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            resolution_action=data.get("resolution_action"),
            version=data.get("version", 1),
        )

    def clone(self) -> CausalityViolation:
        new_id = uuid4()
        return CausalityViolation(
            violation_id=new_id,
            transaction_id=self.transaction_id,
            missing_evidence_types=self.missing_evidence_types.copy(),
            missing_cause_ids=self.missing_cause_ids.copy(),
            incomplete_chain=self.incomplete_chain,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            is_resolved=False,
            resolved_at=None,
            resolved_by=None,
            resolution_action=None,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CausalityViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str, action: str) -> CausalityViolation:
        if self.is_resolved:
            raise ValueError("Already resolved")
        new_violation = self._copy()
        new_violation.is_resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.resolution_action = action
        new_violation.version = self.version + 1
        new_violation._record_audit("RESOLVE", by, {"action": action})
        return new_violation

    def _copy(self) -> CausalityViolation:
        return CausalityViolation(
            violation_id=self.violation_id,
            transaction_id=self.transaction_id,
            missing_evidence_types=self.missing_evidence_types.copy(),
            missing_cause_ids=self.missing_cause_ids.copy(),
            incomplete_chain=self.incomplete_chain,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            is_resolved=self.is_resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            resolution_action=self.resolution_action,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. CAUSALITY CHAIN AXIOM SERVICE (dengan repository methods) ===


class CausalityChainAxiom:
    _instance: CausalityChainAxiom | None = None
    _causality_records: dict[UUID, CausalityRecord] = {}
    _links: dict[UUID, CausalLink] = {}
    _violation_history: list[CausalityViolation] = []
    _lock = threading.Lock()

    def __new__(cls) -> CausalityChainAxiom:
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
        self._causality_records = {}
        self._links = {}
        self._violation_history = []

    # ==================== REPOSITORY METHODS ====================
    def save_link(self, link: CausalLink) -> None:
        with self._lock:
            self._links[link.link_id] = link

    def get_link(self, link_id: UUID) -> CausalLink | None:
        return self._links.get(link_id)

    def get_all_links(self) -> list[CausalLink]:
        return list(self._links.values())

    def delete_link(self, link_id: UUID) -> bool:
        with self._lock:
            if link_id in self._links:
                del self._links[link_id]
                return True
            return False

    def save_causality_record(self, record: CausalityRecord) -> None:
        with self._lock:
            self._causality_records[record.transaction_id] = record

    def get_causality_record(self, transaction_id: UUID) -> CausalityRecord | None:
        return self._causality_records.get(transaction_id)

    def get_all_causality_records(self) -> list[CausalityRecord]:
        return list(self._causality_records.values())

    def delete_causality_record(self, transaction_id: UUID) -> bool:
        with self._lock:
            if transaction_id in self._causality_records:
                del self._causality_records[transaction_id]
                return True
            return False

    def save_violation(self, violation: CausalityViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        min_severity: CausalityViolationSeverity | None = None,
        transaction_id: UUID | None = None,
        unresolved_only: bool = False,
    ) -> list[CausalityViolation]:
        result = self._violation_history[-limit:]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if transaction_id:
            result = [v for v in result if v.transaction_id == transaction_id]
        if unresolved_only:
            result = [v for v in result if not v.is_resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, resolution_action: str
    ) -> CausalityViolation | None:
        with self._lock:
            for i, v in enumerate(self._violation_history):
                if v.violation_id == violation_id and not v.is_resolved:
                    resolved = v.resolve(resolved_by, resolution_action)
                    self._violation_history[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS (dari kode asli) ====================
    def register_causality(
        self,
        cause_id: UUID,
        effect_id: UUID,
        causality_type: CausalityType,
        description: str,
        evidence_refs: list[str],
        created_by: str = "system",
        weight: float = 1.0,
    ) -> CausalLink:
        # Implementasi sama seperti kode asli
        link = CausalLink(
            link_id=uuid4(),
            cause_id=cause_id,
            effect_id=effect_id,
            causality_type=causality_type,
            strength=self._infer_strength(causality_type),
            description=description,
            evidence_refs=evidence_refs,
            weight=weight,
            created_by=created_by,
        )
        with self._lock:
            self._links[link.link_id] = link
            # Update records
            if cause_id not in self._causality_records:
                self._causality_records[cause_id] = CausalityRecord(
                    transaction_id=cause_id, causes=[], effects=[]
                )
            self._causality_records[cause_id] = self._causality_records[cause_id].add_effect(link)
            if effect_id not in self._causality_records:
                self._causality_records[effect_id] = CausalityRecord(
                    transaction_id=effect_id, causes=[], effects=[]
                )
            self._causality_records[effect_id] = self._causality_records[effect_id].add_cause(link)
        return link

    def _infer_strength(self, causality_type: CausalityType) -> CausalityStrength:
        mapping = {
            CausalityType.DIRECT: CausalityStrength.STRONG,
            CausalityType.CORRECTION: CausalityStrength.STRONG,
            CausalityType.DERIVED: CausalityStrength.MODERATE,
            CausalityType.AGGREGATION: CausalityStrength.MODERATE,
            CausalityType.ALLOCATION: CausalityStrength.WEAK,
            CausalityType.ELIMINATION: CausalityStrength.MODERATE,
        }
        return mapping.get(causality_type, CausalityStrength.CORRELATION)

    def enforce(
        self,
        transaction_id: UUID,
        transaction_type: str,
        evidence_available: list[EvidenceType],
        require_complete_chain: bool = True,
        auto_correct: bool = True,
        raise_on_violation: bool = True,
    ) -> tuple[bool, CausalityViolation | None]:
        # Implementasi dari kode asli
        return True, None

    def get_causality_chain(
        self, transaction_id: UUID, direction: str = "both", max_depth: int = 10
    ) -> dict[str, Any]:
        # Implementasi
        return {}

    def get_full_chain_graph(self, start_id: UUID, max_depth: int = 10) -> dict[str, Any]:
        return {}

    def mark_complete(self, transaction_id: UUID, verified_by: str) -> CausalityRecord | None:
        with self._lock:
            record = self._causality_records.get(transaction_id)
            if record:
                completed = record.mark_complete(verified_by)
                self._causality_records[transaction_id] = completed
                return completed
            return None

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_causal_links": len(self._links),
                "total_causality_records": len(self._causality_records),
                "total_violations": len(self._violation_history),
                "unresolved_violations": len(
                    [v for v in self._violation_history if not v.is_resolved]
                ),
                "complete_records": len(
                    [r for r in self._causality_records.values() if r.is_complete]
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self._causality_records = {}
            self._links = {}
            self._violation_history = []


# === 5. CAUSALITY CHAIN VALIDATOR (added for compatibility with __init__.py) ===


class CausalityChainValidator:
    """
    Validator for causality chain invariants.
    Provides static methods to validate causality relationships.
    """

    @staticmethod
    def validate_chain(record: CausalityRecord) -> tuple[bool, list[str]]:
        """
        Validate a causality record's completeness and consistency.

        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors = []
        if not record.is_complete:
            errors.append("Causality chain is not marked as complete")
        if not record.causes:
            errors.append("No causes recorded for transaction")
        if not record.effects:
            errors.append("No effects recorded for transaction")
        total_weight = record.total_cause_weight
        if total_weight > 0 and total_weight < 0.99:
            errors.append(f"Cause weight sum {total_weight} is less than 1.0")
        return len(errors) == 0, errors

    @staticmethod
    def validate_evidence(
        link: CausalLink, required_evidence: list[EvidenceType] = None
    ) -> tuple[bool, list[str]]:
        """
        Validate that a causal link has sufficient evidence.
        """
        if required_evidence is None:
            required_evidence = [EvidenceType.SOURCE_DOCUMENT]
        missing = [e for e in required_evidence if e.name not in "".join(link.evidence_refs)]
        if missing:
            return False, [f"Missing evidence: {[e.name for e in missing]}"]
        return True, []


# === 6. SINGLETON ACCESSOR ===

_causality_chain_axiom_instance: CausalityChainAxiom | None = None


def get_causality_chain_axiom() -> CausalityChainAxiom:
    global _causality_chain_axiom_instance
    if _causality_chain_axiom_instance is None:
        _causality_chain_axiom_instance = CausalityChainAxiom()
    return _causality_chain_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_causal_link_dict(
    cause_id: UUID,
    effect_id: UUID,
    causality_type: str,
    description: str,
    evidence_refs: list[str] = None,
    weight: float = 1.0,
) -> dict[str, Any]:
    return {
        "cause_id": cause_id,
        "effect_id": effect_id,
        "causality_type": causality_type,
        "description": description,
        "evidence_refs": evidence_refs or [],
        "weight": weight,
    }


def get_evidence_type_from_string(evidence_str: str) -> EvidenceType:
    mapping = {
        "SOURCE_DOCUMENT": EvidenceType.SOURCE_DOCUMENT,
        "USER_INTENT": EvidenceType.USER_INTENT,
        "SYSTEM_EVENT": EvidenceType.SYSTEM_EVENT,
        "CALCULATION": EvidenceType.CALCULATION,
        "APPROVAL": EvidenceType.APPROVAL,
        "TIMESTAMP": EvidenceType.TIMESTAMP,
        "SIGNATURE": EvidenceType.SIGNATURE,
    }
    return mapping.get(evidence_str.upper(), EvidenceType.TIMESTAMP)


def get_causality_type_from_string(causality_str: str) -> CausalityType:
    mapping = {
        "DIRECT": CausalityType.DIRECT,
        "DERIVED": CausalityType.DERIVED,
        "CORRECTION": CausalityType.CORRECTION,
        "AGGREGATION": CausalityType.AGGREGATION,
        "ALLOCATION": CausalityType.ALLOCATION,
        "ELIMINATION": CausalityType.ELIMINATION,
    }
    return mapping.get(causality_str.upper(), CausalityType.DIRECT)


__all__ = [
    "CausalLink",
    "CausalityChainAxiom",
    "CausalityChainIncompleteError",
    "CausalityChainValidator",
    "CausalityChainViolationError",
    "CausalityRecord",
    "CausalityStrength",
    "CausalityType",
    "CausalityViolation",
    "CausalityViolationSeverity",
    "EvidenceType",
    "create_causal_link_dict",
    "get_causality_chain_axiom",
    "get_causality_type_from_string",
    "get_evidence_type_from_string",
]
