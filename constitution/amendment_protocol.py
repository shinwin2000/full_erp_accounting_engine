#!/usr/bin/env python3
"""
Module: amendment_protocol.py
Layer: 1 - Foundation / Constitution
Responsibility: Protokol perubahan konstitusi.
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

from constitution.sovereignty_declaration import get_sovereignty_guardian
from constitution.supreme_law import ConstitutionalRule, EmergencyOverrideReason, get_supreme_law

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class AmendmentType(Enum):
    ADD_RULE = auto()
    MODIFY_RULE = auto()
    REPEAL_RULE = auto()
    SUSPEND_RULE = auto()
    RESTORE_RULE = auto()
    UPDATE_VERSION = auto()


class AmendmentStatus(Enum):
    DRAFT = auto()
    UNDER_REVIEW = auto()
    APPROVED = auto()
    REJECTED = auto()
    IMPLEMENTED = auto()
    ROLLED_BACK = auto()
    EXPIRED = auto()


class AmendmentVote(Enum):
    APPROVE = auto()
    REJECT = auto()
    ABSTAIN = auto()


class MigrationStrategy(Enum):
    IMMEDIATE = auto()
    GRACE_PERIOD = auto()
    PHASED_ROLLOUT = auto()
    FUTURE_EFFECTIVE = auto()


class AmendmentUrgency(Enum):
    ROUTINE = auto()
    URGENT = auto()
    EMERGENCY = auto()


# === 2. EXCEPTIONS ===


class AmendmentProtocolError(Exception):
    pass


class InsufficientApprovalError(AmendmentProtocolError):
    pass


class AmendmentConflictError(AmendmentProtocolError):
    pass


class MigrationError(AmendmentProtocolError):
    pass


class AmendmentExpiredError(AmendmentProtocolError):
    pass


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class AmendmentProposal:
    # Required fields (no defaults)
    proposal_id: UUID
    amendment_type: AmendmentType
    justification: str
    impact_assessment: str
    proposed_by: str
    proposed_at: datetime
    migration_strategy: MigrationStrategy
    migration_plan: str
    rollback_plan: str
    requires_emergency: bool
    urgency: AmendmentUrgency
    status: AmendmentStatus
    version: str
    # Optional fields (with defaults)
    target_rule_id: UUID | None = None
    new_rule: ConstitutionalRule | None = None
    effective_date: datetime | None = None
    emergency_reason: str | None = None
    expires_at: datetime | None = None
    _version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.proposed_by, {})

    def _validate(self) -> None:
        errors = []
        if self.amendment_type in [
            AmendmentType.MODIFY_RULE,
            AmendmentType.REPEAL_RULE,
            AmendmentType.SUSPEND_RULE,
        ] and self.target_rule_id is None:
            errors.append("target_rule_id required")
        if self.amendment_type == AmendmentType.ADD_RULE and self.new_rule is None:
            errors.append("new_rule required")
        if self.requires_emergency and not self.emergency_reason:
            errors.append("emergency_reason required")
        if (
            self.migration_strategy == MigrationStrategy.GRACE_PERIOD
            and self.effective_date is None
        ):
            errors.append("effective_date required for grace period")
        if self.expires_at and self.expires_at <= self.proposed_at:
            errors.append("expires_at must be after proposed_at")
        if self._version < 1:
            errors.append("version must be >= 1")
        if errors:
            raise AmendmentProtocolError(f"Invalid proposal: {errors}")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self._version,
                "proposal_id": str(self.proposal_id),
                "status": self.status.name,
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
                "version": self._version,
                "proposal_id": str(self.proposal_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> AmendmentProposal:
        return self

    def update(self, updated_by: str, **kwargs) -> AmendmentProposal:
        if self.status not in [AmendmentStatus.DRAFT, AmendmentStatus.UNDER_REVIEW]:
            raise AmendmentProtocolError(f"Cannot update proposal with status {self.status.name}")
        new_proposal = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_proposal, key) and key not in (
                "proposal_id",
                "proposed_at",
                "proposed_by",
                "_version",
            ):
                setattr(new_proposal, key, value)
        new_proposal._version = self._version + 1
        new_proposal._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_proposal

    def delete(self, deleted_by: str, reason: str | None = None) -> AmendmentProposal:
        if self.status not in [AmendmentStatus.DRAFT, AmendmentStatus.UNDER_REVIEW]:
            raise AmendmentProtocolError(f"Cannot delete proposal with status {self.status.name}")
        new_proposal = self._copy()
        new_proposal.deleted_at = datetime.now(UTC)
        new_proposal.deleted_by = deleted_by
        new_proposal._version = self._version + 1
        new_proposal._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_proposal

    def restore(self, restored_by: str) -> AmendmentProposal:
        if self.deleted_at is None:
            raise ValueError("Proposal not deleted")
        new_proposal = self._copy()
        new_proposal.deleted_at = None
        new_proposal.deleted_by = None
        new_proposal._version = self._version + 1
        new_proposal._record_audit("RESTORE", restored_by, {})
        return new_proposal

    def activate(self, activated_by: str) -> AmendmentProposal:
        if self.status != AmendmentStatus.DRAFT:
            raise AmendmentProtocolError(f"Cannot activate proposal with status {self.status.name}")
        new_proposal = self._copy()
        new_proposal.status = AmendmentStatus.UNDER_REVIEW
        new_proposal._version = self._version + 1
        new_proposal._record_audit("ACTIVATE", activated_by, {})
        return new_proposal

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AmendmentProposal:
        if self.status != AmendmentStatus.UNDER_REVIEW:
            raise AmendmentProtocolError(
                f"Cannot deactivate proposal with status {self.status.name}"
            )
        new_proposal = self._copy()
        new_proposal.status = AmendmentStatus.DRAFT
        new_proposal._version = self._version + 1
        new_proposal._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_proposal

    def lock(self, locked_by: str, reason: str) -> AmendmentProposal:
        new_proposal = self._copy()
        new_proposal._version = self._version + 1
        new_proposal._record_audit("LOCK", locked_by, {"reason": reason})
        return new_proposal

    def unlock(self, unlocked_by: str) -> AmendmentProposal:
        new_proposal = self._copy()
        new_proposal._version = self._version + 1
        new_proposal._record_audit("UNLOCK", unlocked_by, {})
        return new_proposal

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except AmendmentProtocolError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "proposal_id": str(self.proposal_id),
            "version": self._version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": str(self.proposal_id),
            "amendment_type": self.amendment_type.name,
            "target_rule_id": str(self.target_rule_id) if self.target_rule_id else None,
            "justification": self.justification[:200],
            "proposed_by": self.proposed_by,
            "proposed_at": self.proposed_at.isoformat(),
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "migration_strategy": self.migration_strategy.name,
            "requires_emergency": self.requires_emergency,
            "urgency": self.urgency.name,
            "status": self.status.name,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "_version": self._version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmendmentProposal:
        return cls(
            proposal_id=UUID(data["proposal_id"]),
            amendment_type=AmendmentType[data["amendment_type"]],
            target_rule_id=UUID(data["target_rule_id"]) if data.get("target_rule_id") else None,
            new_rule=None,
            justification=data["justification"],
            impact_assessment=data.get("impact_assessment", ""),
            proposed_by=data["proposed_by"],
            proposed_at=datetime.fromisoformat(data["proposed_at"]),
            effective_date=datetime.fromisoformat(data["effective_date"])
            if data.get("effective_date")
            else None,
            migration_strategy=MigrationStrategy[data["migration_strategy"]],
            migration_plan=data.get("migration_plan", ""),
            rollback_plan=data.get("rollback_plan", ""),
            requires_emergency=data["requires_emergency"],
            emergency_reason=data.get("emergency_reason"),
            urgency=AmendmentUrgency[data["urgency"]],
            status=AmendmentStatus[data["status"]],
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            version=data["version"],
            _version=data.get("_version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> AmendmentProposal:
        new_id = uuid4()
        return AmendmentProposal(
            proposal_id=new_id,
            amendment_type=self.amendment_type,
            target_rule_id=self.target_rule_id,
            new_rule=self.new_rule.clone() if self.new_rule else None,
            justification=self.justification,
            impact_assessment=self.impact_assessment,
            proposed_by=self.proposed_by,
            proposed_at=datetime.now(UTC),
            effective_date=self.effective_date,
            migration_strategy=self.migration_strategy,
            migration_plan=self.migration_plan,
            rollback_plan=self.rollback_plan,
            requires_emergency=self.requires_emergency,
            emergency_reason=self.emergency_reason,
            urgency=self.urgency,
            status=AmendmentStatus.DRAFT,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            version="1.0",
            _version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "proposal_id": str(self.proposal_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AmendmentProposal:
        new_proposal = self._copy()
        new_proposal._version = self._version + 1
        new_proposal._record_audit("TOUCH", touched_by, {})
        return new_proposal

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def can_be_processed(self) -> bool:
        return (
            self.status in [AmendmentStatus.DRAFT, AmendmentStatus.UNDER_REVIEW]
            and not self.is_expired()
            and self.deleted_at is None
        )

    def _copy(self) -> AmendmentProposal:
        return AmendmentProposal(
            proposal_id=self.proposal_id,
            amendment_type=self.amendment_type,
            target_rule_id=self.target_rule_id,
            new_rule=self.new_rule,
            justification=self.justification,
            impact_assessment=self.impact_assessment,
            proposed_by=self.proposed_by,
            proposed_at=self.proposed_at,
            effective_date=self.effective_date,
            migration_strategy=self.migration_strategy,
            migration_plan=self.migration_plan,
            rollback_plan=self.rollback_plan,
            requires_emergency=self.requires_emergency,
            emergency_reason=self.emergency_reason,
            urgency=self.urgency,
            status=self.status,
            expires_at=self.expires_at,
            version=self.version,
            _version=self._version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class AmendmentVoteRecord:
    # Required fields (no defaults)
    vote_id: UUID
    proposal_id: UUID
    voter_id: str
    vote: AmendmentVote
    voted_at: datetime
    cryptographic_signature: str
    # Optional fields (with defaults)
    comment: str | None = None
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.voter_id, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "vote_id": str(self.vote_id),
                "vote": self.vote.name,
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
                "vote_id": str(self.vote_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> AmendmentVoteRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> AmendmentVoteRecord:
        raise AttributeError("AmendmentVoteRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> AmendmentVoteRecord:
        raise AttributeError("Cannot delete vote record")

    def restore(self, restored_by: str) -> AmendmentVoteRecord:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> AmendmentVoteRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AmendmentVoteRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> AmendmentVoteRecord:
        return self

    def unlock(self, unlocked_by: str) -> AmendmentVoteRecord:
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
            "vote_id": str(self.vote_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "vote_id": str(self.vote_id),
            "proposal_id": str(self.proposal_id),
            "voter_id": self.voter_id,
            "vote": self.vote.name,
            "comment": self.comment,
            "voted_at": self.voted_at.isoformat(),
            "cryptographic_signature": self.cryptographic_signature[:16] + "...",
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmendmentVoteRecord:
        return cls(
            vote_id=UUID(data["vote_id"]),
            proposal_id=UUID(data["proposal_id"]),
            voter_id=data["voter_id"],
            vote=AmendmentVote[data["vote"]],
            comment=data.get("comment"),
            voted_at=datetime.fromisoformat(data["voted_at"]),
            cryptographic_signature=data.get("cryptographic_signature", ""),
            version=data.get("version", 1),
        )

    def clone(self) -> AmendmentVoteRecord:
        new_id = uuid4()
        return AmendmentVoteRecord(
            vote_id=new_id,
            proposal_id=self.proposal_id,
            voter_id=self.voter_id,
            vote=self.vote,
            comment=self.comment,
            voted_at=self.voted_at,
            cryptographic_signature=self.cryptographic_signature,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "vote_id": str(self.vote_id),
            "vote": self.vote.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AmendmentVoteRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_approval(self) -> bool:
        return self.vote == AmendmentVote.APPROVE


@dataclass(kw_only=True)
class AmendmentExecutionRecord:
    # Required fields (no defaults)
    execution_id: UUID
    proposal_id: UUID
    executed_at: datetime
    executed_by: str
    previous_state_hash: str
    new_state_hash: str
    migration_log: list[str]
    success: bool
    rollback_executed: bool
    # Optional fields (with defaults)
    failure_reason: str | None = None
    rollback_at: datetime | None = None
    rollback_reason: str | None = None
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.executed_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "execution_id": str(self.execution_id),
                "success": self.success,
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
                "execution_id": str(self.execution_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> AmendmentExecutionRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> AmendmentExecutionRecord:
        raise AttributeError("AmendmentExecutionRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> AmendmentExecutionRecord:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> AmendmentExecutionRecord:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> AmendmentExecutionRecord:
        return self

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> AmendmentExecutionRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> AmendmentExecutionRecord:
        return self

    def unlock(self, unlocked_by: str) -> AmendmentExecutionRecord:
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
            "execution_id": str(self.execution_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": str(self.execution_id),
            "proposal_id": str(self.proposal_id),
            "executed_at": self.executed_at.isoformat(),
            "executed_by": self.executed_by,
            "previous_state_hash": self.previous_state_hash[:16] + "...",
            "new_state_hash": self.new_state_hash[:16] + "...",
            "migration_log": self.migration_log[:10],
            "success": self.success,
            "failure_reason": self.failure_reason,
            "rollback_executed": self.rollback_executed,
            "rollback_at": self.rollback_at.isoformat() if self.rollback_at else None,
            "rollback_reason": self.rollback_reason,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmendmentExecutionRecord:
        return cls(
            execution_id=UUID(data["execution_id"]),
            proposal_id=UUID(data["proposal_id"]),
            executed_at=datetime.fromisoformat(data["executed_at"]),
            executed_by=data["executed_by"],
            previous_state_hash=data["previous_state_hash"],
            new_state_hash=data["new_state_hash"],
            migration_log=data.get("migration_log", []),
            success=data["success"],
            failure_reason=data.get("failure_reason"),
            rollback_executed=data["rollback_executed"],
            rollback_at=datetime.fromisoformat(data["rollback_at"])
            if data.get("rollback_at")
            else None,
            rollback_reason=data.get("rollback_reason"),
            version=data.get("version", 1),
        )

    def clone(self) -> AmendmentExecutionRecord:
        new_id = uuid4()
        return AmendmentExecutionRecord(
            execution_id=new_id,
            proposal_id=self.proposal_id,
            executed_at=self.executed_at,
            executed_by=self.executed_by,
            previous_state_hash=self.previous_state_hash,
            new_state_hash=self.new_state_hash,
            migration_log=self.migration_log.copy(),
            success=self.success,
            failure_reason=self.failure_reason,
            rollback_executed=self.rollback_executed,
            rollback_at=self.rollback_at,
            rollback_reason=self.rollback_reason,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "execution_id": str(self.execution_id),
            "success": self.success,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AmendmentExecutionRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self


@dataclass(kw_only=True)
class AmendmentReviewComment:
    # Required fields (no defaults)
    comment_id: UUID
    proposal_id: UUID
    reviewer_id: str
    comment: str
    commented_at: datetime
    is_required_change: bool
    # Optional fields (with defaults)
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.reviewer_id, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "comment_id": str(self.comment_id),
                "is_required_change": self.is_required_change,
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
                "comment_id": str(self.comment_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> AmendmentReviewComment:
        return self

    def update(self, updated_by: str, **kwargs) -> AmendmentReviewComment:
        raise AttributeError("AmendmentReviewComment is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> AmendmentReviewComment:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> AmendmentReviewComment:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> AmendmentReviewComment:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AmendmentReviewComment:
        return self

    def lock(self, locked_by: str, reason: str) -> AmendmentReviewComment:
        return self

    def unlock(self, unlocked_by: str) -> AmendmentReviewComment:
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
            "comment_id": str(self.comment_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "comment_id": str(self.comment_id),
            "proposal_id": str(self.proposal_id),
            "reviewer_id": self.reviewer_id,
            "comment": self.comment,
            "commented_at": self.commented_at.isoformat(),
            "is_required_change": self.is_required_change,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmendmentReviewComment:
        return cls(
            comment_id=UUID(data["comment_id"]),
            proposal_id=UUID(data["proposal_id"]),
            reviewer_id=data["reviewer_id"],
            comment=data["comment"],
            commented_at=datetime.fromisoformat(data["commented_at"]),
            is_required_change=data["is_required_change"],
            version=data.get("version", 1),
        )

    def clone(self) -> AmendmentReviewComment:
        new_id = uuid4()
        return AmendmentReviewComment(
            comment_id=new_id,
            proposal_id=self.proposal_id,
            reviewer_id=self.reviewer_id,
            comment=self.comment,
            commented_at=self.commented_at,
            is_required_change=self.is_required_change,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "comment_id": str(self.comment_id),
            "is_required_change": self.is_required_change,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AmendmentReviewComment:
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. AMENDMENT PROTOCOL AGGREGATE ===


class AmendmentProtocol:
    def __init__(self, protocol_version: str = "1.0.0", committee_members: list[str] | None = None):
        self.protocol_version = protocol_version
        self.committee_members = committee_members or [
            "ceo",
            "cfo",
            "audit_committee_chair",
            "legal_counsel",
            "cto",
        ]
        self.proposals: dict[UUID, AmendmentProposal] = {}
        self.votes: dict[UUID, list[AmendmentVoteRecord]] = {}
        self.executions: dict[UUID, AmendmentExecutionRecord] = {}
        self.review_comments: dict[UUID, list[AmendmentReviewComment]] = {}
        self._active_proposal_ids: list[UUID] = []
        self._lock = threading.Lock()

    # ==================== REPOSITORY METHODS ====================
    def save_proposal(self, proposal: AmendmentProposal) -> None:
        with self._lock:
            self.proposals[proposal.proposal_id] = proposal
            if (
                proposal.can_be_processed()
                and proposal.proposal_id not in self._active_proposal_ids
            ):
                self._active_proposal_ids.append(proposal.proposal_id)

    def get_proposal(self, proposal_id: UUID) -> AmendmentProposal | None:
        return self.proposals.get(proposal_id)

    def get_all_proposals(self) -> list[AmendmentProposal]:
        return list(self.proposals.values())

    def delete_proposal(self, proposal_id: UUID) -> bool:
        with self._lock:
            if proposal_id in self.proposals:
                if proposal_id in self._active_proposal_ids:
                    self._active_proposal_ids.remove(proposal_id)
                del self.proposals[proposal_id]
                return True
            return False

    def save_vote(self, vote: AmendmentVoteRecord) -> None:
        with self._lock:
            if vote.proposal_id not in self.votes:
                self.votes[vote.proposal_id] = []
            self.votes[vote.proposal_id].append(vote)

    def get_votes(self, proposal_id: UUID) -> list[AmendmentVoteRecord]:
        return self.votes.get(proposal_id, [])

    def delete_votes_for_proposal(self, proposal_id: UUID) -> bool:
        with self._lock:
            if proposal_id in self.votes:
                del self.votes[proposal_id]
                return True
            return False

    def save_execution(self, execution: AmendmentExecutionRecord) -> None:
        with self._lock:
            self.executions[execution.execution_id] = execution

    def get_execution(self, execution_id: UUID) -> AmendmentExecutionRecord | None:
        return self.executions.get(execution_id)

    def get_executions_by_proposal(self, proposal_id: UUID) -> list[AmendmentExecutionRecord]:
        return [e for e in self.executions.values() if e.proposal_id == proposal_id]

    def delete_execution(self, execution_id: UUID) -> bool:
        with self._lock:
            if execution_id in self.executions:
                del self.executions[execution_id]
                return True
            return False

    def save_review_comment(self, comment: AmendmentReviewComment) -> None:
        with self._lock:
            if comment.proposal_id not in self.review_comments:
                self.review_comments[comment.proposal_id] = []
            self.review_comments[comment.proposal_id].append(comment)

    def get_review_comments(self, proposal_id: UUID) -> list[AmendmentReviewComment]:
        return self.review_comments.get(proposal_id, [])

    def delete_review_comments_for_proposal(self, proposal_id: UUID) -> bool:
        with self._lock:
            if proposal_id in self.review_comments:
                del self.review_comments[proposal_id]
                return True
            return False

    # ==================== BUSINESS METHODS ====================
    def submit_proposal(
        self,
        amendment_type: AmendmentType,
        justification: str,
        impact_assessment: str,
        proposed_by: str,
        target_rule_id: UUID | None = None,
        new_rule: ConstitutionalRule | None = None,
        effective_date: datetime | None = None,
        migration_strategy: MigrationStrategy = MigrationStrategy.IMMEDIATE,
        migration_plan: str = "",
        rollback_plan: str = "",
        requires_emergency: bool = False,
        emergency_reason: str | None = None,
        urgency: AmendmentUrgency = AmendmentUrgency.ROUTINE,
        expires_in_days: int = 30,
    ) -> AmendmentProposal:
        with self._lock:
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
            proposal = AmendmentProposal(
                proposal_id=uuid4(),
                amendment_type=amendment_type,
                target_rule_id=target_rule_id,
                new_rule=new_rule,
                justification=justification,
                impact_assessment=impact_assessment,
                proposed_by=proposed_by,
                proposed_at=datetime.now(UTC),
                effective_date=effective_date,
                migration_strategy=migration_strategy,
                migration_plan=migration_plan,
                rollback_plan=rollback_plan,
                requires_emergency=requires_emergency,
                emergency_reason=emergency_reason,
                urgency=urgency,
                status=AmendmentStatus.DRAFT,
                expires_at=expires_at,
                version="1.0",
            )
            self._check_conflicts(proposal)
            self.save_proposal(proposal)
            logger.info(
                f"Amendment proposal submitted: {proposal.proposal_id} - Type: {amendment_type.name}"
            )
            return proposal

    def _check_conflicts(self, new_proposal: AmendmentProposal) -> None:
        for active_id in self._active_proposal_ids:
            existing = self.proposals.get(active_id)
            if not existing or not existing.can_be_processed():
                continue
            if (
                new_proposal.target_rule_id
                and existing.target_rule_id
                and new_proposal.target_rule_id == existing.target_rule_id
            ):
                raise AmendmentConflictError(
                    f"Target rule {new_proposal.target_rule_id} already has active proposal {existing.proposal_id}"
                )
            if (
                new_proposal.new_rule
                and existing.new_rule
                and new_proposal.new_rule.principle == existing.new_rule.principle
            ):
                raise AmendmentConflictError(
                    f"Principle {new_proposal.new_rule.principle.name} already has active proposal {existing.proposal_id}"
                )

    def submit_for_review(self, proposal_id: UUID, submitted_by: str) -> AmendmentProposal:
        with self._lock:
            proposal = self.proposals.get(proposal_id)
            if not proposal:
                raise AmendmentProtocolError(f"Proposal {proposal_id} not found")
            if proposal.proposed_by != submitted_by:
                raise AmendmentProtocolError("Only proposer can submit for review")
            if proposal.status != AmendmentStatus.DRAFT:
                raise AmendmentProtocolError(f"Proposal status is {proposal.status.name}")
            updated = proposal.update(submitted_by, status=AmendmentStatus.UNDER_REVIEW)
            self.save_proposal(updated)
            logger.info(f"Proposal {proposal_id} submitted for review by {submitted_by}")
            return updated

    def add_review_comment(
        self, proposal_id: UUID, reviewer_id: str, comment: str, is_required_change: bool = False
    ) -> AmendmentReviewComment:
        proposal = self.proposals.get(proposal_id)
        if not proposal:
            raise AmendmentProtocolError(f"Proposal {proposal_id} not found")
        if proposal.status not in [AmendmentStatus.DRAFT, AmendmentStatus.UNDER_REVIEW]:
            raise AmendmentProtocolError(
                f"Cannot comment on proposal with status {proposal.status.name}"
            )
        comment_obj = AmendmentReviewComment(
            comment_id=uuid4(),
            proposal_id=proposal_id,
            reviewer_id=reviewer_id,
            comment=comment,
            commented_at=datetime.now(UTC),
            is_required_change=is_required_change,
        )
        self.save_review_comment(comment_obj)
        return comment_obj

    def cast_vote(
        self, proposal_id: UUID, voter_id: str, vote: AmendmentVote, comment: str | None = None
    ) -> AmendmentVoteRecord:
        with self._lock:
            proposal = self.proposals.get(proposal_id)
            if not proposal:
                raise AmendmentProtocolError(f"Proposal {proposal_id} not found")
            if proposal.is_expired():
                raise AmendmentExpiredError(f"Proposal {proposal_id} has expired")
            if proposal.status not in [AmendmentStatus.UNDER_REVIEW, AmendmentStatus.APPROVED]:
                raise AmendmentProtocolError(
                    f"Cannot vote on proposal with status {proposal.status.name}"
                )
            if voter_id not in self.committee_members:
                raise InsufficientApprovalError(f"{voter_id} is not a committee member")
            signature_content = (
                f"{proposal_id}|{voter_id}|{vote.value}|{datetime.now(UTC).isoformat()}"
            )
            signature = hashlib.sha3_256(signature_content.encode()).hexdigest()
            vote_record = AmendmentVoteRecord(
                vote_id=uuid4(),
                proposal_id=proposal_id,
                voter_id=voter_id,
                vote=vote,
                comment=comment,
                voted_at=datetime.now(UTC),
                cryptographic_signature=signature,
            )
            self.save_vote(vote_record)
            self._check_and_update_approval_status(proposal_id)
            return vote_record

    def _check_and_update_approval_status(self, proposal_id: UUID) -> None:
        status = self.check_approval_status(proposal_id)
        proposal = self.proposals.get(proposal_id)
        if proposal and proposal.status == AmendmentStatus.UNDER_REVIEW:
            if status["status"] == "approved":
                updated = proposal.update("system", status=AmendmentStatus.APPROVED)
                self.save_proposal(updated)
                logger.info(f"Proposal {proposal_id} approved by vote")
            elif status["status"] == "rejected":
                updated = proposal.update("system", status=AmendmentStatus.REJECTED)
                self.save_proposal(updated)
                if proposal_id in self._active_proposal_ids:
                    self._active_proposal_ids.remove(proposal_id)
                logger.info(f"Proposal {proposal_id} rejected by vote")

    def check_approval_status(self, proposal_id: UUID) -> dict[str, Any]:
        proposal = self.proposals.get(proposal_id)
        if not proposal:
            raise AmendmentProtocolError(f"Proposal {proposal_id} not found")
        votes = self.votes.get(proposal_id, [])
        approve_count = sum(1 for v in votes if v.is_approval())
        reject_count = sum(1 for v in votes if v.vote == AmendmentVote.REJECT)
        abstain_count = sum(1 for v in votes if v.vote == AmendmentVote.ABSTAIN)
        total_committee = len(self.committee_members)
        voted_count = len(votes)
        if proposal.requires_emergency or proposal.urgency == AmendmentUrgency.EMERGENCY:
            required_votes = (total_committee + 1) // 2
            quorum_met = voted_count >= required_votes
            approval_threshold = required_votes
            approved = quorum_met and approve_count >= approval_threshold
            rejected = reject_count >= approval_threshold
        else:
            required_votes = (2 * total_committee + 2) // 3
            quorum_met = voted_count >= required_votes
            approval_threshold = required_votes
            approved = quorum_met and approve_count >= approval_threshold
            rejected = reject_count >= approval_threshold
        return {
            "proposal_id": str(proposal_id),
            "status": "approved" if approved else ("rejected" if rejected else "pending"),
            "approve_count": approve_count,
            "reject_count": reject_count,
            "abstain_count": abstain_count,
            "voted_count": voted_count,
            "total_committee": total_committee,
            "quorum_met": quorum_met,
            "approval_threshold": approval_threshold,
            "requires_emergency": proposal.requires_emergency,
            "urgency": proposal.urgency.name,
        }

    def execute_amendment(
        self,
        proposal_id: UUID,
        executed_by: str,
        state_hasher: Callable[[], str] | None = None,
        migration_executor: Callable[[AmendmentProposal], list[str]] | None = None,
    ) -> AmendmentExecutionRecord:
        with self._lock:
            status = self.check_approval_status(proposal_id)
            if status["status"] != "approved":
                raise InsufficientApprovalError(
                    f"Cannot execute proposal {proposal_id}: status is {status['status']}"
                )
            proposal = self.proposals.get(proposal_id)
            if not proposal:
                raise AmendmentProtocolError(f"Proposal {proposal_id} not found")
            if proposal.is_expired():
                raise AmendmentExpiredError(f"Proposal {proposal_id} has expired")
            previous_hash = state_hasher() if state_hasher else hashlib.sha3_256(b"").hexdigest()
            migration_log = []
            success = True
            failure_reason = None
            rollback_executed = False
            rollback_at = None
            rollback_reason = None
            try:
                if migration_executor:
                    migration_log = migration_executor(proposal)
                else:
                    migration_log = self._default_migration_executor(proposal)
                self._apply_changes_to_constitution(proposal)
                new_hash = state_hasher() if state_hasher else hashlib.sha3_256(b"").hexdigest()
                updated = proposal.update(executed_by, status=AmendmentStatus.IMPLEMENTED)
                self.save_proposal(updated)
                if proposal_id in self._active_proposal_ids:
                    self._active_proposal_ids.remove(proposal_id)
                logger.info(f"Amendment {proposal_id} executed successfully by {executed_by}")
            except Exception as e:
                success = False
                failure_reason = str(e)
                new_hash = previous_hash
                logger.error(f"Failed to execute amendment {proposal_id}: {e}")
                if proposal.rollback_plan:
                    try:
                        self._rollback_amendment(proposal)
                        rollback_executed = True
                        rollback_at = datetime.now(UTC)
                        rollback_reason = f"Rollback after execution failure: {failure_reason}"
                        rolled_back = proposal.update(
                            executed_by, status=AmendmentStatus.ROLLED_BACK
                        )
                        self.save_proposal(rolled_back)
                        logger.warning(f"Amendment {proposal_id} rolled back")
                    except Exception as rb_error:
                        logger.critical(f"Rollback failed: {rb_error}")
                        rollback_reason = f"Rollback failed: {rb_error}"
            execution = AmendmentExecutionRecord(
                execution_id=uuid4(),
                proposal_id=proposal_id,
                executed_at=datetime.now(UTC),
                executed_by=executed_by,
                previous_state_hash=previous_hash,
                new_state_hash=new_hash,
                migration_log=migration_log,
                success=success,
                failure_reason=failure_reason,
                rollback_executed=rollback_executed,
                rollback_at=rollback_at,
                rollback_reason=rollback_reason,
            )
            self.save_execution(execution)
            return execution

    def _default_migration_executor(self, proposal: AmendmentProposal) -> list[str]:
        logs = []
        if proposal.migration_strategy == MigrationStrategy.IMMEDIATE:
            logs.append("Migration: Immediate - applying changes now")
        elif proposal.migration_strategy == MigrationStrategy.GRACE_PERIOD:
            effective = proposal.effective_date or datetime.now(UTC) + timedelta(days=7)
            logs.append(f"Migration: Grace period until {effective.isoformat()}")
        elif proposal.migration_strategy == MigrationStrategy.PHASED_ROLLOUT:
            logs.append("Migration: Phased rollout - requires per-entity activation")
        elif proposal.migration_strategy == MigrationStrategy.FUTURE_EFFECTIVE:
            effective = proposal.effective_date or datetime.now(UTC) + timedelta(days=30)
            logs.append(f"Migration: Future effective from {effective.isoformat()}")
        if proposal.migration_plan:
            logs.append(f"Migration plan: {proposal.migration_plan[:200]}")
        return logs

    def _apply_changes_to_constitution(self, proposal: AmendmentProposal) -> None:
        supreme_law = get_supreme_law()
        constitution = supreme_law.constitution
        if proposal.amendment_type == AmendmentType.ADD_RULE:
            if proposal.new_rule is None:
                raise AmendmentProtocolError("Cannot add rule: new_rule is None")
            constitution.add_rule(proposal.new_rule, authorizer=proposal.proposed_by)
        elif proposal.amendment_type == AmendmentType.MODIFY_RULE:
            if proposal.target_rule_id is None or proposal.new_rule is None:
                raise AmendmentProtocolError("Missing target_rule_id or new_rule")
            constitution.modify_rule(
                proposal.target_rule_id, proposal.new_rule, proposal.proposed_by
            )
        elif proposal.amendment_type == AmendmentType.REPEAL_RULE:
            if proposal.target_rule_id is None:
                raise AmendmentProtocolError("Cannot repeal rule: target_rule_id is None")
            if proposal.target_rule_id in constitution.rules:
                rule = constitution.rules[proposal.target_rule_id]
                inactive_rule = rule.update(proposal.proposed_by, effective_until=datetime.now(UTC))
                constitution.rules[proposal.target_rule_id] = inactive_rule
        elif proposal.amendment_type == AmendmentType.SUSPEND_RULE:
            if proposal.new_rule is None:
                raise AmendmentProtocolError("Cannot suspend: new_rule missing")
            supreme_law.emergency_override(
                reason=EmergencyOverrideReason.SYSTEM_MIGRATION,
                suspended_principles={proposal.new_rule.principle},
                duration_hours=72,
                authorized_by=[proposal.proposed_by],
                justification_document=proposal.justification,
            )
        elif proposal.amendment_type == AmendmentType.UPDATE_VERSION:
            from constitution.version_lock import VersionChangeType, get_version_lock_service

            version_service = get_version_lock_service()
            version_service.commit_version_upgrade(
                target_version=proposal.new_rule.statement if proposal.new_rule else "1.0.0",
                change_type=VersionChangeType.MINOR,
                changelog_entry=proposal.justification,
                committed_by=proposal.proposed_by,
                approved_by=self.committee_members,
                constitution_snapshot_id=None,
            )
        constitution._create_snapshot()

    def _rollback_amendment(self, proposal: AmendmentProposal) -> None:
        supreme_law = get_supreme_law()
        constitution = supreme_law.constitution
        if proposal.amendment_type == AmendmentType.ADD_RULE:
            if proposal.new_rule and proposal.new_rule.rule_id in constitution.rules:
                del constitution.rules[proposal.new_rule.rule_id]
        elif proposal.amendment_type == AmendmentType.MODIFY_RULE:
            # FIX: Periksa proposal.new_rule sebelum mengakses principle
            if (
                len(constitution.snapshots) >= 2
                and proposal.new_rule is not None
            ):
                prev_snapshot = constitution.snapshots[-2]
                for rule in prev_snapshot.active_rules:
                    if rule.principle == proposal.new_rule.principle:
                        constitution.rules[rule.rule_id] = rule
                        break
        elif proposal.amendment_type == AmendmentType.REPEAL_RULE:
            if proposal.target_rule_id and len(constitution.snapshots) >= 2:
                prev_snapshot = constitution.snapshots[-2]
                for rule in prev_snapshot.active_rules:
                    if rule.rule_id == proposal.target_rule_id:
                        constitution.rules[rule.rule_id] = rule
                        break
        elif proposal.amendment_type == AmendmentType.UPDATE_VERSION:
            from constitution.version_lock import get_version_lock_service

            version_service = get_version_lock_service()
            # FIX: Cek _version_lock tidak None, dan akses current_version langsung
            if version_service._version_lock is not None:
                version_service._version_lock.current_version = "1.0.0"
        constitution._create_snapshot()

    def get_proposal_details(self, proposal_id: UUID) -> dict[str, Any]:
        proposal = self.proposals.get(proposal_id)
        if not proposal:
            raise AmendmentProtocolError(f"Proposal {proposal_id} not found")
        status = self.check_approval_status(proposal_id)
        votes_list = [v.to_dict() for v in self.votes.get(proposal_id, [])]
        comments_list = [c.to_dict() for c in self.review_comments.get(proposal_id, [])]
        executions_list = [
            e.to_dict() for e in self.executions.values() if e.proposal_id == proposal_id
        ]
        return {
            "proposal": proposal.to_dict(),
            "approval_status": status,
            "votes": votes_list,
            "review_comments": comments_list,
            "executions": executions_list,
        }

    def get_active_proposals(self) -> list[dict[str, Any]]:
        active = []
        for pid in self._active_proposal_ids:
            proposal = self.proposals.get(pid)
            if proposal and proposal.can_be_processed():
                active.append(proposal.to_dict())
        return active

    def expire_old_proposals(self) -> int:
        expired_count = 0
        for pid, proposal in list(self.proposals.items()):
            if proposal.is_expired() and proposal.status in [
                AmendmentStatus.DRAFT,
                AmendmentStatus.UNDER_REVIEW,
            ]:
                updated = proposal.update("system", status=AmendmentStatus.EXPIRED)
                self.save_proposal(updated)
                if pid in self._active_proposal_ids:
                    self._active_proposal_ids.remove(pid)
                expired_count += 1
        return expired_count

    def get_statistics(self) -> dict[str, Any]:
        total = len(self.proposals)
        by_status = {}
        for status in AmendmentStatus:
            count = len([p for p in self.proposals.values() if p.status == status])
            if count > 0:
                by_status[status.name] = count
        by_type = {}
        for atype in AmendmentType:
            count = len([p for p in self.proposals.values() if p.amendment_type == atype])
            if count > 0:
                by_type[atype.name] = count
        return {
            "total_proposals": total,
            "active_proposals": len(self._active_proposal_ids),
            "by_status": by_status,
            "by_type": by_type,
            "total_votes": sum(len(v) for v in self.votes.values()),
            "total_executions": len(self.executions),
            "successful_executions": len([e for e in self.executions.values() if e.success]),
            "failed_executions": len([e for e in self.executions.values() if not e.success]),
        }

    def reset(self) -> None:
        with self._lock:
            self.proposals = {}
            self.votes = {}
            self.executions = {}
            self.review_comments = {}
            self._active_proposal_ids = []


# === 5. AMENDMENT PROTOCOL SERVICE ===


class AmendmentProtocolService:
    _instance: AmendmentProtocolService | None = None
    _initialized: bool  # FIX: tambahkan anotasi tipe

    def __new__(cls) -> AmendmentProtocolService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # FIX: set _initialized
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._protocol = AmendmentProtocol()

    def propose_amendment(
        self,
        amendment_type: AmendmentType,
        justification: str,
        impact_assessment: str,
        proposed_by: str,
        target_rule_id: UUID | None = None,
        new_rule: ConstitutionalRule | None = None,
        effective_date: datetime | None = None,
        migration_strategy: MigrationStrategy = MigrationStrategy.IMMEDIATE,
        migration_plan: str = "",
        rollback_plan: str = "",
        requires_emergency: bool = False,
        emergency_reason: str | None = None,
        urgency: AmendmentUrgency = AmendmentUrgency.ROUTINE,
    ) -> AmendmentProposal:
        guardian = get_sovereignty_guardian()
        if not guardian.is_system_operational():
            raise AmendmentProtocolError(
                f"Cannot propose amendment when system status is {guardian.get_current_status().name}"
            )
        if (requires_emergency or urgency == AmendmentUrgency.EMERGENCY) and proposed_by not in self._protocol.committee_members:
            raise InsufficientApprovalError(
                "Emergency amendment can only be proposed by committee members"
            )
        return self._protocol.submit_proposal(
            amendment_type=amendment_type,
            justification=justification,
            impact_assessment=impact_assessment,
            proposed_by=proposed_by,
            target_rule_id=target_rule_id,
            new_rule=new_rule,
            effective_date=effective_date,
            migration_strategy=migration_strategy,
            migration_plan=migration_plan,
            rollback_plan=rollback_plan,
            requires_emergency=requires_emergency,
            emergency_reason=emergency_reason,
            urgency=urgency,
        )

    def submit_for_review(self, proposal_id: UUID, submitted_by: str) -> AmendmentProposal:
        return self._protocol.submit_for_review(proposal_id, submitted_by)

    def add_review_comment(
        self, proposal_id: UUID, reviewer_id: str, comment: str, is_required_change: bool = False
    ) -> AmendmentReviewComment:
        return self._protocol.add_review_comment(
            proposal_id, reviewer_id, comment, is_required_change
        )

    def vote(
        self, proposal_id: UUID, voter_id: str, vote: AmendmentVote, comment: str | None = None
    ) -> AmendmentVoteRecord:
        if voter_id not in self._protocol.committee_members:
            raise InsufficientApprovalError(f"{voter_id} is not authorized to vote")
        return self._protocol.cast_vote(proposal_id, voter_id, vote, comment)

    def execute_approved_amendment(
        self, proposal_id: UUID, executed_by: str
    ) -> AmendmentExecutionRecord:
        guardian = get_sovereignty_guardian()
        if not guardian.is_system_operational():
            raise AmendmentProtocolError(
                f"Cannot execute amendment when system status is {guardian.get_current_status().name}"
            )

        def state_hasher() -> str:
            supreme_law = get_supreme_law()
            snapshot = supreme_law.get_constitution_snapshot()
            return snapshot.hash_current

        return self._protocol.execute_amendment(proposal_id, executed_by, state_hasher)

    def get_proposal_status(self, proposal_id: UUID) -> dict[str, Any]:
        return self._protocol.get_proposal_details(proposal_id)

    def get_active_proposals(self) -> list[dict[str, Any]]:
        return self._protocol.get_active_proposals()

    def get_protocol_summary(self) -> dict[str, Any]:
        stats = self._protocol.get_statistics()
        return {
            "protocol_version": self._protocol.protocol_version,
            "committee_members": self._protocol.committee_members,
            "active_proposals": len(self._protocol._active_proposal_ids),
            **stats,
        }

    def add_committee_member(self, member_id: str, added_by: str) -> None:
        if added_by not in self._protocol.committee_members:
            raise InsufficientApprovalError(f"{added_by} cannot add committee members")
        if member_id not in self._protocol.committee_members:
            self._protocol.committee_members.append(member_id)

    def remove_committee_member(self, member_id: str, removed_by: str) -> None:
        if removed_by not in self._protocol.committee_members:
            raise InsufficientApprovalError(f"{removed_by} cannot remove committee members")
        if member_id in self._protocol.committee_members:
            self._protocol.committee_members.remove(member_id)

    def expire_old_proposals(self) -> int:
        return self._protocol.expire_old_proposals()

    def get_protocol(self) -> AmendmentProtocol:
        return self._protocol


def get_amendment_protocol() -> AmendmentProtocolService:
    global _amendment_protocol_service_instance
    if _amendment_protocol_service_instance is None:
        _amendment_protocol_service_instance = AmendmentProtocolService()
    return _amendment_protocol_service_instance


_amendment_protocol_service_instance: AmendmentProtocolService | None = None

__all__ = [
    "AmendmentConflictError",
    "AmendmentExecutionRecord",
    "AmendmentExpiredError",
    "AmendmentProposal",
    "AmendmentProtocol",
    "AmendmentProtocolError",
    "AmendmentProtocolService",
    "AmendmentReviewComment",
    "AmendmentStatus",
    "AmendmentType",
    "AmendmentUrgency",
    "AmendmentVote",
    "AmendmentVoteRecord",
    "InsufficientApprovalError",
    "MigrationError",
    "MigrationStrategy",
    "get_amendment_protocol",
]
