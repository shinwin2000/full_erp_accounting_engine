#!/usr/bin/env python3
"""
Module: regulatory_filing_tracker.py
Layer: Compliance / Legal

Responsibility:
    Pelacakan pengajuan (filing) ke regulator, termasuk status (draft, submitted,
    acknowledged, rejected, completed), tenggat waktu, konfirmasi penerimaan,
    reminder otomatis, dan audit trail. Mendukung pembuatan filing baru,
    submit, acknowledgment, rejection handling, overdue detection, dan export laporan.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, json, logging

Audit:
    Setiap perubahan status filing dicatat dengan timestamp, user, dan hash.
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
class FilingStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    COMPLETED = "completed"
    EXPIRED = "expired"


class FilingType(Enum):
    TAX_RETURN = "tax_return"
    FINANCIAL_STATEMENT = "financial_statement"
    ANNUAL_REPORT = "annual_report"
    CAPITAL_ADJUSTMENT = "capital_adjustment"
    AUDIT_REPORT = "audit_report"
    AML_REPORT = "aml_report"
    OTHER = "other"


# ============================================================================
# Exceptions
# ============================================================================
class FilingTrackerError(Exception):
    pass


class FilingNotFoundError(FilingTrackerError):
    pass


class InvalidStatusTransitionError(FilingTrackerError):
    pass


# ============================================================================
# Data Classes
# ============================================================================
class RegulatoryFiling:
    def __init__(
        self,
        filing_id: UUID,
        filing_type: FilingType,
        regulatory_body: str,
        jurisdiction: str,
        due_date: date,
        title: str,
        description: str = "",
        submitted_date: date | None = None,
        status: FilingStatus = FilingStatus.DRAFT,
        reference_number: str | None = None,
        submitted_by: UUID | None = None,
        acknowledged_date: date | None = None,
        rejection_reason: str | None = None,
        attachments: list[str] | None = None,
    ):
        self.id = filing_id
        self.filing_type = filing_type
        self.regulatory_body = regulatory_body
        self.jurisdiction = jurisdiction
        self.due_date = due_date
        self.title = title
        self.description = description
        self.submitted_date = submitted_date
        self.status = status
        self.reference_number = reference_number
        self.submitted_by = submitted_by
        self.acknowledged_date = acknowledged_date
        self.rejection_reason = rejection_reason
        self.attachments = attachments or []
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.reminder_sent_at: datetime | None = None
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "filing_type": self.filing_type.value,
            "regulatory_body": self.regulatory_body,
            "status": self.status.value,
            "due_date": self.due_date.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def submit(self, submitted_by: UUID, reference_number: str | None = None) -> None:
        if self.status != FilingStatus.DRAFT:
            raise InvalidStatusTransitionError(
                f"Cannot submit filing with status {self.status.value}"
            )
        self.status = FilingStatus.SUBMITTED
        self.submitted_date = date.today()
        self.submitted_by = submitted_by
        if reference_number:
            self.reference_number = reference_number
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Filing {self.id} submitted to {self.regulatory_body}")

    def acknowledge(self, reference_number: str) -> None:
        if self.status not in (FilingStatus.SUBMITTED, FilingStatus.ACKNOWLEDGED):
            raise InvalidStatusTransitionError(
                f"Cannot acknowledge filing with status {self.status.value}"
            )
        self.status = FilingStatus.ACKNOWLEDGED
        self.acknowledged_date = date.today()
        self.reference_number = reference_number or self.reference_number
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Filing {self.id} acknowledged with reference {reference_number}")

    def reject(self, reason: str) -> None:
        if self.status != FilingStatus.SUBMITTED:
            raise InvalidStatusTransitionError(
                f"Cannot reject filing with status {self.status.value}"
            )
        self.status = FilingStatus.REJECTED
        self.rejection_reason = reason
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.warning(f"Filing {self.id} rejected: {reason}")

    def complete(self) -> None:
        if self.status not in (FilingStatus.ACKNOWLEDGED, FilingStatus.SUBMITTED):
            raise InvalidStatusTransitionError(
                f"Cannot complete filing with status {self.status.value}"
            )
        self.status = FilingStatus.COMPLETED
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Filing {self.id} completed")

    def mark_overdue(self) -> None:
        if self.status == FilingStatus.DRAFT and self.due_date < date.today():
            self.status = FilingStatus.EXPIRED
            self.updated_at = datetime.utcnow()
            self._hash = self._compute_hash()

    def add_attachment(self, attachment_url: str) -> None:
        self.attachments.append(attachment_url)
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def is_overdue(self, reference_date: date | None = None) -> bool:
        ref = reference_date or date.today()
        return self.status in (FilingStatus.DRAFT, FilingStatus.SUBMITTED) and self.due_date < ref

    def to_dict(self) -> dict:
        return {
            "filing_id": str(self.id),
            "filing_type": self.filing_type.value,
            "regulatory_body": self.regulatory_body,
            "jurisdiction": self.jurisdiction,
            "due_date": self.due_date.isoformat(),
            "title": self.title,
            "description": self.description,
            "submitted_date": self.submitted_date.isoformat() if self.submitted_date else None,
            "status": self.status.value,
            "reference_number": self.reference_number,
            "submitted_by": str(self.submitted_by) if self.submitted_by else None,
            "acknowledged_date": self.acknowledged_date.isoformat()
            if self.acknowledged_date
            else None,
            "rejection_reason": self.rejection_reason,
            "attachments": self.attachments,
            "hash": self._hash,
        }


# ============================================================================
# RegulatoryFilingTracker Core
# ============================================================================
class RegulatoryFilingTracker:
    """
    Pelacakan filing ke regulator.
    """

    def __init__(self):
        self._filings: dict[UUID, RegulatoryFiling] = {}

    def create_filing(
        self,
        filing_type: FilingType,
        regulatory_body: str,
        jurisdiction: str,
        due_date: date,
        title: str,
        description: str = "",
    ) -> UUID:
        filing_id = uuid4()
        filing = RegulatoryFiling(
            filing_id=filing_id,
            filing_type=filing_type,
            regulatory_body=regulatory_body,
            jurisdiction=jurisdiction,
            due_date=due_date,
            title=title,
            description=description,
        )
        self._filings[filing_id] = filing
        logger.info(f"Filing created: {filing_id} - {title}")
        return filing_id

    def get_filing(self, filing_id: UUID) -> RegulatoryFiling | None:
        return self._filings.get(filing_id)

    def submit_filing(
        self, filing_id: UUID, submitted_by: UUID, reference_number: str | None = None
    ) -> bool:
        filing = self.get_filing(filing_id)
        if not filing:
            return False
        filing.submit(submitted_by, reference_number)
        return True

    def acknowledge_filing(self, filing_id: UUID, reference_number: str) -> bool:
        filing = self.get_filing(filing_id)
        if not filing:
            return False
        filing.acknowledge(reference_number)
        return True

    def reject_filing(self, filing_id: UUID, reason: str) -> bool:
        filing = self.get_filing(filing_id)
        if not filing:
            return False
        filing.reject(reason)
        return True

    def complete_filing(self, filing_id: UUID) -> bool:
        filing = self.get_filing(filing_id)
        if not filing:
            return False
        filing.complete()
        return True

    def add_attachment(self, filing_id: UUID, attachment_url: str) -> bool:
        filing = self.get_filing(filing_id)
        if not filing:
            return False
        filing.add_attachment(attachment_url)
        return True

    def get_filings_by_status(self, status: FilingStatus) -> list[RegulatoryFiling]:
        return [f for f in self._filings.values() if f.status == status]

    def get_filings_by_regulatory_body(self, regulatory_body: str) -> list[RegulatoryFiling]:
        return [f for f in self._filings.values() if f.regulatory_body == regulatory_body]

    def get_filings_by_jurisdiction(self, jurisdiction: str) -> list[RegulatoryFiling]:
        return [f for f in self._filings.values() if f.jurisdiction == jurisdiction]

    def get_overdue_filings(self, as_of: date | None = None) -> list[RegulatoryFiling]:
        as_of = as_of or date.today()
        overdue = []
        for f in self._filings.values():
            if f.is_overdue(as_of):
                f.mark_overdue()
                overdue.append(f)
        return overdue

    def get_upcoming_filings(self, days_ahead: int = 30) -> list[RegulatoryFiling]:
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        return [
            f
            for f in self._filings.values()
            if f.status == FilingStatus.DRAFT and today <= f.due_date <= cutoff
        ]

    def send_reminders(self, days_ahead: int = 7, dry_run: bool = True) -> list[dict]:
        upcoming = self.get_upcoming_filings(days_ahead)
        reminders = []
        for f in upcoming:
            days_left = (f.due_date - date.today()).days
            reminder = {
                "filing_id": str(f.id),
                "title": f.title,
                "regulatory_body": f.regulatory_body,
                "due_date": f.due_date.isoformat(),
                "days_left": days_left,
            }
            if not dry_run:
                f.reminder_sent_at = datetime.utcnow()
                f._hash = f._compute_hash()
                logger.info(f"Reminder sent for filing {f.id}")
            reminders.append(reminder)
        return reminders

    def generate_report(self) -> dict:
        total = len(self._filings)
        by_status = {s.value: len(self.get_filings_by_status(s)) for s in FilingStatus}
        by_jurisdiction = {}
        for f in self._filings.values():
            by_jurisdiction[f.jurisdiction] = by_jurisdiction.get(f.jurisdiction, 0) + 1
        return {
            "total_filings": total,
            "by_status": by_status,
            "by_jurisdiction": by_jurisdiction,
            "overdue_count": len(self.get_overdue_filings()),
            "upcoming_count": len(self.get_upcoming_filings(30)),
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "filings": [f.to_dict() for f in self._filings.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    tracker = RegulatoryFilingTracker()
    filing_id = tracker.create_filing(
        filing_type=FilingType.TAX_RETURN,
        regulatory_body="DJP",
        jurisdiction="ID",
        due_date=date.today() + timedelta(days=10),
        title="SPT Masa PPN Maret 2026",
        description="Laporan PPN bulan Maret",
    )
    tracker.submit_filing(filing_id, submitted_by=uuid4(), reference_number="REF123")
    tracker.acknowledge_filing(filing_id, "ACK456")
    print(tracker.generate_report())
    tracker.export_to_json("regulatory_filings.json")
