#!/usr/bin/env python3
"""
Module: causal_node.py
Layer: Domain / Causality
Responsibility: Node dalam graf kausalitas dengan hash chain, validasi,
               manajemen relasi, dan layanan lengkap.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================


class CausalNodeType(Enum):
    """Jenis node dalam rantai kausalitas."""

    INTENT = auto()
    ECONOMIC_EVENT = auto()
    JOURNAL_ENTRY = auto()
    PAYMENT = auto()
    INVOICE = auto()
    ADJUSTMENT = auto()
    REVERSAL = auto()
    CONSOLIDATION = auto()
    EXTERNAL = auto()


class CausalDirection(Enum):
    """Arah hubungan kausal."""

    FORWARD = auto()
    BACKWARD = auto()


# ============================================================================
# CAUSAL NODE
# ============================================================================


@dataclass
class CausalNode:
    """
    Node dalam rantai kausalitas.

    Business context: Mencatat satu langkah dalam rantai kausalitas
    yang menghubungkan berbagai entitas dalam sistem akuntansi.
    Setiap node memiliki hash kriptografis untuk integritas.
    """

    node_id: UUID
    node_type: CausalNodeType
    entity_id: UUID
    entity_type: str
    timestamp: datetime
    created_by: str
    previous_node_id: UUID | None = None
    next_node_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cryptographic_hash: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        elif self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def _validate(self) -> None:
        if not self.entity_type or not isinstance(self.entity_type, str):
            raise ValueError("entity_type must be a non-empty string")
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.previous_node_id == self.node_id:
            raise ValueError("Node cannot point to itself as previous")
        if self.next_node_id == self.node_id:
            raise ValueError("Node cannot point to itself as next")

    def compute_hash(self) -> str:
        """Menghitung hash SHA3-256 dari konten node."""
        content = {
            "node_id": str(self.node_id),
            "node_type": self.node_type.name,
            "entity_id": str(self.entity_id),
            "entity_type": self.entity_type,
            "timestamp": self.timestamp.isoformat(),
            "previous_node_id": str(self.previous_node_id) if self.previous_node_id else None,
            "next_node_id": str(self.next_node_id) if self.next_node_id else None,
            "metadata": self.metadata,
            "version": self.version,
        }
        return hashlib.sha3_256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def link_to_next(self, next_node: CausalNode) -> CausalNode:
        """Menghubungkan node ini ke node berikutnya."""
        if self.next_node_id:
            raise ValueError(f"Node {self.node_id} already has next node {self.next_node_id}")
        if self.node_id == next_node.node_id:
            raise ValueError("Cannot link a node to itself")
        return CausalNode(
            node_id=self.node_id,
            node_type=self.node_type,
            entity_id=self.entity_id,
            entity_type=self.entity_type,
            timestamp=self.timestamp,
            created_by=self.created_by,
            previous_node_id=self.previous_node_id,
            next_node_id=next_node.node_id,
            metadata=self.metadata.copy(),
            cryptographic_hash="",
            version=self.version + 1,
        )

    def unlink_next(self) -> CausalNode:
        """Memutus hubungan ke node berikutnya."""
        if not self.next_node_id:
            return self
        return CausalNode(
            node_id=self.node_id,
            node_type=self.node_type,
            entity_id=self.entity_id,
            entity_type=self.entity_type,
            timestamp=self.timestamp,
            created_by=self.created_by,
            previous_node_id=self.previous_node_id,
            next_node_id=None,
            metadata=self.metadata.copy(),
            cryptographic_hash="",
            version=self.version + 1,
        )

    def update_metadata(self, new_metadata: dict[str, Any]) -> CausalNode:
        """Memperbarui metadata node."""
        merged = self.metadata.copy()
        merged.update(new_metadata)
        return CausalNode(
            node_id=self.node_id,
            node_type=self.node_type,
            entity_id=self.entity_id,
            entity_type=self.entity_type,
            timestamp=self.timestamp,
            created_by=self.created_by,
            previous_node_id=self.previous_node_id,
            next_node_id=self.next_node_id,
            metadata=merged,
            cryptographic_hash="",
            version=self.version + 1,
        )

    def is_root(self) -> bool:
        """Apakah node ini adalah root (tidak memiliki previous node)."""
        return self.previous_node_id is None

    def is_leaf(self) -> bool:
        """Apakah node ini adalah leaf (tidak memiliki next node)."""
        return self.next_node_id is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": str(self.node_id),
            "node_type": self.node_type.name,
            "entity_id": str(self.entity_id),
            "entity_type": self.entity_type,
            "timestamp": self.timestamp.isoformat(),
            "created_by": self.created_by,
            "previous_node_id": str(self.previous_node_id) if self.previous_node_id else None,
            "next_node_id": str(self.next_node_id) if self.next_node_id else None,
            "metadata": self.metadata,
            "cryptographic_hash": self.cryptographic_hash,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalNode:
        return cls(
            node_id=UUID(data["node_id"]),
            node_type=CausalNodeType[data["node_type"]],
            entity_id=UUID(data["entity_id"]),
            entity_type=data["entity_type"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            created_by=data["created_by"],
            previous_node_id=UUID(data["previous_node_id"])
            if data.get("previous_node_id")
            else None,
            next_node_id=UUID(data["next_node_id"]) if data.get("next_node_id") else None,
            metadata=data.get("metadata", {}),
            cryptographic_hash=data.get("cryptographic_hash", ""),
            version=data.get("version", 1),
        )


# ============================================================================
# CAUSAL NODE SERVICE
# ============================================================================


class CausalNodeService:
    """
    Service untuk mengelola causal nodes.
    Menyediakan CRUD, traversal, ekspor/impor, validasi integritas, statistik.
    """

    _instance: CausalNodeService | None = None
    _initialized: bool = False

    def __new__(cls) -> CausalNodeService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._nodes: dict[UUID, CausalNode] = {}
        self._entity_to_node: dict[tuple[str, UUID], UUID] = {}
        self._audit_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------------
    def _log_audit(self, action: str, node_id: UUID, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "node_id": str(node_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"CAUSAL NODE AUDIT: {action} on {node_id}")

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------
    def create_node(
        self,
        node_type: CausalNodeType,
        entity_id: UUID,
        entity_type: str,
        created_by: str,
        previous_node_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CausalNode:
        if previous_node_id and previous_node_id not in self._nodes:
            raise ValueError(f"Previous node {previous_node_id} not found")
        node = CausalNode(
            node_id=uuid4(),
            node_type=node_type,
            entity_id=entity_id,
            entity_type=entity_type,
            timestamp=datetime.now(UTC),
            created_by=created_by,
            previous_node_id=previous_node_id,
            metadata=metadata or {},
        )
        self._nodes[node.node_id] = node
        self._entity_to_node[(entity_type, entity_id)] = node.node_id
        if previous_node_id:
            prev = self._nodes[previous_node_id]
            updated_prev = prev.link_to_next(node)
            self._nodes[previous_node_id] = updated_prev
        self._log_audit(
            "CREATE", node.node_id, {"type": node_type.name, "entity": f"{entity_type}/{entity_id}"}
        )
        return node

    def create_batch(
        self,
        nodes_data: list[dict[str, Any]],
        created_by: str,
    ) -> list[CausalNode]:
        """Membuat banyak node sekaligus."""
        results = []
        for data in nodes_data:
            node = self.create_node(
                node_type=CausalNodeType[data["node_type"]],
                entity_id=UUID(data["entity_id"]),
                entity_type=data["entity_type"],
                created_by=created_by,
                previous_node_id=UUID(data["previous_node_id"])
                if data.get("previous_node_id")
                else None,
                metadata=data.get("metadata"),
            )
            results.append(node)
        return results

    # ------------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------------
    def get_node(self, node_id: UUID) -> CausalNode | None:
        return self._nodes.get(node_id)

    def get_node_by_entity(self, entity_type: str, entity_id: UUID) -> CausalNode | None:
        node_id = self._entity_to_node.get((entity_type, entity_id))
        return self._nodes.get(node_id) if node_id else None

    def get_all_nodes(self) -> list[CausalNode]:
        return list(self._nodes.values())

    def get_nodes_by_type(self, node_type: CausalNodeType) -> list[CausalNode]:
        return [n for n in self._nodes.values() if n.node_type == node_type]

    def get_nodes_by_creator(self, created_by: str) -> list[CausalNode]:
        return [n for n in self._nodes.values() if n.created_by == created_by]

    def get_nodes_by_date_range(self, start: datetime, end: datetime) -> list[CausalNode]:
        return [n for n in self._nodes.values() if start <= n.timestamp <= end]

    def get_roots(self) -> list[CausalNode]:
        return [n for n in self._nodes.values() if n.is_root()]

    def get_leaves(self) -> list[CausalNode]:
        return [n for n in self._nodes.values() if n.is_leaf()]

    def get_orphans(self) -> list[CausalNode]:
        """Node yang tidak memiliki hubungan (no prev, no next)."""
        return [n for n in self._nodes.values() if n.is_root() and n.is_leaf()]

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------
    def update_node_metadata(
        self, node_id: UUID, metadata: dict[str, Any], updated_by: str
    ) -> CausalNode | None:
        node = self._nodes.get(node_id)
        if not node:
            return None
        updated = node.update_metadata(metadata)
        self._nodes[node_id] = updated
        self._log_audit(
            "UPDATE_METADATA", node_id, {"metadata": metadata, "updated_by": updated_by}
        )
        return updated

    def update_node_type(
        self, node_id: UUID, new_type: CausalNodeType, updated_by: str
    ) -> CausalNode | None:
        node = self._nodes.get(node_id)
        if not node:
            return None
        updated = CausalNode(
            node_id=node.node_id,
            node_type=new_type,
            entity_id=node.entity_id,
            entity_type=node.entity_type,
            timestamp=node.timestamp,
            created_by=node.created_by,
            previous_node_id=node.previous_node_id,
            next_node_id=node.next_node_id,
            metadata=node.metadata.copy(),
            cryptographic_hash="",
            version=node.version + 1,
        )
        self._nodes[node_id] = updated
        self._log_audit(
            "UPDATE_TYPE", node_id, {"new_type": new_type.name, "updated_by": updated_by}
        )
        return updated

    # ------------------------------------------------------------------------
    # Delete / Unlink
    # ------------------------------------------------------------------------
    def unlink_node(self, node_id: UUID) -> CausalNode | None:
        node = self._nodes.get(node_id)
        if not node:
            return None
        if node.previous_node_id:
            prev = self._nodes.get(node.previous_node_id)
            if prev:
                updated_prev = prev.unlink_next()
                self._nodes[prev.node_id] = updated_prev
        new_node = node.unlink_next()
        self._nodes[node_id] = new_node
        self._log_audit("UNLINK", node_id, {})
        return new_node

    def delete_node(self, node_id: UUID, permanent: bool = False) -> bool:
        node = self._nodes.get(node_id)
        if not node:
            return False
        # Repair chain: connect previous to next if both exist
        if node.previous_node_id and node.next_node_id:
            prev = self._nodes.get(node.previous_node_id)
            nxt = self._nodes.get(node.next_node_id)
            if prev and nxt:
                # Update previous node's next to skip this node
                updated_prev = CausalNode(
                    node_id=prev.node_id,
                    node_type=prev.node_type,
                    entity_id=prev.entity_id,
                    entity_type=prev.entity_type,
                    timestamp=prev.timestamp,
                    created_by=prev.created_by,
                    previous_node_id=prev.previous_node_id,
                    next_node_id=node.next_node_id,
                    metadata=prev.metadata.copy(),
                    cryptographic_hash="",
                    version=prev.version + 1,
                )
                self._nodes[prev.node_id] = updated_prev
                # Update next node's previous to skip this node
                updated_nxt = CausalNode(
                    node_id=nxt.node_id,
                    node_type=nxt.node_type,
                    entity_id=nxt.entity_id,
                    entity_type=nxt.entity_type,
                    timestamp=nxt.timestamp,
                    created_by=nxt.created_by,
                    previous_node_id=node.previous_node_id,
                    next_node_id=nxt.next_node_id,
                    metadata=nxt.metadata.copy(),
                    cryptographic_hash="",
                    version=nxt.version + 1,
                )
                self._nodes[nxt.node_id] = updated_nxt
        elif node.previous_node_id:
            prev = self._nodes.get(node.previous_node_id)
            if prev:
                updated_prev = prev.unlink_next()
                self._nodes[prev.node_id] = updated_prev
        elif node.next_node_id:
            nxt = self._nodes.get(node.next_node_id)
            if nxt:
                updated_nxt = CausalNode(
                    node_id=nxt.node_id,
                    node_type=nxt.node_type,
                    entity_id=nxt.entity_id,
                    entity_type=nxt.entity_type,
                    timestamp=nxt.timestamp,
                    created_by=nxt.created_by,
                    previous_node_id=None,
                    next_node_id=nxt.next_node_id,
                    metadata=nxt.metadata.copy(),
                    cryptographic_hash="",
                    version=nxt.version + 1,
                )
                self._nodes[nxt.node_id] = updated_nxt
        del self._nodes[node_id]
        self._entity_to_node.pop((node.entity_type, node.entity_id), None)
        self._log_audit("DELETE", node_id, {"permanent": permanent})
        return True

    def delete_batch(self, node_ids: list[UUID], permanent: bool = False) -> int:
        count = 0
        for nid in node_ids:
            if self.delete_node(nid, permanent):
                count += 1
        return count

    # ------------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------------
    def get_chain(self, start_node_id: UUID, direction: str = "forward") -> list[CausalNode]:
        chain = []
        current_id: UUID | None = start_node_id
        if direction == "forward":
            while current_id is not None:
                if current_id in self._nodes:
                    node = self._nodes[current_id]
                else:
                    break
                chain.append(node)
                current_id = node.next_node_id
        else:
            while current_id is not None:
                if current_id in self._nodes:
                    node = self._nodes[current_id]
                else:
                    break
                chain.insert(0, node)
                current_id = node.previous_node_id
        return chain

    def get_full_chain(self, node_id: UUID) -> list[CausalNode]:
        node = self._nodes.get(node_id)
        if not node:
            return []
        # Go to start
        current = node
        while current.previous_node_id and current.previous_node_id in self._nodes:
            current = self._nodes[current.previous_node_id]
        return self.get_chain(current.node_id, direction="forward")

    def get_ancestors(self, node_id: UUID) -> list[CausalNode]:
        ancestors = self.get_chain(node_id, direction="backward")
        return ancestors[:-1] if ancestors else []

    def get_descendants(self, node_id: UUID) -> list[CausalNode]:
        descendants = self.get_chain(node_id, direction="forward")
        return descendants[1:] if descendants else []

    def get_path_between(self, from_node_id: UUID, to_node_id: UUID) -> list[CausalNode] | None:
        from_chain = self.get_chain(from_node_id, direction="forward")
        from_ids = [n.node_id for n in from_chain]
        if to_node_id in from_ids:
            idx = from_ids.index(to_node_id)
            return from_chain[: idx + 1]
        return None

    def get_subgraph(self, root_node_id: UUID, max_depth: int = 10) -> dict[UUID, list[UUID]]:
        """Mendapatkan subgraph adjacency list dari root."""
        graph: dict[UUID, list[UUID]] = {}
        visited = set()
        queue = [(root_node_id, 0)]
        while queue:
            current_id, depth = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            if current_id not in self._nodes:
                continue
            node = self._nodes[current_id]
            graph[current_id] = []
            if node.next_node_id and node.next_node_id not in visited:
                graph[current_id].append(node.next_node_id)
                queue.append((node.next_node_id, depth + 1))
            if node.previous_node_id and node.previous_node_id not in visited:
                graph[current_id].append(node.previous_node_id)
                queue.append((node.previous_node_id, depth + 1))
        return graph

    # ------------------------------------------------------------------------
    # Validation & Integrity
    # ------------------------------------------------------------------------
    def validate_chain_integrity(self, chain: list[CausalNode]) -> bool:
        for i in range(len(chain) - 1):
            current = chain[i]
            nxt = chain[i + 1]
            if current.next_node_id != nxt.node_id:
                logger.warning(
                    f"Chain integrity broken: {current.node_id}.next = {current.next_node_id}, expected {nxt.node_id}"
                )
                return False
            if nxt.previous_node_id != current.node_id:
                logger.warning(
                    f"Chain integrity broken: {nxt.node_id}.prev = {nxt.previous_node_id}, expected {current.node_id}"
                )
                return False
        return True

    def verify_all_hashes(self) -> dict[UUID, bool]:
        results = {}
        for node_id, node in self._nodes.items():
            expected = node.compute_hash()
            results[node_id] = node.cryptographic_hash == expected
        return results

    def detect_cycles(self) -> list[list[UUID]]:
        """Deteksi siklus dalam graf kausalitas."""
        cycles = []
        visited = set()
        rec_stack = set()
        parent = {}

        def dfs(node_id: UUID, path: list[UUID]) -> None:
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            if node_id in self._nodes:
                node = self._nodes[node_id]
                if node.next_node_id:
                    neighbor = node.next_node_id
                    if neighbor not in visited:
                        parent[neighbor] = node_id
                        dfs(neighbor, path)
                    elif neighbor in rec_stack:
                        # Cycle detected
                        cycle_start = path.index(neighbor)
                        cycles.append([*path[cycle_start:], neighbor])
            rec_stack.remove(node_id)
            path.pop()

        for node_id in list(self._nodes.keys()):
            if node_id not in visited:
                dfs(node_id, [])
        return cycles

    # ------------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------------
    def export_chain(self, node_id: UUID) -> str:
        chain = self.get_full_chain(node_id)
        data = {
            "exported_at": datetime.now(UTC).isoformat(),
            "root_node_id": str(chain[0].node_id) if chain else None,
            "nodes": [n.to_dict() for n in chain],
        }
        return json.dumps(data, indent=2)

    def export_all_chains(self) -> str:
        roots = self.get_roots()
        data = {
            "exported_at": datetime.now(UTC).isoformat(),
            "chains": [self.export_chain(root.node_id) for root in roots],
        }
        return json.dumps(data, indent=2)

    def import_chain(self, json_str: str, overwrite: bool = False) -> list[UUID]:
        data = json.loads(json_str)
        imported_ids = []
        for node_dict in data.get("nodes", []):
            node = CausalNode.from_dict(node_dict)
            if node.node_id in self._nodes and not overwrite:
                continue
            self._nodes[node.node_id] = node
            self._entity_to_node[(node.entity_type, node.entity_id)] = node.node_id
            imported_ids.append(node.node_id)
        self._log_audit("IMPORT", UUID(int=0), {"count": len(imported_ids)})
        return imported_ids

    # ------------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------------
    def search_nodes(self, keyword: str, search_in: str = "entity_type") -> list[CausalNode]:
        keyword_lower = keyword.lower()
        results = []
        for node in self._nodes.values():
            if search_in == "entity_type" and keyword_lower in node.entity_type.lower():
                results.append(node)
            elif search_in == "metadata":
                if any(keyword_lower in str(v).lower() for v in node.metadata.values()):
                    results.append(node)
            elif (search_in == "created_by" and keyword_lower in node.created_by.lower()) or (
                search_in == "node_type" and keyword_lower in node.node_type.name.lower()
            ):
                results.append(node)
        return results

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------
    def get_statistics(self) -> dict[str, Any]:
        total = len(self._nodes)
        by_type: dict[str, int] = defaultdict(int)
        for node in self._nodes.values():
            by_type[node.node_type.name] += 1

        by_entity_type: dict[str, int] = defaultdict(int)
        for node in self._nodes.values():
            by_entity_type[node.entity_type] += 1

        processed = set()
        chain_lengths = []
        for node in self._nodes.values():
            if node.node_id in processed:
                continue
            chain = self.get_full_chain(node.node_id)
            if chain:
                chain_lengths.append(len(chain))
                for n in chain:
                    processed.add(n.node_id)
        avg_len = sum(chain_lengths) / len(chain_lengths) if chain_lengths else 0
        cycles = self.detect_cycles()
        hash_verification = self.verify_all_hashes()
        valid_hashes = sum(1 for v in hash_verification.values() if v)
        return {
            "total_nodes": total,
            "by_node_type": dict(by_type),
            "by_entity_type": dict(by_entity_type),
            "total_chains": len(chain_lengths),
            "average_chain_length": avg_len,
            "max_chain_length": max(chain_lengths) if chain_lengths else 0,
            "cycles_detected": len(cycles),
            "hash_integrity": f"{valid_hashes}/{total} valid",
            "roots_count": len(self.get_roots()),
            "leaves_count": len(self.get_leaves()),
            "orphans_count": len(self.get_orphans()),
            "audit_log_size": len(self._audit_log),
        }

    def reset(self) -> None:
        self._nodes.clear()
        self._entity_to_node.clear()
        self._audit_log.clear()


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_causal_node_service_instance: CausalNodeService | None = None


def get_causal_node_service() -> CausalNodeService:
    global _causal_node_service_instance
    if _causal_node_service_instance is None:
        _causal_node_service_instance = CausalNodeService()
    return _causal_node_service_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CausalDirection",
    "CausalNode",
    "CausalNodeService",
    "CausalNodeType",
    "get_causal_node_service",
]
