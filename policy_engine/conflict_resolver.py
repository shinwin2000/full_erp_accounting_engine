#!/usr/bin/env python3
"""
Module: conflict_resolver.py
Layer: 7 - Policy Engine

Responsibility:
    Resolusi konflik antar kebijakan (policy sets) dan aturan (rules).
    Mendeteksi konflik (duplicate condition, contradictory action, circular dependency,
    priority ambiguity, version conflict). Menyelesaikan konflik menggunakan berbagai
    strategi: highest priority, latest version, most specific, manual override,
    merge actions, atau custom resolver. Mendukung auditing resolusi.

Dependencies:
    - datetime, typing, uuid, hashlib, json, logging, enum, dataclasses

Audit: Setiap konflik yang terdeteksi dan resolusi dicatat.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .loader_yaml import PolicyRule, PolicySet
from .policy_exceptions import PolicyConflictError

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class ConflictType(Enum):
    """Jenis konflik antar kebijakan/aturan."""

    DUPLICATE_CONDITION = "duplicate_condition"  # Kondisi sama, aksi berbeda
    CONTRADICTORY_ACTION = "contradictory_action"  # Aksi saling bertentangan
    CIRCULAR_DEPENDENCY = "circular_dependency"  # Ketergantungan melingkar
    PRIORITY_AMBIGUITY = "priority_ambiguity"  # Prioritas tidak jelas
    VERSION_CONFLICT = "version_conflict"  # Versi tidak kompatibel
    JURISDICTION_OVERLAP = "jurisdiction_overlap"  # Yurisdiksi tumpang tindih
    TEMPORAL_OVERLAP = "temporal_overlap"  # Periode efektif tumpang tindih


class ResolutionStrategy(Enum):
    """Strategi resolusi konflik."""

    HIGHEST_PRIORITY = "highest_priority"  # Ambil prioritas tertinggi
    LATEST_VERSION = "latest_version"  # Ambil versi terbaru
    MOST_SPECIFIC = "most_specific"  # Ambil yang paling spesifik (domain/jurisdiction)
    MANUAL_OVERRIDE = "manual_override"  # Memerlukan override manual
    MERGE_ACTIONS = "merge_actions"  # Gabungkan aksi
    HIGHEST_SEVERITY = "highest_severity"  # Ambil dengan severity tertinggi (untuk konflik aksi)
    NEWEST_EFFECTIVE = "newest_effective"  # Ambil yang effective_from terbaru
    CUSTOM = "custom"  # Resolver kustom


class ConflictSeverity(Enum):
    """Tingkat keparahan konflik."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class Conflict:
    """Representasi konflik antar kebijakan/aturan."""

    conflict_id: str
    conflict_type: ConflictType
    severity: ConflictSeverity
    description: str
    policy_ids: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False
    resolution_strategy: ResolutionStrategy | None = None
    resolution_result: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None

    def to_dict(self) -> dict:
        return {
            "conflict_id": self.conflict_id,
            "type": self.conflict_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "policy_ids": self.policy_ids,
            "rule_ids": self.rule_ids,
            "details": self.details,
            "detected_at": self.detected_at.isoformat(),
            "resolved": self.resolved,
            "resolution_strategy": self.resolution_strategy.value
            if self.resolution_strategy
            else None,
            "resolution_result": self.resolution_result,
        }

    def resolve(
        self, strategy: ResolutionStrategy, result: str, resolved_by: str = "system"
    ) -> None:
        self.resolved = True
        self.resolution_strategy = strategy
        self.resolution_result = result
        self.resolved_at = datetime.now(UTC)
        self.resolved_by = resolved_by


# ============================================================================
# Conflict Detector
# ============================================================================
class ConflictDetector:
    """Mendeteksi berbagai jenis konflik dalam kumpulan kebijakan."""

    @staticmethod
    def detect_duplicate_conditions(policies: list[PolicySet]) -> list[Conflict]:
        """
        Mendeteksi konflik: kondisi yang sama tetapi aksi berbeda.
        """
        conflicts = []
        # Map: (domain, condition) -> list of (policy_id, rule_id, action)
        condition_map: dict[tuple[str, str], list[tuple[str, str, str]]] = {}

        for policy in policies:
            for rule in policy.rules:
                if not rule.enabled:
                    continue
                key = (policy.domain, rule.condition)
                if key not in condition_map:
                    condition_map[key] = []
                condition_map[key].append((policy.id, rule.id, rule.action))

        for (domain, condition), items in condition_map.items():
            if len(items) > 1:
                actions = {a for _, _, a in items}
                if len(actions) > 1:
                    conflicts.append(
                        Conflict(
                            conflict_id=f"dup_cond_{domain}_{hash(condition)}",
                            conflict_type=ConflictType.DUPLICATE_CONDITION,
                            severity=ConflictSeverity.HIGH,
                            description=f"Duplicate condition '{condition}' in domain '{domain}' with different actions: {actions}",
                            policy_ids=list({p for p, _, _ in items}),
                            rule_ids=[r for _, r, _ in items],
                            details={"condition": condition, "actions": list(actions)},
                        )
                    )
        return conflicts

    @staticmethod
    def detect_priority_ambiguity(policies: list[PolicySet]) -> list[Conflict]:
        """
        Mendeteksi ambiguitas prioritas: multiple policies dengan prioritas sama dalam domain yang sama.
        """
        conflicts = []
        domain_priority_map: dict[
            tuple[str, int], list[str]
        ] = {}  # (domain, priority) -> [policy_ids]

        for policy in policies:
            priority = policy.metadata.get("priority", 0)
            key = (policy.domain, priority)
            if key not in domain_priority_map:
                domain_priority_map[key] = []
            domain_priority_map[key].append(policy.id)

        for (domain, priority), policy_ids in domain_priority_map.items():
            if len(policy_ids) > 1:
                conflicts.append(
                    Conflict(
                        conflict_id=f"pri_ambig_{domain}_{priority}",
                        conflict_type=ConflictType.PRIORITY_AMBIGUITY,
                        severity=ConflictSeverity.MEDIUM,
                        description=f"Multiple policies in domain '{domain}' with same priority {priority}",
                        policy_ids=policy_ids,
                        details={"domain": domain, "priority": priority, "count": len(policy_ids)},
                    )
                )
        return conflicts

    @staticmethod
    def detect_temporal_overlap(policies: list[PolicySet]) -> list[Conflict]:
        """
        Mendeteksi temporal overlap: dua kebijakan dalam domain yang sama dan periode efektif tumpang tindih.
        """
        conflicts = []
        domain_policies: dict[str, list[PolicySet]] = {}

        for policy in policies:
            domain_policies.setdefault(policy.domain, []).append(policy)

        for domain, domain_plist in domain_policies.items():
            # Urutkan berdasarkan effective_from
            sorted_policies = sorted(domain_plist, key=lambda p: p.effective_from)
            for i in range(len(sorted_policies)):
                for j in range(i + 1, len(sorted_policies)):
                    p1 = sorted_policies[i]
                    p2 = sorted_policies[j]
                    # Cek overlap
                    if p1.effective_from <= p2.effective_from and (
                        p1.effective_to is None or p2.effective_from <= p1.effective_to
                    ):
                        conflicts.append(
                            Conflict(
                                conflict_id=f"temp_overlap_{domain}_{p1.id}_{p2.id}",
                                conflict_type=ConflictType.TEMPORAL_OVERLAP,
                                severity=ConflictSeverity.MEDIUM,
                                description=f"Temporal overlap between policies {p1.id} and {p2.id} in domain '{domain}'",
                                policy_ids=[p1.id, p2.id],
                                details={
                                    "p1_effective_from": p1.effective_from.isoformat(),
                                    "p1_effective_to": p1.effective_to.isoformat()
                                    if p1.effective_to
                                    else None,
                                    "p2_effective_from": p2.effective_from.isoformat(),
                                    "p2_effective_to": p2.effective_to.isoformat()
                                    if p2.effective_to
                                    else None,
                                },
                            )
                        )
        return conflicts

    @staticmethod
    def detect_jurisdiction_overlap(policies: list[PolicySet]) -> list[Conflict]:
        """
        Mendeteksi overlapping jurisdiksi: policies yang sama dengan jurisdiksi berbeda tapi cakupan tumpang tindih.
        """
        conflicts = []
        # Group by domain
        domain_map: dict[str, list[PolicySet]] = {}
        for policy in policies:
            domain_map.setdefault(policy.domain, []).append(policy)

        for domain, domain_policies in domain_map.items():
            # Cek jika ada policy dengan jurisdiksi parent-child
            for i in range(len(domain_policies)):
                for j in range(i + 1, len(domain_policies)):
                    p1 = domain_policies[i]
                    p2 = domain_policies[j]
                    # Gabungkan kondisi: overlap dan jurisdiksi berbeda
                    if (
                        p1.jurisdiction.startswith(p2.jurisdiction) or p2.jurisdiction.startswith(p1.jurisdiction)
                    ) and p1.jurisdiction != p2.jurisdiction:
                        conflicts.append(
                            Conflict(
                                conflict_id=f"jur_overlap_{domain}_{p1.id}_{p2.id}",
                                conflict_type=ConflictType.JURISDICTION_OVERLAP,
                                severity=ConflictSeverity.LOW,
                                description=f"Jurisdiction overlap between {p1.jurisdiction} and {p2.jurisdiction} in domain '{domain}'",
                                policy_ids=[p1.id, p2.id],
                                details={
                                    "jurisdiction_1": p1.jurisdiction,
                                    "jurisdiction_2": p2.jurisdiction,
                                },
                            )
                        )
        return conflicts

    @staticmethod
    def detect_all(policies: list[PolicySet]) -> list[Conflict]:
        """Deteksi semua jenis konflik."""
        all_conflicts = []
        all_conflicts.extend(ConflictDetector.detect_duplicate_conditions(policies))
        all_conflicts.extend(ConflictDetector.detect_priority_ambiguity(policies))
        all_conflicts.extend(ConflictDetector.detect_temporal_overlap(policies))
        all_conflicts.extend(ConflictDetector.detect_jurisdiction_overlap(policies))
        return all_conflicts


# ============================================================================
# Conflict Resolver
# ============================================================================
class ConflictResolver:
    """
    Resolver konflik kebijakan dengan berbagai strategi.

    Business context: Menyelesaikan konflik antar kebijakan dengan
    berbagai strategi (prioritas, versi terbaru, manual override).
    """

    _instance: ConflictResolver | None = None
    _initialized: bool = False  # FIX: tambahkan anotasi tipe untuk mypy

    def __new__(cls) -> ConflictResolver:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._conflicts: list[Conflict] = []
        self._custom_resolvers: dict[str, Callable[[Conflict], str]] = {}
        self._resolved_history: list[Conflict] = []

    # ------------------------------------------------------------------------
    # Conflict Detection
    # ------------------------------------------------------------------------
    def detect_conflicts(self, policies: list[PolicySet]) -> list[Conflict]:
        """Mendeteksi semua konflik dalam kumpulan kebijakan."""
        conflicts = ConflictDetector.detect_all(policies)
        self._conflicts.extend(conflicts)
        for c in conflicts:
            logger.warning(f"Conflict detected: {c.conflict_id} - {c.description}")
        return conflicts

    def get_unresolved_conflicts(self) -> list[Conflict]:
        return [c for c in self._conflicts if not c.resolved]

    def get_all_conflicts(self) -> list[Conflict]:
        return self._conflicts

    def clear_conflicts(self) -> None:
        self._conflicts.clear()

    # ------------------------------------------------------------------------
    # Conflict Resolution
    # ------------------------------------------------------------------------
    def resolve_conflict(
        self,
        conflict: Conflict,
        strategy: ResolutionStrategy,
        policies_map: dict[str, PolicySet] | None = None,
        manual_policy_id: str | None = None,
        resolver_id: str = "system",
        custom_resolver: Callable[[Conflict], str] | None = None,
    ) -> str | None:
        """
        Menyelesaikan konflik dengan strategi tertentu.
        Returns: policy_id yang dipilih (jika applicable) atau None.
        """
        if conflict.resolved:
            logger.warning(f"Conflict {conflict.conflict_id} already resolved")
            return None

        chosen_policy = None

        if strategy == ResolutionStrategy.HIGHEST_PRIORITY:
            chosen_policy = self._resolve_highest_priority(conflict, policies_map)
        elif strategy == ResolutionStrategy.LATEST_VERSION:
            chosen_policy = self._resolve_latest_version(conflict, policies_map)
        elif strategy == ResolutionStrategy.MOST_SPECIFIC:
            chosen_policy = self._resolve_most_specific(conflict, policies_map)
        elif strategy == ResolutionStrategy.NEWEST_EFFECTIVE:
            chosen_policy = self._resolve_newest_effective(conflict, policies_map)
        elif strategy == ResolutionStrategy.MANUAL_OVERRIDE:
            chosen_policy = manual_policy_id
            if not chosen_policy:
                raise PolicyConflictError(
                    policy_id_1=conflict.policy_ids[0] if conflict.policy_ids else "",
                    policy_id_2=conflict.policy_ids[1] if len(conflict.policy_ids) > 1 else "",
                    conflict_description="Manual override required but no policy specified",
                )
        elif strategy == ResolutionStrategy.MERGE_ACTIONS:
            chosen_policy = self._resolve_merge_actions(conflict, policies_map)
        elif strategy == ResolutionStrategy.CUSTOM:
            if custom_resolver:
                chosen_policy = custom_resolver(conflict)
            else:
                chosen_policy = self._custom_resolvers.get(
                    conflict.conflict_type.value, lambda c: None
                )(conflict)

        conflict.resolve(
            strategy, str(chosen_policy) if chosen_policy else "No resolution", resolver_id
        )
        self._resolved_history.append(conflict)

        logger.info(
            f"Conflict {conflict.conflict_id} resolved with strategy {strategy.value}, result: {chosen_policy}"
        )
        return chosen_policy

    def _resolve_highest_priority(
        self,
        conflict: Conflict,
        policies_map: dict[str, PolicySet] | None = None,
    ) -> str | None:
        """Pilih kebijakan dengan prioritas tertinggi."""
        if not conflict.policy_ids:
            return None
        if not policies_map:
            # Jika tidak ada peta kebijakan, asumsikan urutan pertama adalah yang tertinggi
            return conflict.policy_ids[0]

        best_policy = None
        best_priority = -1
        for pid in conflict.policy_ids:
            policy = policies_map.get(pid)
            if policy:
                priority = policy.metadata.get("priority", 0)
                if priority > best_priority:
                    best_priority = priority
                    best_policy = pid
        return best_policy

    def _resolve_latest_version(
        self,
        conflict: Conflict,
        policies_map: dict[str, PolicySet] | None = None,
    ) -> str | None:
        """Pilih kebijakan dengan versi terbaru."""
        if not conflict.policy_ids:
            return None
        if not policies_map:
            return conflict.policy_ids[0]

        best_policy = None
        best_version = -1
        for pid in conflict.policy_ids:
            policy = policies_map.get(pid)
            if policy and policy.version > best_version:
                best_version = policy.version
                best_policy = pid
        return best_policy

    def _resolve_most_specific(
        self,
        conflict: Conflict,
        policies_map: dict[str, PolicySet] | None = None,
    ) -> str | None:
        """Pilih kebijakan yang paling spesifik (jurisdiksi lebih panjang/domain lebih spesifik)."""
        if not conflict.policy_ids:
            return None
        if not policies_map:
            return conflict.policy_ids[0]

        def specificity(pid: str) -> int:
            policy = policies_map.get(pid)
            if not policy:
                return 0
            # Jurisdiksi dengan lebih banyak segmen dianggap lebih spesifik
            jur_parts = len(policy.jurisdiction.split("-"))
            # Domain juga kontribusi
            domain_parts = len(policy.domain.split("."))
            return jur_parts * 10 + domain_parts

        return max(conflict.policy_ids, key=specificity)

    def _resolve_newest_effective(
        self,
        conflict: Conflict,
        policies_map: dict[str, PolicySet] | None = None,
    ) -> str | None:
        """Pilih kebijakan dengan effective_from terbaru."""
        if not conflict.policy_ids:
            return None
        if not policies_map:
            return conflict.policy_ids[0]

        best_policy = None
        best_date = None
        for pid in conflict.policy_ids:
            policy = policies_map.get(pid)
            if policy and (best_date is None or policy.effective_from > best_date):
                best_date = policy.effective_from
                best_policy = pid
        return best_policy

    def _resolve_merge_actions(
        self,
        conflict: Conflict,
        policies_map: dict[str, PolicySet] | None = None,
    ) -> str:
        """
        Merge actions: gabungkan aksi dari aturan yang berkonflik.
        Returns string "MERGED" atau detail merge.
        """
        # Implementasi sederhana: log dan return "MERGED"
        logger.info(f"Merging actions for conflict {conflict.conflict_id}")
        return "MERGED"

    # ------------------------------------------------------------------------
    # Custom Resolver Registration
    # ------------------------------------------------------------------------
    def register_custom_resolver(
        self, conflict_type: str, resolver: Callable[[Conflict], str]
    ) -> None:
        """Mendaftarkan resolver kustom untuk tipe konflik tertentu."""
        self._custom_resolvers[conflict_type] = resolver
        logger.info(f"Registered custom resolver for conflict type: {conflict_type}")

    # ------------------------------------------------------------------------
    # Bulk Resolution
    # ------------------------------------------------------------------------
    def resolve_all(
        self,
        strategy: ResolutionStrategy,
        policies_map: dict[str, PolicySet] | None = None,
        resolver_id: str = "system",
    ) -> list[tuple[Conflict, str | None]]:
        """Resolve semua unresolved conflicts dengan strategi yang sama."""
        results = []
        for conflict in self.get_unresolved_conflicts():
            result = self.resolve_conflict(
                conflict, strategy, policies_map, resolver_id=resolver_id
            )
            results.append((conflict, result))
        return results

    # ------------------------------------------------------------------------
    # Conflict Audit
    # ------------------------------------------------------------------------
    def get_resolution_history(self) -> list[Conflict]:
        return self._resolved_history

    def get_conflicts_by_type(self, conflict_type: ConflictType) -> list[Conflict]:
        return [c for c in self._conflicts if c.conflict_type == conflict_type]

    # ------------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        total = len(self._conflicts)
        unresolved = len(self.get_unresolved_conflicts())
        resolved = total - unresolved
        by_type = {ct.value: len(self.get_conflicts_by_type(ct)) for ct in ConflictType}
        return {
            "total_conflicts": total,
            "resolved": resolved,
            "unresolved": unresolved,
            "by_type": by_type,
            "recent_resolutions": [c.to_dict() for c in self._resolved_history[-10:]],
        }

    def export_to_json(self, file_path: str) -> None:
        import json

        data = {
            "report": self.generate_report(),
            "conflicts": [c.to_dict() for c in self._conflicts],
            "history": [c.to_dict() for c in self._resolved_history],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ========================================================================
    # TEST COMPATIBILITY METHODS
    # ========================================================================
    def resolve(self, policies: list[dict[str, Any]], method: str = "priority") -> dict[str, Any]:
        """
        Simplified resolve method for test compatibility.
        policies: list of dicts with keys: id, priority, rule, specificity
        method: "priority" (higher priority wins) or "specificity" (higher specificity wins)
        Returns the winning policy dict.
        """
        if not policies:
            return {}

        if method == "priority":
            # Higher priority wins
            return max(policies, key=lambda p: p.get("priority", 0))
        elif method == "specificity":
            # Higher specificity wins
            return max(policies, key=lambda p: p.get("specificity", 0))
        else:
            # Default: first policy
            return policies[0]


# ============================================================================
# Singleton Accessor
# ============================================================================
_conflict_resolver_instance: ConflictResolver | None = None


def get_conflict_resolver() -> ConflictResolver:
    """Mendapatkan instance singleton ConflictResolver."""
    global _conflict_resolver_instance
    if _conflict_resolver_instance is None:
        _conflict_resolver_instance = ConflictResolver()
    return _conflict_resolver_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    from datetime import datetime

    from .loader_yaml import PolicyRule, PolicySet

    # Contoh policies untuk testing
    policy1 = PolicySet(
        id="policy_1",
        name="Policy 1",
        domain="tax",
        version=1,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
        jurisdiction="ID",
        metadata={"priority": 10},
        rules=[
            PolicyRule(
                id="rule1", name="Rule 1", condition="amount > 1000", action="approve", priority=5
            )
        ],
    )
    policy2 = PolicySet(
        id="policy_2",
        name="Policy 2",
        domain="tax",
        version=2,
        effective_from=datetime(2025, 6, 1, tzinfo=UTC),
        jurisdiction="ID-JKT",
        metadata={"priority": 20},
        rules=[
            PolicyRule(
                id="rule2", name="Rule 2", condition="amount > 1000", action="reject", priority=5
            )
        ],
    )

    resolver = get_conflict_resolver()
    conflicts = resolver.detect_conflicts([policy1, policy2])
    print(f"Detected {len(conflicts)} conflicts")

    # Resolve
    policies_map = {policy1.id: policy1, policy2.id: policy2}
    for c in conflicts:
        result = resolver.resolve_conflict(c, ResolutionStrategy.HIGHEST_PRIORITY, policies_map)
        print(f"Conflict {c.conflict_id} resolved: {result}")

    report = resolver.generate_report()
    print(json.dumps(report, indent=2))
    resolver.export_to_json("conflict_resolver_report.json")
