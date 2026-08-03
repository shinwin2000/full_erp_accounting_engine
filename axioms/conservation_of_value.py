#!/usr/bin/env python3
"""
Module: conservation_of_value.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: nilai tidak bisa diciptakan atau dimusnahkan, hanya berpindah.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, getcontext
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)

getcontext().prec = 28

# ============================================================================
# EXCEPTIONS
# ============================================================================
class ConservationOfValueError(Exception):
    """Exception raised when conservation of value axiom is violated."""
    pass


# === 1. ENUMS ===

class ValueFlowType(Enum):
    SOURCE_TO_DESTINATION = auto()
    DESTRUCTION = auto()
    CREATION = auto()
    CONSUMPTION = auto()
    TRANSFER = auto()
    CONVERSION = auto()


class ValueCategory(Enum):
    ASSET = auto()
    LIABILITY = auto()
    EQUITY = auto()
    REVENUE = auto()
    EXPENSE = auto()
    GAIN = auto()
    LOSS = auto()


class ConservationViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


# === 2. EXCEPTIONS ===


class ConservationViolationError(Exception):
    def __init__(
        self,
        message: str,
        source_value: Decimal,
        destination_value: Decimal,
        difference: Decimal,
        flow_id: UUID | None = None,
        transaction_id: UUID | None = None,
        severity: ConservationViolationSeverity = ConservationViolationSeverity.CRITICAL,
    ):
        self.source_value = source_value
        self.destination_value = destination_value
        self.difference = difference
        self.flow_id = flow_id
        self.transaction_id = transaction_id
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | Source: {source_value}, Dest: {destination_value}, Diff: {difference}"
        )


class InvalidValueFlowError(Exception):
    pass


# === 3. VALUE OBJECTS =========================================================

@dataclass(kw_only=True)
class ValueNode:
    node_id: UUID
    category: ValueCategory
    legal_entity_id: UUID
    account_code: str
    amount: Decimal
    currency: str
    description: str
    cost_center: str | None = None
    department: str | None = None
    project_id: UUID | None = None
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
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative: {self.amount}")
        if not self.currency or len(self.currency) != 3:
            raise ValueError(f"Invalid currency: {self.currency}")
        if not self.account_code:
            raise ValueError("Account code required")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.node_id}|{self.category.value}|{self.legal_entity_id}|{self.account_code}|{self.amount}|{self.currency}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "node_id": str(self.node_id),
                "amount": str(self.amount),
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
                "node_id": str(self.node_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ValueNode:
        return self

    def update(self, updated_by: str, **kwargs) -> ValueNode:
        new_node = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_node, key) and key not in ("node_id", "version"):
                setattr(new_node, key, value)
        new_node.version = self.version + 1
        new_node._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_node

    def delete(self, deleted_by: str, reason: str | None = None) -> ValueNode:
        new_node = self._copy()
        new_node.deleted_at = datetime.now(UTC)
        new_node.deleted_by = deleted_by
        new_node.version = self.version + 1
        new_node._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_node

    def restore(self, restored_by: str) -> ValueNode:
        if self.deleted_at is None:
            raise ValueError("Node not deleted")
        new_node = self._copy()
        new_node.deleted_at = None
        new_node.deleted_by = None
        new_node.version = self.version + 1
        new_node._record_audit("RESTORE", restored_by, {})
        return new_node

    def activate(self, activated_by: str) -> ValueNode:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ValueNode:
        return self

    def lock(self, locked_by: str, reason: str) -> ValueNode:
        return self

    def unlock(self, unlocked_by: str) -> ValueNode:
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
            "node_id": str(self.node_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": str(self.node_id),
            "category": self.category.name,
            "legal_entity_id": str(self.legal_entity_id),
            "account_code": self.account_code,
            "amount": str(self.amount),
            "currency": self.currency,
            "description": self.description,
            "cost_center": self.cost_center,
            "department": self.department,
            "project_id": str(self.project_id) if self.project_id else None,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValueNode:
        return cls(
            node_id=UUID(data["node_id"]),
            category=ValueCategory[data["category"]],
            legal_entity_id=UUID(data["legal_entity_id"]),
            account_code=data["account_code"],
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            description=data["description"],
            cost_center=data.get("cost_center"),
            department=data.get("department"),
            project_id=UUID(data["project_id"]) if data.get("project_id") else None,
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> ValueNode:
        new_id = uuid4()
        return ValueNode(
            node_id=new_id,
            category=self.category,
            legal_entity_id=self.legal_entity_id,
            account_code=self.account_code,
            amount=self.amount,
            currency=self.currency,
            description=self.description,
            cost_center=self.cost_center,
            department=self.department,
            project_id=self.project_id,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "node_id": str(self.node_id),
            "amount": str(self.amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ValueNode:
        new_node = self._copy()
        new_node.version = self.version + 1
        new_node._record_audit("TOUCH", touched_by, {})
        return new_node

    def _copy(self) -> ValueNode:
        return ValueNode(
            node_id=self.node_id,
            category=self.category,
            legal_entity_id=self.legal_entity_id,
            account_code=self.account_code,
            amount=self.amount,
            currency=self.currency,
            description=self.description,
            cost_center=self.cost_center,
            department=self.department,
            project_id=self.project_id,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class ValueFlow:
    flow_id: UUID
    transaction_id: UUID
    sources: list[ValueNode]
    destinations: list[ValueNode]
    transaction_fee: Decimal
    fee_currency: str
    effective_date: datetime
    description: str
    created_by: str
    created_at: datetime
    flow_type: ValueFlowType = ValueFlowType.SOURCE_TO_DESTINATION
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
        if self.transaction_fee < 0:
            raise InvalidValueFlowError(f"Fee cannot be negative: {self.transaction_fee}")
        # Currency consistency
        currencies = {node.currency for node in self.sources} | {
            node.currency for node in self.destinations
        }
        if self.fee_currency:
            currencies.add(self.fee_currency)
        if len(currencies) > 1:
            raise InvalidValueFlowError(f"Multiple currencies: {currencies}")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        sources_hash = hashlib.sha3_256(
            "".join(str(n.node_id) for n in self.sources).encode()
        ).hexdigest()
        dests_hash = hashlib.sha3_256(
            "".join(str(n.node_id) for n in self.destinations).encode()
        ).hexdigest()
        content = f"{self.flow_id}|{self.transaction_id}|{self.total_source_value}|{self.total_destination_value}|{self.transaction_fee}|{self.effective_date.isoformat()}|{self.flow_type.value}|{sources_hash}|{dests_hash}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "flow_id": str(self.flow_id),
                "total_source": str(self.total_source_value),
                "total_destination": str(self.total_destination_value),
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
                "flow_id": str(self.flow_id),
                "details": details,
            }
        )

    @property
    def total_source_value(self) -> Decimal:
        return sum(node.amount for node in self.sources)

    @property
    def total_destination_value(self) -> Decimal:
        return sum(node.amount for node in self.destinations)

    @property
    def net_value_change(self) -> Decimal:
        return self.total_source_value - self.total_destination_value - self.transaction_fee

    def is_conserved(self, tolerance: Decimal = Decimal("0.01")) -> tuple[bool, Decimal]:
        diff = self.net_value_change
        return abs(diff) <= tolerance, diff

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ValueFlow:
        return self

    def update(self, updated_by: str, **kwargs) -> ValueFlow:
        new_flow = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_flow, key) and key not in (
                "flow_id",
                "transaction_id",
                "created_at",
                "created_by",
                "version",
            ):
                setattr(new_flow, key, value)
        new_flow.version = self.version + 1
        new_flow._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_flow

    def delete(self, deleted_by: str, reason: str | None = None) -> ValueFlow:
        new_flow = self._copy()
        new_flow.deleted_at = datetime.now(UTC)
        new_flow.deleted_by = deleted_by
        new_flow.version = self.version + 1
        new_flow._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_flow

    def restore(self, restored_by: str) -> ValueFlow:
        if self.deleted_at is None:
            raise ValueError("Flow not deleted")
        new_flow = self._copy()
        new_flow.deleted_at = None
        new_flow.deleted_by = None
        new_flow.version = self.version + 1
        new_flow._record_audit("RESTORE", restored_by, {})
        return new_flow

    def activate(self, activated_by: str) -> ValueFlow:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ValueFlow:
        return self

    def lock(self, locked_by: str, reason: str) -> ValueFlow:
        return self

    def unlock(self, unlocked_by: str) -> ValueFlow:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except (ValueError, InvalidValueFlowError) as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "flow_id": str(self.flow_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_id": str(self.flow_id),
            "transaction_id": str(self.transaction_id),
            "sources_count": len(self.sources),
            "destinations_count": len(self.destinations),
            "total_source": str(self.total_source_value),
            "total_destination": str(self.total_destination_value),
            "transaction_fee": str(self.transaction_fee),
            "fee_currency": self.fee_currency,
            "effective_date": self.effective_date.isoformat(),
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "flow_type": self.flow_type.name,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValueFlow:
        return cls(
            flow_id=UUID(data["flow_id"]),
            transaction_id=UUID(data["transaction_id"]),
            sources=[],
            destinations=[],
            transaction_fee=Decimal(data["transaction_fee"]),
            fee_currency=data["fee_currency"],
            effective_date=datetime.fromisoformat(data["effective_date"]),
            description=data["description"],
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            flow_type=ValueFlowType[data["flow_type"]]
            if "flow_type" in data
            else ValueFlowType.SOURCE_TO_DESTINATION,
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> ValueFlow:
        new_id = uuid4()
        return ValueFlow(
            flow_id=new_id,
            transaction_id=self.transaction_id,
            sources=[n.clone() for n in self.sources],
            destinations=[n.clone() for n in self.destinations],
            transaction_fee=self.transaction_fee,
            fee_currency=self.fee_currency,
            effective_date=datetime.now(UTC),
            description=f"Clone of {self.flow_id}",
            created_by=self.created_by,
            created_at=datetime.now(UTC),
            flow_type=self.flow_type,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "flow_id": str(self.flow_id),
            "total_source": str(self.total_source_value),
            "total_destination": str(self.total_destination_value),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ValueFlow:
        new_flow = self._copy()
        new_flow.version = self.version + 1
        new_flow._record_audit("TOUCH", touched_by, {})
        return new_flow

    def _copy(self) -> ValueFlow:
        return ValueFlow(
            flow_id=self.flow_id,
            transaction_id=self.transaction_id,
            sources=self.sources.copy(),
            destinations=self.destinations.copy(),
            transaction_fee=self.transaction_fee,
            fee_currency=self.fee_currency,
            effective_date=self.effective_date,
            description=self.description,
            created_by=self.created_by,
            created_at=self.created_at,
            flow_type=self.flow_type,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class ConservationRecord:
    record_id: UUID
    flow_id: UUID
    transaction_id: UUID
    verified_at: datetime
    verified_by: str
    is_conserved: bool
    source_total: Decimal
    destination_total: Decimal
    fee: Decimal
    difference: Decimal
    tolerance: Decimal
    severity: ConservationViolationSeverity
    violation_message: str | None
    auto_corrected: bool
    auto_correction_applied: str | None
    forensic_hash: str
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_forensic_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.verified_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_forensic_hash(self) -> None:
        if not self.forensic_hash:
            object.__setattr__(self, "forensic_hash", self.compute_forensic_hash())

    def compute_forensic_hash(self) -> str:
        content = f"{self.record_id}|{self.flow_id}|{self.transaction_id}|{self.verified_at.isoformat()}|{self.is_conserved}|{self.source_total}|{self.destination_total}|{self.fee}|{self.difference}|{self.auto_corrected}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "record_id": str(self.record_id),
                "is_conserved": self.is_conserved,
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

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ConservationRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> ConservationRecord:
        raise AttributeError("ConservationRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> ConservationRecord:
        raise AttributeError("ConservationRecord cannot be deleted")

    def restore(self, restored_by: str) -> ConservationRecord:
        raise AttributeError("ConservationRecord cannot be restored")

    def activate(self, activated_by: str) -> ConservationRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ConservationRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> ConservationRecord:
        return self

    def unlock(self, unlocked_by: str) -> ConservationRecord:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.forensic_hash != self.compute_forensic_hash():
                errors.append("Forensic hash mismatch")
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
            "flow_id": str(self.flow_id),
            "transaction_id": str(self.transaction_id),
            "verified_at": self.verified_at.isoformat(),
            "verified_by": self.verified_by,
            "is_conserved": self.is_conserved,
            "source_total": str(self.source_total),
            "destination_total": str(self.destination_total),
            "fee": str(self.fee),
            "difference": str(self.difference),
            "tolerance": str(self.tolerance),
            "severity": self.severity.name,
            "violation_message": self.violation_message,
            "auto_corrected": self.auto_corrected,
            "auto_correction_applied": self.auto_correction_applied,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConservationRecord:
        return cls(
            record_id=UUID(data["record_id"]),
            flow_id=UUID(data["flow_id"]),
            transaction_id=UUID(data["transaction_id"]),
            verified_at=datetime.fromisoformat(data["verified_at"]),
            verified_by=data["verified_by"],
            is_conserved=data["is_conserved"],
            source_total=Decimal(data["source_total"]),
            destination_total=Decimal(data["destination_total"]),
            fee=Decimal(data["fee"]),
            difference=Decimal(data["difference"]),
            tolerance=Decimal(data["tolerance"]),
            severity=ConservationViolationSeverity[data["severity"]],
            violation_message=data.get("violation_message"),
            auto_corrected=data["auto_corrected"],
            auto_correction_applied=data.get("auto_correction_applied"),
            forensic_hash=data.get("forensic_hash", ""),
            version=data.get("version", 1),
        )

    def clone(self) -> ConservationRecord:
        new_id = uuid4()
        return ConservationRecord(
            record_id=new_id,
            flow_id=self.flow_id,
            transaction_id=self.transaction_id,
            verified_at=datetime.now(UTC),
            verified_by=self.verified_by,
            is_conserved=self.is_conserved,
            source_total=self.source_total,
            destination_total=self.destination_total,
            fee=self.fee,
            difference=self.difference,
            tolerance=self.tolerance,
            severity=self.severity,
            violation_message=self.violation_message,
            auto_corrected=self.auto_corrected,
            auto_correction_applied=self.auto_correction_applied,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "record_id": str(self.record_id),
            "is_conserved": self.is_conserved,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ConservationRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _copy(self) -> ConservationRecord:
        return ConservationRecord(
            record_id=self.record_id,
            flow_id=self.flow_id,
            transaction_id=self.transaction_id,
            verified_at=self.verified_at,
            verified_by=self.verified_by,
            is_conserved=self.is_conserved,
            source_total=self.source_total,
            destination_total=self.destination_total,
            fee=self.fee,
            difference=self.difference,
            tolerance=self.tolerance,
            severity=self.severity,
            violation_message=self.violation_message,
            auto_corrected=self.auto_corrected,
            auto_correction_applied=self.auto_correction_applied,
            forensic_hash=self.forensic_hash,
            version=self.version,
        )


# === 4. VALIDATOR ===


class ConservationOfValueValidator:
    DEFAULT_TOLERANCE = Decimal("0.0001")
    CONSOLIDATION_TOLERANCE = Decimal("0.01")

    @classmethod
    def validate_flow(
        cls, flow: ValueFlow, tolerance: Decimal | None = None, auto_correct: bool = False
    ) -> tuple[bool, ConservationRecord | None, str | None]:
        tolerance = tolerance or (
            cls.CONSOLIDATION_TOLERANCE
            if flow.flow_type == ValueFlowType.TRANSFER
            else cls.DEFAULT_TOLERANCE
        )
        is_conserved, diff = flow.is_conserved(tolerance)
        severity = (
            cls._determine_severity(diff, flow.total_source_value, tolerance)
            if not is_conserved
            else ConservationViolationSeverity.INFO
        )
        auto_hint = None
        auto_corrected = False
        if not is_conserved and auto_correct and severity == ConservationViolationSeverity.LOW:
            auto_hint = f"Adjust destination by {diff} to balance"
            auto_corrected = True
        record = ConservationRecord(
            record_id=uuid4(),
            flow_id=flow.flow_id,
            transaction_id=flow.transaction_id,
            verified_at=datetime.now(UTC),
            verified_by="conservation_validator",
            is_conserved=is_conserved,
            source_total=flow.total_source_value,
            destination_total=flow.total_destination_value,
            fee=flow.transaction_fee,
            difference=diff,
            tolerance=tolerance,
            severity=severity,
            violation_message=None
            if is_conserved
            else f"Conservation violation: difference {diff}",
            auto_corrected=auto_corrected,
            auto_correction_applied=auto_hint,
            forensic_hash="",
        )
        # Compute forensic hash
        record = ConservationRecord(
            record_id=record.record_id,
            flow_id=record.flow_id,
            transaction_id=record.transaction_id,
            verified_at=record.verified_at,
            verified_by=record.verified_by,
            is_conserved=record.is_conserved,
            source_total=record.source_total,
            destination_total=record.destination_total,
            fee=record.fee,
            difference=record.difference,
            tolerance=record.tolerance,
            severity=record.severity,
            violation_message=record.violation_message,
            auto_corrected=record.auto_corrected,
            auto_correction_applied=record.auto_correction_applied,
            forensic_hash=record.compute_forensic_hash(),
            version=record.version,
        )
        if not is_conserved:
            cls._log_violation(flow, diff, severity)
            cls._notify_constitution(flow, diff, severity)
        return is_conserved, record, auto_hint

    @classmethod
    def _determine_severity(
        cls, difference: Decimal, total_value: Decimal, tolerance: Decimal
    ) -> ConservationViolationSeverity:
        abs_diff = abs(difference)
        ratio = abs_diff / total_value if total_value > 0 else Decimal(0)
        if ratio > Decimal("0.05"):
            return ConservationViolationSeverity.CATASTROPHIC
        elif ratio > Decimal("0.01"):
            return ConservationViolationSeverity.CRITICAL
        elif ratio > Decimal("0.001"):
            return ConservationViolationSeverity.HIGH
        elif ratio > Decimal("0.0001"):
            return ConservationViolationSeverity.MEDIUM
        elif ratio > tolerance * 10:
            return ConservationViolationSeverity.LOW
        return ConservationViolationSeverity.INFO

    @classmethod
    def _log_violation(
        cls, flow: ValueFlow, difference: Decimal, severity: ConservationViolationSeverity
    ) -> None:
        log_msg = f"[{severity.name}] Conservation violation: Flow {flow.flow_id}, TX {flow.transaction_id}, Diff {difference}"
        if severity in (
            ConservationViolationSeverity.CATASTROPHIC,
            ConservationViolationSeverity.CRITICAL,
        ):
            logger.critical(log_msg)
        elif severity == ConservationViolationSeverity.HIGH:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(
        cls, flow: ValueFlow, difference: Decimal, severity: ConservationViolationSeverity
    ) -> None:
        try:
            supreme_law = get_supreme_law()
            # Determine severity mapping but not used further; kept for clarity
            _ = {
                ConservationViolationSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                ConservationViolationSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                ConservationViolationSeverity.HIGH: ConstitutionalSeverity.HIGH,
                ConservationViolationSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                ConservationViolationSeverity.LOW: ConstitutionalSeverity.LOW,
                ConservationViolationSeverity.INFO: ConstitutionalSeverity.INFO,
            }.get(severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
                offending_module="conservation_of_value",
                message=f"Conservation violation: diff {difference} in flow {flow.flow_id}",
                offending_command_id=flow.transaction_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")

    @classmethod
    def validate_transaction(
        cls,
        transaction_id: UUID,
        journal_lines: list[dict[str, Any]],
        transaction_fee: Decimal = Decimal(0),
        fee_currency: str = "IDR",
        tolerance: Decimal | None = None,
        auto_correct: bool = False,
    ):
        sources = []
        destinations = []
        for idx, line in enumerate(journal_lines):
            debit = Decimal(str(line.get("debit", 0)))
            credit = Decimal(str(line.get("credit", 0)))
            currency = line.get("currency", "IDR")
            le_id = line.get("legal_entity_id", UUID(int=0))
            account_code = line.get("account_code", "")
            if debit > 0:
                sources.append(
                    ValueNode(
                        node_id=uuid4(),
                        category=ValueCategory.ASSET,
                        legal_entity_id=le_id,
                        account_code=account_code,
                        amount=debit,
                        currency=currency,
                        description=f"Line {idx}",
                    )
                )
            if credit > 0:
                destinations.append(
                    ValueNode(
                        node_id=uuid4(),
                        category=ValueCategory.LIABILITY,
                        legal_entity_id=le_id,
                        account_code=account_code,
                        amount=credit,
                        currency=currency,
                        description=f"Line {idx}",
                    )
                )
        flow = ValueFlow(
            flow_id=uuid4(),
            transaction_id=transaction_id,
            sources=sources,
            destinations=destinations,
            transaction_fee=transaction_fee,
            fee_currency=fee_currency,
            effective_date=datetime.now(UTC),
            description=f"Auto-flow for TX {transaction_id}",
            created_by="conservation_validator",
            created_at=datetime.now(UTC),
        )
        flow = ValueFlow(
            flow_id=flow.flow_id,
            transaction_id=flow.transaction_id,
            sources=flow.sources,
            destinations=flow.destinations,
            transaction_fee=flow.transaction_fee,
            fee_currency=flow.fee_currency,
            effective_date=flow.effective_date,
            description=flow.description,
            created_by=flow.created_by,
            created_at=flow.created_at,
            flow_type=flow.flow_type,
            cryptographic_hash=flow.compute_hash(),
            version=flow.version,
        )
        is_conserved, record, hint = cls.validate_flow(flow, tolerance, auto_correct)
        return is_conserved, record, flow, hint


# === 5. AXIOM SERVICE ===


class ConservationOfValueAxiom:
    _instance: ClassVar[ConservationOfValueAxiom | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _validator = ConservationOfValueValidator

    def __new__(cls) -> ConservationOfValueAxiom:
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
        self._flows: dict[UUID, ValueFlow] = {}
        self._records: list[ConservationRecord] = []
        self._violation_history: list[ConservationRecord] = []

    # ==================== REPOSITORY METHODS ====================
    def save_flow(self, flow: ValueFlow) -> None:
        with self._lock:
            self._flows[flow.flow_id] = flow

    def get_flow(self, flow_id: UUID) -> ValueFlow | None:
        return self._flows.get(flow_id)

    def get_all_flows(self) -> list[ValueFlow]:
        return list(self._flows.values())

    def delete_flow(self, flow_id: UUID) -> bool:
        with self._lock:
            if flow_id in self._flows:
                del self._flows[flow_id]
                return True
            return False

    def save_record(self, record: ConservationRecord) -> None:
        with self._lock:
            self._records.append(record)
            if not record.is_conserved:
                self._violation_history.append(record)

    def get_records(
        self, limit: int = 100, only_violations: bool = False
    ) -> list[ConservationRecord]:
        if only_violations:
            return self._violation_history[-limit:]
        return self._records[-limit:]

    # ==================== BUSINESS METHODS ====================
    def create_flow(
        self,
        transaction_id: UUID,
        sources: list[ValueNode],
        destinations: list[ValueNode],
        transaction_fee: Decimal = Decimal(0),
        fee_currency: str = "IDR",
        effective_date: datetime | None = None,
        description: str = "",
        created_by: str = "system",
        flow_type: ValueFlowType = ValueFlowType.SOURCE_TO_DESTINATION,
    ) -> ValueFlow:
        flow = ValueFlow(
            flow_id=uuid4(),
            transaction_id=transaction_id,
            sources=sources,
            destinations=destinations,
            transaction_fee=transaction_fee,
            fee_currency=fee_currency,
            effective_date=effective_date or datetime.now(UTC),
            description=description,
            created_by=created_by,
            created_at=datetime.now(UTC),
            flow_type=flow_type,
        )
        flow = ValueFlow(
            flow_id=flow.flow_id,
            transaction_id=flow.transaction_id,
            sources=flow.sources,
            destinations=flow.destinations,
            transaction_fee=flow.transaction_fee,
            fee_currency=flow.fee_currency,
            effective_date=flow.effective_date,
            description=flow.description,
            created_by=flow.created_by,
            created_at=flow.created_at,
            flow_type=flow.flow_type,
            cryptographic_hash=flow.compute_hash(),
            version=flow.version,
        )
        with self._lock:
            self._flows[flow.flow_id] = flow
        return flow

    def enforce(
        self,
        flow: ValueFlow,
        tolerance: Decimal | None = None,
        auto_correct: bool = True,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ConservationRecord | None]:
        is_conserved, record, _ = self._validator.validate_flow(flow, tolerance, auto_correct)
        if record:
            with self._lock:
                self._records.append(record)
                if not is_conserved:
                    self._violation_history.append(record)
            if (
                not is_conserved
                and raise_on_violation
                and record.severity.value >= ConservationViolationSeverity.HIGH.value
            ):
                raise ConservationViolationError(
                    message=record.violation_message or "Conservation violation",
                    source_value=record.source_total,
                    destination_value=record.destination_total,
                    difference=record.difference,
                    flow_id=flow.flow_id,
                    transaction_id=flow.transaction_id,
                    severity=record.severity,
                )
        return is_conserved, record

    def enforce_transaction(
        self,
        transaction_id: UUID,
        journal_lines: list[dict[str, Any]],
        transaction_fee: Decimal = Decimal(0),
        fee_currency: str = "IDR",
        tolerance: Decimal | None = None,
        auto_correct: bool = True,
        raise_on_violation: bool = True,
    ) -> tuple[bool, ConservationRecord | None, ValueFlow | None]:
        is_conserved, record, flow, _ = self._validator.validate_transaction(
            transaction_id, journal_lines, transaction_fee, fee_currency, tolerance, auto_correct
        )
        if flow:
            with self._lock:
                self._flows[flow.flow_id] = flow
        if record:
            with self._lock:
                self._records.append(record)
                if not is_conserved:
                    self._violation_history.append(record)
            if (
                not is_conserved
                and raise_on_violation
                and record.severity.value >= ConservationViolationSeverity.HIGH.value
            ):
                raise ConservationViolationError(
                    message=record.violation_message or "Conservation violation",
                    source_value=record.source_total,
                    destination_value=record.destination_total,
                    difference=record.difference,
                    flow_id=flow.flow_id if flow else None,
                    transaction_id=transaction_id,
                    severity=record.severity,
                )
        return is_conserved, record, flow

    def get_flows_by_transaction(self, transaction_id: UUID) -> list[ValueFlow]:
        return [f for f in self._flows.values() if f.transaction_id == transaction_id]

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_flows = len(self._flows)
            total_records = len(self._records)
            total_violations = len(self._violation_history)
            by_severity = {}
            for sev in ConservationViolationSeverity:
                count = len([r for r in self._violation_history if r.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count
            auto_corrected = len([r for r in self._violation_history if r.auto_corrected])
            return {
                "total_flows": total_flows,
                "total_validations": total_records,
                "violation_count": total_violations,
                "compliance_rate": (total_records - total_violations) / total_records
                if total_records > 0
                else 1.0,
                "by_severity": by_severity,
                "auto_corrected_violations": auto_corrected,
                "latest_violation": self._violation_history[-1].verified_at.isoformat()
                if self._violation_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._flows = {}
            self._records = []
            self._violation_history = []


# === 6. ADDITIONAL VALUE TYPES FOR TEST COMPATIBILITY ========================

@dataclass
class ValuePool:
    """Representasi pool nilai (akun/saldo)."""
    pool_id: UUID
    balance: Decimal
    pool_type: str = "cash"
    currency: str = "IDR"
    metadata: dict[str, Any] = field(default_factory=dict)

    def apply_debit(self, amount: Decimal) -> ValuePool:
        if amount < 0:
            raise ValueError("Debit amount must be non-negative")
        if self.balance < amount:
            raise ValueError(f"Insufficient balance: {self.balance} < {amount}")
        return ValuePool(
            pool_id=self.pool_id,
            balance=self.balance - amount,
            pool_type=self.pool_type,
            currency=self.currency,
            metadata=self.metadata,
        )

    def apply_credit(self, amount: Decimal) -> ValuePool:
        if amount < 0:
            raise ValueError("Credit amount must be positive")
        return ValuePool(
            pool_id=self.pool_id,
            balance=self.balance + amount,
            pool_type=self.pool_type,
            currency=self.currency,
            metadata=self.metadata,
        )


@dataclass
class ValueTransfer:
    """Transfer nilai antara dua pool."""
    source: ValuePool
    destination: ValuePool
    amount: Decimal
    fee: Decimal = Decimal(0)
    tax: Decimal = Decimal(0)
    executed: bool = False

    def execute(self) -> ValueTransfer:
        if self.executed:
            raise ValueError("Transfer already executed")
        if self.amount <= 0:
            raise ValueError("Amount must be positive")
        if self.fee < 0 or self.tax < 0:
            raise ValueError("Fee and tax must be non-negative")

        total_debit = self.amount + self.fee + self.tax
        if self.source.balance < total_debit:
            raise ValueError(f"Insufficient balance: need {total_debit}, have {self.source.balance}")

        self.source = self.source.apply_debit(total_debit)
        self.destination = self.destination.apply_credit(self.amount)
        self.executed = True
        return self

    def reverse(self) -> ValueTransfer:
        """Balik transfer (source <-> destination)."""
        if not self.executed:
            raise ValueError("Cannot reverse unexecuted transfer")
        return ValueTransfer(
            source=self.destination,
            destination=self.source,
            amount=self.amount,
            fee=self.fee,
            tax=self.tax,
            executed=False,
        )


@dataclass
class ValueConservationRule:
    """Aturan konservasi nilai untuk validasi."""
    name: str = "Default Conservation Rule"
    description: str = "Ensures value is conserved in transfers"
    is_active: bool = True
    tolerance: Decimal = Decimal("0.01")

    def apply(self, transfer: ValueTransfer) -> dict[str, Any]:
        """Periksa konservasi nilai pada transfer."""
        if not self.is_active:
            return {"valid": True, "violations": []}
        violations = []
        required = transfer.amount + transfer.fee + transfer.tax
        if transfer.source.balance < required:
            violations.append(f"Insufficient balance: need {required}, have {transfer.source.balance}")
        total_before = transfer.source.balance + transfer.destination.balance
        # Simulasikan eksekusi
        temp_source = transfer.source.balance - required
        temp_dest = transfer.destination.balance + transfer.amount
        total_after = temp_source + temp_dest
        if abs(total_after - total_before) > self.tolerance:
            violations.append(f"Value leak: before {total_before}, after {total_after}, diff {total_after - total_before}")
        return {"valid": len(violations) == 0, "violations": violations}


# === 7. VALIDATION FUNCTIONS (modul-level) ===================================

def validate_conservation_of_value(
    transfer: ValueTransfer,
    include_pools: list[ValuePool] | None = None,
) -> tuple[bool, list[str]]:
    """Validasi konservasi nilai untuk satu transfer."""
    rule = ValueConservationRule()
    result = rule.apply(transfer)
    violations = result.get("violations", [])
    if include_pools:
        total_before = transfer.source.balance + transfer.destination.balance + sum(p.balance for p in include_pools)
        # simulasi eksekusi + include pools
        temp_source = transfer.source.balance - (transfer.amount + transfer.fee + transfer.tax)
        temp_dest = transfer.destination.balance + transfer.amount
        total_after = temp_source + temp_dest + sum(p.balance for p in include_pools)
        if abs(total_after - total_before) > Decimal("0.01"):
            violations.append(f"Conservation failed with extra pools: before {total_before}, after {total_after}")
    return len(violations) == 0, violations


def validate_value_flow(flow: ValueFlow) -> tuple[bool, list[str]]:
    """Validasi flow nilai."""
    violations = []
    try:
        is_conserved, record, _ = ConservationOfValueValidator.validate_flow(flow)
        if not is_conserved:
            violations.append(record.violation_message or "Flow not conserved")
    except Exception as e:
        violations.append(str(e))
    return len(violations) == 0, violations


def validate_value_pool(pool: ValuePool) -> tuple[bool, list[str]]:
    """Validasi pool nilai."""
    violations = []
    if pool.balance < 0:
        violations.append(f"Balance cannot be negative: {pool.balance}")
    return len(violations) == 0, violations


def validate_value_transfer(transfer: ValueTransfer) -> tuple[bool, list[str]]:
    """Validasi transfer nilai."""
    return validate_conservation_of_value(transfer)


# === 8. HELPER FUNCTIONS =====================================================

def create_value_node(
    category: ValueCategory,
    legal_entity_id: UUID,
    account_code: str,
    amount: Decimal,
    currency: str,
    description: str = "",
    cost_center: str | None = None,
    department: str | None = None,
    project_id: UUID | None = None,
) -> ValueNode:
    return ValueNode(
        node_id=uuid4(),
        category=category,
        legal_entity_id=legal_entity_id,
        account_code=account_code,
        amount=amount,
        currency=currency,
        description=description,
        cost_center=cost_center,
        department=department,
        project_id=project_id,
    )


def create_journal_line_dict(
    account_code: str,
    debit: Decimal = Decimal(0),
    credit: Decimal = Decimal(0),
    currency: str = "IDR",
    legal_entity_id: UUID | None = None,
    description: str = "",
    cost_center: str | None = None,
    department: str | None = None,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "account_code": account_code,
        "debit": debit,
        "credit": credit,
        "currency": currency,
        "legal_entity_id": legal_entity_id,
        "description": description,
        "cost_center": cost_center,
        "department": department,
        "project_id": project_id,
    }


# === 9. SINGLETON ACCESSOR ===================================================

_conservation_axiom_instance: ConservationOfValueAxiom | None = None


def get_conservation_axiom() -> ConservationOfValueAxiom:
    global _conservation_axiom_instance
    if _conservation_axiom_instance is None:
        _conservation_axiom_instance = ConservationOfValueAxiom()
    return _conservation_axiom_instance


# === 10. EXPORTS =============================================================

__all__ = [
    "ConservationOfValueAxiom",
    "ConservationOfValueValidator",
    "ConservationRecord",
    "ConservationViolationError",
    "ConservationViolationSeverity",
    "InvalidValueFlowError",
    "ValueCategory",
    "ValueConservationRule",
    "ValueFlow",
    "ValueFlowType",
    "ValueNode",
    "ValuePool",
    "ValueTransfer",
    "create_journal_line_dict",
    "create_value_node",
    "get_conservation_axiom",
    "validate_conservation_of_value",
    "validate_value_flow",
    "validate_value_pool",
    "validate_value_transfer",
]
