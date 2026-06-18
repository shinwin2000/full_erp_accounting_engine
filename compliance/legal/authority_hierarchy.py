#!/usr/bin/env python3
"""
Module: authority_hierarchy.py
Layer: Compliance / Legal

Responsibility:
    Mendefinisikan hierarki sumber hukum (Konstitusi > Undang-Undang > Peraturan Pemerintah > Peraturan Menteri > Keputusan/Edaran).
    Menentukan tingkat kekuatan mengikat suatu sumber hukum, mendukung pencarian berdasarkan yurisdiksi,
    dan manajemen perubahan (amendemen, supersede).

Dependencies:
    - datetime, enum, typing, hashlib, json, logging

Audit:
    Setiap perubahan hierarki (penambahan, penghapusan, supersede) dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class LegalSourceType(IntEnum):
    """Tingkat hierarki sumber hukum (semakin kecil angka semakin tinggi)."""

    CONSTITUTION = 1
    TREATY = 2
    ACT_OF_PARLIAMENT = 3
    GOVERNMENT_REGULATION = 4
    PRESIDENTIAL_REGULATION = 5
    MINISTERIAL_REGULATION = 6
    DIRECTOR_GENERAL_REGULATION = 7
    CIRCULAR_LETTER = 8
    COURT_RULING = 9
    GUIDANCE = 10


class LegalSourceStatus(Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REPEALED = "repealed"
    EXPIRED = "expired"


# ============================================================================
# Data Classes
# ============================================================================
class LegalSource:
    def __init__(
        self,
        source_id: UUID,
        source_type: LegalSourceType,
        title: str,
        citation: str,
        effective_date: str,
        issuing_body: str,
        jurisdiction: str = "ID",
        description: str = "",
        url: str | None = None,
        status: LegalSourceStatus = LegalSourceStatus.ACTIVE,
    ):
        self.id = source_id
        self.source_type = source_type
        self.title = title
        self.citation = citation
        self.effective_date = effective_date
        self.issuing_body = issuing_body
        self.jurisdiction = jurisdiction
        self.description = description
        self.url = url
        self.status = status
        self.is_superseded = False
        self.superseded_by: UUID | None = None
        self.superseded_date: str | None = None
        self.created_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "source_type": self.source_type.value,
            "citation": self.citation,
            "effective_date": self.effective_date,
            "status": self.status.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def get_hierarchy_level(self) -> int:
        return self.source_type.value

    def supersede(self, new_source_id: UUID, date: str) -> None:
        self.is_superseded = True
        self.superseded_by = new_source_id
        self.superseded_date = date
        self.status = LegalSourceStatus.SUPERSEDED
        self.updated_at = datetime.utcnow().isoformat()
        self._hash = self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "source_type": self.source_type.value,
            "title": self.title,
            "citation": self.citation,
            "effective_date": self.effective_date,
            "issuing_body": self.issuing_body,
            "jurisdiction": self.jurisdiction,
            "description": self.description,
            "url": self.url,
            "status": self.status.value,
            "is_superseded": self.is_superseded,
            "superseded_by": str(self.superseded_by) if self.superseded_by else None,
            "superseded_date": self.superseded_date,
            "hash": self._hash,
        }


# ============================================================================
# AuthorityHierarchy Core
# ============================================================================
class AuthorityHierarchy:
    """
    Manager hierarki otoritas hukum.
    Mendukung registrasi sumber hukum, pencarian berdasarkan hierarki,
    resolusi konflik, dan audit trail perubahan.
    """

    def __init__(self, jurisdiction: str = "ID"):
        self.jurisdiction = jurisdiction
        self._sources: dict[UUID, LegalSource] = {}
        self._citation_index: dict[str, UUID] = {}
        self._history: list[dict] = []

    def add_source(self, source: LegalSource) -> UUID:
        if source.id in self._sources:
            raise ValueError(f"Source with id {source.id} already exists")
        self._sources[source.id] = source
        self._citation_index[source.citation] = source.id
        self._record_history("ADD", source.id, source.title)
        logger.info(f"Legal source added: {source.citation} ({source.source_type.name})")
        return source.id

    def get_source(self, source_id: UUID) -> LegalSource | None:
        return self._sources.get(source_id)

    def get_source_by_citation(self, citation: str) -> LegalSource | None:
        sid = self._citation_index.get(citation)
        return self._sources.get(sid) if sid else None

    def get_sources_by_type(self, source_type: LegalSourceType) -> list[LegalSource]:
        return [s for s in self._sources.values() if s.source_type == source_type]

    def get_active_sources(self) -> list[LegalSource]:
        return [
            s
            for s in self._sources.values()
            if s.status == LegalSourceStatus.ACTIVE and not s.is_superseded
        ]

    def get_highest_applicable_source(self, criteria: dict[str, Any]) -> LegalSource | None:
        applicable = [s for s in self.get_active_sources() if self._matches_criteria(s, criteria)]
        if not applicable:
            return None
        return min(applicable, key=lambda s: s.get_hierarchy_level())

    def _matches_criteria(self, source: LegalSource, criteria: dict) -> bool:
        for key, value in criteria.items():
            if key == "jurisdiction" and source.jurisdiction != value:
                return False
            if key == "issuing_body" and source.issuing_body != value:
                return False
            if (
                key == "keyword"
                and value.lower() not in source.title.lower()
                and value.lower() not in source.description.lower()
            ):
                return False
        return True

    def is_higher_than(self, source_a: LegalSource, source_b: LegalSource) -> bool:
        return source_a.get_hierarchy_level() < source_b.get_hierarchy_level()

    def supersede(self, old_source_id: UUID, new_source_id: UUID, date: str) -> bool:
        old = self._sources.get(old_source_id)
        new = self._sources.get(new_source_id)
        if not old or not new:
            return False
        if not self.is_higher_than(new, old):
            raise ValueError("New source must have higher authority (lower hierarchy number)")
        old.supersede(new_source_id, date)
        self._record_history("SUPERSEDE", old_source_id, f"Superseded by {new.citation}")
        return True

    def _record_history(self, action: str, source_id: UUID, details: str) -> None:
        self._history.append(
            {
                "action": action,
                "source_id": str(source_id),
                "details": details,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    def get_hierarchy_tree(self) -> dict:
        """Mengembalikan hierarki dalam bentuk tree."""
        tree = {}
        for source_type in LegalSourceType:
            sources = [s.to_dict() for s in self.get_sources_by_type(source_type)]
            if sources:
                tree[source_type.name] = sources
        return tree

    def export_to_json(self, file_path: str) -> None:
        data = {
            "jurisdiction": self.jurisdiction,
            "sources": [s.to_dict() for s in self._sources.values()],
            "history": self._history,
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    hierarchy = AuthorityHierarchy("ID")
    source1 = LegalSource(
        source_id=uuid4(),
        source_type=LegalSourceType.CONSTITUTION,
        title="Undang-Undang Dasar 1945",
        citation="UUD 1945",
        effective_date="1945-08-18",
        issuing_body="PPKI",
        description="Konstitusi Negara Republik Indonesia",
    )
    hierarchy.add_source(source1)
    print("Hierarchy tree:", hierarchy.get_hierarchy_tree())
    hierarchy.export_to_json("authority_hierarchy.json")
