#!/usr/bin/env python3
"""
Module: ethics_committee_decision_log.py
Layer: Compliance / Ethics

Responsibility:
    Log keputusan komite etik, termasuk notulen rapat, voting anggota, tindak lanjut,
    dan dokumentasi keputusan. Mendukung pembuatan keputusan baru, pencarian berdasarkan
    kasus, eskalasi, dan laporan aktivitas komite etik.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, json, logging

Audit:
    Setiap keputusan dicatat dengan hash integrity dan timestamp.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class DecisionType(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    INVESTIGATE = "investigate"
    DISMISS = "dismiss"
    ESCALATE = "escalate"


class VotingResult(Enum):
    UNANIMOUS = "unanimous"
    MAJORITY = "majority"
    TIE = "tie"
    INVALID = "invalid"


class DecisionStatus(Enum):
    DRAFT = "draft"
    FINAL = "final"
    SUPERSEDED = "superseded"
    IMPLEMENTED = "implemented"
    APPEALED = "appealed"


# ============================================================================
# Data Classes
# ============================================================================
class EthicsCommitteeDecision:
    """
    Keputusan komite etik untuk suatu kasus.
    """

    def __init__(
        self,
        decision_id: UUID,
        case_id: UUID,
        meeting_date: datetime,
        chairperson: str,
        members_present: list[str],
        summary: str,
        decision: DecisionType,
        vote_count: dict[str, int],  # {"approve": 5, "reject": 1, "abstain": 0}
        action_items: list[str],
        minutes_url: str | None = None,
        status: DecisionStatus = DecisionStatus.FINAL,
        appeal_deadline: datetime | None = None,
        parent_decision_id: UUID | None = None,
    ):
        self.id = decision_id
        self.case_id = case_id
        self.meeting_date = meeting_date
        self.chairperson = chairperson
        self.members_present = members_present
        self.summary = summary
        self.decision = decision
        self.vote_count = vote_count
        self.action_items = action_items
        self.minutes_url = minutes_url
        self.status = status
        self.appeal_deadline = appeal_deadline
        self.parent_decision_id = parent_decision_id
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.implementation_notes: list[str] = []
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "meeting_date": self.meeting_date.isoformat(),
            "decision": self.decision.value,
            "vote_count": self.vote_count,
            "status": self.status.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_implementation_note(self, note: str, added_by: str) -> None:
        """Tambahkan catatan implementasi tindak lanjut."""
        timestamp = datetime.utcnow().isoformat()
        self.implementation_notes.append(f"[{timestamp}] {added_by}: {note}")
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def mark_implemented(self) -> None:
        """Tandai keputusan sudah diimplementasikan."""
        self.status = DecisionStatus.IMPLEMENTED
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def supersede(self, new_decision_id: UUID) -> None:
        """Keputusan digantikan oleh keputusan lain (appeal atau revisi)."""
        self.status = DecisionStatus.SUPERSEDED
        self.parent_decision_id = new_decision_id
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def is_appeal_possible(self, as_of: datetime | None = None) -> bool:
        """Cek apakah masih bisa diajukan banding (belum lewat deadline)."""
        ref = as_of or datetime.utcnow()
        if self.appeal_deadline and ref > self.appeal_deadline:
            return False
        return self.status == DecisionStatus.FINAL

    def to_dict(self) -> dict:
        return {
            "decision_id": str(self.id),
            "case_id": str(self.case_id),
            "meeting_date": self.meeting_date.isoformat(),
            "chairperson": self.chairperson,
            "members_present": self.members_present,
            "summary": self.summary,
            "decision": self.decision.value,
            "vote_count": self.vote_count,
            "action_items": self.action_items,
            "minutes_url": self.minutes_url,
            "status": self.status.value,
            "implementation_notes": self.implementation_notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "hash": self._hash,
        }


# ============================================================================
# EthicsCommitteeDecisionLog Core
# ============================================================================
class EthicsCommitteeDecisionLog:
    """
    Log keputusan komite etik.
    """

    def __init__(self) -> None:  # FIX: tambahkan anotasi tipe
        self._decisions: dict[UUID, EthicsCommitteeDecision] = {}
        self._case_index: dict[UUID, list[UUID]] = {}
        self._appeal_index: dict[UUID, UUID] = {}  # original_decision_id -> appeal_decision_id

    def add_decision(self, decision: EthicsCommitteeDecision) -> UUID:
        self._decisions[decision.id] = decision
        if decision.case_id not in self._case_index:
            self._case_index[decision.case_id] = []
        self._case_index[decision.case_id].append(decision.id)
        if decision.parent_decision_id:
            self._appeal_index[decision.parent_decision_id] = decision.id
        logger.info(f"Decision {decision.id} added for case {decision.case_id}")
        return decision.id

    def get_decision(self, decision_id: UUID) -> EthicsCommitteeDecision | None:
        return self._decisions.get(decision_id)

    def get_decisions_by_case(self, case_id: UUID) -> list[EthicsCommitteeDecision]:
        dec_ids = self._case_index.get(case_id, [])
        return [self._decisions[did] for did in dec_ids if did in self._decisions]

    def get_latest_decision_by_case(self, case_id: UUID) -> EthicsCommitteeDecision | None:
        decisions = self.get_decisions_by_case(case_id)
        if not decisions:
            return None
        return max(decisions, key=lambda d: d.meeting_date)

    def get_appeal_of(self, decision_id: UUID) -> EthicsCommitteeDecision | None:
        appeal_id = self._appeal_index.get(decision_id)
        if appeal_id:
            return self.get_decision(appeal_id)
        return None

    def get_all_decisions(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        decision_type: DecisionType | None = None,
        status: DecisionStatus | None = None,
    ) -> list[EthicsCommitteeDecision]:
        result = list(self._decisions.values())
        if from_date:
            result = [d for d in result if d.meeting_date.date() >= from_date]
        if to_date:
            result = [d for d in result if d.meeting_date.date() <= to_date]
        if decision_type:
            result = [d for d in result if d.decision == decision_type]
        if status:
            result = [d for d in result if d.status == status]
        return result

    def get_pending_implementations(self) -> list[EthicsCommitteeDecision]:
        return [
            d
            for d in self._decisions.values()
            if d.status == DecisionStatus.FINAL and d.decision != DecisionType.DISMISS
        ]

    def generate_summary(self) -> dict:
        total = len(self._decisions)
        by_decision = {
            dt.value: sum(1 for d in self._decisions.values() if d.decision == dt)
            for dt in DecisionType
        }
        by_status = {
            st.value: sum(1 for d in self._decisions.values() if d.status == st)
            for st in DecisionStatus
        }
        unique_cases = len(self._case_index)
        return {
            "total_decisions": total,
            "by_decision_type": by_decision,
            "by_status": by_status,
            "unique_cases_handled": unique_cases,
            "pending_implementations": len(self.get_pending_implementations()),
        }

    def to_json(self, file_path: str) -> None:
        data = {
            "summary": self.generate_summary(),
            "decisions": [d.to_dict() for d in self._decisions.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    log = EthicsCommitteeDecisionLog()
    case_id = uuid4()

    # Decision 1
    decision1 = EthicsCommitteeDecision(
        decision_id=uuid4(),
        case_id=case_id,
        meeting_date=datetime(2026, 5, 15, 14, 0),
        chairperson="Dr. Ethics",
        members_present=["Member A", "Member B", "Member C"],
        summary="Whistleblower complaint about expense fraud",
        decision=DecisionType.INVESTIGATE,
        vote_count={"approve": 5, "reject": 0, "abstain": 0},
        action_items=["Assign internal audit", "Interview employees"],
        minutes_url="s3://ethics/minutes_001.pdf",
        appeal_deadline=datetime(2026, 6, 15, 0, 0, 0),
    )
    log.add_decision(decision1)

    # Decision 2 (appeal/supersede)
    decision2 = EthicsCommitteeDecision(
        decision_id=uuid4(),
        case_id=case_id,
        meeting_date=datetime(2026, 6, 10, 14, 0),
        chairperson="Dr. Ethics",
        members_present=["Member A", "Member B", "Member C", "Member D"],
        summary="Appeal hearing: fraud case - found not guilty",
        decision=DecisionType.DISMISS,
        vote_count={"approve": 4, "reject": 1, "abstain": 0},
        action_items=["Notify whistleblower", "Close case"],
        minutes_url="s3://ethics/minutes_002.pdf",
        parent_decision_id=decision1.id,
    )
    log.add_decision(decision2)
    decision1.supersede(decision2.id)

    # Implementation note
    decision2.add_implementation_note("Whistleblower notified", "Ethics Officer")
    decision2.mark_implemented()

    # FIX: cek None sebelum mengakses atribut
    latest = log.get_latest_decision_by_case(case_id)
    if latest:
        print(f"Latest decision for case: {latest.decision.value}")
    else:
        print("No decision found for case")
    print(log.generate_summary())
    log.to_json("ethics_decisions.json")
    print("Exported to ethics_decisions.json")
