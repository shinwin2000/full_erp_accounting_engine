# test_why_query_engine.py
# =========================
# Comprehensive tests for domain/causality/why_query_engine.py.
# Covers all enums, data classes, and WhyQueryEngine methods.

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.causality.why_query_engine import (
    WhyQueryCacheEntry,
    WhyQueryDepth,
    WhyQueryEngine,
    WhyQueryResult,
    WhyQueryResultStatus,
    get_why_query_engine,
)


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestWhyQueryDepth:
    def test_members_exist(self):
        assert hasattr(WhyQueryDepth, "SHALLOW")
        assert hasattr(WhyQueryDepth, "MEDIUM")
        assert hasattr(WhyQueryDepth, "DEEP")
        assert hasattr(WhyQueryDepth, "FULL")

    def test_member_is_instance(self):
        assert isinstance(WhyQueryDepth.SHALLOW, WhyQueryDepth)


class TestWhyQueryResultStatus:
    def test_members_exist(self):
        assert hasattr(WhyQueryResultStatus, "SUCCESS")
        assert hasattr(WhyQueryResultStatus, "NO_CAUSES_FOUND")
        assert hasattr(WhyQueryResultStatus, "PARTIAL")
        assert hasattr(WhyQueryResultStatus, "TIMEOUT")
        assert hasattr(WhyQueryResultStatus, "ERROR")

    def test_member_is_instance(self):
        assert isinstance(WhyQueryResultStatus.SUCCESS, WhyQueryResultStatus)


# ----------------------------------------------------------------------
# WhyQueryResult
# ----------------------------------------------------------------------
class TestWhyQueryResult:
    def test_construction(self):
        qid = uuid4()
        target = uuid4()
        result = WhyQueryResult(
            query_id=qid,
            target_entity_id=target,
            target_entity_type="journal",
            depth=WhyQueryDepth.MEDIUM,
            causes=[{"id": "cause1"}],
            root_causes=[{"id": "root1"}],
            explanation="Test explanation",
            detailed_explanation="Detailed test",
            status=WhyQueryResultStatus.SUCCESS,
            execution_time_ms=12.5,
            queried_by="alice",
            queried_at=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
            cached=False,
        )
        assert result.query_id == qid
        assert result.target_entity_id == target
        assert result.target_entity_type == "journal"
        assert result.depth == WhyQueryDepth.MEDIUM
        assert len(result.causes) == 1
        assert len(result.root_causes) == 1
        assert result.explanation == "Test explanation"
        assert result.status == WhyQueryResultStatus.SUCCESS
        assert result.execution_time_ms == 12.5
        assert result.queried_by == "alice"
        assert result.cached is False

    def test_to_dict(self):
        qid = uuid4()
        target = uuid4()
        result = WhyQueryResult(
            query_id=qid,
            target_entity_id=target,
            target_entity_type="journal",
            depth=WhyQueryDepth.SHALLOW,
            causes=[{"id": "cause1"}],
            root_causes=[{"id": "root1"}],
            explanation="Simple explanation",
            detailed_explanation="Detailed",
            status=WhyQueryResultStatus.SUCCESS,
            execution_time_ms=5.0,
            queried_by="bob",
            queried_at=datetime(2025, 1, 2, 12, 0, tzinfo=UTC),
            cached=True,
        )
        d = result.to_dict()
        assert d["query_id"] == str(qid)
        assert d["target_entity_id"] == str(target)
        assert d["target_entity_type"] == "journal"
        assert d["depth"] == 1
        assert d["causes_count"] == 1
        assert d["root_causes_count"] == 1
        assert d["explanation"] == "Simple explanation"
        assert d["status"] == "SUCCESS"
        assert d["execution_time_ms"] == 5.0
        assert d["queried_by"] == "bob"
        assert d["cached"] is True

    def test_to_json(self):
        qid = uuid4()
        target = uuid4()
        result = WhyQueryResult(
            query_id=qid,
            target_entity_id=target,
            target_entity_type="journal",
            depth=WhyQueryDepth.FULL,
            causes=[],
            root_causes=[],
            explanation="No causes",
            detailed_explanation="",
            status=WhyQueryResultStatus.NO_CAUSES_FOUND,
            execution_time_ms=1.0,
            queried_by="carol",
            queried_at=datetime.now(UTC),
            cached=False,
        )
        import json
        data = json.loads(result.to_json())
        assert data["query_id"] == str(qid)
        assert data["depth"] == "FULL"


# ----------------------------------------------------------------------
# WhyQueryCacheEntry
# ----------------------------------------------------------------------
class TestWhyQueryCacheEntry:
    def test_construction(self):
        result = WhyQueryResult(
            query_id=uuid4(),
            target_entity_id=uuid4(),
            target_entity_type="journal",
            depth=WhyQueryDepth.SHALLOW,
            causes=[],
            root_causes=[],
            explanation="",
            detailed_explanation="",
            status=WhyQueryResultStatus.SUCCESS,
            execution_time_ms=0,
            queried_by="system",
            queried_at=datetime.now(UTC),
        )
        expires = datetime.now(UTC) + timedelta(seconds=300)
        entry = WhyQueryCacheEntry(result=result, expires_at=expires)
        assert entry.result is result
        assert entry.expires_at == expires


# ----------------------------------------------------------------------
# WhyQueryEngine
# ----------------------------------------------------------------------
class TestWhyQueryEngine:
    @pytest.fixture
    def engine(self):
        WhyQueryEngine._instance = None
        eng = WhyQueryEngine()
        # Mock dependencies
        eng._chain_builder = MagicMock()
        eng._causality_tracker = MagicMock()
        eng._node_service = MagicMock()
        eng._explanation_gen = MagicMock()
        return eng

    def test_singleton(self):
        e1 = get_why_query_engine()
        e2 = get_why_query_engine()
        assert e1 is e2
        e1.reset()
        WhyQueryEngine._instance = None

    def test_query_why_error_no_node(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"error": "Node not found"}
        result = engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        assert result.status == WhyQueryResultStatus.ERROR
        assert "Error: Node not found" in result.explanation

    def test_query_why_no_chain(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"chain": []}
        result = engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        assert result.status == WhyQueryResultStatus.NO_CAUSES_FOUND
        assert "No causal chain found" in result.explanation

    def test_query_why_success_with_causes(self, engine):
        # Mock trace
        trace = {
            "chain": [{"node_type": "INTENT"}],
            "root_cause": {"entity_type": "intent", "entity_id": "int-123"},
        }
        engine._chain_builder.get_traceability_report.return_value = trace
        # Mock upstream causes
        engine._causality_tracker.get_upstream.return_value = [
            (uuid4(), 1, []),
            (uuid4(), 2, []),
        ]
        # Mock node service to return node info
        def mock_get_node(entity_type, entity_id):
            node = MagicMock()
            node.entity_type = "intent"
            node.node_type.name = "INTENT"
            node.timestamp = datetime.now(UTC)
            node.created_by = "alice"
            return node
        engine._node_service.get_node_by_entity.side_effect = mock_get_node

        result = engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
            depth=WhyQueryDepth.MEDIUM,
        )
        assert result.status == WhyQueryResultStatus.SUCCESS
        assert len(result.causes) == 2
        assert result.explanation is not None
        assert "influenced by 2 upstream cause(s)" in result.explanation

    def test_query_why_upstream_exception(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.side_effect = Exception("DB error")
        result = engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        assert result.status == WhyQueryResultStatus.ERROR
        assert "DB error" in result.explanation

    def test_query_why_general_exception(self, engine):
        engine._chain_builder.get_traceability_report.side_effect = Exception("Unexpected")
        result = engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        assert result.status == WhyQueryResultStatus.ERROR
        assert "Unexpected" in result.explanation

    def test_cache_hit(self, engine):
        # First query stores in cache
        entity_id = uuid4()
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        result1 = engine.query_why(
            entity_id=entity_id,
            entity_type="journal",
            queried_by="alice",
            use_cache=True,
        )
        # Second query should hit cache
        result2 = engine.query_why(
            entity_id=entity_id,
            entity_type="journal",
            queried_by="alice",
            use_cache=True,
        )
        # The cache hit should return same result object (identical)
        assert result2.cached is True
        # Verify that the cached result is the same as the first one (by id)
        assert result2.query_id == result1.query_id

    def test_cache_expiry(self, engine):
        entity_id = uuid4()
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        # First query with short TTL
        with patch("domain.causality.why_query_engine.timedelta") as mock_timedelta:
            # Set expiry to 0 seconds so cache entry expires immediately
            mock_timedelta.return_value = timedelta(seconds=0)
            result1 = engine.query_why(
                entity_id=entity_id,
                entity_type="journal",
                queried_by="alice",
                use_cache=True,
            )
        # Second query should not hit cache because expired
        # We need to manually clear the cache? Actually the cache entry is expired, but the _get_from_cache checks expires_at.
        # We need to ensure the second query doesn't use cache.
        # Easiest: use use_cache=False to bypass.
        # But we want to test that expired entry is ignored.
        # We'll patch datetime.now to be after expiry.
        with patch("domain.causality.why_query_engine.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.now(UTC) + timedelta(seconds=10)
            # The cached entry will be ignored because it's expired.
            result2 = engine.query_why(
                entity_id=entity_id,
                entity_type="journal",
                queried_by="alice",
                use_cache=True,
            )
            # It should be a new result with different query_id
            assert result2.query_id != result1.query_id
            assert result2.cached is False

    def test_cache_invalidation_all(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        for _ in range(3):
            engine.query_why(
                entity_id=uuid4(),
                entity_type="journal",
                queried_by="alice",
                use_cache=True,
            )
        assert len(engine._cache) == 3
        invalidated = engine.invalidate_cache()
        assert invalidated == 3
        assert len(engine._cache) == 0

    def test_cache_invalidation_specific_entity(self, engine):
        entity_id = uuid4()
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        engine.query_why(
            entity_id=entity_id,
            entity_type="journal",
            queried_by="alice",
            use_cache=True,
        )
        engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
            use_cache=True,
        )
        assert len(engine._cache) == 2
        invalidated = engine.invalidate_cache(entity_id=entity_id)
        assert invalidated == 1
        assert len(engine._cache) == 1

    def test_query_why_batch(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        entities = [(uuid4(), "journal"), (uuid4(), "journal")]
        results = engine.query_why_batch(entities, "alice")
        assert len(results) == 2
        for r in results:
            assert r.status == WhyQueryResultStatus.SUCCESS

    def test_query_why_narrative(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        narrative = engine.query_why_narrative(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        assert "This journal transaction was influenced by" in narrative

    def test_query_why_detailed(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = [
            (uuid4(), 1, []),
        ]
        # Need to mock node service
        node = MagicMock()
        node.entity_type = "intent"
        node.node_type.name = "INTENT"
        node.timestamp = datetime.now(UTC)
        node.created_by = "alice"
        engine._node_service.get_node_by_entity.return_value = node

        detailed = engine.query_why_detailed(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        assert "DETAILED WHY ANALYSIS" in detailed
        assert "UPSTREAM CAUSES" in detailed

    def test_get_query_history(self, engine):
        """Test get_query_history returns correct results."""
        # Initially empty
        assert len(engine.get_query_history()) == 0

        # Add some queries
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        # Run queries
        for i in range(5):
            engine.query_why(
                entity_id=uuid4(),
                entity_type="journal",
                queried_by="alice",
            )

        # Get all history (default limit 50)
        history = engine.get_query_history()
        assert len(history) == 5

        # Test limit
        limited = engine.get_query_history(limit=2)
        assert len(limited) == 2
        # The latest should be the last one, so limited[0] is the latest.
        # We can check that the query_ids are the last two.
        # Since we don't store references, we just check length.

        # Test filter by entity_id
        target_id = uuid4()
        engine.query_why(
            entity_id=target_id,
            entity_type="journal",
            queried_by="alice",
        )
        filtered = engine.get_query_history(entity_id=target_id)
        assert len(filtered) == 1
        assert filtered[0].target_entity_id == target_id

        # Test filter by status
        # Force an error query
        engine._chain_builder.get_traceability_report.return_value = {"error": "Not found"}
        engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        error_filtered = engine.get_query_history(status=WhyQueryResultStatus.ERROR)
        assert len(error_filtered) >= 1
        for r in error_filtered:
            assert r.status == WhyQueryResultStatus.ERROR

    def test_get_statistics(self, engine):
        stats = engine.get_statistics()
        assert stats["total_queries"] == 0
        assert stats["cache_size"] == 0

        # Add some queries
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        for _ in range(5):
            engine.query_why(
                entity_id=uuid4(),
                entity_type="journal",
                queried_by="alice",
            )
        stats = engine.get_statistics()
        assert stats["total_queries"] == 5
        assert stats["by_status"]["SUCCESS"] == 5
        assert stats["by_depth"]["MEDIUM"] == 5
        assert stats["average_causes_per_query"] == 0  # no causes
        assert stats["cache_size"] == 5

    def test_get_audit_log(self, engine):
        # Initially empty
        assert len(engine.get_audit_log()) == 0
        # Run a query -> should add audit log
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        log = engine.get_audit_log()
        assert len(log) >= 1
        assert log[-1]["action"] == "CACHE_HIT"  # Actually the first query might be cache miss? It depends.
        # We can just check that at least one audit entry exists.
        assert any(entry["action"] == "CACHE_HIT" for entry in log) or any(entry["action"] == "QUERY" for entry in log)

    def test_reset(self, engine):
        engine._chain_builder.get_traceability_report.return_value = {"chain": [{"node_type": "INTENT"}]}
        engine._causality_tracker.get_upstream.return_value = []
        engine.query_why(
            entity_id=uuid4(),
            entity_type="journal",
            queried_by="alice",
        )
        assert len(engine._query_history) == 1
        assert len(engine._cache) == 1
        assert len(engine._audit_log) >= 1
        engine.reset()
        assert len(engine._query_history) == 0
        assert len(engine._cache) == 0
        assert len(engine._audit_log) == 1  # The reset itself adds an audit entry
        assert engine._audit_log[0]["action"] == "RESET"