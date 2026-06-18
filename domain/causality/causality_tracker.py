#!/usr/bin/env python3
"""
Module: causality_tracker.py
Layer: Domain / Causality
Responsibility: Melacak hubungan kausal antar transaksi, menyediakan analisis dampak,
               deteksi siklus, path finding, dan statistik graf.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================


class RelationshipType(Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    CONTRIBUTES = "contributes"
    MITIGATES = "mitigates"
    CORRELATES = "correlates"


class TraversalDirection(Enum):
    FORWARD = "forward"
    BACKWARD = "backward"
    BOTH = "both"


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class CausalRelationship:
    """Hubungan kausal antara dua entitas."""

    relationship_id: UUID
    source_id: UUID
    target_id: UUID
    relationship_type: RelationshipType
    strength: float  # 0-1
    discovered_at: datetime
    discovered_by: str
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": str(self.relationship_id),
            "source_id": str(self.source_id),
            "target_id": str(self.target_id),
            "relationship_type": self.relationship_type.value,
            "strength": self.strength,
            "discovered_at": self.discovered_at.isoformat(),
            "discovered_by": self.discovered_by,
            "metadata": self.metadata,
            "version": self.version,
        }

    def compute_hash(self) -> str:
        content = {
            "relationship_id": str(self.relationship_id),
            "source_id": str(self.source_id),
            "target_id": str(self.target_id),
            "relationship_type": self.relationship_type.value,
            "strength": self.strength,
            "discovered_at": self.discovered_at.isoformat(),
            "discovered_by": self.discovered_by,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()


@dataclass
class PathResult:
    """Hasil pencarian path antara dua entitas."""

    path: list[UUID]
    length: int
    relationships: list[CausalRelationship]
    total_strength: float


@dataclass
class ImpactAnalysis:
    """Hasil analisis dampak suatu entitas."""

    entity_id: UUID
    downstream_count: int
    upstream_count: int
    max_downstream_depth: int
    max_upstream_depth: int
    affected_types: dict[str, int]
    has_cycles: bool
    direct_impact_entities: list[UUID]
    root_causes: list[UUID]


# ============================================================================
# CAUSALITY TRACKER
# ============================================================================


class CausalityTracker:
    """
    Tracker untuk hubungan kausal antar transaksi.
    Menyediakan graf terarah dengan kemampuan analisis dampak dan deteksi siklus.
    """

    _instance: CausalityTracker | None = None

    def __new__(cls) -> CausalityTracker:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._relationships: dict[tuple[UUID, UUID], CausalRelationship] = {}
        self._graph: dict[UUID, set[UUID]] = defaultdict(set)  # forward adjacency
        self._reverse_graph: dict[UUID, set[UUID]] = defaultdict(set)  # backward adjacency
        self._entity_metadata: dict[UUID, dict[str, Any]] = {}
        self._audit_log: list[dict[str, Any]] = []

    # ========================================================================
    # Audit
    # ========================================================================
    def _log_audit(self, action: str, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"CAUSALITY TRACKER AUDIT: {action}")

    # ========================================================================
    # Relationship Management
    # ========================================================================
    def add_relationship(
        self,
        source_id: UUID,
        target_id: UUID,
        relationship_type: RelationshipType,
        discovered_by: str,
        strength: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> CausalRelationship:
        """
        Menambahkan hubungan kausal antara dua entitas.
        """
        if source_id == target_id:
            raise ValueError("Cannot add relationship from an entity to itself")
        if not 0 <= strength <= 1:
            raise ValueError(f"Strength must be between 0 and 1, got {strength}")

        key = (source_id, target_id)
        if key in self._relationships:
            logger.warning(
                f"Relationship already exists between {source_id} and {target_id}, updating..."
            )
            old = self._relationships[key]
            # Remove from graphs
            self._graph[source_id].discard(target_id)
            self._reverse_graph[target_id].discard(source_id)

        relationship = CausalRelationship(
            relationship_id=uuid4(),
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
            strength=strength,
            discovered_at=datetime.now(UTC),
            discovered_by=discovered_by,
            metadata=metadata or {},
            version=1,
        )

        self._relationships[key] = relationship
        self._graph[source_id].add(target_id)
        self._reverse_graph[target_id].add(source_id)

        self._log_audit(
            "ADD_RELATIONSHIP",
            {
                "source": str(source_id),
                "target": str(target_id),
                "type": relationship_type.value,
                "strength": strength,
            },
        )
        return relationship

    def add_batch_relationships(
        self,
        relationships: list[tuple[UUID, UUID, RelationshipType, float, str]],
        discovered_by: str,
    ) -> list[CausalRelationship]:
        """
        Menambahkan banyak hubungan sekaligus.
        """
        results = []
        for src, tgt, rel_type, strength, _ in relationships:
            rel = self.add_relationship(src, tgt, rel_type, discovered_by, strength)
            results.append(rel)
        return results

    def get_relationship(self, source_id: UUID, target_id: UUID) -> CausalRelationship | None:
        return self._relationships.get((source_id, target_id))

    def get_all_relationships(self) -> list[CausalRelationship]:
        return list(self._relationships.values())

    def get_relationships_from(self, source_id: UUID) -> list[CausalRelationship]:
        return [rel for (s, _), rel in self._relationships.items() if s == source_id]

    def get_relationships_to(self, target_id: UUID) -> list[CausalRelationship]:
        return [rel for (_, t), rel in self._relationships.items() if t == target_id]

    def update_relationship_strength(
        self,
        source_id: UUID,
        target_id: UUID,
        new_strength: float,
        updated_by: str,
    ) -> CausalRelationship | None:
        key = (source_id, target_id)
        rel = self._relationships.get(key)
        if not rel:
            return None
        if not 0 <= new_strength <= 1:
            raise ValueError(f"Strength must be between 0 and 1, got {new_strength}")
        updated = CausalRelationship(
            relationship_id=rel.relationship_id,
            source_id=rel.source_id,
            target_id=rel.target_id,
            relationship_type=rel.relationship_type,
            strength=new_strength,
            discovered_at=rel.discovered_at,
            discovered_by=rel.discovered_by,
            metadata=rel.metadata.copy(),
            version=rel.version + 1,
        )
        self._relationships[key] = updated
        self._log_audit(
            "UPDATE_STRENGTH",
            {
                "source": str(source_id),
                "target": str(target_id),
                "old": rel.strength,
                "new": new_strength,
                "updated_by": updated_by,
            },
        )
        return updated

    def delete_relationship(self, source_id: UUID, target_id: UUID, permanent: bool = True) -> bool:
        key = (source_id, target_id)
        rel = self._relationships.pop(key, None)
        if not rel:
            return False
        self._graph[source_id].discard(target_id)
        self._reverse_graph[target_id].discard(source_id)
        self._log_audit(
            "DELETE_RELATIONSHIP",
            {
                "source": str(source_id),
                "target": str(target_id),
                "permanent": permanent,
            },
        )
        return True

    def clear_all_relationships(self) -> int:
        count = len(self._relationships)
        self._relationships.clear()
        self._graph.clear()
        self._reverse_graph.clear()
        self._log_audit("CLEAR_ALL", {"count": count})
        return count

    # ========================================================================
    # Entity Metadata
    # ========================================================================
    def set_entity_metadata(self, entity_id: UUID, metadata: dict[str, Any]) -> None:
        if entity_id not in self._entity_metadata:
            self._entity_metadata[entity_id] = {}
        self._entity_metadata[entity_id].update(metadata)

    def get_entity_metadata(self, entity_id: UUID) -> dict[str, Any]:
        return self._entity_metadata.get(entity_id, {}).copy()

    def delete_entity_metadata(self, entity_id: UUID) -> bool:
        if entity_id in self._entity_metadata:
            del self._entity_metadata[entity_id]
            return True
        return False

    # ========================================================================
    # Graph Traversal
    # ========================================================================
    def get_downstream(
        self,
        entity_id: UUID,
        max_depth: int = 5,
        relationship_filter: list[RelationshipType] | None = None,
    ) -> list[tuple[UUID, int, list[CausalRelationship]]]:
        """
        Mendapatkan semua entitas yang dipengaruhi (downstream) dengan path info.
        """
        result = []
        visited = set()
        queue = deque([(entity_id, 0, [])])  # (node, depth, path_relationships)
        while queue:
            current, depth, path = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor in self._graph.get(current, set()):
                if neighbor in visited:
                    continue
                rel = self._relationships.get((current, neighbor))
                if relationship_filter and rel and rel.relationship_type not in relationship_filter:
                    continue
                visited.add(neighbor)
                new_path = path + ([rel] if rel else [])
                result.append((neighbor, depth + 1, new_path))
                queue.append((neighbor, depth + 1, new_path))
        return result

    def get_upstream(
        self,
        entity_id: UUID,
        max_depth: int = 5,
        relationship_filter: list[RelationshipType] | None = None,
    ) -> list[tuple[UUID, int, list[CausalRelationship]]]:
        """
        Mendapatkan semua entitas yang mempengaruhi (upstream) dengan path info.
        """
        result = []
        visited = set()
        queue = deque([(entity_id, 0, [])])
        while queue:
            current, depth, path = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor in self._reverse_graph.get(current, set()):
                if neighbor in visited:
                    continue
                rel = self._relationships.get((neighbor, current))
                if relationship_filter and rel and rel.relationship_type not in relationship_filter:
                    continue
                visited.add(neighbor)
                new_path = path + ([rel] if rel else [])
                result.append((neighbor, depth + 1, new_path))
                queue.append((neighbor, depth + 1, new_path))
        return result

    def find_path(
        self,
        source_id: UUID,
        target_id: UUID,
        max_depth: int = 10,
    ) -> PathResult | None:
        """
        Mencari jalur kausal antara source dan target (BFS).
        """
        if source_id == target_id:
            return PathResult(path=[source_id], length=0, relationships=[], total_strength=1.0)

        visited = set()
        queue = deque([(source_id, [source_id], [])])  # (node, path, relationships)
        while queue:
            current, path, rel_path = queue.popleft()
            if len(path) > max_depth:
                continue
            visited.add(current)
            for neighbor in self._graph.get(current, set()):
                if neighbor in visited:
                    continue
                rel = self._relationships.get((current, neighbor))
                new_path = path + [neighbor]
                new_rel_path = rel_path + ([rel] if rel else [])
                if neighbor == target_id:
                    total_strength = 1.0
                    for r in new_rel_path:
                        total_strength *= r.strength
                    return PathResult(
                        path=new_path,
                        length=len(new_path) - 1,
                        relationships=new_rel_path,
                        total_strength=total_strength,
                    )
                queue.append((neighbor, new_path, new_rel_path))
        return None

    def find_all_paths(
        self,
        source_id: UUID,
        target_id: UUID,
        max_depth: int = 10,
        max_paths: int = 10,
    ) -> list[PathResult]:
        """
        Mencari semua jalur kausal antara source dan target (DFS terbatas).
        """
        paths = []
        stack = [(source_id, [source_id], [])]

        while stack and len(paths) < max_paths:
            current, path, rel_path = stack.pop()
            if len(path) > max_depth:
                continue
            for neighbor in self._graph.get(current, set()):
                if neighbor in path:  # avoid cycles
                    continue
                rel = self._relationships.get((current, neighbor))
                new_path = path + [neighbor]
                new_rel_path = rel_path + ([rel] if rel else [])
                if neighbor == target_id:
                    total_strength = 1.0
                    for r in new_rel_path:
                        total_strength *= r.strength
                    paths.append(
                        PathResult(
                            path=new_path,
                            length=len(new_path) - 1,
                            relationships=new_rel_path,
                            total_strength=total_strength,
                        )
                    )
                else:
                    stack.append((neighbor, new_path, new_rel_path))
        return paths

    def get_all_reachable(
        self,
        start_id: UUID,
        direction: TraversalDirection = TraversalDirection.FORWARD,
        max_depth: int = 10,
    ) -> list[UUID]:
        """
        Mendapatkan semua entitas yang dapat dijangkau dari start_id.
        """
        visited = set()
        queue = deque([(start_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            if direction in (TraversalDirection.FORWARD, TraversalDirection.BOTH):
                for neighbor in self._graph.get(current, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, depth + 1))
            if direction in (TraversalDirection.BACKWARD, TraversalDirection.BOTH):
                for neighbor in self._reverse_graph.get(current, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, depth + 1))
        return list(visited)

    # ========================================================================
    # Cycle Detection
    # ========================================================================
    def detect_cycles(self) -> list[list[UUID]]:
        """
        Mendeteksi semua siklus dalam graf kausalitas.
        """
        cycles = []
        visited = set()
        rec_stack = set()
        parent = {}

        def dfs(node_id: UUID, path: list[UUID]) -> None:
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            for neighbor in self._graph.get(node_id, set()):
                if neighbor not in visited:
                    parent[neighbor] = node_id
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Cycle detected
                    cycle_start_idx = path.index(neighbor)
                    cycle = path[cycle_start_idx:] + [neighbor]
                    cycles.append(cycle)
            rec_stack.remove(node_id)
            path.pop()

        for node in list(self._graph.keys()):
            if node not in visited:
                dfs(node, [])
        return cycles

    def has_cycle(self) -> bool:
        return len(self.detect_cycles()) > 0

    def find_cycles_involving(self, entity_id: UUID) -> list[list[UUID]]:
        all_cycles = self.detect_cycles()
        return [cycle for cycle in all_cycles if entity_id in cycle]

    # ========================================================================
    # Impact Analysis
    # ========================================================================
    def analyze_impact(self, entity_id: UUID, max_depth: int = 5) -> ImpactAnalysis:
        """
        Menganalisis dampak dari suatu entitas.
        """
        downstream = self.get_downstream(entity_id, max_depth)
        upstream = self.get_upstream(entity_id, max_depth)

        affected_types: dict[str, int] = defaultdict(int)
        for target_id, depth, _ in downstream:
            ent_type = self._entity_metadata.get(target_id, {}).get("type", "unknown")
            affected_types[ent_type] += 1

        direct_impact = [uid for uid, depth, _ in downstream if depth == 1]

        root_causes = []
        for uid, depth, _ in upstream:
            # Check if this node has no upstream
            if not self._reverse_graph.get(uid, set()):
                root_causes.append(uid)

        cycles = self.detect_cycles()
        has_cycles = any(entity_id in cycle for cycle in cycles)

        max_down_depth = max([d for _, d, _ in downstream], default=0)
        max_up_depth = max([d for _, d, _ in upstream], default=0)

        return ImpactAnalysis(
            entity_id=entity_id,
            downstream_count=len(downstream),
            upstream_count=len(upstream),
            max_downstream_depth=max_down_depth,
            max_upstream_depth=max_up_depth,
            affected_types=dict(affected_types),
            has_cycles=has_cycles,
            direct_impact_entities=direct_impact,
            root_causes=root_causes,
        )

    # ========================================================================
    # Graph Statistics
    # ========================================================================
    def get_statistics(self) -> dict[str, Any]:
        total_relationships = len(self._relationships)
        total_nodes = len(self._graph.keys()) | len(self._reverse_graph.keys())
        by_type: dict[str, int] = defaultdict(int)
        for rel in self._relationships.values():
            by_type[rel.relationship_type.value] += 1

        avg_strength = (
            sum(r.strength for r in self._relationships.values()) / total_relationships
            if total_relationships
            else 0
        )
        cycles = self.detect_cycles()
        out_degrees = [len(self._graph.get(n, set())) for n in self._graph]
        avg_out_degree = sum(out_degrees) / len(self._graph) if self._graph else 0

        return {
            "total_relationships": total_relationships,
            "total_nodes": total_nodes,
            "by_relationship_type": dict(by_type),
            "average_strength": avg_strength,
            "cycles_detected": len(cycles),
            "average_out_degree": avg_out_degree,
            "max_out_degree": max(out_degrees) if out_degrees else 0,
            "audit_log_size": len(self._audit_log),
        }

    def get_subgraph(self, root_id: UUID, max_depth: int = 3) -> dict[UUID, list[UUID]]:
        """
        Mendapatkan subgraph adjacency list dari root_id.
        """
        subgraph = {}
        visited = set()
        queue = deque([(root_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            if current not in subgraph:
                subgraph[current] = []
            for neighbor in self._graph.get(current, set()):
                subgraph[current].append(neighbor)
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
            for neighbor in self._reverse_graph.get(current, set()):
                if neighbor not in subgraph[current]:
                    subgraph[current].append(neighbor)
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return subgraph

    # ========================================================================
    # Export / Import
    # ========================================================================
    def export_to_json(self) -> str:
        data = {
            "exported_at": datetime.now(UTC).isoformat(),
            "relationships": [rel.to_dict() for rel in self._relationships.values()],
            "entity_metadata": {str(k): v for k, v in self._entity_metadata.items()},
        }
        return json.dumps(data, indent=2)

    def import_from_json(self, json_str: str, overwrite: bool = False) -> int:
        data = json.loads(json_str)
        count = 0
        if overwrite:
            self.clear_all_relationships()
            self._entity_metadata.clear()
        for rel_dict in data.get("relationships", []):
            source_id = UUID(rel_dict["source_id"])
            target_id = UUID(rel_dict["target_id"])
            rel_type = RelationshipType(rel_dict["relationship_type"])
            strength = rel_dict["strength"]
            discovered_by = rel_dict["discovered_by"]
            metadata = rel_dict.get("metadata", {})
            if not overwrite and (source_id, target_id) in self._relationships:
                continue
            self.add_relationship(source_id, target_id, rel_type, discovered_by, strength, metadata)
            count += 1
        for eid_str, meta in data.get("entity_metadata", {}).items():
            self.set_entity_metadata(UUID(eid_str), meta)
        self._log_audit("IMPORT", {"count": count, "overwrite": overwrite})
        return count

    # ========================================================================
    # Reset
    # ========================================================================
    def reset(self) -> None:
        self._relationships.clear()
        self._graph.clear()
        self._reverse_graph.clear()
        self._entity_metadata.clear()
        self._audit_log.clear()
        self._log_audit("RESET", {})


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_causality_tracker_instance: CausalityTracker | None = None


def get_causality_tracker() -> CausalityTracker:
    global _causality_tracker_instance
    if _causality_tracker_instance is None:
        _causality_tracker_instance = CausalityTracker()
    return _causality_tracker_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CausalRelationship",
    "CausalityTracker",
    "ImpactAnalysis",
    "PathResult",
    "RelationshipType",
    "TraversalDirection",
    "get_causality_tracker",
]
