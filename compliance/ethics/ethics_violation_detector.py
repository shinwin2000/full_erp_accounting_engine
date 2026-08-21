#!/usr/bin/env python3
"""
Module: ethics_violation_detector.py
Layer: Compliance / Ethics

Responsibility:
    Deteksi pelanggaran kode etik berdasarkan pola transaksi, pengaduan (whistleblower),
    audit internal, atau sumber lain. Mendukung rule-based detection, anomaly detection
    sederhana, scoring risiko pelanggaran, dan workflow investigasi.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, json, logging, re

Audit:
    Setiap pelanggaran yang terdeteksi dicatat dengan hash chain, status investigasi,
    dan tindak lanjut.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class ViolationSeverity(Enum):
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    CRITICAL = "critical"


class ViolationStatus(Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class ViolationCategory(Enum):
    CONFLICT_OF_INTEREST = "conflict_of_interest"
    INSIDER_TRADING = "insider_trading"
    BRIBERY = "bribery"
    FRAUD = "fraud"
    DATA_PRIVACY = "data_privacy"
    HARASSMENT = "harassment"
    MISUSE_OF_ASSETS = "misuse_of_assets"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    FINANCIAL_MISSTATEMENT = "financial_misstatement"
    WHISTLEBLOWER_RETALIATION = "whistleblower_retaliation"


# ============================================================================
# Data Classes
# ============================================================================
class ViolationEvidence:
    def __init__(self, evidence_id: UUID, description: str, source: str, url: str | None = None):
        self.id = evidence_id
        self.description = description
        self.source = source
        self.url = url
        self.created_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "description": self.description,
            "source": self.source,
            "url": self.url,
            "created_at": self.created_at.isoformat(),
        }


class EthicsViolation:
    def __init__(
        self,
        violation_id: UUID,
        description: str,
        category: ViolationCategory,
        severity: ViolationSeverity,
        reported_by: UUID,
        reported_date: datetime,
        involved_parties: list[UUID],
        evidence: list[ViolationEvidence],
        status: ViolationStatus = ViolationStatus.OPEN,
        policy_reference: str | None = None,
    ):
        self.id = violation_id
        self.description = description
        self.category = category
        self.severity = severity
        self.reported_by = reported_by
        self.reported_date = reported_date
        self.involved_parties = involved_parties
        self.evidence = evidence
        self.status = status
        self.policy_reference = policy_reference
        self.investigation_notes: list[str] = []
        self.resolution_notes: str | None = None
        self.resolved_by: UUID | None = None
        self.resolved_date: datetime | None = None
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "category": self.category.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "reported_date": self.reported_date.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def update_status(self, new_status: ViolationStatus, updated_by: UUID, notes: str = "") -> None:
        old = self.status.value
        self.status = new_status
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        self.investigation_notes.append(
            f"{datetime.utcnow().isoformat()} - Status changed from {old} to {new_status.value} by {updated_by}: {notes}"
        )
        logger.info(f"Violation {self.id} status: {old} -> {new_status.value}")

    def add_evidence(self, evidence: ViolationEvidence, added_by: UUID) -> None:
        self.evidence.append(evidence)
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        self.investigation_notes.append(
            f"{datetime.utcnow().isoformat()} - Evidence added by {added_by}: {evidence.description}"
        )

    def resolve(self, resolved_by: UUID, resolution_notes: str) -> None:
        self.status = ViolationStatus.RESOLVED
        self.resolved_by = resolved_by
        self.resolution_notes = resolution_notes
        self.resolved_date = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def escalate(self, escalated_by: UUID, reason: str) -> None:
        self.status = ViolationStatus.ESCALATED
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        self.investigation_notes.append(
            f"{datetime.utcnow().isoformat()} - Escalated by {escalated_by}: {reason}"
        )

    def to_dict(self) -> dict:
        return {
            "violation_id": str(self.id),
            "description": self.description,
            "category": self.category.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "reported_by": str(self.reported_by),
            "reported_date": self.reported_date.isoformat(),
            "involved_parties": [str(p) for p in self.involved_parties],
            "evidence": [e.to_dict() for e in self.evidence],
            "investigation_notes": self.investigation_notes,
            "resolution_notes": self.resolution_notes,
            "hash": self._hash,
        }


# ============================================================================
# EthicsViolationDetector Core
# ============================================================================
class EthicsViolationDetector:
    """
    Detektor pelanggaran kode etik.
    """

    def __init__(self) -> None:  # FIX: tambahkan anotasi tipe
        self._violations: dict[UUID, EthicsViolation] = {}
        self._red_flags = self._init_red_flags()
        self._suspicious_patterns = self._init_patterns()

    def _init_red_flags(self) -> list[dict]:
        return [
            {
                "pattern": r"unauthorized|unapproved",
                "category": ViolationCategory.UNAUTHORIZED_ACCESS,
                "severity": ViolationSeverity.MAJOR,
            },
            {
                "pattern": r"insider trading|non-public",
                "category": ViolationCategory.INSIDER_TRADING,
                "severity": ViolationSeverity.CRITICAL,
            },
            {
                "pattern": r"conflict of interest|related party|family business",
                "category": ViolationCategory.CONFLICT_OF_INTEREST,
                "severity": ViolationSeverity.MODERATE,
            },
            {
                "pattern": r"fraud|falsified|manipulated",
                "category": ViolationCategory.FRAUD,
                "severity": ViolationSeverity.CRITICAL,
            },
            {
                "pattern": r"bribe|kickback|gift",
                "category": ViolationCategory.BRIBERY,
                "severity": ViolationSeverity.CRITICAL,
            },
            {
                "pattern": r"data breach|personal data|gdpr",
                "category": ViolationCategory.DATA_PRIVACY,
                "severity": ViolationSeverity.MAJOR,
            },
            {
                "pattern": r"harass|discrimination|bullying",
                "category": ViolationCategory.HARASSMENT,
                "severity": ViolationSeverity.MAJOR,
            },
            {
                "pattern": r"misappropriation|theft|misuse",
                "category": ViolationCategory.MISUSE_OF_ASSETS,
                "severity": ViolationSeverity.MAJOR,
            },
            {
                "pattern": r"restate|material misstatement|accounting error",
                "category": ViolationCategory.FINANCIAL_MISSTATEMENT,
                "severity": ViolationSeverity.MAJOR,  # FIX: ganti HIGH -> MAJOR
            },
            {
                "pattern": r"retaliation|whistleblower",
                "category": ViolationCategory.WHISTLEBLOWER_RETALIATION,
                "severity": ViolationSeverity.CRITICAL,
            },
        ]

    def _init_patterns(self) -> list[dict]:
        return [
            {
                "type": "large_self_approved",
                "threshold_amount": 1_000_000_000,
                "severity": ViolationSeverity.MAJOR,
            },
            {"type": "circular_transaction", "severity": ViolationSeverity.CRITICAL},
            {"type": "after_hours_access", "severity": ViolationSeverity.MODERATE},
        ]

    def scan_transaction(self, transaction: dict[str, Any]) -> EthicsViolation | None:
        """Scan transaksi tunggal berdasarkan aturan."""
        # Rule: Large transaction self-approved
        amount = transaction.get("amount", 0)
        approval = transaction.get("approval", "")
        if (
            amount > self._red_flags[0].get("threshold_amount", 1_000_000_000)
            and approval == "self"
        ):
            # FIX: konversi user_id ke UUID dengan fallback
            user_id = transaction.get("user_id")
            if not isinstance(user_id, UUID):
                user_id = UUID(int=0)
            return EthicsViolation(
                violation_id=uuid4(),
                description=f"Large transaction {amount} self-approved without justification",
                category=ViolationCategory.UNAUTHORIZED_ACCESS,
                severity=ViolationSeverity.MAJOR,
                reported_by=user_id,
                reported_date=datetime.utcnow(),
                involved_parties=[user_id],
                evidence=[
                    ViolationEvidence(uuid4(), f"Transaction ID: {transaction.get('id')}", "system")
                ],
            )
        # Rule: Suspicious keyword in description
        description = transaction.get("description", "")
        for flag in self._red_flags:
            if re.search(flag["pattern"], description, re.IGNORECASE):
                # FIX: konversi user_id ke UUID dengan fallback
                user_id = transaction.get("user_id")
                if not isinstance(user_id, UUID):
                    user_id = UUID(int=0)
                return EthicsViolation(
                    violation_id=uuid4(),
                    description=f"Suspicious transaction: {description[:100]}",
                    category=flag["category"],
                    severity=flag["severity"],
                    reported_by=user_id,
                    reported_date=datetime.utcnow(),
                    involved_parties=[user_id],
                    evidence=[
                        ViolationEvidence(
                            uuid4(), f"Transaction ID: {transaction.get('id')}", "system"
                        )
                    ],
                )
        return None

    def report_violation(
        self,
        description: str,
        category: ViolationCategory,
        severity: ViolationSeverity,
        reported_by: UUID,
        involved_parties: list[UUID],
        evidence: list[ViolationEvidence],
        policy_reference: str | None = None,
    ) -> UUID:
        violation = EthicsViolation(
            violation_id=uuid4(),
            description=description,
            category=category,
            severity=severity,
            reported_by=reported_by,
            reported_date=datetime.utcnow(),
            involved_parties=involved_parties,
            evidence=evidence,
            policy_reference=policy_reference,
        )
        self._violations[violation.id] = violation
        logger.warning(f"Ethics violation reported: {violation.id} - {category.value}")
        return violation.id

    def get_violation(self, violation_id: UUID) -> EthicsViolation | None:
        return self._violations.get(violation_id)

    def update_violation_status(
        self, violation_id: UUID, new_status: ViolationStatus, updated_by: UUID, notes: str = ""
    ) -> bool:
        v = self._violations.get(violation_id)
        if not v:
            return False
        v.update_status(new_status, updated_by, notes)
        return True

    def add_evidence_to_violation(
        self, violation_id: UUID, evidence: ViolationEvidence, added_by: UUID
    ) -> bool:
        v = self._violations.get(violation_id)
        if not v:
            return False
        v.add_evidence(evidence, added_by)
        return True

    def resolve_violation(
        self, violation_id: UUID, resolved_by: UUID, resolution_notes: str
    ) -> bool:
        v = self._violations.get(violation_id)
        if not v:
            return False
        v.resolve(resolved_by, resolution_notes)
        return True

    def escalate_violation(self, violation_id: UUID, escalated_by: UUID, reason: str) -> bool:
        v = self._violations.get(violation_id)
        if not v:
            return False
        v.escalate(escalated_by, reason)
        return True

    def get_violations(
        self,
        status: ViolationStatus | None = None,
        category: ViolationCategory | None = None,
        severity: ViolationSeverity | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[EthicsViolation]:
        result = list(self._violations.values())
        if status:
            result = [v for v in result if v.status == status]
        if category:
            result = [v for v in result if v.category == category]
        if severity:
            result = [v for v in result if v.severity == severity]
        if from_date:
            result = [v for v in result if v.reported_date.date() >= from_date]
        if to_date:
            result = [v for v in result if v.reported_date.date() <= to_date]
        return result

    def get_open_violations(self) -> list[EthicsViolation]:
        open_statuses = [ViolationStatus.OPEN, ViolationStatus.INVESTIGATING]
        return [v for v in self._violations.values() if v.status in open_statuses]

    def generate_report(self) -> dict:
        total = len(self._violations)
        open_count = len(self.get_open_violations())
        by_category = {
            cat.value: len([v for v in self._violations.values() if v.category == cat])
            for cat in ViolationCategory
        }
        by_severity = {
            sev.value: len([v for v in self._violations.values() if v.severity == sev])
            for sev in ViolationSeverity
        }
        by_status = {
            st.value: len([v for v in self._violations.values() if v.status == st])
            for st in ViolationStatus
        }
        # FIX: cek apakah ada violations sebelum mengambil max
        most_recent = None
        if self._violations:
            latest_id = max(self._violations.keys())
            most_recent = self._violations[latest_id].to_dict()
        return {
            "total_violations": total,
            "open_violations": open_count,
            "by_category": by_category,
            "by_severity": by_severity,
            "by_status": by_status,
            "most_recent": most_recent,
        }

    def to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "violations": [v.to_dict() for v in self._violations.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    detector = EthicsViolationDetector()
    tx = {
        "id": "T001",
        "amount": 1_500_000_000,
        "approval": "self",
        "user_id": uuid4(),
        "description": "Payment to related party",
    }
    violation = detector.scan_transaction(tx)
    if violation:
        detector.report_violation(
            description=violation.description,
            category=violation.category,
            severity=violation.severity,
            reported_by=violation.reported_by,
            involved_parties=violation.involved_parties,
            evidence=violation.evidence,
        )
    print("Open violations:", len(detector.get_open_violations()))
    detector.to_json("ethics_violations.json")
