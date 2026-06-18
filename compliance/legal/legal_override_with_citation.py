#!/usr/bin/env python3
"""
Module: legal_override_with_citation.py
Layer: Compliance / Legal

Responsibility:
    Mekanisme override keputusan sistem berdasarkan ketentuan hukum tertentu (dengan sitasi).
    Memungkinkan otorisasi khusus dengan dasar hukum yang jelas. Mendukung workflow
    request override, approval multi-level, tracking masa berlaku, audit trail,
    dan pelaporan override yang dilakukan.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, json, logging

Audit:
    Setiap override request, approval, rejection, dan implementasi dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class OverrideStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class OverrideRiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OverrideApprovalLevel(Enum):
    SUPERVISOR = "supervisor"
    MANAGER = "manager"
    DIRECTOR = "director"
    VP = "vp"
    C_SUITE = "c_suite"
    BOARD = "board"


# ============================================================================
# Exceptions
# ============================================================================
class OverrideError(Exception):
    pass


class OverrideNotAllowedError(OverrideError):
    pass


class OverrideNotFoundError(OverrideError):
    pass


# ============================================================================
# Data Classes
# ============================================================================
class LegalOverride:
    def __init__(
        self,
        override_id: UUID,
        rule_id: str,
        rule_description: str,
        justification: str,
        legal_citation: str,
        requested_by: UUID,
        requested_by_name: str,
        risk_level: OverrideRiskLevel,
        effective_date: date,
        expiry_date: date | None = None,
        status: OverrideStatus = OverrideStatus.PENDING,
        approved_by: UUID | None = None,
        approved_by_name: str | None = None,
        approved_at: datetime | None = None,
        approval_level: OverrideApprovalLevel | None = None,
        rejection_reason: str | None = None,
    ):
        self.id = override_id
        self.rule_id = rule_id
        self.rule_description = rule_description
        self.justification = justification
        self.legal_citation = legal_citation
        self.requested_by = requested_by
        self.requested_by_name = requested_by_name
        self.risk_level = risk_level
        self.effective_date = effective_date
        self.expiry_date = expiry_date or (effective_date + timedelta(days=90))  # default 90 days
        self.status = status
        self.approved_by = approved_by
        self.approved_by_name = approved_by_name
        self.approved_at = approved_at
        self.approval_level = approval_level
        self.rejection_reason = rejection_reason
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "rule_id": self.rule_id,
            "legal_citation": self.legal_citation,
            "status": self.status.value,
            "effective_date": self.effective_date.isoformat(),
            "requested_by": str(self.requested_by),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def approve(
        self, approver_id: UUID, approver_name: str, approval_level: OverrideApprovalLevel
    ) -> None:
        if self.status != OverrideStatus.PENDING:
            raise OverrideError(f"Cannot approve override with status {self.status.value}")
        self.status = OverrideStatus.APPROVED
        self.approved_by = approver_id
        self.approved_by_name = approver_name
        self.approved_at = datetime.utcnow()
        self.approval_level = approval_level
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(
            f"Override {self.id} approved by {approver_name} at level {approval_level.value}"
        )

    def reject(self, approver_id: UUID, approver_name: str, reason: str) -> None:
        if self.status != OverrideStatus.PENDING:
            raise OverrideError(f"Cannot reject override with status {self.status.value}")
        self.status = OverrideStatus.REJECTED
        self.approved_by = approver_id
        self.approved_by_name = approver_name
        self.rejection_reason = reason
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Override {self.id} rejected by {approver_name}: {reason}")

    def revoke(self, revoked_by: UUID, reason: str) -> None:
        if self.status != OverrideStatus.APPROVED:
            raise OverrideError(f"Cannot revoke override with status {self.status.value}")
        self.status = OverrideStatus.REVOKED
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.warning(f"Override {self.id} revoked by {revoked_by}: {reason}")

    def is_active(self, as_of: date | None = None) -> bool:
        ref = as_of or date.today()
        return self.status == OverrideStatus.APPROVED and self.effective_date <= ref <= (
            self.expiry_date or ref
        )

    def to_dict(self) -> dict:
        return {
            "override_id": str(self.id),
            "rule_id": self.rule_id,
            "rule_description": self.rule_description,
            "justification": self.justification,
            "legal_citation": self.legal_citation,
            "requested_by": str(self.requested_by),
            "requested_by_name": self.requested_by_name,
            "risk_level": self.risk_level.value,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "status": self.status.value,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_by_name": self.approved_by_name,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approval_level": self.approval_level.value if self.approval_level else None,
            "rejection_reason": self.rejection_reason,
            "hash": self._hash,
        }


# ============================================================================
# LegalOverrideWithCitation Core
# ============================================================================
class LegalOverrideWithCitation:
    """
    Mekanisme override keputusan sistem dengan sitasi hukum.
    """

    def __init__(self):
        self._overrides: dict[UUID, LegalOverride] = {}
        self._allowed_citations = self._init_allowed_citations()
        self._rule_index: dict[str, list[UUID]] = {}  # rule_id -> list of override ids

    def _init_allowed_citations(self) -> list[dict]:
        """Daftar sitasi hukum yang diizinkan untuk override beserta level approval yang diperlukan."""
        return [
            {
                "citation": "PSAK 25 paragraf 12",
                "approval_level": OverrideApprovalLevel.MANAGER,
                "risk": OverrideRiskLevel.MEDIUM,
            },
            {
                "citation": "Permenkeu No. 68/PMK.03/2022",
                "approval_level": OverrideApprovalLevel.DIRECTOR,
                "risk": OverrideRiskLevel.HIGH,
            },
            {
                "citation": "PP No. 9 Tahun 2021",
                "approval_level": OverrideApprovalLevel.VP,
                "risk": OverrideRiskLevel.HIGH,
            },
            {
                "citation": "UU Cipta Kerja Pasal 117",
                "approval_level": OverrideApprovalLevel.C_SUITE,
                "risk": OverrideRiskLevel.CRITICAL,
            },
            {
                "citation": "POJK No. 29/POJK.04/2016",
                "approval_level": OverrideApprovalLevel.DIRECTOR,
                "risk": OverrideRiskLevel.MEDIUM,
            },
            {
                "citation": "SE-11/PJ/2024",
                "approval_level": OverrideApprovalLevel.MANAGER,
                "risk": OverrideRiskLevel.LOW,
            },
        ]

    def _get_citation_info(self, citation: str) -> dict | None:
        for c in self._allowed_citations:
            if c["citation"] == citation:
                return c
        return None

    def request_override(
        self,
        rule_id: str,
        rule_description: str,
        justification: str,
        legal_citation: str,
        requested_by: UUID,
        requested_by_name: str,
        effective_date: date | None = None,
        expiry_date: date | None = None,
    ) -> UUID:
        """
        Mengajukan override untuk suatu aturan.
        """
        citation_info = self._get_citation_info(legal_citation)
        if not citation_info:
            raise OverrideNotAllowedError(
                f"Legal citation '{legal_citation}' is not recognized for override"
            )

        risk_level = citation_info["risk"]
        override_id = uuid4()
        override = LegalOverride(
            override_id=override_id,
            rule_id=rule_id,
            rule_description=rule_description,
            justification=justification,
            legal_citation=legal_citation,
            requested_by=requested_by,
            requested_by_name=requested_by_name,
            risk_level=risk_level,
            effective_date=effective_date or date.today(),
            expiry_date=expiry_date,
        )
        self._overrides[override_id] = override
        self._rule_index.setdefault(rule_id, []).append(override_id)
        logger.info(
            f"Override request {override_id} submitted for rule {rule_id} with citation {legal_citation}"
        )
        return override_id

    def approve_override(
        self,
        override_id: UUID,
        approver_id: UUID,
        approver_name: str,
        approver_level: OverrideApprovalLevel,
    ) -> bool:
        override = self._overrides.get(override_id)
        if not override:
            raise OverrideNotFoundError(f"Override {override_id} not found")

        citation_info = self._get_citation_info(override.legal_citation)
        required_level = (
            citation_info["approval_level"] if citation_info else OverrideApprovalLevel.DIRECTOR
        )

        # Check if approver has sufficient level
        levels_order = list(OverrideApprovalLevel)
        if levels_order.index(approver_level) < levels_order.index(required_level):
            raise OverrideNotAllowedError(
                f"Approver level {approver_level.value} insufficient, required {required_level.value}"
            )

        override.approve(approver_id, approver_name, approver_level)
        return True

    def reject_override(
        self, override_id: UUID, approver_id: UUID, approver_name: str, reason: str
    ) -> bool:
        override = self._overrides.get(override_id)
        if not override:
            return False
        override.reject(approver_id, approver_name, reason)
        return True

    def revoke_override(self, override_id: UUID, revoked_by: UUID, reason: str) -> bool:
        override = self._overrides.get(override_id)
        if not override:
            return False
        override.revoke(revoked_by, reason)
        return True

    def is_overridden(self, rule_id: str, as_of: date | None = None) -> bool:
        """Cek apakah suatu aturan sedang di-override (ada override aktif)."""
        override_ids = self._rule_index.get(rule_id, [])
        for oid in override_ids:
            override = self._overrides.get(oid)
            if override and override.is_active(as_of):
                return True
        return False

    def get_active_override(self, rule_id: str, as_of: date | None = None) -> LegalOverride | None:
        override_ids = self._rule_index.get(rule_id, [])
        for oid in override_ids:
            override = self._overrides.get(oid)
            if override and override.is_active(as_of):
                return override
        return None

    def get_all_overrides(self, status: OverrideStatus | None = None) -> list[LegalOverride]:
        if status:
            return [o for o in self._overrides.values() if o.status == status]
        return list(self._overrides.values())

    def get_pending_overrides(self) -> list[LegalOverride]:
        return [o for o in self._overrides.values() if o.status == OverrideStatus.PENDING]

    def get_expired_overrides(self) -> list[LegalOverride]:
        today = date.today()
        return [
            o
            for o in self._overrides.values()
            if o.status == OverrideStatus.APPROVED and o.expiry_date and o.expiry_date < today
        ]

    def generate_report(self) -> dict:
        total = len(self._overrides)
        pending = len(self.get_pending_overrides())
        approved = len([o for o in self._overrides.values() if o.status == OverrideStatus.APPROVED])
        rejected = len([o for o in self._overrides.values() if o.status == OverrideStatus.REJECTED])
        active = len([o for o in self._overrides.values() if o.is_active()])
        expired = len(self.get_expired_overrides())
        by_risk = {
            "low": len(
                [o for o in self._overrides.values() if o.risk_level == OverrideRiskLevel.LOW]
            ),
            "medium": len(
                [o for o in self._overrides.values() if o.risk_level == OverrideRiskLevel.MEDIUM]
            ),
            "high": len(
                [o for o in self._overrides.values() if o.risk_level == OverrideRiskLevel.HIGH]
            ),
            "critical": len(
                [o for o in self._overrides.values() if o.risk_level == OverrideRiskLevel.CRITICAL]
            ),
        }
        return {
            "total_overrides": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "active": active,
            "expired": expired,
            "by_risk_level": by_risk,
        }

    def expire_pending_overrides(self, days_threshold: int = 30) -> int:
        """Tandai override pending yang sudah lebih dari threshold hari sebagai expired."""
        cutoff = datetime.utcnow() - timedelta(days=days_threshold)
        count = 0
        for o in self._overrides.values():
            if o.status == OverrideStatus.PENDING and o.created_at < cutoff:
                o.status = OverrideStatus.EXPIRED
                o.updated_at = datetime.utcnow()
                o._hash = o._compute_hash()
                count += 1
        return count

    def to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "overrides": [o.to_dict() for o in self._overrides.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    manager = LegalOverrideWithCitation()
    req_id = manager.request_override(
        rule_id="JOURNAL_POSTING_RULE",
        rule_description="Journal must have approval before posting",
        justification="Emergency year-end adjustment needed",
        legal_citation="PSAK 25 paragraf 12",
        requested_by=uuid4(),
        requested_by_name="Finance Manager",
        expiry_date=date.today() + timedelta(days=30),
    )
    print(f"Request ID: {req_id}")

    # Approve
    manager.approve_override(req_id, uuid4(), "Compliance Director", OverrideApprovalLevel.DIRECTOR)
    print(f"Is overridden? {manager.is_overridden('JOURNAL_POSTING_RULE')}")

    print(manager.generate_report())
    manager.to_json("legal_overrides.json")
