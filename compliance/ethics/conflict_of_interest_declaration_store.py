#!/usr/bin/env python3
"""
Module: conflict_of_interest_declaration_store.py
Layer: Compliance / Ethics

Responsibility:
    Penyimpanan dan manajemen deklarasi konflik kepentingan dari karyawan, manajemen,
    dan dewan komisaris. Mendukung tracking status, notifikasi ke komite etik,
    resolusi konflik, dan audit trail.

Dependencies:
    - datetime, uuid, enum, typing, hashlib, logging

Audit:
    Setiap deklarasi, perubahan status, dan resolusi dicatat dengan hash.
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
class ConflictStatus(Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    UNDER_REVIEW = "under_review"


class RelationshipType(Enum):
    PERSONAL = "personal"
    FAMILY = "family"
    BUSINESS = "business"
    FINANCIAL = "financial"
    EMPLOYMENT = "employment"


class ConflictSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# Exceptions
# ============================================================================
class ConflictOfInterestError(Exception):
    pass


class DeclarationNotFoundError(ConflictOfInterestError):
    pass


# ============================================================================
# Data Classes
# ============================================================================
class ConflictOfInterestDeclaration:
    def __init__(
        self,
        declaration_id: UUID,
        declarant_id: UUID,
        declarant_name: str,
        declarant_role: str,
        relationship_type: RelationshipType,
        related_party: str,
        nature_of_conflict: str,
        financial_impact: str | None = None,
        declaration_date: date | None = None,
        status: ConflictStatus = ConflictStatus.ACTIVE,
        severity: ConflictSeverity = ConflictSeverity.MEDIUM,
        reviewer_notes: str | None = None,
    ):
        self.id = declaration_id
        self.declarant_id = declarant_id
        self.declarant_name = declarant_name
        self.declarant_role = declarant_role
        self.relationship_type = relationship_type
        self.related_party = related_party
        self.nature_of_conflict = nature_of_conflict
        self.financial_impact = financial_impact
        self.declaration_date = declaration_date or date.today()
        self.status = status
        self.severity = severity
        self.reviewer_notes = reviewer_notes
        self.resolution_date: date | None = None
        self.resolution_notes: str | None = None
        self.resolved_by: UUID | None = None
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "declarant_id": str(self.declarant_id),
            "relationship_type": self.relationship_type.value,
            "status": self.status.value,
            "declaration_date": self.declaration_date.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def update_status(self, new_status: ConflictStatus, updated_by: UUID, notes: str = "") -> None:
        old = self.status.value
        self.status = new_status
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()
        logger.info(
            f"Declaration {self.id} status changed from {old} to {new_status.value} by {updated_by}"
        )

    def resolve(self, resolution_notes: str, resolved_by: UUID) -> None:
        self.status = ConflictStatus.RESOLVED
        self.resolution_date = date.today()
        self.resolution_notes = resolution_notes
        self.resolved_by = resolved_by
        self.updated_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "declarant_id": str(self.declarant_id),
            "declarant_name": self.declarant_name,
            "declarant_role": self.declarant_role,
            "relationship_type": self.relationship_type.value,
            "related_party": self.related_party,
            "nature_of_conflict": self.nature_of_conflict,
            "financial_impact": self.financial_impact,
            "declaration_date": self.declaration_date.isoformat(),
            "status": self.status.value,
            "severity": self.severity.value,
            "resolution_date": self.resolution_date.isoformat() if self.resolution_date else None,
            "hash": self._hash,
        }


class ConflictOfInterestDeclarationStore:
    """
    Store untuk deklarasi konflik kepentingan dengan manajemen lifecycle lengkap.
    """

    def __init__(self):
        self._declarations: dict[UUID, ConflictOfInterestDeclaration] = {}
        self._declarant_index: dict[
            UUID, list[UUID]
        ] = {}  # declarant_id -> list of declaration ids

    def add_declaration(
        self,
        declarant_id: UUID,
        declarant_name: str,
        declarant_role: str,
        relationship_type: RelationshipType,
        related_party: str,
        nature_of_conflict: str,
        financial_impact: str | None = None,
        severity: ConflictSeverity = ConflictSeverity.MEDIUM,
    ) -> UUID:
        if declarant_id not in self._declarant_index:
            self._declarant_index[declarant_id] = []
        dec_id = uuid4()
        declaration = ConflictOfInterestDeclaration(
            declaration_id=dec_id,
            declarant_id=declarant_id,
            declarant_name=declarant_name,
            declarant_role=declarant_role,
            relationship_type=relationship_type,
            related_party=related_party,
            nature_of_conflict=nature_of_conflict,
            financial_impact=financial_impact,
            severity=severity,
        )
        self._declarations[dec_id] = declaration
        self._declarant_index[declarant_id].append(dec_id)
        logger.info(f"Conflict declaration {dec_id} added for {declarant_name}")
        return dec_id

    def get_declaration(self, declaration_id: UUID) -> ConflictOfInterestDeclaration | None:
        return self._declarations.get(declaration_id)

    def get_declarations_by_declarant(
        self, declarant_id: UUID
    ) -> list[ConflictOfInterestDeclaration]:
        dec_ids = self._declarant_index.get(declarant_id, [])
        return [self._declarations[did] for did in dec_ids if did in self._declarations]

    def get_active_declarations(
        self, declarant_id: UUID | None = None
    ) -> list[ConflictOfInterestDeclaration]:
        result = [d for d in self._declarations.values() if d.status == ConflictStatus.ACTIVE]
        if declarant_id:
            result = [d for d in result if d.declarant_id == declarant_id]
        return result

    def get_overdue_review(self, days_threshold: int = 30) -> list[ConflictOfInterestDeclaration]:
        cutoff = date.today() - timedelta(days=days_threshold)
        return [
            d
            for d in self._declarations.values()
            if d.declaration_date < cutoff and d.status == ConflictStatus.ACTIVE
        ]

    def update_status(
        self, declaration_id: UUID, new_status: ConflictStatus, updated_by: UUID, notes: str = ""
    ) -> bool:
        dec = self._declarations.get(declaration_id)
        if not dec:
            return False
        dec.update_status(new_status, updated_by, notes)
        return True

    def resolve_declaration(
        self, declaration_id: UUID, resolution_notes: str, resolved_by: UUID
    ) -> bool:
        dec = self._declarations.get(declaration_id)
        if not dec:
            return False
        dec.resolve(resolution_notes, resolved_by)
        return True

    def has_active_conflict(self, declarant_id: UUID) -> bool:
        return any(
            d.declarant_id == declarant_id and d.status == ConflictStatus.ACTIVE
            for d in self._declarations.values()
        )

    def generate_report(self) -> dict:
        total = len(self._declarations)
        active = len(self.get_active_declarations())
        resolved = len(
            [d for d in self._declarations.values() if d.status == ConflictStatus.RESOLVED]
        )
        by_severity = {
            "critical": len(
                [d for d in self._declarations.values() if d.severity == ConflictSeverity.CRITICAL]
            ),
            "high": len(
                [d for d in self._declarations.values() if d.severity == ConflictSeverity.HIGH]
            ),
            "medium": len(
                [d for d in self._declarations.values() if d.severity == ConflictSeverity.MEDIUM]
            ),
            "low": len(
                [d for d in self._declarations.values() if d.severity == ConflictSeverity.LOW]
            ),
        }
        return {
            "total_declarations": total,
            "active": active,
            "resolved": resolved,
            "by_severity": by_severity,
            "overdue_review": len(self.get_overdue_review()),
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "declarations": [d.to_dict() for d in self._declarations.values()],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    store = ConflictOfInterestDeclarationStore()
    user_id = uuid4()
    dec_id = store.add_declaration(
        declarant_id=user_id,
        declarant_name="Budi Santoso",
        declarant_role="CFO",
        relationship_type=RelationshipType.FAMILY,
        related_party="PT Keluarga Sejahtera",
        nature_of_conflict="Memiliki saham di vendor yang bekerja sama dengan perusahaan",
        financial_impact="Potensi transaksi > 1 Milyar",
        severity=ConflictSeverity.HIGH,
    )
    print(f"Added declaration: {dec_id}")
    print("Active conflicts:", store.has_active_conflict(user_id))
    store.resolve_declaration(dec_id, "Vendor diganti", resolved_by=uuid4())
    print("Report:", store.generate_report())
    store.export_to_json("conflict_declarations.json")
