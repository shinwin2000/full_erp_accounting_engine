#!/usr/bin/env python3
"""
Module: professional_judgment_template.py
Layer: Compliance / Ethics

Responsibility:
    Template untuk mendokumentasikan judgment profesional akuntan sesuai standar
    (PSAK, IFRS, GAAP). Mendukung pengisian judgment, alternatif yang dipertimbangkan,
    justifikasi, referensi standar, dan pengesahan (approval). Template dapat
    diekspor ke JSON dan memiliki audit trail hash.

Dependencies:
    - datetime, uuid, typing, hashlib, json, logging

Audit:
    Setiap judgment yang dibuat dicatat dengan timestamp dan hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================
class ProfessionalJudgmentTemplate:
    """
    Template untuk mendokumentasikan judgment profesional akuntan.
    """

    def __init__(
        self,
        judgment_id: UUID,
        title: str,
        accounting_standard: str,  # e.g., "PSAK 72", "IFRS 15", "US GAAP ASC 606"
        issue_description: str,
        alternatives_considered: list[str],
        selected_alternative: str,
        rationale: str,
        preparer_id: UUID,
        preparer_name: str | None = None,
        additional_references: list[str] | None = None,
        impact_estimation: str | None = None,
    ):
        self.id = judgment_id
        self.title = title
        self.standard = accounting_standard
        self.issue_description = issue_description
        self.alternatives = alternatives_considered
        self.selected = selected_alternative
        self.rationale = rationale
        self.preparer_id = preparer_id
        self.preparer_name = preparer_name
        self.additional_references = additional_references or []
        self.impact_estimation = impact_estimation
        self.created_at = datetime.utcnow()
        self.approved_by: UUID | None = None
        self.approved_at: datetime | None = None
        self.revision: int = 1
        self.revision_history: list[dict] = []
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "title": self.title,
            "standard": self.standard,
            "selected": self.selected,
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def approve(self, approver_id: UUID) -> None:
        """Tandai judgment sebagai disetujui."""
        self.approved_by = approver_id
        self.approved_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(f"Judgment {self.id} approved by {approver_id}")

    def revise(
        self,
        new_rationale: str | None = None,
        new_selected: str | None = None,
        revision_note: str = "",
    ) -> None:
        """Buat revisi judgment."""
        old_hash = self._hash
        self.revision_history.append(
            {
                "revision": self.revision,
                "rationale": self.rationale,
                "selected": self.selected,
                "hash": old_hash,
                "revised_at": datetime.utcnow().isoformat(),
                "note": revision_note,
            }
        )
        self.revision += 1
        if new_rationale:
            self.rationale = new_rationale
        if new_selected:
            self.selected = new_selected
        self.approved_by = None
        self.approved_at = None
        self._hash = self._compute_hash()
        logger.info(f"Judgment {self.id} revised to version {self.revision}")

    def is_approved(self) -> bool:
        return self.approved_by is not None

    def to_dict(self) -> dict:
        return {
            "judgment_id": str(self.id),
            "title": self.title,
            "accounting_standard": self.standard,
            "issue_description": self.issue_description,
            "alternatives_considered": self.alternatives,
            "selected_alternative": self.selected,
            "rationale": self.rationale,
            "preparer_id": str(self.preparer_id),
            "preparer_name": self.preparer_name,
            "additional_references": self.additional_references,
            "impact_estimation": self.impact_estimation,
            "created_at": self.created_at.isoformat(),
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "revision": self.revision,
            "revision_history": self.revision_history,
            "hash": self._hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProfessionalJudgmentTemplate:
        """Reconstruct from dictionary (for deserialization)."""
        judgment = cls(
            judgment_id=UUID(data["judgment_id"]),
            title=data["title"],
            accounting_standard=data["accounting_standard"],
            issue_description=data["issue_description"],
            alternatives_considered=data["alternatives_considered"],
            selected_alternative=data["selected_alternative"],
            rationale=data["rationale"],
            preparer_id=UUID(data["preparer_id"]),
            preparer_name=data.get("preparer_name"),
            additional_references=data.get("additional_references", []),
            impact_estimation=data.get("impact_estimation"),
        )
        judgment.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("approved_by"):
            judgment.approved_by = UUID(data["approved_by"])
            judgment.approved_at = datetime.fromisoformat(data["approved_at"])
        judgment.revision = data.get("revision", 1)
        judgment.revision_history = data.get("revision_history", [])
        judgment._hash = data.get("hash", judgment._compute_hash())
        return judgment


# ============================================================================
# Judgment Repository (In-memory, for demo)
# ============================================================================
class JudgmentRepository:
    """Simple in-memory repository for professional judgments."""

    def __init__(self):
        self._judgments: dict[UUID, ProfessionalJudgmentTemplate] = {}

    def save(self, judgment: ProfessionalJudgmentTemplate) -> None:
        self._judgments[judgment.id] = judgment

    def get(self, judgment_id: UUID) -> ProfessionalJudgmentTemplate | None:
        return self._judgments.get(judgment_id)

    def list_all(self) -> list[ProfessionalJudgmentTemplate]:
        return list(self._judgments.values())

    def delete(self, judgment_id: UUID) -> bool:
        if judgment_id in self._judgments:
            del self._judgments[judgment_id]
            return True
        return False

    def to_json(self, file_path: str) -> None:
        data = [j.to_dict() for j in self._judgments.values()]
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    # Create a judgment
    judgment = ProfessionalJudgmentTemplate(
        judgment_id=uuid4(),
        title="Lease classification for new warehouse",
        accounting_standard="PSAK 73",
        issue_description="Determine whether the warehouse lease should be classified as operating or finance lease",
        alternatives_considered=["Operating lease", "Finance lease"],
        selected_alternative="Finance lease",
        rationale="The lease term covers major part of economic life and present value of payments substantially all of fair value",
        preparer_id=uuid4(),
        preparer_name="Senior Accountant",
        additional_references=["IFRS 16.B31-B34", "PSAK 73 paragraf 20-25"],
        impact_estimation="Recognition of right-of-use asset IDR 5B and lease liability IDR 5B",
    )
    print("Judgment created:")
    print(json.dumps(judgment.to_dict(), indent=2))

    # Approve
    judgment.approve(approver_id=uuid4())
    print(f"Approved: {judgment.is_approved()}")

    # Revise
    judgment.revise(
        new_rationale="After re-evaluation, the lease term is 75% of economic life, qualifying as finance lease",
        revision_note="Updated rationale based on additional data",
    )
    print(f"After revision - version: {judgment.revision}")

    # Save to file
    repo = JudgmentRepository()
    repo.save(judgment)
    repo.to_json("professional_judgments.json")
    print("Saved to professional_judgments.json")
