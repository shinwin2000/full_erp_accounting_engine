#!/usr/bin/env python3
"""
Module: whistleblower_case_tracker.py
Layer: Compliance / Ethics

Responsibility:
    Pelacakan kasus whistleblower, termasuk pelaporan anonim, investigasi,
    status tracking, dokumentasi evidence, resolusi, dan perlindungan
    whistleblower dari retaliasi. Mendukung anonimitas, eskalasi, dan pelaporan.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, json, logging

Audit:
    Setiap perubahan status, penambahan bukti, atau resolusi dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class WhistleblowerCaseStatus(Enum):
    OPEN = "open"
    UNDER_INVESTIGATION = "under_investigation"
    CLOSED = "closed"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"
    REFERRED_TO_AUTHORITY = "referred_to_authority"


class WhistleblowerCategory(Enum):
    FRAUD = "fraud"
    CORRUPTION = "corruption"
    HARASSMENT = "harassment"
    SAFETY = "safety"
    FINANCIAL_MISSTATEMENT = "financial_misstatement"
    CONFLICT_OF_INTEREST = "conflict_of_interest"
    DATA_PRIVACY = "data_privacy"
    OTHER = "other"


class WhistleblowerProtectionStatus(Enum):
    NOT_APPLICABLE = "not_applicable"
    PROTECTED = "protected"
    RETALIATION_DETECTED = "retaliation_detected"
    PROTECTION_ENFORCED = "protection_enforced"


# ============================================================================
# Data Classes
# ============================================================================
class EvidenceAttachment:
    def __init__(
        self, attachment_id: UUID, filename: str, url: str, uploaded_by: UUID | None = None
    ):
        self.id = attachment_id
        self.filename = filename
        self.url = url
        self.uploaded_by = uploaded_by
        self.uploaded_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "filename": self.filename,
            "url": self.url,
            "uploaded_by": str(self.uploaded_by) if self.uploaded_by else None,
            "uploaded_at": self.uploaded_at.isoformat(),
        }


class InvestigationNote:
    def __init__(self, note: str, author: str, is_confidential: bool = True):
        self.id = uuid4()
        self.note = note
        self.author = author
        self.is_confidential = is_confidential
        self.created_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "note": self.note,
            "author": self.author,
            "is_confidential": self.is_confidential,
            "created_at": self.created_at.isoformat(),
        }


class WhistleblowerCase:
    def __init__(
        self,
        case_id: UUID,
        report_text: str,
        category: WhistleblowerCategory,
        reported_by: UUID | None,  # None for anonymous
        reporter_contact: str | None = None,
        reported_date: datetime | None = None,
        status: WhistleblowerCaseStatus = WhistleblowerCaseStatus.OPEN,
        protection_status: WhistleblowerProtectionStatus = WhistleblowerProtectionStatus.NOT_APPLICABLE,
    ):
        self.id = case_id
        self.report_text = report_text
        self.category = category
        self.reported_by = reported_by
        self.reporter_contact = reporter_contact
        self.reported_date = reported_date or datetime.utcnow()
        self.status = status
        self.protection_status = protection_status
        self.assigned_to: UUID | None = None
        self.assigned_at: datetime | None = None
        self.investigation_notes: list[InvestigationNote] = []
        self.evidence: list[EvidenceAttachment] = []
        self.resolution_notes: str | None = None
        self.resolved_by: UUID | None = None
        self.resolved_date: datetime | None = None
        self.escalation_reason: str | None = None
        self.escalated_to: str | None = None
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "category": self.category.value,
            "status": self.status.value,
            "reported_date": self.reported_date.isoformat(),
            "protection_status": self.protection_status.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def assign_investigator(self, investigator_id: UUID) -> None:
        self.assigned_to = investigator_id
        self.assigned_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Case {self.id} assigned to investigator {investigator_id}")

    def update_status(
        self, new_status: WhistleblowerCaseStatus, updated_by: UUID, notes: str = ""
    ) -> None:
        old = self.status.value
        self.status = new_status
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        self.add_investigation_note(
            f"Status changed from {old} to {new_status.value} by {updated_by}. {notes}", "system"
        )
        logger.info(f"Case {self.id} status: {old} -> {new_status.value}")

    def add_investigation_note(self, note: str, author: str, is_confidential: bool = True) -> None:
        self.investigation_notes.append(InvestigationNote(note, author, is_confidential))
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def add_evidence(self, attachment: EvidenceAttachment) -> None:
        self.evidence.append(attachment)
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def resolve(self, resolved_by: UUID, resolution_notes: str) -> None:
        self.status = WhistleblowerCaseStatus.CLOSED
        self.resolved_by = resolved_by
        self.resolution_notes = resolution_notes
        self.resolved_date = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Case {self.id} resolved by {resolved_by}")

    def escalate(self, reason: str, escalated_to: str) -> None:
        self.status = WhistleblowerCaseStatus.ESCALATED
        self.escalation_reason = reason
        self.escalated_to = escalated_to
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.warning(f"Case {self.id} escalated to {escalated_to}: {reason}")

    def protect_reporter(self) -> None:
        self.protection_status = WhistleblowerProtectionStatus.PROTECTED
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def report_retaliation(self, description: str) -> None:
        self.protection_status = WhistleblowerProtectionStatus.RETALIATION_DETECTED
        self.add_investigation_note(f"Retaliation reported: {description}", "system")
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def is_anonymous(self) -> bool:
        return self.reported_by is None

    def to_dict(self, include_sensitive: bool = False) -> dict:
        data = {
            "case_id": str(self.id),
            "report_text": self.report_text[:500],  # truncate for safety
            "category": self.category.value,
            "status": self.status.value,
            "reported_date": self.reported_date.isoformat(),
            "assigned_to": str(self.assigned_to) if self.assigned_to else None,
            "investigation_notes": [n.to_dict() for n in self.investigation_notes],
            "evidence": [e.to_dict() for e in self.evidence],
            "resolution_notes": self.resolution_notes,
            "protection_status": self.protection_status.value,
            "hash": self._hash,
        }
        if include_sensitive and not self.is_anonymous():
            data["reported_by"] = str(self.reported_by)
            data["reporter_contact"] = self.reporter_contact
        return data


# ============================================================================
# WhistleblowerCaseTracker Core
# ============================================================================
class WhistleblowerCaseTracker:
    """
    Tracker untuk kasus whistleblower.
    """

    def __init__(self):
        self._cases: dict[UUID, WhistleblowerCase] = {}
        self._anonymous_counter = 0

    def _generate_anonymous_id(self) -> str:
        self._anonymous_counter += 1
        return f"ANON-{self._anonymous_counter:04d}"

    def report_case(
        self,
        report_text: str,
        category: WhistleblowerCategory,
        reported_by: UUID | None = None,
        reporter_contact: str | None = None,
    ) -> UUID:
        case_id = uuid4()
        case = WhistleblowerCase(
            case_id=case_id,
            report_text=report_text,
            category=category,
            reported_by=reported_by,
            reporter_contact=reporter_contact if reported_by else None,
        )
        self._cases[case_id] = case
        logger.info(f"Whistleblower case {case_id} reported (anonymous={case.is_anonymous()})")
        return case_id

    def get_case(self, case_id: UUID) -> WhistleblowerCase | None:
        return self._cases.get(case_id)

    def assign_case(self, case_id: UUID, investigator_id: UUID) -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        case.assign_investigator(investigator_id)
        return True

    def update_case_status(
        self, case_id: UUID, new_status: WhistleblowerCaseStatus, updated_by: UUID, notes: str = ""
    ) -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        case.update_status(new_status, updated_by, notes)
        return True

    def add_investigation_note(
        self, case_id: UUID, note: str, author: str, is_confidential: bool = True
    ) -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        case.add_investigation_note(note, author, is_confidential)
        return True

    def add_evidence(
        self, case_id: UUID, filename: str, url: str, uploaded_by: UUID | None = None
    ) -> UUID | None:
        case = self.get_case(case_id)
        if not case:
            return None
        attachment = EvidenceAttachment(uuid4(), filename, url, uploaded_by)
        case.add_evidence(attachment)
        return attachment.id

    def resolve_case(self, case_id: UUID, resolved_by: UUID, resolution_notes: str) -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        case.resolve(resolved_by, resolution_notes)
        return True

    def escalate_case(self, case_id: UUID, reason: str, escalated_to: str) -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        case.escalate(reason, escalated_to)
        return True

    def protect_reporter(self, case_id: UUID) -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        case.protect_reporter()
        return True

    def report_retaliation(self, case_id: UUID, description: str) -> bool:
        case = self.get_case(case_id)
        if not case:
            return False
        case.report_retaliation(description)
        return True

    def get_cases_by_status(self, status: WhistleblowerCaseStatus) -> list[WhistleblowerCase]:
        return [c for c in self._cases.values() if c.status == status]

    def get_open_cases(self) -> list[WhistleblowerCase]:
        open_statuses = [WhistleblowerCaseStatus.OPEN, WhistleblowerCaseStatus.UNDER_INVESTIGATION]
        return [c for c in self._cases.values() if c.status in open_statuses]

    def get_cases_by_category(self, category: WhistleblowerCategory) -> list[WhistleblowerCase]:
        return [c for c in self._cases.values() if c.category == category]

    def get_assigned_cases(self, investigator_id: UUID) -> list[WhistleblowerCase]:
        return [c for c in self._cases.values() if c.assigned_to == investigator_id]

    def generate_summary(self) -> dict:
        total = len(self._cases)
        open_cases = len(self.get_open_cases())
        by_category = {
            cat.value: len(self.get_cases_by_category(cat)) for cat in WhistleblowerCategory
        }
        by_status = {st.value: len(self.get_cases_by_status(st)) for st in WhistleblowerCaseStatus}
        anonymous_count = sum(1 for c in self._cases.values() if c.is_anonymous())
        protection_active = sum(
            1
            for c in self._cases.values()
            if c.protection_status == WhistleblowerProtectionStatus.PROTECTED
        )
        return {
            "total_cases": total,
            "open_cases": open_cases,
            "anonymous_reports": anonymous_count,
            "protected_reporters": protection_active,
            "by_category": by_category,
            "by_status": by_status,
        }

    def to_json(self, file_path: str, include_sensitive: bool = False) -> None:
        data = {
            "summary": self.generate_summary(),
            "cases": [c.to_dict(include_sensitive=include_sensitive) for c in self._cases.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    tracker = WhistleblowerCaseTracker()

    # Anonymous report
    case1_id = tracker.report_case(
        report_text="I suspect my manager is inflating expense reports",
        category=WhistleblowerCategory.FRAUD,
        reported_by=None,
    )
    print(f"Case 1 (anonymous): {case1_id}")

    # Identified reporter
    reporter_id = uuid4()
    case2_id = tracker.report_case(
        report_text="Conflict of interest in procurement",
        category=WhistleblowerCategory.CONFLICT_OF_INTEREST,
        reported_by=reporter_id,
        reporter_contact="whistleblower@example.com",
    )

    # Assign investigator
    inv_id = uuid4()
    tracker.assign_case(case2_id, inv_id)

    # Add investigation note
    tracker.add_investigation_note(
        case2_id, "Reviewed procurement documents, found irregularities", "Investigator A"
    )

    # Add evidence
    tracker.add_evidence(
        case2_id, "procurement_logs.xlsx", "s3://evidence/procurement_logs.xlsx", inv_id
    )

    # Update status
    tracker.update_case_status(
        case2_id,
        WhistleblowerCaseStatus.UNDER_INVESTIGATION,
        inv_id,
        "Starting formal investigation",
    )

    # Protect reporter
    tracker.protect_reporter(case2_id)

    # Resolve
    tracker.resolve_case(case2_id, inv_id, "Confirmed violation, training ordered for manager")

    # Summary
    print(tracker.generate_summary())
    tracker.to_json("whistleblower_cases.json")
    print("Exported to whistleblower_cases.json")
