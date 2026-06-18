#!/usr/bin/env python3
"""
Module: why_query_engine.py
Layer: Domain / Causality
Responsibility: Mesin query "mengapa" untuk investigasi akar penyebab,
               dengan analisis upstream, penjelasan naratif, caching,
               dan sejarah query.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from domain.causality.causal_chain_builder import get_causal_chain_builder
from domain.causality.causal_node import get_causal_node_service
from domain.causality.causality_tracker import get_causality_tracker
from domain.causality.explanation_generator import get_explanation_generator

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================


class WhyQueryDepth(Enum):
    SHALLOW = 1  # Hanya langsung (parent)
    MEDIUM = 3  # 3 level ke belakang
    DEEP = 5  # 5 level ke belakang
    FULL = -1  # Semua level (unlimited)


class WhyQueryResultStatus(Enum):
    SUCCESS = auto()
    NO_CAUSES_FOUND = auto()
    PARTIAL = auto()
    TIMEOUT = auto()
    ERROR = auto()


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class WhyQueryResult:
    """Hasil query "why" untuk suatu transaksi."""

    query_id: UUID
    target_entity_id: UUID
    target_entity_type: str
    depth: WhyQueryDepth
    causes: list[dict[str, Any]]
    root_causes: list[dict[str, Any]]
    explanation: str
    detailed_explanation: str
    status: WhyQueryResultStatus
    execution_time_ms: float
    queried_by: str
    queried_at: datetime
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": str(self.query_id),
            "target_entity_id": str(self.target_entity_id),
            "target_entity_type": self.target_entity_type,
            "depth": self.depth.value if self.depth != WhyQueryDepth.FULL else "FULL",
            "causes_count": len(self.causes),
            "root_causes_count": len(self.root_causes),
            "explanation": self.explanation,
            "detailed_explanation": self.detailed_explanation,
            "status": self.status.name,
            "execution_time_ms": self.execution_time_ms,
            "queried_by": self.queried_by,
            "queried_at": self.queried_at.isoformat(),
            "cached": self.cached,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class WhyQueryCacheEntry:
    """Cache entry untuk query why."""

    result: WhyQueryResult
    expires_at: datetime


# ============================================================================
# WHY QUERY ENGINE
# ============================================================================


class WhyQueryEngine:
    """
    Mesin query "why" untuk investigasi akar penyebab.
    Menjawab pertanyaan "mengapa transaksi ini terjadi?" dengan menganalisis
    rantai kausalitas ke belakang hingga ke akar penyebab.
    """

    _instance: WhyQueryEngine | None = None

    def __new__(cls) -> WhyQueryEngine:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._node_service = get_causal_node_service()
        self._chain_builder = get_causal_chain_builder()
        self._causality_tracker = get_causality_tracker()
        self._explanation_gen = get_explanation_generator()
        self._query_history: list[WhyQueryResult] = []
        self._cache: dict[str, WhyQueryCacheEntry] = {}
        self._max_history = 500
        self._max_cache_size = 200
        self._default_timeout_ms = 5000
        self._audit_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------------
    def _log_audit(self, action: str, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"WHY QUERY ENGINE AUDIT: {action}")

    # ------------------------------------------------------------------------
    # Cache Helpers
    # ------------------------------------------------------------------------
    def _get_cache_key(
        self,
        entity_id: UUID,
        entity_type: str,
        depth: WhyQueryDepth,
    ) -> str:
        content = f"{entity_id}:{entity_type}:{depth.value}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_from_cache(
        self,
        entity_id: UUID,
        entity_type: str,
        depth: WhyQueryDepth,
        max_age_seconds: int = 300,
    ) -> WhyQueryResult | None:
        key = self._get_cache_key(entity_id, entity_type, depth)
        entry = self._cache.get(key)
        if entry and entry.expires_at > datetime.now(UTC):
            return entry.result
        if key in self._cache:
            del self._cache[key]
        return None

    def _store_in_cache(
        self,
        result: WhyQueryResult,
        ttl_seconds: int = 300,
    ) -> None:
        key = self._get_cache_key(
            result.target_entity_id,
            result.target_entity_type,
            result.depth,
        )
        self._cache[key] = WhyQueryCacheEntry(
            result=result,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        # Prune cache if too large
        if len(self._cache) > self._max_cache_size:
            # Remove oldest entries
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1].expires_at)
            for old_key in sorted_items[: self._max_cache_size // 2]:
                del self._cache[old_key[0]]

    # ------------------------------------------------------------------------
    # Core Query
    # ------------------------------------------------------------------------
    def query_why(
        self,
        entity_id: UUID,
        entity_type: str,
        queried_by: str,
        depth: WhyQueryDepth = WhyQueryDepth.MEDIUM,
        use_cache: bool = True,
        timeout_ms: int | None = None,
    ) -> WhyQueryResult:
        """
        Menjalankan query "why" untuk suatu entitas.
        """
        start_time = time.perf_counter()
        timeout = timeout_ms or self._default_timeout_ms

        # Check cache
        if use_cache:
            cached = self._get_from_cache(entity_id, entity_type, depth)
            if cached:
                self._log_audit(
                    "CACHE_HIT",
                    {
                        "entity_id": str(entity_id),
                        "entity_type": entity_type,
                    },
                )
                return cached

        try:
            # Get traceability report
            trace = self._chain_builder.get_traceability_report(entity_id, entity_type)
            if "error" in trace:
                execution_time = (time.perf_counter() - start_time) * 1000
                result = WhyQueryResult(
                    query_id=uuid4(),
                    target_entity_id=entity_id,
                    target_entity_type=entity_type,
                    depth=depth,
                    causes=[],
                    root_causes=[],
                    explanation=f"Error: {trace['error']}",
                    detailed_explanation=f"Unable to retrieve causal chain: {trace['error']}",
                    status=WhyQueryResultStatus.ERROR,
                    execution_time_ms=execution_time,
                    queried_by=queried_by,
                    queried_at=datetime.now(UTC),
                )
                self._store_result(result)
                return result

            chain = trace.get("chain", [])
            if not chain:
                execution_time = (time.perf_counter() - start_time) * 1000
                result = WhyQueryResult(
                    query_id=uuid4(),
                    target_entity_id=entity_id,
                    target_entity_type=entity_type,
                    depth=depth,
                    causes=[],
                    root_causes=[],
                    explanation="No causal chain found.",
                    detailed_explanation="The system has no recorded causal information for this entity.",
                    status=WhyQueryResultStatus.NO_CAUSES_FOUND,
                    execution_time_ms=execution_time,
                    queried_by=queried_by,
                    queried_at=datetime.now(UTC),
                )
                self._store_result(result)
                return result

            # Get upstream causes from causality tracker with timeout protection
            max_depth = depth.value if depth != WhyQueryDepth.FULL else 20
            try:
                upstream = self._causality_tracker.get_upstream(entity_id, max_depth=max_depth)
            except Exception as e:
                execution_time = (time.perf_counter() - start_time) * 1000
                result = WhyQueryResult(
                    query_id=uuid4(),
                    target_entity_id=entity_id,
                    target_entity_type=entity_type,
                    depth=depth,
                    causes=[],
                    root_causes=[],
                    explanation=f"Error retrieving upstream: {e!s}",
                    detailed_explanation=f"Failed to query causality tracker: {e!s}",
                    status=WhyQueryResultStatus.ERROR,
                    execution_time_ms=execution_time,
                    queried_by=queried_by,
                    queried_at=datetime.now(UTC),
                )
                self._store_result(result)
                return result

            causes = []
            root_causes = []

            for cause_id, dist, rel_path in upstream:
                # Get node info
                node = self._node_service.get_node_by_entity("unknown", cause_id)
                if node:
                    cause_info = {
                        "entity_id": str(cause_id),
                        "entity_type": node.entity_type,
                        "node_type": node.node_type.name,
                        "distance": dist,
                        "timestamp": node.timestamp.isoformat(),
                        "created_by": node.created_by,
                        "strength": sum(r.strength for r in rel_path) / len(rel_path)
                        if rel_path
                        else 1.0,
                    }
                    causes.append(cause_info)

                    # Check if this cause has no upstream (root cause)
                    if not self._causality_tracker.get_upstream(cause_id, max_depth=1):
                        root_causes.append(cause_info)

            # Generate explanations
            explanation = self._generate_why_explanation(
                entity_id, entity_type, causes, root_causes, trace, depth, language="en"
            )
            detailed_explanation = self._generate_detailed_explanation(
                entity_id, entity_type, causes, root_causes, trace, depth, language="en"
            )

            execution_time = (time.perf_counter() - start_time) * 1000
            status = (
                WhyQueryResultStatus.SUCCESS if causes else WhyQueryResultStatus.NO_CAUSES_FOUND
            )

            result = WhyQueryResult(
                query_id=uuid4(),
                target_entity_id=entity_id,
                target_entity_type=entity_type,
                depth=depth,
                causes=causes[:50],  # limit
                root_causes=root_causes[:20],
                explanation=explanation,
                detailed_explanation=detailed_explanation,
                status=status,
                execution_time_ms=execution_time,
                queried_by=queried_by,
                queried_at=datetime.now(UTC),
            )

            self._store_result(result, use_cache)
            return result

        except Exception as e:
            execution_time = (time.perf_counter() - start_time) * 1000
            result = WhyQueryResult(
                query_id=uuid4(),
                target_entity_id=entity_id,
                target_entity_type=entity_type,
                depth=depth,
                causes=[],
                root_causes=[],
                explanation=f"Query failed: {e!s}",
                detailed_explanation=f"Exception occurred: {e!s}",
                status=WhyQueryResultStatus.ERROR,
                execution_time_ms=execution_time,
                queried_by=queried_by,
                queried_at=datetime.now(UTC),
            )
            self._store_result(result)
            return result

    def _store_result(self, result: WhyQueryResult, use_cache: bool = False) -> None:
        self._query_history.append(result)
        if len(self._query_history) > self._max_history:
            self._query_history = self._query_history[-self._max_history :]
        if use_cache:
            self._store_in_cache(result)

    # ------------------------------------------------------------------------
    # Explanation Generation
    # ------------------------------------------------------------------------
    def _generate_why_explanation(
        self,
        entity_id: UUID,
        entity_type: str,
        causes: list[dict[str, Any]],
        root_causes: list[dict[str, Any]],
        trace: dict[str, Any],
        depth: WhyQueryDepth,
        language: str = "en",
    ) -> str:
        if language == "en":
            if not causes:
                return f"No causes found for {entity_type} {entity_id}. This transaction has no recorded upstream dependencies."

            chain_length = len(trace.get("chain", []))
            rc_text = ""
            if root_causes:
                rc = root_causes[0]
                rc_text = (
                    f" The root cause appears to be {rc['entity_type']} {rc['entity_id'][:12]}..."
                )

            return (
                f"This {entity_type} transaction was influenced by {len(causes)} upstream cause(s) across a "
                f"chain of {chain_length} steps.{rc_text} Depth of analysis: {depth.name}."
            )
        else:
            if not causes:
                return f"Tidak ditemukan penyebab untuk {entity_type} {entity_id}."

            rc_text = ""
            if root_causes:
                rc = root_causes[0]
                rc_text = f" Akar penyebabnya adalah {rc['entity_type']} {rc['entity_id'][:12]}..."

            return (
                f"Transaksi {entity_type} ini dipengaruhi oleh {len(causes)} penyebab upstream melalui "
                f"{len(trace.get('chain', []))} langkah.{rc_text} Kedalaman analisis: {depth.name}."
            )

    def _generate_detailed_explanation(
        self,
        entity_id: UUID,
        entity_type: str,
        causes: list[dict[str, Any]],
        root_causes: list[dict[str, Any]],
        trace: dict[str, Any],
        depth: WhyQueryDepth,
        language: str = "en",
    ) -> str:
        if language == "en":
            lines = [
                f"DETAILED WHY ANALYSIS FOR {entity_type.upper()} {entity_id}",
                "=" * 60,
                f"Analysis depth: {depth.name}",
                f"Total causes found: {len(causes)}",
                f"Root causes: {len(root_causes)}",
                "",
            ]

            if causes:
                lines.append("UPSTREAM CAUSES (by distance):")
                # Group by distance
                by_distance = {}
                for c in causes:
                    dist = c["distance"]
                    by_distance.setdefault(dist, []).append(c)
                for dist in sorted(by_distance.keys()):
                    lines.append(f"\nDistance {dist} (direct cause if 1):")
                    for c in by_distance[dist][:5]:
                        lines.append(
                            f"  - {c['entity_type']} {c['entity_id'][:12]}... ({c['node_type']}) "
                            f"by {c['created_by']} at {c['timestamp'][:19]}"
                        )
                        if len(by_distance[dist]) > 5:
                            lines.append(f"    ... and {len(by_distance[dist]) - 5} more")

            if root_causes:
                lines.extend(["", "ROOT CAUSES (ultimate sources):"])
                for rc in root_causes[:5]:
                    lines.append(
                        f"  - {rc['entity_type']} {rc['entity_id']} ({rc['node_type']}) at {rc['timestamp'][:19]}"
                    )
                if len(root_causes) > 5:
                    lines.append(f"    ... and {len(root_causes) - 5} more")

            chain = trace.get("chain", [])
            if chain:
                lines.extend(["", "CAUSAL CHAIN SUMMARY:"])
                first = chain[0]
                last = chain[-1]
                lines.append(
                    f"  Origin: {first['entity_type']} {first['entity_id'][:12]}... ({first['node_type']})"
                )
                lines.append(
                    f"  Final: {last['entity_type']} {last['entity_id'][:12]}... ({last['node_type']})"
                )
                lines.append(f"  Total steps: {len(chain)}")

            return "\n".join(lines)
        else:
            # Indonesian version (simplified for length)
            lines = [
                f"ANALISIS WHY DETAIL UNTUK {entity_type.upper()} {entity_id}",
                "=" * 60,
                f"Kedalaman analisis: {depth.name}",
                f"Total penyebab ditemukan: {len(causes)}",
                f"Akar penyebab: {len(root_causes)}",
                "",
            ]
            if causes:
                lines.append("PENYEBAB UPSTREAM (berdasarkan jarak):")
                by_distance = {}
                for c in causes:
                    by_distance.setdefault(c["distance"], []).append(c)
                for dist in sorted(by_distance.keys()):
                    lines.append(f"\nJarak {dist}:")
                    for c in by_distance[dist][:5]:
                        lines.append(
                            f"  - {c['entity_type']} {c['entity_id'][:12]}... ({c['node_type']})"
                        )
            return "\n".join(lines)

    # ------------------------------------------------------------------------
    # Batch & Convenience Methods
    # ------------------------------------------------------------------------
    def query_why_batch(
        self,
        entities: list[tuple[UUID, str]],
        queried_by: str,
        depth: WhyQueryDepth = WhyQueryDepth.MEDIUM,
    ) -> list[WhyQueryResult]:
        """Query multiple entities in batch."""
        results = []
        for eid, etype in entities:
            result = self.query_why(eid, etype, queried_by, depth)
            results.append(result)
        return results

    def query_why_narrative(
        self,
        entity_id: UUID,
        entity_type: str,
        queried_by: str,
        depth: WhyQueryDepth = WhyQueryDepth.MEDIUM,
    ) -> str:
        """Returns only the explanation text."""
        result = self.query_why(entity_id, entity_type, queried_by, depth)
        return result.explanation

    def query_why_detailed(
        self,
        entity_id: UUID,
        entity_type: str,
        queried_by: str,
        depth: WhyQueryDepth = WhyQueryDepth.MEDIUM,
    ) -> str:
        """Returns detailed explanation text."""
        result = self.query_why(entity_id, entity_type, queried_by, depth)
        return result.detailed_explanation

    # ------------------------------------------------------------------------
    # Cache Management
    # ------------------------------------------------------------------------
    def invalidate_cache(
        self, entity_id: UUID | None = None, entity_type: str | None = None
    ) -> int:
        """Invalidate cache for specific entity or all."""
        if entity_id is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        else:
            keys_to_remove = []
            for key, entry in self._cache.items():
                if entry.result.target_entity_id == entity_id:
                    if entity_type is None or entry.result.target_entity_type == entity_type:
                        keys_to_remove.append(key)
            for key in keys_to_remove:
                del self._cache[key]
            return len(keys_to_remove)

    def clear_cache(self) -> int:
        return self.invalidate_cache()

    # ------------------------------------------------------------------------
    # History & Statistics
    # ------------------------------------------------------------------------
    def get_query_history(
        self,
        limit: int = 50,
        entity_id: UUID | None = None,
        status: WhyQueryResultStatus | None = None,
    ) -> list[WhyQueryResult]:
        results = self._query_history[-limit:]
        if entity_id:
            results = [r for r in results if r.target_entity_id == entity_id]
        if status:
            results = [r for r in results if r.status == status]
        return results

    def get_statistics(self) -> dict[str, Any]:
        total = len(self._query_history)
        if total == 0:
            return {"total_queries": 0, "cache_size": len(self._cache)}

        by_status = {}
        by_depth = {}
        total_time = 0.0
        total_causes = 0
        for q in self._query_history:
            by_status[q.status.name] = by_status.get(q.status.name, 0) + 1
            depth_key = q.depth.name if q.depth != WhyQueryDepth.FULL else "FULL"
            by_depth[depth_key] = by_depth.get(depth_key, 0) + 1
            total_time += q.execution_time_ms
            total_causes += len(q.causes)

        return {
            "total_queries": total,
            "by_status": by_status,
            "by_depth": by_depth,
            "average_causes_per_query": total_causes / total if total > 0 else 0,
            "average_execution_time_ms": total_time / total if total > 0 else 0,
            "cache_size": len(self._cache),
            "max_history": self._max_history,
            "audit_log_size": len(self._audit_log),
        }

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_log[-limit:]

    def reset(self) -> None:
        self._query_history = []
        self._cache = {}
        self._audit_log = []
        self._log_audit("RESET", {})


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_why_query_engine_instance: WhyQueryEngine | None = None


def get_why_query_engine() -> WhyQueryEngine:
    global _why_query_engine_instance
    if _why_query_engine_instance is None:
        _why_query_engine_instance = WhyQueryEngine()
    return _why_query_engine_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "WhyQueryCacheEntry",
    "WhyQueryDepth",
    "WhyQueryEngine",
    "WhyQueryResult",
    "WhyQueryResultStatus",
    "get_why_query_engine",
]
