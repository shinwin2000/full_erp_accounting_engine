#!/usr/bin/env python3
"""
Module: binding_precedence_resolver.py
Layer: Compliance / Legal

Responsibility:
    Menyelesaikan konflik antara dua aturan hukum berdasarkan preseden mengikat (stare decisis)
    dan hierarki sumber hukum. Mendukung resolusi berdasarkan tingkat hierarki, tanggal efektif,
    yurisdiksi, dan otoritas pengadilan (court hierarchy). Juga menyediakan history resolusi,
    audit trail, dan export hasil.

Dependencies:
    - datetime, typing, hashlib, json, logging, uuid
    - dari modul ini: authority_hierarchy (LegalSource, AuthorityHierarchy)

Audit:
    Setiap resolusi konflik dicatat dengan hash integrity, timestamp, dan alasan.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from .authority_hierarchy import AuthorityHierarchy, LegalSource, LegalSourceStatus, LegalSourceType
from .legal_exceptions import LegalError

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class PrecedenceRule(Enum):
    HIERARCHY = "hierarchy"  # Lex superior (higher authority wins)
    TEMPORAL = "temporal"  # Lex posterior (newer wins, if equal hierarchy)
    SPECIALITY = "speciality"  # Lex specialis (more specific wins)
    JURISDICTION = "jurisdiction"  # Domestic over foreign unless treaty


class ResolutionReason(Enum):
    HIERARCHY_WINS = "higher_hierarchy_wins"
    NEWER_WINS = "newer_enactment_wins"
    MORE_SPECIFIC_WINS = "more_specific_wins"
    DOMESTIC_WINS = "domestic_over_international"
    TIE_BREAKER = "tie_broken_by_rule_order"


# ============================================================================
# Data Classes
# ============================================================================
class PrecedenceResolution:
    """Hasil resolusi konflik antar sumber hukum."""

    def __init__(
        self,
        resolution_id: UUID,
        source_a: LegalSource,
        source_b: LegalSource,
        winner: LegalSource,
        reason: ResolutionReason,
        applied_rules: list[PrecedenceRule],
        resolver_id: str,
        resolved_at: datetime | None = None,
    ):
        self.id = resolution_id
        self.source_a = source_a
        self.source_b = source_b
        self.winner = winner
        self.reason = reason
        self.applied_rules = applied_rules
        self.resolver_id = resolver_id
        self.resolved_at = resolved_at or datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "source_a": self.source_a.citation,
            "source_b": self.source_b.citation,
            "winner": self.winner.citation,
            "reason": self.reason.value,
            "applied_rules": [r.value for r in self.applied_rules],
            "resolved_at": self.resolved_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "resolution_id": str(self.id),
            "source_a": {
                "citation": self.source_a.citation,
                "title": self.source_a.title,
                "type": self.source_a.source_type.name,
                "effective_date": self.source_a.effective_date,
            },
            "source_b": {
                "citation": self.source_b.citation,
                "title": self.source_b.title,
                "type": self.source_b.source_type.name,
                "effective_date": self.source_b.effective_date,
            },
            "winner": {
                "citation": self.winner.citation,
                "title": self.winner.title,
            },
            "reason": self.reason.value,
            "applied_rules": [r.value for r in self.applied_rules],
            "resolver_id": self.resolver_id,
            "resolved_at": self.resolved_at.isoformat(),
            "hash": self._hash,
        }


# ============================================================================
# BindingPrecedenceResolver Core
# ============================================================================
class BindingPrecedenceResolver:
    """
    Resolver konflik antar sumber hukum berdasarkan hierarki dan aturan preseden.
    """

    def __init__(self, authority_hierarchy: AuthorityHierarchy):
        self._hierarchy = authority_hierarchy
        self._resolutions: list[PrecedenceResolution] = []
        self._rule_order: list[PrecedenceRule] = [
            PrecedenceRule.HIERARCHY,
            PrecedenceRule.JURISDICTION,
            PrecedenceRule.SPECIALITY,
            PrecedenceRule.TEMPORAL,
        ]

    def set_rule_order(self, rules: list[PrecedenceRule]) -> None:
        """Menentukan urutan prioritas aturan resolusi."""
        self._rule_order = rules

    def resolve(
        self, source_a: LegalSource, source_b: LegalSource, resolver_id: str = "system"
    ) -> PrecedenceResolution:
        """
        Menyelesaikan konflik antara dua sumber hukum.
        Mengembalikan sumber yang menang beserta alasan.
        """
        # Validasi: kedua sumber harus aktif (belum disupersede)
        if source_a.status != LegalSourceStatus.ACTIVE or source_a.is_superseded:
            raise LegalError(f"Source {source_a.citation} is not active")
        if source_b.status != LegalSourceStatus.ACTIVE or source_b.is_superseded:
            raise LegalError(f"Source {source_b.citation} is not active")

        winner = None
        reason = None
        applied_rules = []

        for rule in self._rule_order:
            if rule == PrecedenceRule.HIERARCHY:
                if self._hierarchy.is_higher_than(source_a, source_b):
                    winner = source_a
                    reason = ResolutionReason.HIERARCHY_WINS
                    applied_rules.append(rule)
                    break
                elif self._hierarchy.is_higher_than(source_b, source_a):
                    winner = source_b
                    reason = ResolutionReason.HIERARCHY_WINS
                    applied_rules.append(rule)
                    break
                # else equal hierarchy, lanjut ke rule berikutnya

            elif rule == PrecedenceRule.TEMPORAL:
                # Yang lebih baru (effective date) menang
                if source_a.effective_date > source_b.effective_date:
                    winner = source_a
                    reason = ResolutionReason.NEWER_WINS
                    applied_rules.append(rule)
                    break
                elif source_b.effective_date > source_a.effective_date:
                    winner = source_b
                    reason = ResolutionReason.NEWER_WINS
                    applied_rules.append(rule)
                    break

            elif rule == PrecedenceRule.SPECIALITY:
                # Sumber yang lebih spesifik (judul lebih panjang atau memiliki cakupan khusus)
                spec_a = self._calculate_specificity(source_a)
                spec_b = self._calculate_specificity(source_b)
                if spec_a > spec_b:
                    winner = source_a
                    reason = ResolutionReason.MORE_SPECIFIC_WINS
                    applied_rules.append(rule)
                    break
                elif spec_b > spec_a:
                    winner = source_b
                    reason = ResolutionReason.MORE_SPECIFIC_WINS
                    applied_rules.append(rule)
                    break

            elif rule == PrecedenceRule.JURISDICTION:
                # Sumber domestik (yurisdiksi sama dengan konteks) menang atas asing
                context_jur = self._hierarchy.jurisdiction
                if source_a.jurisdiction == context_jur and source_b.jurisdiction != context_jur:
                    winner = source_a
                    reason = ResolutionReason.DOMESTIC_WINS
                    applied_rules.append(rule)
                    break
                elif source_b.jurisdiction == context_jur and source_a.jurisdiction != context_jur:
                    winner = source_b
                    reason = ResolutionReason.DOMESTIC_WINS
                    applied_rules.append(rule)
                    break

        # Jika masih belum ada pemenang, gunakan tie-breaker: pilih berdasarkan ID (deterministik)
        if winner is None:
            winner = source_a if str(source_a.id) > str(source_b.id) else source_b
            reason = ResolutionReason.TIE_BREAKER
            applied_rules = [*self._rule_order, PrecedenceRule.TEMPORAL]  # fallback

        resolution = PrecedenceResolution(
            resolution_id=uuid4(),
            source_a=source_a,
            source_b=source_b,
            winner=winner,
            reason=reason,
            applied_rules=applied_rules,
            resolver_id=resolver_id,
        )
        self._resolutions.append(resolution)
        logger.info(
            f"Resolution: {source_a.citation} vs {source_b.citation} -> winner: {winner.citation} ({reason.value})"
        )
        return resolution

    def _calculate_specificity(self, source: LegalSource) -> int:
        """
        Menghitung tingkat kekhususan sumber hukum berdasarkan panjang judul,
        ada tidaknya detail, dan tingkat hierarki (semakin rendah angka hierarki semakin umum).
        """
        score = len(source.title) + len(source.description)
        # Sumber dengan hierarki lebih rendah (lebih rinci) dianggap lebih spesifik
        score += (100 - source.source_type.value) * 10
        return score

    def resolve_conflict(
        self, sources: list[LegalSource], resolver_id: str = "system"
    ) -> LegalSource | None:
        """
        Menyelesaikan konflik dari daftar sumber (lebih dari dua).
        Menggunakan pairwise elimination.
        """
        if not sources:
            return None
        if len(sources) == 1:
            return sources[0]
        winner = sources[0]
        for s in sources[1:]:
            resolution = self.resolve(winner, s, resolver_id)
            winner = resolution.winner
        return winner

    def get_resolution_history(self, limit: int = 100) -> list[PrecedenceResolution]:
        return self._resolutions[-limit:]

    def get_resolutions_by_resolver(self, resolver_id: str) -> list[PrecedenceResolution]:
        return [r for r in self._resolutions if r.resolver_id == resolver_id]

    def generate_report(self) -> dict:
        total = len(self._resolutions)
        by_reason = {
            reason.value: sum(1 for r in self._resolutions if r.reason == reason)
            for reason in ResolutionReason
        }
        return {
            "total_resolutions": total,
            "by_reason": by_reason,
            "rule_order": [r.value for r in self._rule_order],
            "last_resolution": self._resolutions[-1].to_dict() if self._resolutions else None,
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "resolutions": [r.to_dict() for r in self._resolutions],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    from .authority_hierarchy import AuthorityHierarchy, LegalSource, LegalSourceType

    # Setup
    hierarchy = AuthorityHierarchy()
    source_uu = LegalSource(
        source_id=uuid4(),
        source_type=LegalSourceType.ACT_OF_PARLIAMENT,
        title="Undang-Undang Ketenagakerjaan",
        citation="UU No. 13/2003",
        effective_date="2003-03-25",
        issuing_body="DPR",
        jurisdiction="ID",
    )
    source_pp = LegalSource(
        source_id=uuid4(),
        source_type=LegalSourceType.GOVERNMENT_REGULATION,
        title="Peraturan Pemerintah tentang Pekerja Asing",
        citation="PP No. 34/2021",
        effective_date="2021-12-15",
        issuing_body="Pemerintah",
        jurisdiction="ID",
    )
    hierarchy.add_source(source_uu)
    hierarchy.add_source(source_pp)

    resolver = BindingPrecedenceResolver(hierarchy)
    resolution = resolver.resolve(source_uu, source_pp, resolver_id="legal_dept")
    print(f"Winner: {resolution.winner.citation} - Reason: {resolution.reason.value}")
    resolver.export_to_json("binding_precedence.json")
