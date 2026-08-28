#!/usr/bin/env python3
"""
Module: causal_chain_builder.py
Layer: Domain / Causality
Responsibility: Membangun rantai kausalitas dari intent, economic event, hingga journal entry.
               Mendukung pembuatan chain reversal, adjustment, traceability report,
               root cause analysis, dan visualisasi path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from domain.causality.causal_node import (
    CausalNode,
    CausalNodeType,
    get_causal_node_service,
)

# Optional imports with fallback untuk menghindari error import
try:
    from domain.intent.immutable_record import get_immutable_intent_record_service
except ImportError:
    get_immutable_intent_record_service = None

try:
    from domain.reality.economic_event_immutable import get_economic_event_service
except ImportError:
    get_economic_event_service = None

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class ChainBuildStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ChainDirection(Enum):
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass
class BuildResult:
    """Hasil pembangunan rantai kausalitas."""

    status: ChainBuildStatus
    nodes: list[CausalNode]
    errors: list[str]
    warnings: list[str]
    duration_ms: float


# ============================================================================
# CAUSAL CHAIN BUILDER
# ============================================================================


class CausalChainBuilder:
    """
    Builder untuk membangun dan memanipulasi rantai kausalitas.
    Menghubungkan intent → economic event → journal entry → dll.
    """

    _instance: CausalChainBuilder | None = None
    _initialized: bool = False

    def __new__(cls) -> CausalChainBuilder:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._node_service = get_causal_node_service()
        self._intent_service = (
            get_immutable_intent_record_service() if get_immutable_intent_record_service else None
        )
        self._event_service = get_economic_event_service() if get_economic_event_service else None
        self._build_history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # Core Build Methods
    # ------------------------------------------------------------------------

    def build_from_intent_to_event(
        self,
        intent_id: UUID,
        event_id: UUID,
        created_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> BuildResult:
        """
        Membangun rantai dari intent ke economic event.
        """
        start_time = datetime.now(UTC)
        errors: list[str] = []
        warnings: list[str] = []
        nodes: list[CausalNode] = []

        try:
            # Cari atau buat node intent
            intent_node = self._node_service.get_node_by_entity("intent", intent_id)
            if not intent_node:
                intent_node = self._node_service.create_node(
                    node_type=CausalNodeType.INTENT,
                    entity_id=intent_id,
                    entity_type="intent",
                    created_by=created_by,
                    metadata=metadata or {},
                )
                nodes.append(intent_node)
                warnings.append(f"Intent node {intent_id} did not exist, created automatically")
            else:
                nodes.append(intent_node)

            # Cari atau buat node event
            event_node = self._node_service.get_node_by_entity("economic_event", event_id)
            if not event_node:
                event_node = self._node_service.create_node(
                    node_type=CausalNodeType.ECONOMIC_EVENT,
                    entity_id=event_id,
                    entity_type="economic_event",
                    created_by=created_by,
                    previous_node_id=intent_node.node_id,
                    metadata=metadata or {},
                )
                nodes.append(event_node)
            else:
                # Jika event node sudah ada, pastikan terhubung ke intent
                if event_node.previous_node_id != intent_node.node_id:
                    # Update event node to point to intent
                    updated_event = CausalNode(
                        node_id=event_node.node_id,
                        node_type=event_node.node_type,
                        entity_id=event_node.entity_id,
                        entity_type=event_node.entity_type,
                        timestamp=event_node.timestamp,
                        created_by=event_node.created_by,
                        previous_node_id=intent_node.node_id,
                        next_node_id=event_node.next_node_id,
                        metadata=event_node.metadata,
                        cryptographic_hash="",
                        version=event_node.version + 1,
                    )
                    self._node_service._nodes[event_node.node_id] = updated_event
                    nodes.append(updated_event)
                else:
                    nodes.append(event_node)

            # Update intent node's next if needed
            if intent_node.next_node_id != event_node.node_id:
                updated_intent = intent_node.link_to_next(event_node)
                self._node_service._nodes[intent_node.node_id] = updated_intent

            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.SUCCESS,
                nodes=nodes,
                errors=errors,
                warnings=warnings,
                duration_ms=duration_ms,
            )
        except Exception as e:
            errors.append(str(e))
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.FAILED,
                nodes=nodes,
                errors=errors,
                warnings=warnings,
                duration_ms=duration_ms,
            )

    def build_from_event_to_journal(
        self,
        event_id: UUID,
        journal_id: UUID,
        created_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> BuildResult:
        """
        Membangun rantai dari economic event ke journal entry.
        """
        start_time = datetime.now(UTC)
        errors: list[str] = []
        warnings: list[str] = []
        nodes: list[CausalNode] = []

        try:
            # Cari atau buat node event
            event_node = self._node_service.get_node_by_entity("economic_event", event_id)
            if not event_node:
                event_node = self._node_service.create_node(
                    node_type=CausalNodeType.ECONOMIC_EVENT,
                    entity_id=event_id,
                    entity_type="economic_event",
                    created_by=created_by,
                    metadata=metadata or {},
                )
                nodes.append(event_node)
                warnings.append(f"Event node {event_id} did not exist, created automatically")
            else:
                nodes.append(event_node)

            # Cari atau buat node journal
            journal_node = self._node_service.get_node_by_entity("journal", journal_id)
            if not journal_node:
                journal_node = self._node_service.create_node(
                    node_type=CausalNodeType.JOURNAL_ENTRY,
                    entity_id=journal_id,
                    entity_type="journal",
                    created_by=created_by,
                    previous_node_id=event_node.node_id,
                    metadata=metadata or {},
                )
                nodes.append(journal_node)
            else:
                if journal_node.previous_node_id != event_node.node_id:
                    updated_journal = CausalNode(
                        node_id=journal_node.node_id,
                        node_type=journal_node.node_type,
                        entity_id=journal_node.entity_id,
                        entity_type=journal_node.entity_type,
                        timestamp=journal_node.timestamp,
                        created_by=journal_node.created_by,
                        previous_node_id=event_node.node_id,
                        next_node_id=journal_node.next_node_id,
                        metadata=journal_node.metadata,
                        cryptographic_hash="",
                        version=journal_node.version + 1,
                    )
                    self._node_service._nodes[journal_node.node_id] = updated_journal
                    nodes.append(updated_journal)
                else:
                    nodes.append(journal_node)

            # Update event node's next
            if event_node.next_node_id != journal_node.node_id:
                updated_event = event_node.link_to_next(journal_node)
                self._node_service._nodes[event_node.node_id] = updated_event

            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.SUCCESS,
                nodes=nodes,
                errors=errors,
                warnings=warnings,
                duration_ms=duration_ms,
            )
        except Exception as e:
            errors.append(str(e))
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.FAILED,
                nodes=nodes,
                errors=errors,
                warnings=warnings,
                duration_ms=duration_ms,
            )

    def build_complete_chain(
        self,
        intent_id: UUID,
        event_id: UUID,
        journal_id: UUID,
        created_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> BuildResult:
        """
        Membangun rantai lengkap: intent → event → journal.
        """
        start_time = datetime.now(UTC)
        all_nodes: list[CausalNode] = []
        errors: list[str] = []
        warnings: list[str] = []

        # Step 1: intent → event
        result1 = self.build_from_intent_to_event(intent_id, event_id, created_by, metadata)
        all_nodes.extend(result1.nodes)
        errors.extend(result1.errors)
        warnings.extend(result1.warnings)

        # Step 2: event → journal
        result2 = self.build_from_event_to_journal(event_id, journal_id, created_by, metadata)
        all_nodes.extend(result2.nodes)
        errors.extend(result2.errors)
        warnings.extend(result2.warnings)

        # Get the full chain from first node
        if all_nodes:
            first_node = all_nodes[0]
            full_chain = self._node_service.get_full_chain(first_node.node_id)
        else:
            full_chain = []

        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
        status = ChainBuildStatus.FAILED if errors else ChainBuildStatus.SUCCESS
        return BuildResult(
            status=status,
            nodes=full_chain,
            errors=errors,
            warnings=warnings,
            duration_ms=duration_ms,
        )

    def build_reversal_chain(
        self,
        original_journal_id: UUID,
        reversal_journal_id: UUID,
        created_by: str,
        reason: str = "Reversal",
        metadata: dict[str, Any] | None = None,
    ) -> BuildResult:
        """
        Membangun rantai reversal dari journal asli ke reversal journal.
        """
        start_time = datetime.now(UTC)
        errors: list[str] = []
        nodes: list[CausalNode] = []

        try:
            # Cari node journal asli
            original_node = self._node_service.get_node_by_entity("journal", original_journal_id)
            if not original_node:
                original_node = self._node_service.create_node(
                    node_type=CausalNodeType.JOURNAL_ENTRY,
                    entity_id=original_journal_id,
                    entity_type="journal",
                    created_by=created_by,
                )
                nodes.append(original_node)
            else:
                nodes.append(original_node)

            # Cari atau buat node reversal
            reversal_node = self._node_service.get_node_by_entity("journal", reversal_journal_id)
            if not reversal_node:
                reversal_node = self._node_service.create_node(
                    node_type=CausalNodeType.REVERSAL,
                    entity_id=reversal_journal_id,
                    entity_type="journal",
                    created_by=created_by,
                    previous_node_id=original_node.node_id,
                    metadata={
                        "reversal_reason": reason,
                        "original_journal_id": str(original_journal_id),
                        **(metadata or {}),
                    },
                )
                nodes.append(reversal_node)
            else:
                if reversal_node.previous_node_id != original_node.node_id:
                    updated_reversal = CausalNode(
                        node_id=reversal_node.node_id,
                        node_type=reversal_node.node_type,
                        entity_id=reversal_node.entity_id,
                        entity_type=reversal_node.entity_type,
                        timestamp=reversal_node.timestamp,
                        created_by=reversal_node.created_by,
                        previous_node_id=original_node.node_id,
                        next_node_id=reversal_node.next_node_id,
                        metadata={**reversal_node.metadata, "reversal_reason": reason},
                        cryptographic_hash="",
                        version=reversal_node.version + 1,
                    )
                    self._node_service._nodes[reversal_node.node_id] = updated_reversal
                    nodes.append(updated_reversal)
                else:
                    nodes.append(reversal_node)

            # Update original node's next
            if original_node.next_node_id != reversal_node.node_id:
                updated_original = original_node.link_to_next(reversal_node)
                self._node_service._nodes[original_node.node_id] = updated_original

            # Get full chain
            full_chain = self._node_service.get_full_chain(original_node.node_id)
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.SUCCESS,
                nodes=full_chain,
                errors=errors,
                warnings=[],
                duration_ms=duration_ms,
            )
        except Exception as e:
            errors.append(str(e))
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.FAILED,
                nodes=nodes,
                errors=errors,
                warnings=[],
                duration_ms=duration_ms,
            )

    def build_adjustment_chain(
        self,
        original_event_id: UUID,
        adjustment_event_id: UUID,
        created_by: str,
        reason: str = "Adjustment",
        metadata: dict[str, Any] | None = None,
    ) -> BuildResult:
        """
        Membangun rantai penyesuaian dari event asli ke adjustment event.
        """
        start_time = datetime.now(UTC)
        errors: list[str] = []
        nodes: list[CausalNode] = []

        try:
            original_node = self._node_service.get_node_by_entity(
                "economic_event", original_event_id
            )
            if not original_node:
                original_node = self._node_service.create_node(
                    node_type=CausalNodeType.ECONOMIC_EVENT,
                    entity_id=original_event_id,
                    entity_type="economic_event",
                    created_by=created_by,
                )
                nodes.append(original_node)
            else:
                nodes.append(original_node)

            adjustment_node = self._node_service.get_node_by_entity(
                "economic_event", adjustment_event_id
            )
            if not adjustment_node:
                adjustment_node = self._node_service.create_node(
                    node_type=CausalNodeType.ADJUSTMENT,
                    entity_id=adjustment_event_id,
                    entity_type="economic_event",
                    created_by=created_by,
                    previous_node_id=original_node.node_id,
                    metadata={
                        "adjustment_reason": reason,
                        "original_event_id": str(original_event_id),
                        **(metadata or {}),
                    },
                )
                nodes.append(adjustment_node)
            else:
                if adjustment_node.previous_node_id != original_node.node_id:
                    updated_adjustment = CausalNode(
                        node_id=adjustment_node.node_id,
                        node_type=adjustment_node.node_type,
                        entity_id=adjustment_node.entity_id,
                        entity_type=adjustment_node.entity_type,
                        timestamp=adjustment_node.timestamp,
                        created_by=adjustment_node.created_by,
                        previous_node_id=original_node.node_id,
                        next_node_id=adjustment_node.next_node_id,
                        metadata={**adjustment_node.metadata, "adjustment_reason": reason},
                        cryptographic_hash="",
                        version=adjustment_node.version + 1,
                    )
                    self._node_service._nodes[adjustment_node.node_id] = updated_adjustment
                    nodes.append(updated_adjustment)
                else:
                    nodes.append(adjustment_node)

            if original_node.next_node_id != adjustment_node.node_id:
                updated_original = original_node.link_to_next(adjustment_node)
                self._node_service._nodes[original_node.node_id] = updated_original

            full_chain = self._node_service.get_full_chain(original_node.node_id)
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.SUCCESS,
                nodes=full_chain,
                errors=errors,
                warnings=[],
                duration_ms=duration_ms,
            )
        except Exception as e:
            errors.append(str(e))
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return BuildResult(
                status=ChainBuildStatus.FAILED,
                nodes=nodes,
                errors=errors,
                warnings=[],
                duration_ms=duration_ms,
            )

    # ------------------------------------------------------------------------
    # Traceability & Reporting
    # ------------------------------------------------------------------------

    def get_traceability_report(self, end_entity_id: UUID, end_entity_type: str) -> dict[str, Any]:
        """
        Mendapatkan laporan traceability lengkap untuk suatu entitas.
        """
        node = self._node_service.get_node_by_entity(end_entity_type, end_entity_id)
        if not node:
            return {
                "error": f"Node not found for {end_entity_type} {end_entity_id}",
                "target_entity_id": str(end_entity_id),
                "target_entity_type": end_entity_type,
            }

        full_chain = self._node_service.get_full_chain(node.node_id)
        chain_info = []
        for n in full_chain:
            chain_info.append(
                {
                    "node_id": str(n.node_id),
                    "node_type": n.node_type.name,
                    "entity_id": str(n.entity_id),
                    "entity_type": n.entity_type,
                    "timestamp": n.timestamp.isoformat(),
                    "created_by": n.created_by,
                    "metadata": n.metadata,
                }
            )

        result = {
            "target_entity_id": str(end_entity_id),
            "target_entity_type": end_entity_type,
            "chain_length": len(full_chain),
            "chain": chain_info,
        }

        # Root cause
        if full_chain:
            root = full_chain[0]
            result["root_cause"] = {
                "entity_id": str(root.entity_id),
                "entity_type": root.entity_type,
                "node_type": root.node_type.name,
                "timestamp": root.timestamp.isoformat(),
            }

        # Final outcome
        last = full_chain[-1] if full_chain else None
        if last:
            result["final_outcome"] = {
                "entity_id": str(last.entity_id),
                "entity_type": last.entity_type,
                "timestamp": last.timestamp.isoformat(),
            }

        return result

    def get_root_cause(self, entity_id: UUID, entity_type: str) -> dict[str, Any] | None:
        """
        Mendapatkan akar penyebab (root cause) dari suatu entitas.
        """
        node = self._node_service.get_node_by_entity(entity_type, entity_id)
        if not node:
            return None
        full_chain = self._node_service.get_full_chain(node.node_id)
        if full_chain:
            root = full_chain[0]
            return {
                "entity_id": str(root.entity_id),
                "entity_type": root.entity_type,
                "node_type": root.node_type.name,
                "timestamp": root.timestamp.isoformat(),
                "created_by": root.created_by,
            }
        return None

    def get_impact_chain(self, entity_id: UUID, entity_type: str) -> list[dict[str, Any]]:
        """
        Mendapatkan semua entitas yang dipengaruhi (downstream) dari suatu entitas.
        """
        node = self._node_service.get_node_by_entity(entity_type, entity_id)
        if not node:
            return []
        descendants = self._node_service.get_descendants(node.node_id)
        return [
            {
                "entity_id": str(n.entity_id),
                "entity_type": n.entity_type,
                "node_type": n.node_type.name,
                "distance": idx + 1,
            }
            for idx, n in enumerate(descendants)
        ]

    # ------------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------------

    def validate_chain_completeness(
        self, start_entity_id: UUID, start_entity_type: str
    ) -> dict[str, Any]:
        """
        Memvalidasi apakah chain dari suatu entitas lengkap.
        """
        node = self._node_service.get_node_by_entity(start_entity_type, start_entity_id)
        if not node:
            return {"valid": False, "reason": "Node not found"}

        full_chain = self._node_service.get_full_chain(node.node_id)
        if not full_chain:
            return {"valid": False, "reason": "No chain found"}

        # Check for missing links
        broken_links = []
        for i in range(len(full_chain) - 1):
            current = full_chain[i]
            nxt = full_chain[i + 1]
            if current.next_node_id != nxt.node_id:
                broken_links.append((current.node_id, nxt.node_id))
            if nxt.previous_node_id != current.node_id:
                broken_links.append((nxt.node_id, current.node_id))

        return {
            "valid": len(broken_links) == 0,
            "chain_length": len(full_chain),
            "broken_links": [{"from": str(f), "to": str(t)} for f, t in broken_links],
        }

    # ------------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------------

    def record_build(self, build_type: str, result: BuildResult, params: dict[str, Any]) -> None:
        """
        Mencatat history pembangunan chain.
        """
        self._build_history.append(
            {
                "build_type": build_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "status": result.status.value,
                "nodes_count": len(result.nodes),
                "errors": result.errors,
                "warnings": result.warnings,
                "duration_ms": result.duration_ms,
                "params": params,
            }
        )
        # Limit history size
        if len(self._build_history) > 1000:
            self._build_history = self._build_history[-1000:]

    def get_build_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._build_history[-limit:]

    def get_statistics(self) -> dict[str, Any]:
        total_builds = len(self._build_history)
        if total_builds == 0:
            return {"total_builds": 0}

        by_status: dict[str, int] = {}
        avg_duration = 0.0
        for h in self._build_history:
            status = h["status"]
            by_status[status] = by_status.get(status, 0) + 1
            avg_duration += h["duration_ms"]
        avg_duration /= total_builds

        return {
            "total_builds": total_builds,
            "by_status": by_status,
            "average_duration_ms": avg_duration,
            "node_service_stats": self._node_service.get_statistics(),
        }

    def reset(self) -> None:
        self._build_history.clear()
        self._node_service.reset()


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_causal_chain_builder_instance: CausalChainBuilder | None = None


def get_causal_chain_builder() -> CausalChainBuilder:
    global _causal_chain_builder_instance
    if _causal_chain_builder_instance is None:
        _causal_chain_builder_instance = CausalChainBuilder()
    return _causal_chain_builder_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BuildResult",
    "CausalChainBuilder",
    "ChainBuildStatus",
    "ChainDirection",
    "get_causal_chain_builder",
]
