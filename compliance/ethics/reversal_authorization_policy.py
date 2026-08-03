#!/usr/bin/env python3
"""
Module: reversal_authorization_policy.py
Layer: Compliance / Ethics

Responsibility:
    Kebijakan otorisasi untuk pembalikan jurnal (journal reversal) sesuai standar etika
    dan internal control. Mendukung workflow request, approval multi-level,
    auto-approval untuk kondisi tertentu (same-day error), rejection dengan alasan,
    dokumentasi audit trail, dan pelaporan kepatuhan.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, json, logging

Audit:
    Setiap request reversal, approval, rejection, atau implementasi dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class ReversalReason(Enum):
    ERROR_CORRECTION = "error_correction"
    ADJUSTMENT = "adjustment"
    CANCELLATION = "cancellation"
    RESTATEMENT = "restatement"
    FRAUD_CORRECTION = "fraud_correction"


class ReversalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ReversalApprovalLevel(Enum):
    SUPERVISOR = "supervisor"
    MANAGER = "manager"
    CONTROLLER = "controller"
    CFO = "cfo"
    AUDIT_COMMITTEE = "audit_committee"


class ReversalRiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# Data Classes
# ============================================================================
class ReversalRequest:
    def __init__(
        self,
        request_id: UUID,
        journal_id: UUID,
        journal_amount: Decimal,
        journal_date: datetime,
        requested_by: UUID,
        requested_by_name: str,
        reason: ReversalReason,
        justification: str,
        risk_level: ReversalRiskLevel,
        original_journal_hash: str | None = None,
        expires_at: datetime | None = None,
    ):
        self.id = request_id
        self.journal_id = journal_id
        self.journal_amount = journal_amount
        self.journal_date = journal_date
        self.requested_by = requested_by
        self.requested_by_name = requested_by_name
        self.reason = reason
        self.justification = justification
        self.risk_level = risk_level
        self.original_journal_hash = original_journal_hash
        self.status = ReversalStatus.PENDING
        self.created_at = datetime.utcnow()
        self.expires_at = expires_at or (self.created_at + timedelta(days=7))
        self.approvals: list[ReversalApproval] = []
        self.implemented_by: UUID | None = None
        self.implemented_at: datetime | None = None
        self.rejection_reason: str | None = None
        self.reversal_journal_id: UUID | None = None
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "request_id": str(self.id),
            "journal_id": str(self.journal_id),
            "reason": self.reason.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_approval(
        self, approver_id: UUID, approver_name: str, level: ReversalApprovalLevel, notes: str = ""
    ) -> None:
        approval = ReversalApproval(
            approver_id=approver_id,
            approver_name=approver_name,
            level=level,
            decision="approved",
            notes=notes,
            approved_at=datetime.utcnow(),
        )
        self.approvals.append(approval)
        self._hash = self._compute_hash()
        logger.info(
            f"Reversal request {self.id} approved by {approver_name} at level {level.value}"
        )

    def add_rejection(
        self, approver_id: UUID, approver_name: str, level: ReversalApprovalLevel, reason: str
    ) -> None:
        approval = ReversalApproval(
            approver_id=approver_id,
            approver_name=approver_name,
            level=level,
            decision="rejected",
            notes=reason,
            approved_at=datetime.utcnow(),
        )
        self.approvals.append(approval)
        self.status = ReversalStatus.REJECTED
        self.rejection_reason = reason
        self._hash = self._compute_hash()
        logger.warning(f"Reversal request {self.id} rejected by {approver_name}: {reason}")

    def mark_implemented(self, implemented_by: UUID, reversal_journal_id: UUID) -> None:
        self.status = ReversalStatus.IMPLEMENTED
        self.implemented_by = implemented_by
        self.implemented_at = datetime.utcnow()
        self.reversal_journal_id = reversal_journal_id
        self._hash = self._compute_hash()
        logger.info(f"Reversal request {self.id} implemented with journal {reversal_journal_id}")

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "request_id": str(self.id),
            "journal_id": str(self.journal_id),
            "journal_amount": str(self.journal_amount),
            "journal_date": self.journal_date.isoformat(),
            "requested_by": str(self.requested_by),
            "requested_by_name": self.requested_by_name,
            "reason": self.reason.value,
            "justification": self.justification,
            "risk_level": self.risk_level.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "approvals": [a.to_dict() for a in self.approvals],
            "rejection_reason": self.rejection_reason,
            "reversal_journal_id": str(self.reversal_journal_id)
            if self.reversal_journal_id
            else None,
            "hash": self._hash,
        }


class ReversalApproval:
    def __init__(
        self,
        approver_id: UUID,
        approver_name: str,
        level: ReversalApprovalLevel,
        decision: str,
        notes: str,
        approved_at: datetime,
    ):
        self.approver_id = approver_id
        self.approver_name = approver_name
        self.level = level
        self.decision = decision
        self.notes = notes
        self.approved_at = approved_at

    def to_dict(self) -> dict:
        return {
            "approver_id": str(self.approver_id),
            "approver_name": self.approver_name,
            "level": self.level.value,
            "decision": self.decision,
            "notes": self.notes,
            "approved_at": self.approved_at.isoformat(),
        }


# ============================================================================
# ReversalAuthorizationPolicy Core
# ============================================================================
class ReversalAuthorizationPolicy:
    """
    Kebijakan otorisasi untuk pembalikan jurnal.
    """

    def __init__(self):
        self._requests: dict[UUID, ReversalRequest] = {}
        self._policy_rules = self._init_policy_rules()

    def _init_policy_rules(self) -> dict[ReversalRiskLevel, ReversalApprovalLevel]:
        """Mendefinisikan level approval yang diperlukan berdasarkan tingkat risiko."""
        return {
            ReversalRiskLevel.LOW: ReversalApprovalLevel.SUPERVISOR,
            ReversalRiskLevel.MEDIUM: ReversalApprovalLevel.MANAGER,
            ReversalRiskLevel.HIGH: ReversalApprovalLevel.CONTROLLER,
            ReversalRiskLevel.CRITICAL: ReversalApprovalLevel.CFO,
        }

    def _determine_risk_level(
        self,
        journal_amount: Decimal,
        reason: ReversalReason,
        journal_age_days: int,
        is_fraud: bool = False,
    ) -> ReversalRiskLevel:
        """Tentukan tingkat risiko reversal berdasarkan faktor-faktor."""
        if is_fraud or reason == ReversalReason.FRAUD_CORRECTION:
            return ReversalRiskLevel.CRITICAL
        if journal_age_days > 30:
            return ReversalRiskLevel.HIGH
        if journal_amount > Decimal("1_000_000_000"):
            return ReversalRiskLevel.HIGH
        if journal_amount > Decimal("100_000_000"):
            return ReversalRiskLevel.MEDIUM
        if reason == ReversalReason.RESTATEMENT:
            return ReversalRiskLevel.HIGH
        return ReversalRiskLevel.LOW

    def _can_auto_approve(self, request: ReversalRequest) -> bool:
        """Auto-approval untuk kesalahan same-day (error correction) dengan amount kecil."""
        if request.reason != ReversalReason.ERROR_CORRECTION:
            return False
        # Same-day reversal (within 24 hours)
        age_hours = (datetime.utcnow() - request.journal_date).total_seconds() / 3600
        if age_hours > 24:
            return False
        # Amount below threshold
        return not request.journal_amount > Decimal("10_000_000")

    def request_reversal(
        self,
        journal_id: UUID,
        journal_amount: Decimal,
        journal_date: datetime,
        requested_by: UUID,
        requested_by_name: str,
        reason: ReversalReason,
        justification: str,
        original_journal_hash: str | None = None,
        is_fraud: bool = False,
    ) -> ReversalRequest:
        """Ajukan request reversal jurnal."""
        # Hitung usia jurnal
        age_days = (datetime.utcnow() - journal_date).days
        risk_level = self._determine_risk_level(journal_amount, reason, age_days, is_fraud)

        request_id = uuid4()
        request = ReversalRequest(
            request_id=request_id,
            journal_id=journal_id,
            journal_amount=journal_amount,
            journal_date=journal_date,
            requested_by=requested_by,
            requested_by_name=requested_by_name,
            reason=reason,
            justification=justification,
            risk_level=risk_level,
            original_journal_hash=original_journal_hash,
        )
        self._requests[request_id] = request

        # Auto-approve jika memenuhi syarat
        if self._can_auto_approve(request):
            request.add_approval(
                approver_id=requested_by,
                approver_name="System Auto-Approval",
                level=ReversalApprovalLevel.SUPERVISOR,
                notes="Auto-approved: same-day error correction within threshold",
            )
            request.status = ReversalStatus.APPROVED
            request._hash = request._compute_hash()
            logger.info(f"Reversal request {request_id} auto-approved")
        else:
            logger.info(f"Reversal request {request_id} created, requires approval")

        return request

    def get_request(self, request_id: UUID) -> ReversalRequest | None:
        return self._requests.get(request_id)

    def approve(
        self,
        request_id: UUID,
        approver_id: UUID,
        approver_name: str,
        approver_level: ReversalApprovalLevel,
        notes: str = "",
    ) -> bool:
        """Setujui reversal request."""
        req = self.get_request(request_id)
        if not req:
            return False
        if req.status != ReversalStatus.PENDING:
            logger.warning(f"Cannot approve request {request_id} with status {req.status.value}")
            return False
        if req.is_expired():
            req.status = ReversalStatus.EXPIRED
            req._hash = req._compute_hash()
            logger.warning(f"Request {request_id} expired")
            return False

        # Cek level approval yang diperlukan
        required_level = self._policy_rules.get(req.risk_level, ReversalApprovalLevel.MANAGER)
        # Mapping level ke urutan
        levels_order = list(ReversalApprovalLevel)
        if levels_order.index(approver_level) < levels_order.index(required_level):
            logger.warning(
                f"Approver level {approver_level.value} insufficient, required {required_level.value}"
            )
            return False

        req.add_approval(approver_id, approver_name, approver_level, notes)

        # Jika level approver sudah mencapai atau melebihi required, request dianggap approved
        if levels_order.index(approver_level) >= levels_order.index(required_level):
            req.status = ReversalStatus.APPROVED
            req._hash = req._compute_hash()
            logger.info(f"Request {request_id} fully approved by {approver_name}")
        return True

    def reject(
        self,
        request_id: UUID,
        approver_id: UUID,
        approver_name: str,
        approver_level: ReversalApprovalLevel,
        reason: str,
    ) -> bool:
        """Tolak reversal request."""
        req = self.get_request(request_id)
        if not req:
            return False
        if req.status != ReversalStatus.PENDING:
            return False
        req.add_rejection(approver_id, approver_name, approver_level, reason)
        return True

    def implement_reversal(
        self,
        request_id: UUID,
        implemented_by: UUID,
        reversal_journal_id: UUID,
    ) -> bool:
        """Tandai reversal sudah diimplementasikan (jurnal reversal sudah di-posting)."""
        req = self.get_request(request_id)
        if not req or req.status != ReversalStatus.APPROVED:
            return False
        req.mark_implemented(implemented_by, reversal_journal_id)
        return True

    def get_pending_requests(self) -> list[ReversalRequest]:
        return [r for r in self._requests.values() if r.status == ReversalStatus.PENDING]

    def get_approved_requests(self) -> list[ReversalRequest]:
        return [r for r in self._requests.values() if r.status == ReversalStatus.APPROVED]

    def get_rejected_requests(self) -> list[ReversalRequest]:
        return [r for r in self._requests.values() if r.status == ReversalStatus.REJECTED]

    def get_requests_by_requester(self, requester_id: UUID) -> list[ReversalRequest]:
        return [r for r in self._requests.values() if r.requested_by == requester_id]

    def get_requests_by_risk_level(self, risk_level: ReversalRiskLevel) -> list[ReversalRequest]:
        return [r for r in self._requests.values() if r.risk_level == risk_level]

    def expire_pending_requests(self) -> int:
        """Tandai semua pending request yang sudah expired."""
        count = 0
        for req in self._requests.values():
            if req.status == ReversalStatus.PENDING and req.is_expired():
                req.status = ReversalStatus.EXPIRED
                req._hash = req._compute_hash()
                count += 1
        return count

    def generate_report(self) -> dict:
        total = len(self._requests)
        pending = len(self.get_pending_requests())
        approved = len(self.get_approved_requests())
        rejected = len(self.get_rejected_requests())
        implemented = len(
            [r for r in self._requests.values() if r.status == ReversalStatus.IMPLEMENTED]
        )
        expired = len([r for r in self._requests.values() if r.status == ReversalStatus.EXPIRED])
        by_risk = {
            level.value: len(self.get_requests_by_risk_level(level)) for level in ReversalRiskLevel
        }
        by_reason = {
            reason.value: len([r for r in self._requests.values() if r.reason == reason])
            for reason in ReversalReason
        }
        return {
            "total_requests": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "implemented": implemented,
            "expired": expired,
            "by_risk_level": by_risk,
            "by_reason": by_reason,
        }

    def to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "requests": [r.to_dict() for r in self._requests.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    from decimal import Decimal

    policy = ReversalAuthorizationPolicy()

    # Request 1: error correction same day, small amount -> auto-approve
    req1 = policy.request_reversal(
        journal_id=uuid4(),
        journal_amount=Decimal("5_000_000"),
        journal_date=datetime.utcnow(),
        requested_by=uuid4(),
        requested_by_name="Accountant A",
        reason=ReversalReason.ERROR_CORRECTION,
        justification="Wrong account code",
    )
    print(f"Request 1 status: {req1.status.value}")

    # Request 2: large amount, requires controller approval
    req2 = policy.request_reversal(
        journal_id=uuid4(),
        journal_amount=Decimal("500_000_000"),
        journal_date=datetime.utcnow() - timedelta(days=5),
        requested_by=uuid4(),
        requested_by_name="Accountant B",
        reason=ReversalReason.ADJUSTMENT,
        justification="Accrual adjustment",
    )
    print(f"Request 2 status: {req2.status.value}, risk: {req2.risk_level.value}")

    # Approve request 2 at manager level (not enough)
    policy.approve(
        request_id=req2.id,
        approver_id=uuid4(),
        approver_name="Manager",
        approver_level=ReversalApprovalLevel.MANAGER,
        notes="Looks reasonable",
    )
    print(f"After manager: {policy.get_request(req2.id).status.value}")

    # Approve at controller level (sufficient)
    policy.approve(
        request_id=req2.id,
        approver_id=uuid4(),
        approver_name="Controller",
        approver_level=ReversalApprovalLevel.CONTROLLER,
        notes="Approved",
    )
    print(f"After controller: {policy.get_request(req2.id).status.value}")

    # Implement reversal
    policy.implement_reversal(req2.id, implemented_by=uuid4(), reversal_journal_id=uuid4())
    print(f"Implemented: {policy.get_request(req2.id).status.value}")

    # Report
    print(policy.generate_report())
    policy.to_json("reversal_requests.json")
